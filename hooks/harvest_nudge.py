#!/usr/bin/env python3
"""SessionStart hook: nudge to harvest when un-harvested trail records accumulate.

Reads the current repo's learning-trail and its harvest watermark; if the count of
un-harvested records (newer than the watermark) meets a threshold, prints a
one-line reminder to stdout, which Claude Code injects as session context. Fires
only on ``startup``/``resume``; silent on ``clear``/``compact``. Exits 0 always.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import record_stop as rs  # noqa: E402

try:
    NUDGE_THRESHOLD = int(os.environ.get("CLAUDE_HARVEST_NUDGE_THRESHOLD", "20"))
except ValueError:
    # A bad/empty env value must never crash the SessionStart hook at import.
    NUDGE_THRESHOLD = 20
NUDGE_SOURCES = {"startup", "resume"}


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
    root = rs.git_root(cwd)
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
