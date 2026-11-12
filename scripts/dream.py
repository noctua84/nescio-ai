#!/usr/bin/env python3
"""Review past session transcripts and write a *proposal* for memory curation.

"Dreaming" is an offline pass between sessions: read what the crew actually did,
find what recurred, and hand a human a short list of things worth acting on.
This script is the deterministic half. It makes **no model call**, writes
nothing under ``memory/``, ``agents/`` or ``CLAUDE.md``, and its only output is
a Markdown file (plus an optional watermark) under ``<config>/dreams/``. The
other half -- turning the signals into harvest nominations or held prompt
suggestions -- is the ``/dream`` command, run by a human-supervised session.

Deliberate design decisions, each with a failure mode behind it:

  * **Stream line by line; a malformed line is counted and skipped.** Same
    contract as ``session_anatomy.py``: transcripts run to hundreds of MB, and
    one truncated line must not blank out the rest of a session.

  * **Theme-agnostic.** Agent names are themeable, so nothing here knows what
    agents exist. Tier comes from the ``-simple`` / ``-standard`` suffix of the
    literal ``agentType`` (none = complex) and family is the stem.

  * **"Recurring" means distinct sessions, not occurrences.** One bad session
    can emit forty identical tool errors; that is an incident, not a pattern.
    A pattern is reported as recurring only when seen in ``--min-sessions``
    distinct sessions.

  * **Privacy by construction.** Every excerpt passes ``record_stop.redact``
    (which blanks the whole excerpt on any secret shape), has the home dir
    replaced by ``~``, and is truncated. Whole messages are never emitted. The
    proposal is machine-local and is never synced.

  * **The watermark moves only after the proposal is written.** A crash
    between reading and writing must not mark sessions as dreamt-about.

Usage:
    python scripts/dream.py                          # this repo, since last run
    python scripts/dream.py --repo ../other --since 2026-01-01
    python scripts/dream.py --no-stamp --json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))

import record_stop as rs  # noqa: E402

DEFAULT_DAYS = 14
EXCERPT_MAX = 160
LINE_MAX = 200
MAX_EXCERPTS = 3
TOP_ERRORS = 5
STATE_NAME = "last-dream.json"
VERDICTS = ("COMPLETE", "PARTIAL", "BLOCKED")
TIER_NAMES = ("simple", "standard", "complex")

VERDICT_RE = re.compile(r"<verdict>\s*(COMPLETE|PARTIAL|BLOCKED)\s*</verdict>")
CORRECTION_RE = re.compile(
    r"^(no\b|nope|don'?t|do not|stop\b|wrong|that'?s (not|wrong)|instead\b|actually\b|undo|revert)",
    re.IGNORECASE,
)
REVERT_RE = re.compile(r"\bgit\s+(revert|reset\s+--hard|checkout\s+--\s|restore\s)")
PATH_RE = re.compile(r"(?:[A-Za-z]:[\\/]|~?/)[^\s'\"`<>]+")
HEX_RE = re.compile(r"\b[0-9a-fA-F]{7,}\b")
DIGITS_RE = re.compile(r"\d+")


def _tag_lines(text: str, tag: str) -> list[str]:
    """Non-empty bullet-stripped lines of the last ``<tag>`` block in ``text``."""
    blocks = re.findall(rf"<{tag}>(.*?)</{tag}>", text, re.DOTALL)
    if not blocks:
        return []
    lines = (ln.strip().lstrip("-*").strip() for ln in blocks[-1].splitlines())
    return [ln for ln in lines if ln]


def _text_of(content) -> str:
    """Text of a string or a list of ``{type: text}`` blocks; "" otherwise."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            b["text"]
            for b in content
            if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str)
        )
    return ""


def home_forms() -> list[str]:
    """The home dir in native and forward-slash form, longest first."""
    home = str(Path.home())
    return sorted({home, home.replace("\\", "/")}, key=len, reverse=True)


def scrub(text: str, limit: int = EXCERPT_MAX) -> str:
    """Redact secrets, replace the home dir with ``~``, collapse and truncate."""
    text = rs.redact(" ".join(text.split()))
    for form in home_forms():
        text = re.sub(re.escape(form), "~", text, flags=re.IGNORECASE if os.name == "nt" else 0)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def split_tier(agent_type: str) -> tuple[str, int]:
    """``(family, tier)``: ``-simple`` 0, ``-standard`` 1, anything else 2."""
    for tier, suffix in enumerate(("-simple", "-standard")):
        if agent_type.endswith(suffix):
            return agent_type[: -len(suffix)], tier
    return agent_type, 2


