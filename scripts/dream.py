#!/usr/bin/env python3
"""Review past session transcripts and write a *proposal* for memory curation.

"Dreaming" is an offline pass between sessions: read what the crew actually did,
find what recurred, and hand a human a short list of things worth acting on.
This script is the deterministic half. It makes **no model call**, writes
nothing under ``memory/``, ``agents/`` or ``CLAUDE.md``, and its only output is
a Markdown file (plus an optional watermark) under ``<config>/dreams/``. The
other half -- turning the signals into harvest nominations or held prompt
suggestions -- is the ``/dream`` command, run by a human-supervised session.

Parsing one transcript lives in ``_dream_parse.py``, the extra inputs
(subagent transcripts, QA audit reports) in ``_dream_inputs.py`` and the fold of
per-session summaries into signals (with their stable ids) in
``_dream_aggregate.py``; this file renders the proposal and owns discovery and
the CLI.

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
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from _dream_parse import parse_session, scrub  # noqa: E402  (also puts hooks/ on sys.path)
from _dream_inputs import QA_HISTORY_CAP, SEVERITIES, merge_subagent_reports, parse_subagents, qa_reports, qa_trend  # noqa: E402
from _dream_aggregate import (  # noqa: E402,F401  (re-exported: tests and callers use ``dream.<name>``)
    KNOWN_KEYS, TIER_NAMES, TOP_ERRORS, aggregate, drift_warnings, signal_id, signal_table, total_shape,
)
import _dream_measure as measure  # noqa: E402
from _dream_testruns import AFTER_FAIL_KEYS  # noqa: E402
import record_stop as rs  # noqa: E402

DEFAULT_DAYS = 14
STATE_NAME = "last-dream.json"
VERDICTS = ("COMPLETE", "PARTIAL", "BLOCKED")


NEXT_STEPS = (
    "Memory-worthy items go through `/harvest-memory` nominations (`promote_learnings.py`); this file is not a source of truth.",
    "Agent or `CLAUDE.md` tweaks are written as suggestions only and are never auto-applied.",
    "Anything bound for the public repo must be generic: no private names, paths or identifiers.",
)


def _section(title: str, lines: list[str], empty: str) -> list[str]:
    return ["", f"## {title}", "", *(lines or [empty])]


def _test_lines(tests: dict) -> list[str]:
    """Per-agent table of subagent test runs and what followed each failure, plus COMPLETE-on-red; ``[]`` if no runs."""
    if not tests["totals"]["runs"]:
        return []
    head = ["| Agent | Runs | Known | Failed | Masked | Fixed after edit | Passed, no edit seen | Refailed after edit "
            "| Retried, no edit | Not rerun |", "|---|---|---|---|---|---|---|---|---|---|"]
    rows = [
        f"| {a} | {c['runs']} | {c['known']} | {c['failed']} | {c['masked']} | "
        + " | ".join(str(c["after_fail"][k]) for k in AFTER_FAIL_KEYS) + " |"
        for a, c in tests["by_agent"].items()
    ]
    red = tests["complete_on_red"]
    by = ", ".join(f"{a} {n}" for a, n in red["by_agent"].items())
    return [*head, *rows, "", f"COMPLETE reports whose last test run failed: {red['count']}" + (f" (by agent: {by})" if by else "")]


def _qa_trend_lines(trend: dict | None) -> list[str]:
    """Trend table (last k, previous k, all; mean per audit) and its note; ``[]`` if not read or no audits."""
    if not trend or not trend["audits"]:
        return []
    k = trend["k"]
    head = ["| Audits | Count | Critical | Major | Minor | Info |", "|---|---|---|---|---|---|"]
    rows = [
        f"| {label} | {m['audits'] if m else 0} | " + " | ".join(str(m[s]) if m else "—" for s in SEVERITIES) + " |"
        for label, m in ((f"Last {k}", trend["recent"]), (f"Previous {k}", trend["previous"]), ("All", trend["all"]))
    ]
    prev = trend["previous"]
    note = "- Mean findings per audit; reports are counted by date in their filename."
    if prev is None or prev["audits"] < k:
        note += f' Fewer than {2 * k} audits means "previous" is partial.'
    return [*head, *rows, note]


def render(agg: dict, *, repo_key: str, since: str, until: str) -> str:
    """The proposal, as Markdown."""
    out = [
        f"# Dream proposal: {repo_key}",
        "",
        f"- Window: {since} to {until}",
        f"- Sessions read: {agg['sessions_read']} (skipped by cap: {agg['sessions_skipped']})",
        f"- Subagent transcripts read: {agg['subagents_read']} (skipped by cap: {agg['subagents_skipped']})",
        f"- Malformed lines skipped: {agg['malformed_lines']}",
        f"- Agent reports parsed: {agg['agent_reports']}, of which {agg['reports_from_subagents']} from subagent "
        f"transcripts (dispatches seen: {agg['agent_dispatches']})",
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
    sub = [
        f"- {e['agent']} {e['tool']}: {e['signature']} ({e['sessions']} sessions, {e['count']} errors)"
        for e in agg["subagent_errors"]
    ]
    rr = agg["subagent_reruns"]
    if rr["count"]:
        by = ", ".join(f"{a} {n}" for a, n in rr["by_agent"].items())
        sub.append(f"- Identical Bash reruns: {rr['count']} in {rr['sessions']} sessions (by agent: {by})")
    out += _section("Subagent tool errors", sub, "None found (or subagent transcripts not read).")
    out += _section("Test runs in subagents", _test_lines(agg["subagent_tests"]), "No test runs found in subagent transcripts (or not read).")
    qa = agg["qa_reports"]
    rows = [
        f"| {r['name']} | {r['date']} | " + " | ".join(str(r[k]) for k in SEVERITIES) + " |" for r in qa["reports"]
    ]
    if rows:
        rows = ["| Report | Date | Critical | Major | Minor | Info |", "|---|---|---|---|---|---|", *rows,
                "| **Total** | | " + " | ".join(f"**{qa['totals'][k]}**" for k in SEVERITIES) + " |"]
    out += _section("QA audits", rows, "No QA reports in the window (or reading disabled).")
    trend = agg["qa_trend"]
    out += _section("QA trend", _qa_trend_lines(trend), "QA reading disabled." if trend is None else "No QA audits found.")
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
    if not args.no_subagents:
        for f, s in zip(files, sessions):
            s["sub"] = parse_subagents(f, args.max_subagents)
            s["sub"]["merged"] = merge_subagent_reports(s, s["sub"])
    qa = qa_reports(root, since, args.max_qa_reports) if args.max_qa_reports > 0 else None
    trend = qa_trend(qa_reports(root, None, QA_HISTORY_CAP)) if args.max_qa_reports > 0 else None
    agg = aggregate(sessions, min_sessions=args.min_sessions, skipped=skipped, qa=qa, qa_trend=trend)
    since_s, until_s = since.strftime("%Y-%m-%dT%H:%M:%SZ"), start.strftime("%Y-%m-%dT%H:%M:%SZ")
    out = args.out or state_dir / f"{start.strftime('%Y%m%dT%H%M%SZ')}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(agg, repo_key=key, since=since_s, until=until_s), encoding="utf-8", newline="")
    sidecar = {"schema": measure.SCHEMA, "repo_key": key, "since": since_s, "until": until_s,
               "sessions_read": agg["sessions_read"], "agent_dispatches": agg["agent_dispatches"], "signals": signal_table(sessions)}
    out.with_suffix(".json").write_text(json.dumps(sidecar, indent=2), encoding="utf-8", newline="")
    if not args.no_stamp:
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / STATE_NAME).write_text(json.dumps({"since": until_s}), encoding="utf-8", newline="")
    if args.json:
        print(json.dumps({**agg, "repo_key": key, "since": since_s, "until": until_s, "proposal": scrub(str(out), 500)}, indent=2))
    else:
        print(f"proposal written: {scrub(str(out), 500)} ({agg['sessions_read']} sessions read)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
