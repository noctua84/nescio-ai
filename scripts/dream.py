#!/usr/bin/env python3
"""Review past session transcripts and write a *proposal* for memory curation.

"Dreaming" is an offline pass between sessions: read what the crew actually did,
find what recurred, and hand a human a short list of things worth acting on.
This script is the deterministic half. It makes **no model call**, writes
nothing under ``memory/``, ``agents/`` or ``CLAUDE.md``, and its only output is
a Markdown file (plus an optional watermark) under ``<config>/dreams/``. The
other half -- turning the signals into harvest nominations or held prompt
suggestions -- is the ``/dream`` command, run by a human-supervised session.

Parsing one transcript lives in ``_dream_parse.py`` and the extra inputs
(subagent transcripts, QA audit reports) in ``_dream_inputs.py``; this file
folds the per-session summaries into a proposal and owns discovery and the CLI.

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
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from _dream_parse import MAX_EXCERPTS, parse_session, scrub  # noqa: E402  (also puts hooks/ on sys.path)
from _dream_inputs import SEVERITIES, parse_subagents, qa_reports  # noqa: E402
import record_stop as rs  # noqa: E402

DEFAULT_DAYS = 14
TOP_ERRORS = 5
STATE_NAME = "last-dream.json"
VERDICTS = ("COMPLETE", "PARTIAL", "BLOCKED")
TIER_NAMES = ("simple", "standard", "complex")


def _subagent_rollup(sessions: list[dict]) -> tuple[list, dict, dict]:
    """``(ranked errors, reruns, read/skipped/malformed)`` over the sessions' optional ``sub`` summaries."""
    errs: dict[tuple, list] = defaultdict(lambda: [set(), 0])
    by_agent: Counter = Counter()
    rerun_ids: set = set()
    totals = {"read": 0, "skipped": 0, "malformed": 0}
    for s in sessions:
        sub = s.get("sub")
        if not sub:
            continue
        totals["read"] += sub["files"]
        totals["skipped"] += sub["skipped"]
        totals["malformed"] += sub["malformed"]
        for key, n in sub["errors"].items():
            errs[key][0].add(s["id"])
            errs[key][1] += n
        if sub["reruns"] > 0:
            rerun_ids.add(s["id"])
            by_agent.update(sub["rerun_agents"])
    top = sorted(errs.items(), key=lambda kv: (-len(kv[1][0]), -kv[1][1], kv[0]))[:TOP_ERRORS]
    reruns = {"count": sum(by_agent.values()), "sessions": len(rerun_ids), "by_agent": dict(sorted(by_agent.items()))}
    return top, reruns, totals


def aggregate(sessions: list[dict], *, min_sessions: int = 2, skipped: int = 0, qa: list[dict] | None = None) -> dict:
    """Fold per-session summaries into the proposal's data.

    Sessions may carry an optional ``sub`` summary (``parse_subagents``) and
    ``qa`` is the optional ``qa_reports`` list; both default to "not read".
    """
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
    sub_top, sub_reruns, sub_totals = _subagent_rollup(sessions)
    recurring += [
        {"kind": "subagent-tool-error", "summary": f"{a} {t}: {sig}", "sessions": len(ids), "count": n}
        for (a, t, sig), (ids, n) in sub_top
    ]
    if sub_reruns["sessions"]:
        recurring.append({
            "kind": "subagent-reruns", "sessions": sub_reruns["sessions"],
            "summary": f"{sub_reruns['count']} identical Bash reruns in subagents",
        })
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
        "malformed_lines": total("malformed") + sub_totals["malformed"],
        "subagents_read": sub_totals["read"],
        "subagents_skipped": sub_totals["skipped"],
        "agent_reports": sum(len(s["reports"]) for s in sessions),
        "agent_dispatches": sum(1 for s in sessions for e in s["events"] if e[0] == "dispatch"),
        "min_sessions": min_sessions,
        "recurring": [r for r in recurring if r["sessions"] >= min_sessions],
        "verdicts": {a: dict(c) for a, c in sorted(verdicts.items())},
        "tool_errors": [{"tool": t, "signature": sig, "sessions": len(i), "count": n} for (t, sig), (i, n) in top],
        "subagent_errors": [
            {"agent": a, "tool": t, "signature": sig, "sessions": len(i), "count": n} for (a, t, sig), (i, n) in sub_top
        ],
        "subagent_reruns": sub_reruns,
        "qa_reports": {
            "reports": list(qa or []),
            "totals": {sev: sum(r[sev] for r in qa or []) for sev in SEVERITIES},
        },
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
        f"- Subagent transcripts read: {agg['subagents_read']} (skipped by cap: {agg['subagents_skipped']})",
        f"- Malformed lines skipped: {agg['malformed_lines']}",
        f"- Agent reports parsed: {agg['agent_reports']} (dispatches seen: {agg['agent_dispatches']})",
        f"- Recurring means seen in at least {agg['min_sessions']} distinct sessions",
    ]
    if agg["sessions_read"] and not agg["agent_reports"]:
        out.append("- Note: sessions were read but no agent reports were parsed; transcript format may have changed.")
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
    sub = [
        f"- {e['agent']} {e['tool']}: {e['signature']} ({e['sessions']} sessions, {e['count']} errors)"
        for e in agg["subagent_errors"]
    ]
    rr = agg["subagent_reruns"]
    if rr["count"]:
        by = ", ".join(f"{a} {n}" for a, n in rr["by_agent"].items())
        sub.append(f"- Identical Bash reruns: {rr['count']} in {rr['sessions']} sessions (by agent: {by})")
    out += _section("Subagent tool errors", sub, "None found (or subagent transcripts not read).")
    qa = agg["qa_reports"]
    rows = [
        f"| {r['name']} | {r['date']} | " + " | ".join(str(r[k]) for k in SEVERITIES) + " |" for r in qa["reports"]
    ]
    if rows:
        rows = ["| Report | Date | Critical | Major | Minor | Info |", "|---|---|---|---|---|---|", *rows,
                "| **Total** | | " + " | ".join(f"**{qa['totals'][k]}**" for k in SEVERITIES) + " |"]
    out += _section("QA audits", rows, "No QA reports in the window (or reading disabled).")
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
    p.add_argument("--max-subagents", type=int, default=25, help="subagent transcripts read per parent session")
    p.add_argument("--no-subagents", action="store_true", help="do not read subagent transcripts")
    p.add_argument("--max-qa-reports", type=int, default=10, help="QA reports under docs/reports/ (0 disables)")
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
    sessions = [parse_session(f) for f in files]
    if not args.no_subagents:
        for f, s in zip(files, sessions):
            s["sub"] = parse_subagents(f, args.max_subagents)
    qa = qa_reports(root, since, args.max_qa_reports) if args.max_qa_reports > 0 else None
    agg = aggregate(sessions, min_sessions=args.min_sessions, skipped=skipped, qa=qa)
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
