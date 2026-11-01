#!/usr/bin/env python3
"""The ADR 0002 memory-trigger reminder, run from the SessionStart hook.

Split out of `harvest_nudge.py`: this module changes when
`scripts/check_memory_triggers.py`'s JSON payload shape or ADR 0002's trigger
set changes, whereas the harvest reminders change with the harvest flow.

`scripts/check_memory_triggers.py` evaluates ADR 0002's four memory-revisit
triggers but nothing invokes it, so a fired trigger can stay silent
indefinitely. This module shells out to it (as a subprocess — never imported,
the same boundary `harvest_nudge.py` applies to `mark_harvested.py`; see
`PENDING_PREFIX` there) against *this repo's* `memory/`, not the framework's
own, and produces at most two lines naming any trigger at `FIRED`, or — only
when nothing has fired — any trigger nearing its threshold. `t4-index-bypass`
always reports `unknown` here because transcript scanning is skipped for cost;
it is never rendered.

`harvest_nudge.main()` calls `trigger_nudge()` and prints its result *in
addition* to whichever harvest reminder fires. Every failure — missing trigger
script, a trigger-check timeout, malformed trigger JSON — degrades to '' rather
than raising.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import record_stop as rs  # noqa: E402

# Duplicated from harvest_nudge.NUDGE_SOURCES, not imported: harvest_nudge
# imports this module for main(), so importing back would be a cycle.
NUDGE_SOURCES = {"startup", "resume"}

# Measured 0.17s on a 12-note memory/, 0.23-0.26s on 556 notes (min of 3 runs
# each, --skip-transcripts --json). Generous headroom over that, still far
# short of anything a human notices at session start.
TRIGGER_TIMEOUT = 5  # seconds

# Only consulted when nothing has FIRED (see _near_threshold_lines). The live
# case motivating this — a directory at 95 of a ~100 threshold — sits well
# above 90%; that fraction leaves enough runway that a corpus growing by a
# note or two a day doesn't pick up a standing reminder for an extended
# stretch, the way a lower fraction (e.g. 80%) would.
NEAR_THRESHOLD_FRACTION = 0.9


def _framework_root() -> Path:
    """Repo root that owns this hook file, resolved through the hooks symlink.

    `install.py` symlinks the whole `hooks/` directory into `~/.claude/hooks/`;
    `Path.resolve()` follows that symlink back to the real checkout, so
    `<root>/scripts/check_memory_triggers.py` is reachable even though
    `scripts/` itself is never linked into `~/.claude/` (see module docstring).
    A copy-install with no such symlink still resolves to its own parent, which
    is exactly what's wanted there too.
    """
    return Path(__file__).resolve().parent.parent


def _trigger_payload(memory_root: Path, script: Path) -> dict | None:
    """Run check_memory_triggers.py against `memory_root`; its parsed JSON, or None.

    None on every failure: the subprocess timing out or erroring, a return
    code outside the script's own two defined exits (0 = clear, 1 = FIRED —
    its own EXIT_PASS/EXIT_FIRED), or stdout that isn't the JSON object it
    promises. rc 1 is deliberately accepted: it is the script's signal that a
    trigger fired, i.e. exactly the condition this reminder exists to surface,
    not a failure to degrade away from.
    """
    try:
        proc = subprocess.run(
            [
                sys.executable,
                str(script),
                "--memory-root",
                str(memory_root),
                "--skip-transcripts",
                "--json",
            ],
            capture_output=True,
            text=True,
            timeout=TRIGGER_TIMEOUT,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    if proc.returncode not in (0, 1):
        return None
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _fired_lines(payload: dict) -> list[str]:
    """Up to two lines naming FIRED triggers, each with its measured number and limit.

    Read from the payload's own structured fields (`corpus_notes`,
    `directory_notes`, `limits`) rather than from `headline`/`detail`, which are
    formatted for the full human report and not a contract this hook should
    parse. `t4-index-bypass` can never land here: with `--skip-transcripts` it
    is always `unknown` with `can_fire=False`, never `FIRED`.
    """
    triggers = payload.get("triggers")
    if not isinstance(triggers, list):
        return []
    fired = {
        t.get("trigger"): t
        for t in triggers
        if isinstance(t, dict) and t.get("verdict") == "FIRED"
    }
    limits = payload.get("limits")
    limits = limits if isinstance(limits, dict) else {}
    lines: list[str] = []

    if "t1-directory-size" in fired:
        dir_notes = payload.get("directory_notes")
        dir_limit = limits.get("directory")
        if isinstance(dir_notes, dict) and dir_notes and isinstance(dir_limit, int):
            largest = max(dir_notes.values())
            if isinstance(largest, int):
                lines.append(
                    f"Memory trigger FIRED (T1, ADR 0002): a memory/ directory "
                    f"holds {largest} notes, at or past the ~{dir_limit} "
                    f"revisit threshold."
                )

    if "t2-corpus-size" in fired and len(lines) < 2:
        corpus = payload.get("corpus_notes")
        corpus_limit = limits.get("corpus")
        if isinstance(corpus, int) and isinstance(corpus_limit, int):
            lines.append(
                f"Memory trigger FIRED (T2, ADR 0002): memory/ holds {corpus} "
                f"notes, at or past the ~{corpus_limit} revisit threshold."
            )

    if "t3-unrouted-harvest" in fired and len(lines) < 2:
        headline = fired["t3-unrouted-harvest"].get("headline")
        if isinstance(headline, str) and headline:
            lines.append(f"Memory trigger FIRED (T3, ADR 0002): {headline}.")

    return lines[:2]


def _near_threshold_lines(payload: dict) -> list[str]:
    """Up to two lines for T1/T2 nearing (but not past) their threshold.

    Only consulted when `_fired_lines` returned none: a FIRED trigger already
    implies this territory, and the combined budget is two lines either way.
    See `NEAR_THRESHOLD_FRACTION` for why 90%.
    """
    limits = payload.get("limits")
    limits = limits if isinstance(limits, dict) else {}
    lines: list[str] = []

    dir_notes = payload.get("directory_notes")
    dir_limit = limits.get("directory")
    if (
        isinstance(dir_notes, dict)
        and dir_notes
        and isinstance(dir_limit, int)
        and dir_limit > 0
    ):
        largest = max(dir_notes.values())
        if isinstance(largest, int) and largest >= dir_limit * NEAR_THRESHOLD_FRACTION:
            pct = largest * 100 // dir_limit
            lines.append(
                f"Memory trigger nearing threshold (T1, ADR 0002): a memory/ "
                f"directory holds {largest} notes ({pct}% of the ~{dir_limit} "
                f"revisit threshold)."
            )

    corpus = payload.get("corpus_notes")
    corpus_limit = limits.get("corpus")
    if (
        len(lines) < 2
        and isinstance(corpus, int)
        and isinstance(corpus_limit, int)
        and corpus_limit > 0
        and corpus >= corpus_limit * NEAR_THRESHOLD_FRACTION
    ):
        pct = corpus * 100 // corpus_limit
        lines.append(
            f"Memory trigger nearing threshold (T2, ADR 0002): memory/ holds "
            f"{corpus} notes ({pct}% of the ~{corpus_limit} revisit threshold)."
        )

    return lines[:2]


def trigger_message(repo_root: str) -> str:
    """Up to two lines about ADR 0002 memory triggers for `repo_root`, or ''.

    Shells out to scripts/check_memory_triggers.py (never imported — see module
    docstring) against *this repo's* `memory/`, never the framework's own: the
    framework's `memory/` would report the same dozen notes in every repo,
    which is worse than silence. Every failure — absent `memory/`, absent
    script, a subprocess timeout or crash, malformed or oddly-shaped JSON —
    degrades to '', exactly like every other reminder in this hook.
    """
    try:
        memory_root = Path(repo_root) / "memory"
        if not memory_root.is_dir():
            return ""
        script = _framework_root() / "scripts" / "check_memory_triggers.py"
        if not script.is_file():
            return ""
        payload = _trigger_payload(memory_root, script)
        if payload is None:
            return ""
        lines = _fired_lines(payload)
        if not lines:
            lines = _near_threshold_lines(payload)
        return "\n".join(lines)
    except Exception:
        return ""


def trigger_nudge(event: dict) -> str:
    """Return the ADR 0002 trigger reminder for this session, or '' to stay silent.

    Independent of `nudge()`'s two reminders: a fired memory-size trigger is a
    different subject from an unfinished or pending harvest, so the
    priority-exclusivity between those two does not apply here — this is
    printed in addition, not instead. Gated by the same `NUDGE_SOURCES` check
    as `nudge()`, for the same reason (nothing should print on `clear`/
    `compact`), and re-resolves the repo root independently rather than
    threading it through `nudge()`'s signature, matching this file's existing
    preference for small duplication over cross-function coupling.
    """
    if event.get("source") not in NUDGE_SOURCES:
        return ""
    cwd = str(event.get("cwd") or os.getcwd())
    root = rs.git_roots(cwd)[1]
    return trigger_message(root)
