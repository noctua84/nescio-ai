#!/usr/bin/env python3
"""SessionStart hook: nudge to harvest, surface a harvest left unstamped, and
flag a fired ADR 0002 memory-revisit trigger.

Three reminders. The first two are priority-ordered against each other; the
third is an independent subject and is printed *in addition* to whichever of
the first two fires, never instead:

1. **An unfinished harvest.** `scripts/mark_harvested.py` drops a
   ``.harvest-pending-<repo_key>`` marker when it refuses to stamp a watermark (a
   missing or invalid read manifest) or when a stamp fails part-way. That refusal
   happens at the very end of a harvest, after notes and ledger are already
   written, and it returns 0 so as not to strand the flow — which means nothing
   else would ever mention it again. This takes priority over the ordinary count
   nudge: records piling up is routine, a harvest that half-landed is not. The
   marker is keyed **per repo**, so another repo's unfinished harvest can neither
   suppress this repo's count nudge nor be erased by this repo's next stamp.
2. **Un-harvested records.** Reads the current repo's learning-trail and its
   harvest watermark; if the count of records newer than the watermark meets a
   threshold, prints a one-line reminder.
3. **A fired (or near-fired) ADR 0002 memory trigger.** `scripts/check_memory_
   triggers.py` evaluates ADR 0002's four memory-revisit triggers but nothing
   invokes it, so a fired trigger can stay silent indefinitely. This hook shells
   out to it (as a subprocess — never imported, see `PENDING_PREFIX` below for
   the same boundary applied to `mark_harvested.py`) against *this repo's*
   `memory/`, not the framework's own, and prints at most two lines naming any
   trigger at `FIRED`, or — only when nothing has fired — any trigger nearing
   its threshold. `t4-index-bypass` always reports `unknown` here because
   transcript scanning is skipped for cost; it is never rendered.

The irony is deliberate: the machine-global stamping bug was invisible precisely
because it silenced this hook (a spurious watermark zeroes every count), so this
hook is now also what catches a stamp that did not happen.

Output goes to stdout, which Claude Code injects as session context. Fires only
on ``startup``/``resume``; silent on ``clear``/``compact``. Exits 0 always, and
every failure — unreadable or malformed marker, missing trigger script, a
trigger-check timeout, malformed trigger JSON — degrades to silence on that one
reminder rather than raising or suppressing the others.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import record_stop as rs  # noqa: E402

try:
    NUDGE_THRESHOLD = int(os.environ.get("CLAUDE_HARVEST_NUDGE_THRESHOLD", "20"))
except ValueError:
    # A bad/empty env value must never crash the SessionStart hook at import.
    NUDGE_THRESHOLD = 20
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

# Written by scripts/mark_harvested.py when it refuses to stamp. Kept in sync
# with its PENDING_PREFIX/pending_name by duplication, not by import: this hook
# must not depend on scripts/ being importable. tests/test_harvest_nudge.py pins
# the prefix *and* the derivation against mark_harvested's so a rename on either
# side cannot silently orphan the marker.
PENDING_PREFIX = ".harvest-pending-"


def pending_name(repo_root_path: str) -> str:
    """Marker filename for one repository — see mark_harvested.pending_name.

    Takes the **repository** root, not the worktree root, matching the writer.
    """
    return PENDING_PREFIX + rs.repo_key(repo_root_path)


def pending_message(repo_root_path: str) -> str:
    """Reminder about *this repo's* unstamped harvest, or '' when there is none.

    Scoped to ``repo_root_path``: a marker left by some other repo on this machine
    is none of this session's business, and must not displace the count nudge the
    current repo would otherwise have got.

    Best-effort by design: a missing marker, an unreadable one, or one whose JSON
    is malformed all return '' so the caller falls through to the ordinary count
    nudge. A broken marker must never cost the operator the reminder they would
    otherwise have got.
    """
    try:
        path = rs.trail_dir() / pending_name(repo_root_path)
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return ""
        reason = str(data.get("reason") or "no reason recorded")
        read = data.get("read")
        where = f" Read manifest: {read}" if read else " No read manifest was given."
        return (
            f"A previous /harvest-memory finished WITHOUT stamping its harvest "
            f"watermark: {reason}.{where} Those records are still un-harvested and "
            f"protected from pruning. Re-run scripts/mark_harvested.py with a valid "
            f"--read manifest, or re-run /harvest-memory."
        )
    except Exception:
        return ""


def count_unharvested(trail_path: Path, watermark, *, limit=None) -> int:
    """Number of parseable trail records newer than the watermark (0 if unreadable).

    When ``limit`` is set, counting short-circuits: as soon as the running count
    reaches ``limit`` the scan stops and returns ``limit``, so a huge trail is
    never fully parsed just to confirm the nudge threshold is met.
    """
    try:
        lines = trail_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return 0
    n = 0
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rs._is_unharvested(str(rec.get("ts", "")), watermark):
            n += 1
            if limit is not None and n >= limit:
                return limit
    return n


def nudge(event: dict) -> str:
    """Return the reminder string to emit, or '' to stay silent."""
    if event.get("source") not in NUDGE_SOURCES:
        return ""
    cwd = str(event.get("cwd") or os.getcwd())
    # One git_roots call serves both the marker name and the trail name — they are
    # the same repo identity, and the hook must stay cheap. Element [1] is the
    # *repository* root, not [0] (the worktree): this is the identity
    # `_trail_scope.current_repo_root` and `begin_harvest.py` use, so the nudge
    # and the harvest agree about which repo is being discussed. Keying on the
    # worktree made both halves wrong — a marker written in a worktree was
    # orphaned when that worktree was deleted, and a session started in a fresh
    # worktree counted only that worktree's near-empty trail, so the threshold
    # was unreachable in exactly the worktree-driven workflow this framework
    # mandates.
    root = rs.git_roots(cwd)[1]
    # This repo's unfinished harvest outranks "you have records": the first is a
    # job left half-done, the second is the normal accumulation it was meant to
    # clear. Another repo's marker is not consulted at all.
    pending = pending_message(root)
    if pending:
        return pending
    # KNOWN UNDERCOUNT: this reads only the repo's *canonical* trail, not the
    # aggregate across its worktree trails, so the count is a lower bound and a
    # repo whose recent work all happened in worktrees can stay below the
    # threshold. Closing that gap means sweeping the machine-global trail dir
    # (potentially hundreds of files on a well-used machine, with a possible `git`
    # subprocess per unattributable trail) inside a *synchronous* SessionStart
    # hook — a latency tax on every session start, paid for a reminder. Not worth
    # it: the nudge is a tripwire, `begin_harvest.py` does the accurate aggregate,
    # and the message already says "(N+)".
    trail = rs.trail_dir() / f"{rs.repo_key(root)}.jsonl"
    if not trail.exists():
        return ""
    watermark = rs.read_watermark(rs.watermark_path(trail))
    # Cap the scan at the threshold: an exact count isn't needed above it.
    count = count_unharvested(trail, watermark, limit=NUDGE_THRESHOLD)
    if count >= NUDGE_THRESHOLD:
        return (
            f"You have un-harvested learning-trail records ({count}+) for this "
            f"repo. Consider running /harvest-memory to distil them into memory/."
        )
    return ""


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


def main() -> int:
    try:
        # Issue #55, applied to a hook. This output interpolates
        # operator-controlled path strings (the manifest path recorded in the
        # marker) and hook stdout is a pipe, which on Windows takes the ANSI
        # codepage — so a manifest path outside cp1252 raises UnicodeEncodeError.
        # The blanket handler below would turn that into silence: rc 0, nothing
        # printed, and because the marker persists it would fail identically
        # every session. The reminder for the exact failure this hook exists to
        # catch would be lost permanently and invisibly.
        try:
            sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass
        raw = sys.stdin.read()
        event = json.loads(raw)
        if not isinstance(event, dict):
            return 0
        msg = nudge(event)
        if msg:
            print(msg)
        # A different subject from the two reminders above (see trigger_nudge's
        # docstring): printed in addition, never in place of them.
        trig = trigger_nudge(event)
        if trig:
            print(trig)
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
