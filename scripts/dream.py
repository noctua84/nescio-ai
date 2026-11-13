#!/usr/bin/env python3
"""Review past session transcripts and write a *proposal* for memory curation.

"Dreaming" is an offline pass between sessions: read what the crew actually did,
find what recurred, and hand a human a short list of things worth acting on.
This script is the deterministic half. It makes **no model call**, writes
nothing under ``memory/``, ``agents/`` or ``CLAUDE.md``, and its only output is
a Markdown file (plus an optional watermark) under ``<config>/dreams/``. The
other half -- turning the signals into harvest nominations or held prompt
suggestions -- is the ``/dream`` command, run by a human-supervised session.

Parsing one transcript lives in ``_dream_parse.py``; this file folds the
per-session summaries into a proposal and owns discovery and the CLI.

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
    python scripts/dream.py --link HASH12 SIG_ID     # note HASH12 answers signal SIG_ID
    python scripts/dream.py --compare                # did the linked signals drop?
"""

from __future__ import annotations

import argparse
import json
import os
import hashlib
import re
import subprocess
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from _dream_parse import MAX_EXCERPTS, SHAPE_COUNTS, parse_session, scrub  # noqa: E402  (also puts hooks/ on sys.path)
import _dream_measure as measure  # noqa: E402
import record_stop as rs  # noqa: E402

DEFAULT_DAYS = 14
TOP_ERRORS = 5
STATE_NAME = "last-dream.json"
VERDICTS = ("COMPLETE", "PARTIAL", "BLOCKED")
TIER_NAMES = ("simple", "standard", "complex")
# Top-level transcript-entry keys seen in practice; a key outside this set on most entries is reported as drift.
KNOWN_KEYS = frozenset({
    "type", "message", "uuid", "parentUuid", "isSidechain", "userType", "cwd", "sessionId", "version", "gitBranch",
    "timestamp", "requestId", "toolUseResult", "sourceToolAssistantUUID", "isMeta", "promptId", "entrypoint", "slug",
    "effort", "perTurnEffort", "advisorModel", "apiBlockIndex", "rendered", "renderedRole", "requestedModel",
    "serverClassifierRequest", "serverClassifierContext", "wireToolInputs", "requestRef", "isCompactSummary",
    "isVisibleInTranscriptOnly", "thinkingMetadata", "todos", "permissionMode", "level", "subtype", "content",
    "isApiErrorMessage", "error", "origin", "imagePasteIds",
})


def drift_warnings(shape: dict) -> list[str]:
    """One-line warnings when the transcript shapes the parser relies on look different.

    ``shape`` is ``aggregate()["shape"]``. A format change must not read as "zero signals".
    """
    typed = shape["typed"]
    found = []
    if shape["entries"] > 0 and typed == 0:
        found.append("No user/assistant entries found; the `type` field may have changed.")
    if typed > 0 and shape["with_message"] < typed / 2:
        found.append("Most user/assistant entries lack `message.content`; the message shape may have changed.")
    if typed >= 50 and shape["tool_uses"] == 0:
        found.append("No `tool_use` blocks found in a large transcript sample; the content-block shape may have changed.")
    if shape["tool_results"] > 0 and shape["result_dicts"] == 0:
        found.append("Tool results seen but no `toolUseResult` dicts; the field may have changed.")
    if shape["agent_dispatches"] > 0 and shape["agent_reports"] == 0:
        found.append("Agent dispatches seen but no agent reports parsed; the report shape may have changed.")
    if shape["agent_results"] > 0 and shape["agent_dispatches"] == 0:
        found.append("Agent results seen but no Agent/Task dispatches; the dispatch tool may have been renamed.")
    if shape["unknown_keys"]:
        found.append(f"New top-level keys on most entries: {', '.join(shape['unknown_keys'])} (informational).")
    return found


def total_shape(sessions: list[dict], key: str) -> int:
    return sum(s["shape"][key] for s in sessions)


