#!/usr/bin/env python3
"""Stamp the harvest watermark for exactly the trails a harvest declared it read.

Run at the end of a `/harvest-memory` pass. The watermark is an assertion —
"every record in this trail at or below this timestamp was read and considered"
— and `hooks/record_stop.py` prunes on it: a record past the retention window
AND at-or-below the watermark is deleted. So a watermark that overstates its
coverage silently destroys undistilled session exhaust.

**The bug this shape exists to kill.** The old CLI stamped by inferring scope at
stamp time — `--all` swept every `<config>/learning-trail/*.jsonl` on the
machine. One harvest of one repo marked 2,438 records across 96 unrelated trails
as reviewed, which also zeroed those repos' `harvest_nudge.py` reminders (they
count records newer than the watermark). Nothing about the stamping step could
know which trails had actually been read, because the read had happened in
another process, minutes earlier, guided by a prompt.

So the harvest now **declares its subject up front**. `scripts/begin_harvest.py`
writes a read manifest (`read.json`) at step 1 recording which trails were
opened and the newest record seen in each; this script stamps that list and
nothing else, each trail at *its own* `max_ts` rather than a global read-time.
The watermark can then never claim coverage past the last record actually seen
in that file. Scope is data produced by the read, not a guess made afterwards.

**Refusing to stamp is not the same as failing.** This script runs at the very
end of a long interactive flow — notes, ledger, `MEMORY.md` and `readiness.md`
are already on disk by the time it is called. Exiting non-zero there strands the
operator: memory changed, trail unstamped, and the next harvest re-reads the same
records and may promote reworded near-duplicates. So an invalid or missing
manifest writes **nothing**, prints a loud banner with the exact command to
re-run, drops a `.harvest-pending-<repo_key>` marker for `hooks/harvest_nudge.py`
to surface at the next session start — and returns **0**. Non-zero is reserved
for argparse usage errors. The unsafe stamp is prevented without the flow being
wrecked, and the unfinished harvest is remembered by the very hook the original
bug silenced. An I/O error part-way through the stamping loop is handled the same
way: the trails that did land stay stamped (each was genuinely declared read, so
no invariant is broken), the failures are reported, a marker is dropped, and the
exit code stays 0.

**The promotion receipt is advisory.** `--receipt` is optional and can never
block a correctly-declared stamp. A pass that read 500 records and promoted one
satisfies "promoted >= 1" completely, so that was never the honest invariant;
the honest one is per-trail — *was this trail read* — and the manifest answers
it. A receipt reporting zero promotions is the legitimate "read it, kept
nothing" case: it warns and stamps. That is also why there is no `--allow-empty`
any more — there is no gate left to bypass, and a bypass flag decided by the
agent that tripped the gate was never a safeguard.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import record_stop as rs  # noqa: E402

READ_VERSION = 1
RECEIPT_VERSION = 1

# The unfinished-harvest marker is per repo: `<prefix><repo_key>`. See
# ``pending_name`` for why it may not be machine-global. `hooks/harvest_nudge.py`
# carries a byte-identical prefix and derivation (it must not import scripts/);
# tests/test_harvest_nudge.py pins the two together so a rename cannot orphan a
# marker.
PENDING_PREFIX = ".harvest-pending-"

REFUSE = "mark_harvested: refusing to stamp — "


# ---- watermark writing ---------------------------------------------------


def stamp_watermark(trail_path: Path, ts: datetime) -> Path:
    """Stamp the watermark paired with ``trail_path`` to ``ts``; return its path."""
    wm = rs.watermark_path(trail_path)
    rs.write_watermark(wm, ts)
    return wm


def mark_trails_harvested(trails: list[Path], *, now: datetime | None = None) -> list[Path]:
    """Stamp exactly the given ``trails`` to ``now`` (default: current UTC time).

    The caller decides which trails the harvest covered; this only writes.
    Returns the watermark paths written, empty when ``trails`` is empty. There is
    deliberately no machine-global counterpart — enumerating the trail dir is the
    bug, and a function that does it is a loaded gun left on the table.
    """
    ts = now or datetime.now(timezone.utc)
    return [stamp_watermark(trail, ts) for trail in trails]


# ---- the pending marker --------------------------------------------------


def pending_name(git_root_path: str) -> str:
    """Marker filename for one repository.

    The marker was originally a single machine-global ``.harvest-pending``, which
    quietly reintroduced the very cross-repo coupling the read manifest exists to
    remove. Two ways round: a successful harvest in repo B deleted repo A's
    still-unread warning (A's records then stayed un-harvested *and* unmentioned,
    the exact outcome the marker was invented to prevent), and while A's marker
    sat there every *other* repo on the machine got A's message in place of its
    own count nudge — one broken harvest blinding ~100 repos' reminders.

    Keying on ``repo_key(git_root)`` — the identity `record_stop.py` already uses
    for the trail filename — makes each repo's reminder independent. The priority
    of pending-over-count is deliberate and kept; only the scope changes.
    """
    return PENDING_PREFIX + rs.repo_key(git_root_path)


def pending_path(cwd: str | None = None) -> Path:
    """Path of the marker for the repo containing ``cwd`` (default: the real cwd)."""
    return rs.trail_dir() / pending_name(rs.git_root(cwd or os.getcwd()))


def write_pending(reason: str, read_arg: str | None, *, cwd: str | None = None) -> None:
    """Record that a harvest was left unstamped. Never raises.

    Written atomically (temp + ``os.replace``), mirroring
    ``record_stop.write_watermark``: `harvest_nudge.py` may read it at any moment
    and must never see a half-written file. Marker I/O is best-effort — failing
    to leave a note about a refusal must not turn the refusal into a crash.
    """
    try:
        where = cwd or os.getcwd()
        path = pending_path(where)
        payload = {
            "at": datetime.now(timezone.utc).isoformat(),
            "reason": reason,
            "read": read_arg,
            "cwd": where,
        }
        tmp = path.parent / (path.name + f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        return


def clear_pending(cwd: str | None = None) -> None:
    """Remove *this repo's* unfinished-harvest marker, if any. Never raises.

    Scoped on purpose: clearing every marker on the machine is how one repo's
    successful harvest used to erase another repo's unread warning.
    """
    try:
        pending_path(cwd).unlink()
    except Exception:
        return


# ---- the read manifest ---------------------------------------------------


def load_read_manifest(path: str | None) -> tuple[list[dict] | None, str | None]:
    """Parse a read manifest. Returns ``(trails, None)`` or ``(None, reason)``.

    ``reason`` is the operator-facing explanation appended to ``REFUSE``. Every
    check runs here, before a single watermark is touched, so a refusal is never
    partial. Entries that are individually unusable (not an object, no ``trail``
    name, a name that is not a bare basename) are dropped rather than fataling —
    but if nothing usable survives there is no declared scope at all, and that is
    a refusal.
    """
    if path is None:
        return None, (
            "no --read manifest given (pass the read.json written by "
            "begin_harvest.py at step 1 of the harvest)"
        )
    p = Path(path)
    try:
        raw = p.read_text(encoding="utf-8")
    except OSError:
        return None, f"read manifest not readable: {p}"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return None, f"read manifest is not valid JSON: {p} ({exc})"
    if not isinstance(data, dict):
        return None, f"read manifest is not a JSON object: {p}"
    if data.get("version") != READ_VERSION:
        return None, (
            f"read manifest version {data.get('version')!r} is not {READ_VERSION} "
            f"(schema changed; update mark_harvested.py before trusting it)"
        )
    trails = data.get("trails")
    if not isinstance(trails, list):
        return None, f"read manifest has no 'trails' list: {p}"
    usable = [
        entry
        for entry in trails
        if isinstance(entry, dict) and _trail_name(entry) is not None
    ]
    if not usable:
        return None, (
            f"read manifest names no usable trails: {p} — nothing was declared "
            f"read, so nothing may be marked reviewed"
        )
    return usable, None


def _trail_name(entry: dict) -> str | None:
    """The entry's trail basename, or None when it is missing or not a basename.

    ``trail`` is documented as a basename resolved against
    ``record_stop.trail_dir()``. Anything carrying a separator or a drive is
    refused rather than joined: a manifest is a file, and a file must not be able
    to steer this script at a watermark outside the trail directory.
    """
    name = entry.get("trail")
    if not isinstance(name, str) or not name.strip():
        return None
    name = name.strip()
    if name != Path(name).name or name in (".", ".."):
        return None
    return name


def _parse_ts(raw: object) -> datetime | None:
    """Parse an ISO8601 stamp to an aware UTC datetime, or None if unusable."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        parsed = datetime.fromisoformat(raw.strip())
    except (ValueError, TypeError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


# ---- the advisory receipt ------------------------------------------------


def check_receipt(path: str | None) -> str | None:
    """Inspect a promotion receipt. Return a warning to print, or None.

    Advisory only: the return value is never a refusal. The receipt's own
    ``manifest`` field is deliberately not resolved as a path — it is recorded
    verbatim as the operator typed it and may be relative or Windows-backslashed.
    Co-location beside the manifest is the authoritative link.
    """
    if path is None:
        return None
    p = Path(path)
    try:
        raw = p.read_text(encoding="utf-8")
    except OSError:
        return f"receipt not readable: {p} (stamping anyway — the receipt is an audit record, not a gate)"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return f"receipt is not valid JSON: {p} ({exc}) — stamping anyway"
    if not isinstance(data, dict):
        return f"receipt is not a JSON object: {p} — stamping anyway"
    if data.get("version") != RECEIPT_VERSION:
        return (
            f"receipt version {data.get('version')!r} is not {RECEIPT_VERSION}: "
            f"{p} — stamping anyway"
        )
    promoted = data.get("promoted")
    # bool is a subclass of int; `"promoted": true` is a malformed count, not 1.
    if not isinstance(promoted, int) or isinstance(promoted, bool):
        return f"receipt has no integer 'promoted' count: {promoted!r} — stamping anyway"
    if promoted == 0:
        return (
            "receipt records 0 promotions — this pass read the trails below and "
            "kept nothing. Stamping regardless: they were read. If that is a "
            "surprise, re-check the promote step before the retention window "
            "ages these records out."
        )
    return None


# ---- CLI -----------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mark_harvested.py",
        description="Stamp the harvest watermark for the trails named in a read manifest.",
    )
    # `--read` is intentionally NOT required: its absence is a refusal that must
    # still return 0 and leave a pending marker, not an argparse exit(2).
    parser.add_argument("--read", help="path to the read.json written by begin_harvest.py")
    parser.add_argument("--receipt", help="optional promote receipt.json (advisory)")
    return parser