def error_signature(text: str) -> str:
    """First line of an error with paths, hex and numbers collapsed."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    first = " ".join(lines[:2]) if lines and lines[0].startswith("Exit code") else (lines[0] if lines else "")
    first = PATH_RE.sub("<path>", first)
    first = HEX_RE.sub("<hex>", first)
    return scrub(DIGITS_RE.sub("<n>", first), 120)


def find_escalations(events: list[tuple]) -> list[tuple[str, int, int]]:
    """Failed (BLOCKED/PARTIAL) family-F report then a later higher-tier F dispatch.

    ``events`` are ``("dispatch", agent)`` / ``("report", agent, verdict)`` in
    transcript order. Each dispatch is consumed by at most one escalation.
    """
    used: set[int] = set()
    found = []
    for i, ev in enumerate(events):
        if ev[0] != "report" or ev[2] not in ("BLOCKED", "PARTIAL"):
            continue
        fam, tier = split_tier(ev[1])
        for j in range(i + 1, len(events)):
            if events[j][0] != "dispatch" or j in used:
                continue
            fam2, tier2 = split_tier(events[j][1])
            if fam2 == fam and tier2 > tier:
                used.add(j)
                found.append((fam, tier, tier2))
                break
    return found


def parse_report(text: str) -> dict:
    """Verdict, pin/deferred-red lines and out-of-scope lines of a builder report."""
    verdicts = VERDICT_RE.findall(text)
    deviations = _tag_lines(text, "deviations")
    return {
        "verdict": verdicts[-1] if verdicts else None,
        "flags": [ln for ln in deviations if ln.startswith(("Inverted pin:", "Deferred red:"))],
        "out_of_scope": [ln for ln in _tag_lines(text, "out-of-scope") if not ln.lower().startswith("none")],
    }


def _new_session(path: Path) -> dict:
    return {
        "id": path.stem, "malformed": 0, "reports": [], "events": [], "corrections": 0,
        "excerpts": [], "interrupts": 0, "errors": Counter(), "reverts": 0, "escalations": [],
    }


def _on_assistant(entry: dict, s: dict, tools: dict, seen: set) -> None:
    content = (entry.get("message") or {}).get("content")
    for block in content if isinstance(content, list) else []:
        if not isinstance(block, dict) or block.get("type") != "tool_use":
            continue
        uid, name, inp = block.get("id"), block.get("name"), block.get("input")
        tools[uid] = name
        if uid in seen:  # the same message is re-emitted as tool results resolve
            continue
        seen.add(uid)
        inp = inp if isinstance(inp, dict) else {}
        if name in ("Agent", "Task") and isinstance(inp.get("subagent_type"), str):
            s["events"].append(("dispatch", inp["subagent_type"]))
        cmd = inp.get("command")
        if name == "Bash" and isinstance(cmd, str) and REVERT_RE.search(cmd):
            s["reverts"] += 1


def _on_report(entry: dict, result: dict, s: dict) -> None:
    rep = parse_report(_text_of(result.get("content")))
    rep["agent"] = result["agentType"]
    rep["ts"] = entry.get("timestamp")
    rep["flags"] = [scrub(ln, LINE_MAX) for ln in rep["flags"]]
    rep["out_of_scope"] = [scrub(ln, LINE_MAX) for ln in rep["out_of_scope"]]
    s["reports"].append(rep)
    if rep["verdict"]:
        s["events"].append(("report", rep["agent"], rep["verdict"]))


def _on_human(text: str, s: dict) -> None:
    text = text.strip()
    if text.startswith("[Request interrupted by user"):
        s["interrupts"] += 1
    elif text and not text.startswith("<") and CORRECTION_RE.match(text):
        s["corrections"] += 1
        if len(s["excerpts"]) < MAX_EXCERPTS:
            s["excerpts"].append(scrub(text))


def _on_user(entry: dict, s: dict, tools: dict) -> None:
    result = entry.get("toolUseResult")
    if isinstance(result, dict) and isinstance(result.get("agentType"), str):
        _on_report(entry, result, s)
    content = (entry.get("message") or {}).get("content")
    results = [b for b in content if isinstance(b, dict) and b.get("type") == "tool_result"] if isinstance(content, list) else []
    for block in results:
        if block.get("is_error") is True:
            tool = tools.get(block.get("tool_use_id"), "unknown")
            s["errors"][(str(tool), error_signature(_text_of(block.get("content"))))] += 1
    if not results and result is None and not entry.get("isMeta"):
        _on_human(_text_of(content), s)


def parse_session(path: Path) -> dict:
    """Stream one transcript into a per-session summary (no raw text kept)."""
    s, tools, seen = _new_session(path), {}, set()
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                entry = None
            if not isinstance(entry, dict):
                s["malformed"] += 1
            elif entry.get("type") == "assistant":
                _on_assistant(entry, s, tools, seen)
            elif entry.get("type") == "user":
                _on_user(entry, s, tools)
    s["escalations"] = find_escalations(s["events"])
    return s


def aggregate(sessions: list[dict], *, min_sessions: int = 2, skipped: int = 0) -> dict:
    """Fold per-session summaries into the proposal's data."""
    verdicts: dict[str, Counter] = defaultdict(Counter)
    esc: dict[str, set] = defaultdict(set)
    errs: dict[tuple, list] = defaultdict(lambda: [set(), 0])
    oos: dict[str, list] = defaultdict(lambda: [set(), ""])
    flags = []
    for s in sessions:
        for rep in s["reports"]:
            verdicts[rep["agent"]][rep["verdict"] or "none"] += 1
            flags += [{"session": s["id"], "ts": rep["ts"], "agent": rep["agent"], "text": t} for t in rep["flags"]]
            for t in rep["out_of_scope"]:
                entry = oos[" ".join(t.lower().split())]
                entry[0].add(s["id"])
                entry[1] = t
        for fam, t1, t2 in s["escalations"]:
            esc[f"{fam}: {TIER_NAMES[t1]}→{TIER_NAMES[t2]}"].add(s["id"])
        for key, n in s["errors"].items():
            errs[key][0].add(s["id"])
            errs[key][1] += n
    top = sorted(errs.items(), key=lambda kv: (-len(kv[1][0]), -kv[1][1], kv[0]))[:TOP_ERRORS]
    having = lambda key: {s["id"] for s in sessions if s[key]}  # noqa: E731
    total = lambda key: sum(s[key] for s in sessions)  # noqa: E731
    pins = {f["session"] for f in flags if f["text"].startswith("Inverted pin:")}
    recurring = [{"kind": "escalation", "summary": k, "sessions": len(v)} for k, v in sorted(esc.items())]
    recurring += [
        {"kind": "tool-error", "summary": f"{t}: {sig}", "sessions": len(ids), "count": n} for (t, sig), (ids, n) in top
    ]
    recurring += [
        {"kind": kind, "summary": text, "sessions": len(ids)}
        for kind, text, ids in (
            ("corrections", f"{total('corrections')} user corrections", having("corrections")),
            ("reverts", f"{total('reverts')} revert-style git commands", having("reverts")),
            ("inverted-pins", "inverted test pins in builder reports", pins),
        )
    ]
    return {
        "sessions_read": len(sessions),
        "sessions_skipped": skipped,
        "malformed_lines": total("malformed"),
        "min_sessions": min_sessions,
        "recurring": [r for r in recurring if r["sessions"] >= min_sessions],
        "verdicts": {a: dict(c) for a, c in sorted(verdicts.items())},
        "tool_errors": [{"tool": t, "signature": sig, "sessions": len(i), "count": n} for (t, sig), (i, n) in top],
        "corrections": {
            "count": total("corrections"),
            "sessions": len(having("corrections")),
            "excerpts": [x for s in sessions for x in s["excerpts"]][:MAX_EXCERPTS],
        },
        "interrupts": total("interrupts"),
        "reverts": {"count": total("reverts"), "sessions": len(having("reverts"))},
        "to_confirm": flags,
        "follow_ups": sorted(
            ({"text": t, "sessions": len(ids)} for ids, t in oos.values()), key=lambda f: (-f["sessions"], f["text"])
        ),
    }


