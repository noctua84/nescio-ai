#!/usr/bin/env python3
"""The durable per-repo tally of learnings a harvest could not route (#168).

ADR 0002 named "a harvest pass reports it cannot determine where to file a
learning" as a trigger for reopening the semantic-retrieval decision. That
trigger could never fire, because the signal was **unrepresentable**:
`promote_learnings.REQUIRED_FIELDS` demands a non-empty `target`, so a
nomination that could not be placed failed validation as malformed rather than
being recorded as an unrouted learning. ADR 0005 superseded 0002 still blind to
it. This module is the record that makes the condition expressible.

## Why it lives in the learning-trail directory, not in `receipt.json`

A trigger asks a question about *accumulated* history — "has the harvest been
unable to route learnings?" — and `receipt.json` answers only for one run. It is
written per-pass beside a manifest under a timestamped staging dir, so reading a
rate out of it means globbing an unbounded set of directories that a cleanup is
free to delete. The machine-local learning-trail directory already holds exactly
this class of state: the per-trail `.watermark` cursors and
`mark_harvested.py`'s `.harvest-pending-<repo_key>` marker both persist across
runs and both are deliberately *not* in git.

So the tally is keyed the same way those are:
``<trail dir>/<repo_key(<repo root>)>.unrouted.json``.

Three properties of that naming are load-bearing:

1. **`repo_key` of the REPOSITORY root, not the worktree root** — the identity
   `mark_harvested.pending_name` and `_trail_scope.current_repo_root` already
   agree on. A worktree is ephemeral (this framework's own `repo-hygiene` skill
   deletes them), so keying on one would strand the tally the moment the
   worktree went away, and a harvest run from the main checkout would read zero
   while the real count sat in an orphaned file.

2. **The extension is `.json`, emphatically not `.jsonl`.** Four callers —
   `compute_readiness`, `unmark_harvested` (twice) and `_trail_scope.trails_for_repo`
   — enumerate the trail dir with `glob("*.jsonl")` and treat every hit as a
   session trail. A `.jsonl` tally would be swept up as a trail: stamped with a
   watermark it has no use for, examined by `unmark_harvested`, and counted as a
   repo's trail by anything scoping a harvest. The extension is the thing that
   keeps this file out of that machinery.

3. **One document, rewritten atomically**, rather than an append log. The write
   is a temp-file + `os.replace`, mirroring `record_stop.write_watermark`, so a
   concurrent reader can never observe a half-written tally. An append log would
   survive concurrent *writers* better, but promote passes are serial and
   operator-driven while readers (`check_memory_triggers.py`) are not, so
   torn reads are the risk actually worth designing against.

## What is stored

`count` is the authoritative number the trigger reads — a monotonically
increasing total over the life of the file. `entries` is a bounded tail
(`MAX_ENTRIES`) kept for the human who wants to know *why* routing failed; it is
diagnostic, and a reader must never derive the count from `len(entries)`.
Keeping both is what lets the file stay small forever while the count stays
true.

Nothing here raises on a damaged file. A tally that cannot be read degrades to
"no record" so a reporter sweeping the trail dir cannot be derailed by one bad
entry, and a tally that cannot be *written* is reported by the caller as a lost
record rather than a failed promote — the learning itself was never going to
produce a note.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))
import record_stop as rs  # noqa: E402

# Bumped only on a breaking schema change. A reader that does not recognise a
# version says so and reports the trigger `unknown` rather than guessing at a
# count — the same refusal-to-guess `mark_harvested.py` applies to an
# unrecognised receipt version.
RECORD_VERSION = 1

# Suffix appended to `repo_key(<repo root>)`. See the module docstring on why
# this may never end in `.jsonl`.
RECORD_SUFFIX = ".unrouted.json"

# How many of the most recent entries the file keeps. The tally is forever; the
# diagnostic tail is not. Large enough that a reader can see the shape of a
# routing problem, small enough that the file cannot grow without bound.
MAX_ENTRIES = 50


def record_path(repo_dir: Path | str) -> Path:
    """Path of the unrouted tally for the repository that owns ``repo_dir``.

    Resolves ``repo_dir`` through ``git_roots``' second element — the
    *repository*, which outlives any worktree cut from it — so a harvest run
    from inside a linked worktree reads and writes the same tally as one run
    from the main checkout. Outside a git repository (a test's temp dir)
    ``git_roots`` returns its input unchanged, which gives that directory its
    own private key; that is what keeps the hermetic tests off the real tally.
    """
    repo_root = rs.git_roots(str(repo_dir))[1]
    return rs.trail_dir() / f"{rs.repo_key(repo_root)}{RECORD_SUFFIX}"


def read_record(path: Path) -> dict | None:
    """The tally at ``path``, or None when there is nothing usable to read.

    None covers every degraded case alike — absent, unreadable, not JSON, not an
    object, or carrying a `version` this module does not recognise. The caller
    cannot distinguish them and should not: all of them mean "this repo has no
    answer for trigger 3", which is `unknown`, not zero. Reporting an unreadable
    tally as a count of 0 would be the ADR 0004 failure mode exactly — missing
    evidence collapsing into a clean verdict.

    Never raises.
    """
    try:
        text = path.read_text(encoding="utf-8", newline="")
    except (OSError, ValueError):
        return None
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    if data.get("version") != RECORD_VERSION:
        return None
    if not isinstance(data.get("count"), int):
        return None
    return data


def append_unrouted(
    path: Path, *, reason: str, name: str, date: str, now: datetime | None = None
) -> dict:
    """Add one unrouted learning to the tally at ``path``; return the new record.

    Increments `count` and appends to the bounded `entries` tail. A damaged or
    absent file starts a fresh tally at 1 rather than refusing: the alternative
    is losing the signal to protect a file whose only content was the signal.

    Raises ``OSError`` — the caller decides whether that is fatal. In
    `promote_learnings` it is not: an unrouted nomination writes no note, so
    there is nothing half-done to roll back, and the run reports the lost record
    instead of failing.
    """
    existing = read_record(path)
    count = (existing or {}).get("count", 0)
    entries = (existing or {}).get("entries", [])
    if not isinstance(entries, list):
        entries = []

    stamp = (now or datetime.now(timezone.utc)).isoformat()
    entries = [*entries, {"name": name, "reason": reason, "date": date, "recorded_at": stamp}]
    record = {
        "version": RECORD_VERSION,
        "count": count + 1,
        "entries": entries[-MAX_ENTRIES:],
        "updated_at": stamp,
    }

    path.parent.mkdir(parents=True, exist_ok=True)
    # Per-process temp name so two racing writers never collide on a fixed one;
    # `os.replace` keeps the swap atomic. Same discipline as
    # `record_stop.write_watermark`, for the same reason: a reader may arrive at
    # any moment and must never see a partial file.
    tmp = path.parent / (path.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8", newline="")
    os.replace(tmp, path)
    return record