def signal_id(key: str) -> str:
    """Stable 8-hex id of a signal key; independent of counts, so it survives across runs."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:8]


def _esc_key(fam: str, t1: int, t2: int) -> str:
    return f"escalation:{scrub(fam, 80)}:{TIER_NAMES[t1]}->{TIER_NAMES[t2]}"


def _err_key(tool: str, sig: str) -> str:
    return f"tool-error:{scrub(tool, 80)}:{sig}"


def signal_table(sessions: list[dict]) -> dict:
    """``{sig_id: {key, sessions, count}}`` for *every* signal seen in at least one session.

    Unlike ``aggregate``'s top-N and ``--min-sessions`` cuts, nothing is dropped:
    a signature that slips out of the top 5 must not read as zero to ``--compare``.
    Keys are built from already-scrubbed text only.
    """
    seen: dict[str, list] = defaultdict(lambda: [set(), 0])

    def add(key: str, sid: str, n: int) -> None:
        seen[key][0].add(sid)
        seen[key][1] += n

    for s in sessions:
        for rep in s["reports"]:
            if rep["verdict"] in ("BLOCKED", "PARTIAL"):
                add(f"{rep['verdict'].lower()}:{scrub(rep['agent'], 80)}", s["id"], 1)
            pins = sum(1 for t in rep["flags"] if t.startswith("Inverted pin:"))
            if pins:
                add("inverted-pins", s["id"], pins)
        for fam, t1, t2 in s["escalations"]:
            add(_esc_key(fam, t1, t2), s["id"], 1)
        for (tool, sig), n in s["errors"].items():
            add(_err_key(tool, sig), s["id"], n)
        for key in ("corrections", "reverts", "interrupts"):
            if s[key]:
                add(key, s["id"], s[key])
    return {signal_id(k): {"key": k, "sessions": len(ids), "count": n} for k, (ids, n) in sorted(seen.items())}


def aggregate(sessions: list[dict], *, min_sessions: int = 2, skipped: int = 0) -> dict:
    """Fold per-session summaries into the proposal's data."""
    verdicts: dict[str, Counter] = defaultdict(Counter)
    esc: dict[tuple, set] = defaultdict(set)
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
            esc[(fam, t1, t2)].add(s["id"])
        for key, n in s["errors"].items():
            errs[key][0].add(s["id"])
            errs[key][1] += n
    top = sorted(errs.items(), key=lambda kv: (-len(kv[1][0]), -kv[1][1], kv[0]))[:TOP_ERRORS]
    having = lambda key: {s["id"] for s in sessions if s[key]}  # noqa: E731
    total = lambda key: sum(s[key] for s in sessions)  # noqa: E731
    pins = {f["session"] for f in flags if f["text"].startswith("Inverted pin:")}
    recurring = sorted(
        (
            {"kind": "escalation", "summary": f"{f}: {TIER_NAMES[a]}→{TIER_NAMES[b]}", "sessions": len(v),
             "id": signal_id(_esc_key(f, a, b))}
            for (f, a, b), v in esc.items()
        ),
        key=lambda r: r["summary"],
    )
    recurring += [
        {"kind": "tool-error", "summary": f"{t}: {sig}", "sessions": len(ids), "count": n, "id": signal_id(_err_key(t, sig))}
        for (t, sig), (ids, n) in top
    ]
    recurring += [
        {"kind": kind, "summary": text, "sessions": len(ids), "id": signal_id(kind)}
        for kind, text, ids in (
            ("corrections", f"{total('corrections')} user corrections", having("corrections")),
            ("reverts", f"{total('reverts')} revert-style git commands", having("reverts")),
            ("inverted-pins", "inverted test pins in builder reports", pins),
        )
    ]
    shape = {k: total_shape(sessions, k) for k in SHAPE_COUNTS}
    keys = sum((s["shape"]["typed_keys"] for s in sessions), Counter())
    shape["agent_dispatches"] = sum(1 for s in sessions for e in s["events"] if e[0] == "dispatch")
    shape["agent_reports"] = sum(len(s["reports"]) for s in sessions)
    shape["unknown_keys"] = sorted(k for k, n in keys.items() if n * 2 > shape["typed"] and k not in KNOWN_KEYS)
    return {
        "sessions_read": len(sessions),
        "sessions_skipped": skipped,
        "malformed_lines": total("malformed"),
        "agent_reports": shape["agent_reports"],
        "agent_dispatches": shape["agent_dispatches"],
        "shape": shape,
        "drift": drift_warnings(shape),
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
        f"- Agent reports parsed: {agg['agent_reports']} (dispatches seen: {agg['agent_dispatches']})",
        f"- Recurring means seen in at least {agg['min_sessions']} distinct sessions",
    ]
    out += _section("Format check", [f"- {w}" for w in agg["drift"]], "Transcript shapes look as expected.")
    empty = "None met the threshold." if agg["sessions_read"] else "No transcripts found in the window; nothing to review."
    rec = [f"- [{r['kind']}] {r['summary']} ({r['sessions']} sessions) [sig {r['id']}]" for r in agg["recurring"]]
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
    p.add_argument("--link", nargs=2, metavar=("HASH12", "SIG_ID"), help="record that ledger note HASH12 answers signal SIG_ID")
    p.add_argument("--compare", action="store_true", help="per linked note, compare its signal's rate before and after")
    p.add_argument("--ledger", type=Path, help="learning ledger for --compare (default: <repo>/memory/learning-log.md)")
    p.add_argument("--min-after", type=int, default=10, help="sessions needed after a note before judging it (default 10)")
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.out and args.out.suffix.lower() == ".json":
        # The sidecar is written at out.with_suffix(".json"); a .json --out would be overwritten by it.
        parser.error("--out must not end in .json: that path is reserved for the run's JSON sidecar")
    start = datetime.now(timezone.utc)
    config = rs.config_dir()
    root = main_root(args.repo)
    key = rs.repo_key(str(root))
    state_dir = config / "dreams" / key
    if args.link:
        return measure.run_link(state_dir, *args.link, start)
    if args.compare:
        return measure.run_compare(state_dir, args.ledger or root / "memory" / "learning-log.md", args.min_after, args.json)
    since = parse_iso(args.since) if args.since else read_since(state_dir / STATE_NAME, start)
    dirs = args.transcripts or transcript_dirs(args.projects_dir or config / "projects", root)
    files, skipped = select_sessions([Path(d) for d in dirs], since, args.max_sessions)
    sessions = [parse_session(f) for f in files]
    agg = aggregate(sessions, min_sessions=args.min_sessions, skipped=skipped)
    since_s, until_s = since.strftime("%Y-%m-%dT%H:%M:%SZ"), start.strftime("%Y-%m-%dT%H:%M:%SZ")
    out = args.out or state_dir / f"{start.strftime('%Y%m%dT%H%M%SZ')}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(agg, repo_key=key, since=since_s, until=until_s), encoding="utf-8")
    sidecar = {"schema": measure.SCHEMA, "repo_key": key, "since": since_s, "until": until_s,
               "sessions_read": agg["sessions_read"], "agent_dispatches": agg["agent_dispatches"], "signals": signal_table(sessions)}
    out.with_suffix(".json").write_text(json.dumps(sidecar, indent=2), encoding="utf-8")
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