NEXT_STEPS = (
    "Memory-worthy items go through `/harvest-memory` nominations (`promote_learnings.py`); this file is not a source of truth.",
    "Agent or `CLAUDE.md` tweaks are written as suggestions only and are never auto-applied.",
    "Anything bound for the public repo must be generic: no private names, paths or identifiers.",
)


def _section(title: str, lines: list[str], empty: str) -> list[str]:
    return ["", f"## {title}", "", *(lines or [empty])]


def render(agg: dict, *, repo_key: str, since: str, until: str) -> str:
    """The proposal, as Markdown."""
    out = [
        f"# Dream proposal: {repo_key}",
        "",
        f"- Window: {since} to {until}",
        f"- Sessions read: {agg['sessions_read']} (skipped by cap: {agg['sessions_skipped']})",
        f"- Malformed lines skipped: {agg['malformed_lines']}",
        f"- Recurring means seen in at least {agg['min_sessions']} distinct sessions",
    ]
    empty = "None met the threshold." if agg["sessions_read"] else "No transcripts found in the window; nothing to review."
    rec = [f"- [{r['kind']}] {r['summary']} ({r['sessions']} sessions)" for r in agg["recurring"]]
    rec += [f"  - correction excerpt: {x}" for x in agg["corrections"]["excerpts"]]
    out += _section("Recurring patterns", rec, empty)
    table = [
        f"| {agent} | " + " | ".join(str(c.get(k, 0)) for k in (*VERDICTS, "none")) + " |"
        for agent, c in agg["verdicts"].items()
    ]
    head = ["| Agent | COMPLETE | PARTIAL | BLOCKED | no verdict |", "|---|---|---|---|---|"]
    out += _section("Agent verdicts", head + table if table else [], "No agent reports found.")
    confirm = [f"- {f['text']} (agent {f['agent']}, session {f['session'][:8]}, {f['ts'] or 'no ts'})" for f in agg["to_confirm"]]
    out += _section("To confirm", confirm, "No inverted pins or deferred reds.")
    follow = [f"- {f['text']} ({f['sessions']} sessions)" for f in agg["follow_ups"]]
    out += _section("Candidate follow-ups", follow, "None reported.")
    out += _section("Suggested next steps", [f"- {t}" for t in NEXT_STEPS], "")
    return "\n".join(out) + "\n"


