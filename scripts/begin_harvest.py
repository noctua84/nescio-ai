#!/usr/bin/env python3
"""Open a harvest by declaring, on the record, which trails it is about to read.

Run at step 1 of `/harvest-memory`, before anything is read. It captures the
read-time and writes `read.json` into the run's staging dir; step 8
(`mark_harvested.py`) stamps exactly the trails named there and nothing else.

**Why a declaration rather than a default.** The watermark is not bookkeeping —
it is an assertion that a human or agent *read and considered* those records, and
the Stop-hook pruner deletes on the strength of it. Step 1 has always read one
project's sources while stamping swept every trail on the machine, so a single
one-repo harvest declared 2,438 records across 96 unrelated repositories
reviewed and silently killed their `harvest_nudge.py` reminders. The asymmetry
was invisible because the two steps derived their scope independently. Writing
the subject down at the start removes the second derivation entirely: the read
and the stamp cite the same file.

That is also why `--repo` exists and why it only ever *adds*. An operator who
genuinely reads another repository's trail can say so — but it costs an explicit
flag and leaves a record in `read.json`, rather than being the invisible global
default that caused the bug.

`read.json` is a manifest of what will be read, not of what was found. It is
written before the reading starts and is never revised afterwards: a trail that
turns out to hold nothing worth promoting was still read, and is still the
harvest's subject.

Every trail's `max_ts` is bounded by the read-time, because nothing written after
the file was opened can have been read. That bound is what stops a single
clock-skewed record from handing step 8 a watermark reaching weeks into the
future — see `scan_trail` for why the two directions of clock error are not
equally dangerous.

The staging dir mirrors the adopt flow's `eval/adopt/<ts>/` inbox and is where
step 5's `manifest.json` and step 7's `receipt.json` also land, so one harvest's
whole paper trail sits in one directory. `eval/` is gitignored by design — this
is scratch evidence for one run, not repo content.

Usage:
    python scripts/begin_harvest.py                       # the current repo
    python scripts/begin_harvest.py --repo ../other-repo  # ...and that one too
    python scripts/begin_harvest.py --out eval/learnings/mine
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))

import _trail_scope as scope  # noqa: E402
from _learning_common import REPO_DIR  # noqa: E402

# Bumped only on a breaking change to the read.json schema below. Consumers
# (`mark_harvested.py`) refuse a version they do not understand rather than
# guessing at a field, so a silent shape change must not reuse this number.
READ_VERSION = 1

READ_NAME = "read.json"

# Compact UTC stamp for the staging dir. Sortable, filename-safe on Windows
# (no colons), and matching the adopt flow's `eval/adopt/<ts>/` convention.
STAMP_FMT = "%Y%m%dT%H%M%S"


def scan_trail(
    trail_path: Path, read_at: datetime | None = None
) -> tuple[int, str | None, str | None]:
    """`(record count, max ts, clamped-away ts)` for one trail; `(0, None, None)` when empty.

    The max is taken over the whole file rather than the tail, because append
    order is only *usually* chronological: several windows and worktrees on one
    repo append to the same trail concurrently, and a machine whose clock stepped
    backwards leaves a later line holding an earlier `ts`. A watermark derived
    from a non-maximal timestamp would leave records above it looking
    un-harvested forever, so the real max is worth the full read.

    **The max is then clamped to ``read_at``.** A clock excursion is not
    symmetric, and the max alone only defends the harmless direction. A clock
    that steps *backwards* fails **safe**: records look un-harvested, so they are
    kept and re-read. A clock that steps *forwards* — an RTC in local time on a
    dual boot, a VM resumed from suspend, a container before NTP settles — fails
    **unsafe**: one record stamped a month ahead drags the watermark a month
    ahead with it, and for that month every genuinely new record lands at-or-below
    it. `harvest_nudge` then reports nothing to harvest, `compute_readiness`
    counts nothing un-harvested, and `record_stop.prune_lines` deletes records
    nobody ever read — this script's founding bug, arriving through data instead
    of through scope. One skewed turn is enough, so the unsafe direction is the
    one to design for.

    Clamping to the read-time never under-claims: a record dated in the future was
    still physically appended before the file was opened, so ``read_at`` covers it
    too. It simply refuses to claim coverage of records that had not been written
    yet. ``read_at`` defaults to the current instant rather than to "no bound",
    because an unclamped max is the failure this parameter exists to prevent; a
    caller scanning several trails should pass one captured instant so every trail
    is bounded against the same moment.

    The third element is the raw max that was clamped away, or None when no clamp
    fired. A future-dated record is a real anomaly on this machine, and the
    operator is told rather than having it quietly corrected.

    Naive timestamps are treated as UTC — the same reading `record_stop`'s pruner
    applies — so a legacy record cannot raise on comparison against an aware one,
    and the returned string is the normalised, timezone-aware rendering of the
    winner. Records whose `ts` will not parse still count toward the record total
    but cannot win the max: they carry no usable time, and inventing one would
    stamp a watermark over records nobody placed in time.

    Never raises. An unreadable trail reads as empty, because a harvest must not
    be derailed at step 1 by one bad file in a machine-global directory.
    """
    bound = read_at if read_at is not None else datetime.now(timezone.utc)
    records = 0
    best: datetime | None = None
    try:
        with open(trail_path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(rec, dict):
                    continue
                records += 1
                try:
                    parsed = datetime.fromisoformat(str(rec.get("ts", "")))
                except (ValueError, TypeError):
                    continue
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                if best is None or parsed > best:
                    best = parsed
    except (OSError, ValueError, TypeError):
        return 0, None, None
    if best is None:
        return records, None, None
    if best > bound:
        return records, bound.isoformat(), best.isoformat()
    return records, best.isoformat(), None


def collect(
    repos: list[Path], read_at: datetime
) -> tuple[list[str], list[dict], dict[str, list[str]], list[tuple[str, str]]]:
    """Resolve the subject repos into `(repos, trails, per-repo names, clamps)`.

    ``read_at`` is the harvest's single captured read-time and is threaded into
    every scan, so a trail is never bounded against a different instant than its
    neighbour — the manifest's `read_at` and every `max_ts` in it then describe
    one consistent moment. ``clamps`` is `(trail name, clamped-away ts)` for each
    trail that held a future-dated record, for the caller to report.

    A trail is deduped by filename: two subject repos can select the same file
    (a nested checkout, or the same repo named twice on the command line), and it
    must appear — and be stamped — exactly once. The first repo to claim it, in
    sorted order, is the one whose `repo_root` is recorded on the entry, so the
    output does not depend on the order the operator typed `--repo`.

    The per-repo name lists are returned alongside rather than derived from
    ``trails``, because dedup makes those two views differ: a trail selected by
    two repos appears once in ``trails`` but is genuinely in scope for both, and
    the summary must not tell the second repo it has nothing when it does.

    One repo-root cache is allocated here and shared across every subject repo.
    Attribution resolves a live path through `git` at most once per distinct
    `git_root` that way; unshared, a machine with ~100 trails forks ~100
    subprocesses per subject repo. The cache is keyed on the recorded path, not on
    the repo being tested, so sharing it across repos cannot change any answer.
    """
    roots = sorted({scope.posix_path(r) for r in repos})
    cache: dict[str, str] = {}
    by_name: dict[str, dict] = {}
    claimed: dict[str, list[str]] = {}
    clamps: list[tuple[str, str]] = []
    for root in roots:
        matched = scope.trails_for_repo(Path(root), cache=cache)
        claimed[root] = [t.name for t in matched]
        for trail in matched:
            if trail.name in by_name:
                continue
            records, max_ts, clamped_from = scan_trail(trail, read_at)
            if clamped_from is not None:
                clamps.append((trail.name, clamped_from))
            by_name[trail.name] = {
                "trail": trail.name,
                "repo_root": root,
                "records": records,
                "max_ts": max_ts,
            }
    return roots, [by_name[n] for n in sorted(by_name)], claimed, clamps


def write_read(out_dir: Path, payload: dict) -> Path:
    """Write ``payload`` as ``read.json`` under ``out_dir``; return its path."""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / READ_NAME
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def default_out_dir(read_at: datetime) -> Path:
    """Staging dir for a harvest opened at ``read_at``: `eval/learnings/<stamp>/`."""
    return REPO_DIR / "eval" / "learnings" / read_at.strftime(STAMP_FMT)


def main(argv: list[str] | None = None) -> int:
    """Declare the harvest's subject and stamp the read-time. Always returns 0.

    A subject repo with no trails is reported, not refused: a repo may simply
    never have run a session on this machine. It is printed loudly all the same,
    because it is the difference between "step 8 will stamp this repo" and "step
    8 will stamp nothing for this repo", and that is exactly the confusion this
    script exists to end.
    """
    read_at = datetime.now(timezone.utc)

    # Repo paths and the ISO read-time can carry non-ASCII, and a legacy Windows
    # console defaults to cp1252 — which would turn a successful open into a
    # UnicodeEncodeError traceback (#55). Guarded: a redirected StringIO in tests
    # has no `reconfigure`.
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass

    ap = argparse.ArgumentParser(
        description="Open a harvest: record its read-time and the trails it will read."
    )
    ap.add_argument(
        "--repo",
        action="append",
        default=[],
        metavar="PATH",
        help="additional repository to include (repeatable); the current repo is always included",
    )
    ap.add_argument(
        "--out",
        metavar="DIR",
        help="staging dir for read.json (default: eval/learnings/<UTC timestamp>/)",
    )
    # None (the CLI path) means "read sys.argv"; a list is what tests pass.
    args = ap.parse_args(argv)

    repos = [scope.current_repo_root()] + [Path(r).resolve() for r in args.repo]
    roots, trails, claimed, clamps = collect(repos, read_at)

    out_dir = Path(args.out) if args.out else default_out_dir(read_at)
    read_path = write_read(
        out_dir,
        {
            "version": READ_VERSION,
            "read_at": read_at.isoformat(),
            "repos": roots,
            "trails": trails,
        },
    )

    print(read_at.isoformat())
    print(read_path.resolve())
    # A clamp means this machine wrote a record dated after the moment the file
    # was opened — a clock excursion, not a normal state. Say so: correcting it
    # silently would hide the very anomaly the operator needs to go fix.
    for name, future_ts in clamps:
        print(
            f"{name}: clamped max_ts to the read-time — a record is dated "
            f"{future_ts}, after this harvest opened (clock skew?)"
        )
    by_name = {t["trail"]: t for t in trails}
    for root in roots:
        names = claimed[root]
        if not names:
            print(
                f"{root}: no learning-trails — step 8 will stamp nothing for this repo"
            )
            continue
        total = sum(by_name[n]["records"] for n in names)
        print(f"{root}: {len(names)} trail(s), {total} record(s)")
    print(
        f"next: python scripts/promote_learnings.py {out_dir / 'manifest.json'} "
        f"(draft the manifest there first)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
