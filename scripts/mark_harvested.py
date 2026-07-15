#!/usr/bin/env python3
"""Stamp the harvest watermark for every learning-trail.

Run at the end of a successful /harvest-memory pass. `/harvest-memory` reads
ALL repos' trails, so stamping is GLOBAL: it writes a watermark for every
``<config>/learning-trail/*.jsonl`` so the Stop-hook pruner knows everything up
to the harvest read-time has been reviewed and only newer (un-harvested) records
are protected from the retention window.

The stamp uses the harvest READ-TIME (passed via ``--at``), not the moment this
script runs: records written *during* the harvest are newer than the read-time
watermark and stay protected, rather than being marked harvested and aging out
undistilled.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))
import record_stop as rs  # noqa: E402


def stamp_watermark(trail_path: Path, ts: datetime) -> Path:
    """Stamp the watermark paired with ``trail_path`` to ``ts``; return its path."""
    wm = rs.watermark_path(trail_path)
    rs.write_watermark(wm, ts)
    return wm


def mark_all_harvested(*, now: datetime | None = None) -> list[Path]:
    """Stamp every trail's watermark to ``now`` (default: current UTC time).

    Iterates every ``*.jsonl`` in the learning-trail dir and stamps its paired
    watermark. Returns the list of watermark paths written (empty if the trail
    dir holds no trails).
    """
    ts = now or datetime.now(timezone.utc)
    written: list[Path] = []
    for trail in sorted(rs.trail_dir().glob("*.jsonl")):
        written.append(stamp_watermark(trail, ts))
    return written


def _parse_at(argv: list[str]) -> datetime | None:
    """Extract ``--at <ISO8601>`` from argv; return None if absent.

    Raises ValueError on a malformed value so the caller can fall back to now().
    """
    if "--at" in argv:
        i = argv.index("--at")
        if i + 1 < len(argv):
            return datetime.fromisoformat(argv[i + 1])
        raise ValueError("--at requires an ISO8601 value")
    return None


def main(argv: list[str] | None = None) -> int:
    """Stamp all trails as harvested up to the read-time (``--at``) or now.

    Robust by design — this runs at the end of a harvest flow and must never
    hard-fail: a bad ``--at`` value logs to stderr and falls back to now(),
    still returning 0.
    """
    argv = sys.argv[1:] if argv is None else argv
    try:
        at = _parse_at(argv)
    except ValueError as exc:
        print(f"mark_harvested: invalid --at value, using now(): {exc}", file=sys.stderr)
        at = None
    now = at or datetime.now(timezone.utc)
    written = mark_all_harvested(now=now)
    print(f"harvest watermark stamped for {len(written)} trail(s) at {now.isoformat()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
