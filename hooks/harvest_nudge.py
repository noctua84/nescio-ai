#!/usr/bin/env python3
"""SessionStart hook: nudge to harvest, and surface a harvest left unstamped.

Two reminders, in priority order:

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

The irony is deliberate: the machine-global stamping bug was invisible precisely
because it silenced this hook (a spurious watermark zeroes every count), so this
hook is now also what catches a stamp that did not happen.

Output goes to stdout, which Claude Code injects as session context. Fires only
on ``startup``/``resume``; silent on ``clear``/``compact``. Exits 0 always, and
every failure — unreadable or malformed marker included — degrades to the next
reminder rather than raising.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import record_stop as rs  # noqa: E402

try:
    NUDGE_THRESHOLD = int(os.environ.get("CLAUDE_HARVEST_NUDGE_THRESHOLD", "20"))
except ValueError:
    # A bad/empty env value must never crash the SessionStart hook at import.
    NUDGE_THRESHOLD = 20
NUDGE_SOURCES = {"startup", "resume"}

# Written by scripts/mark_harvested.py when it refuses to stamp. Kept in sync
# with its PENDING_PREFIX/pending_name by duplication, not by import: this hook
# must not depend on scripts/ being importable. tests/test_harvest_nudge.py pins
# the prefix *and* the derivation against mark_harvested's so a rename on either
# side cannot silently orphan the marker.
PENDING_PREFIX = ".harvest-pending-"


def pending_name(git_root_path: str) -> str:
    """Marker filename for one repository — see mark_harvested.pending_name."""
    return PENDING_PREFIX + rs.repo_key(git_root_path)


def pending_message(git_root_path: str) -> str:
    """Reminder about *this repo's* unstamped harvest, or '' when there is none.

    Scoped to ``git_root_path``: a marker left by some other repo on this machine
    is none of this session's business, and must not displace the count nudge the
    current repo would otherwise have got.

    Best-effort by design: a missing marker, an unreadable one, or one whose JSON
    is malformed all return '' so the caller falls through to the ordinary count
    nudge. A broken marker must never cost the operator the reminder they would
    otherwise have got.
    """
    try:
        path = rs.trail_dir() / pending_name(git_root_path)
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
    # One git_root call serves both the marker name and the trail name — they are
    # the same repo identity, and the hook must stay cheap.
    root = rs.git_root(cwd)
    # This repo's unfinished harvest outranks "you have records": the first is a
    # job left half-done, the second is the normal accumulation it was meant to
    # clear. Another repo's marker is not consulted at all.
    pending = pending_message(root)
    if pending:
        return pending
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
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