def _rerun_command(read_arg: str | None, receipt_arg: str | None) -> str:
    read_part = read_arg if read_arg else "eval/learnings/<ts>/read.json"
    cmd = f'python scripts/mark_harvested.py --read "{read_part}"'
    if receipt_arg:
        cmd += f' --receipt "{receipt_arg}"'
    return cmd


def _refuse(reason: str, read_arg: str | None, receipt_arg: str | None) -> int:
    """Print the refusal banner, drop the pending marker, and return 0."""
    bar = "=" * 72
    print(bar, file=sys.stderr)
    print(f"{REFUSE}{reason}", file=sys.stderr)
    print(
        "No watermark was written. The harvest is UNSTAMPED: the records it read "
        "are still protected from pruning, and the next session start will remind "
        "you.",
        file=sys.stderr,
    )
    print("Fix the manifest, then re-run:", file=sys.stderr)
    print(f"    {_rerun_command(read_arg, receipt_arg)}", file=sys.stderr)
    print(bar, file=sys.stderr)
    write_pending(reason, read_arg)
    return 0


def main(argv: list[str] | None = None) -> int:
    """Stamp the manifest's trails, each at its own ``max_ts``. Returns 0 or 0.

    Non-zero escapes only via argparse usage errors (``SystemExit(2)``); every
    other failure is a refusal that writes nothing and returns 0. See the module
    docstring for why that separation matters here.
    """
    argv = sys.argv[1:] if argv is None else argv

    # The refusal banner uses an em dash and messages echo repo paths, which can
    # carry non-ASCII; a legacy Windows console defaults to cp1252 and would raise
    # UnicodeEncodeError — turning a clean refusal into a traceback (issue #55).
    # Reconfigure both streams to UTF-8 when possible (guarded — a redirected
    # StringIO in tests has no reconfigure).
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass

    args = _build_parser().parse_args(argv)

    entries, reason = load_read_manifest(args.read)
    if reason is not None:
        return _refuse(reason, args.read, args.receipt)
    assert entries is not None  # load_read_manifest's contract

    warning = check_receipt(args.receipt)
    if warning is not None:
        print(f"mark_harvested: WARNING {warning}", file=sys.stderr)

    stamped: list[tuple[str, datetime]] = []
    unchanged: list[str] = []
    skipped: list[tuple[str, str]] = []
    failed: list[tuple[str, str]] = []

    td = rs.trail_dir()
    now = datetime.now(timezone.utc)
    for entry in entries:
        name = _trail_name(entry)
        if name is None:  # unreachable: load_read_manifest filtered these out
            continue
        max_ts = _parse_ts(entry.get("max_ts"))
        if max_ts is None:
            skipped.append((name, "no records read (max_ts is null/unparseable)"))
            continue
        if max_ts > now:
            # Defence in depth. A watermark is an assertion that everything at or
            # below it was read; a future stamp asserts coverage of records that
            # do not exist yet, and record_stop's prune would then delete them
            # unread. begin_harvest.py clamps at read time, but this manifest is
            # just a file — hand-written, stale, or produced by an older writer —
            # so the stamping side refuses to take its word for it.
            print(
                f"mark_harvested: clamped {name}'s max_ts {max_ts.isoformat()} to "
                f"now ({now.isoformat()}) — a manifest may not stamp a watermark "
                f"into the future (clock skew or a hand-edited manifest?)",
                file=sys.stderr,
            )
            max_ts = now
        trail = td / name
        if not trail.is_file():
            skipped.append((name, "trail is absent from disk"))
            continue
        existing = rs.read_watermark(rs.watermark_path(trail))
        if existing is not None and existing >= max_ts:
            unchanged.append(name)
            continue
        try:
            stamp_watermark(trail, max_ts)
        except OSError as exc:
            # Disk full, permissions, an AV file lock on Windows. Letting this
            # escape would contradict this script's whole contract: a traceback
            # and a non-zero exit at the end of a harvest whose notes, ledger and
            # readiness are already on disk, with no marker left behind so the
            # SessionStart safety net never fires for this failure class. The
            # trails that did land stay stamped — each was genuinely declared
            # read, so a partial stamp breaks no invariant. Report and move on.
            failed.append((name, str(exc)))
            continue
        stamped.append((name, max_ts))

    for name, why in skipped:
        print(f"mark_harvested: skipped {name} — {why}", file=sys.stderr)
    for name in unchanged:
        print(
            f"mark_harvested: left {name} unchanged — its watermark is already "
            f"newer than this manifest's max_ts (never move a watermark backward)",
            file=sys.stderr,
        )
    for name, why in failed:
        print(
            f"mark_harvested: FAILED to stamp {name} — {why}. That trail is still "
            f"un-harvested; its records stay protected from pruning.",
            file=sys.stderr,
        )
    if failed:
        print(
            f"Fix the cause (disk space, permissions, a file lock), then re-run:\n"
            f"    {_rerun_command(args.read, args.receipt)}\n"
            f"Already-stamped trails are left alone on a re-run.",
            file=sys.stderr,
        )

    print(
        f"harvest watermark stamped for {len(stamped)} trail(s) "
        f"({len(unchanged)} unchanged, {len(skipped)} skipped"
        + (f", {len(failed)} FAILED" if failed else "")
        + f"); scope came from the read manifest {args.read}"
    )
    for name, ts in stamped:
        print(f"  {name} -> {ts.isoformat()}")

    if failed:
        # Leave the reminder standing: part of this harvest did not land.
        write_pending(
            f"{len(failed)} trail(s) could not be stamped "
            f"({', '.join(name for name, _ in failed)})",
            args.read,
        )
    else:
        clear_pending()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