def slug(path: str) -> str:
    """Claude Code's transcript-directory name for an absolute path."""
    return re.sub(r"[^0-9A-Za-z]", "-", path)


def _git(cwd: Path, *args: str) -> str:
    try:
        r = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, timeout=5, check=True)
        return r.stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return ""


def main_root(repo: Path) -> Path:
    """Main worktree root: parent of ``--git-common-dir``, else toplevel, else ``repo``."""
    common = _git(repo, "rev-parse", "--git-common-dir")
    if common:
        p = (repo / common).resolve()
        if p.name == ".git":
            return p.parent
    top = _git(repo, "rev-parse", "--show-toplevel")
    return Path(top).resolve() if top else repo.resolve()


def transcript_dirs(projects: Path, root: Path) -> list[Path]:
    """Directories named for the main root's slug, or its worktree-slug children."""
    fold = str.casefold if os.name == "nt" else str
    base = fold(slug(str(root)))
    if not projects.is_dir():
        return []
    return sorted(
        d for d in projects.iterdir()
        if d.is_dir() and (fold(d.name) == base or fold(d.name).startswith(base + "--claude-worktrees-"))
    )


def parse_iso(text: str) -> datetime:
    dt = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def read_since(state: Path, now: datetime) -> datetime:
    try:
        return parse_iso(json.loads(state.read_text(encoding="utf-8"))["since"])
    except (OSError, ValueError, KeyError, TypeError):
        return now - timedelta(days=DEFAULT_DAYS)


def select_sessions(dirs: list[Path], since: datetime, cap: int) -> tuple[list[Path], int]:
    """Newest-first ``*.jsonl`` with mtime >= since, capped; returns (kept, skipped)."""
    found = []
    for d in dirs:
        for f in d.glob("*.jsonl"):
            try:
                if f.stat().st_mtime >= since.timestamp():
                    found.append((f.stat().st_mtime, f))
            except OSError:
                continue
    found.sort(key=lambda t: (-t[0], str(t[1])))
    return [f for _, f in found[:cap]], max(0, len(found) - cap)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Review past sessions and write a memory-curation proposal.")
    p.add_argument("--projects-dir", type=Path)
    p.add_argument("--repo", type=Path, default=Path.cwd())
    p.add_argument("--transcripts", type=Path, action="append", help="transcript dir (repeatable); bypasses discovery")
    p.add_argument("--since")
    p.add_argument("--max-sessions", type=int, default=50)
    p.add_argument("--min-sessions", type=int, default=2)
    p.add_argument("--out", type=Path)
    p.add_argument("--json", action="store_true", help="also print the structured result to stdout")
    p.add_argument("--no-stamp", action="store_true", help="do not advance the watermark")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    start = datetime.now(timezone.utc)
    config = rs.config_dir()
    root = main_root(args.repo)
    key = rs.repo_key(str(root))
    state_dir = config / "dreams" / key
    since = parse_iso(args.since) if args.since else read_since(state_dir / STATE_NAME, start)
    dirs = args.transcripts or transcript_dirs(args.projects_dir or config / "projects", root)
    files, skipped = select_sessions([Path(d) for d in dirs], since, args.max_sessions)
    agg = aggregate([parse_session(f) for f in files], min_sessions=args.min_sessions, skipped=skipped)
    since_s, until_s = since.strftime("%Y-%m-%dT%H:%M:%SZ"), start.strftime("%Y-%m-%dT%H:%M:%SZ")
    out = args.out or state_dir / f"{start.strftime('%Y%m%dT%H%M%SZ')}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(agg, repo_key=key, since=since_s, until=until_s), encoding="utf-8")
    if not args.no_stamp:
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / STATE_NAME).write_text(json.dumps({"since": until_s}), encoding="utf-8")
    if args.json:
        print(json.dumps({**agg, "repo_key": key, "since": since_s, "until": until_s, "proposal": scrub(str(out), 500)}, indent=2))
    else:
        print(f"proposal written: {scrub(str(out), 500)} ({agg['sessions_read']} sessions read)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
