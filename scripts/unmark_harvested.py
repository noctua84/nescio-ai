#!/usr/bin/env python3
"""Revert one bad *global* harvest stamp by deleting the watermarks it wrote.

`scripts/mark_harvested.py` used to stamp every trail on the machine. On
2026-08-20 a harvest of a single repository stamped **105** watermarks with one
identical instant; only ~9 of them belonged to the repo that was actually read.
The other ~96 declared **2,438 records reviewed that no harvest ever opened**.
This script undoes exactly that: given the offending instant, it finds the
watermarks holding it and removes them.

## Why deletion, and not restoring the previous value

Because there is no previous value left to restore. `record_stop.write_watermark`
is a whole-file `os.replace` — the prior timestamp was overwritten in place, and
every one of the 105 files on disk now holds the *same* instant, so nothing older
survives anywhere to copy back from. Deletion is also the state the consumers
already understand: `record_stop._is_unharvested` reads a missing watermark as
``watermark is None`` and treats **every** parseable record as un-harvested. That
is the maximally protective reading, and it is precisely what puts the records
back in front of a human.

## What this buys

`hooks/harvest_nudge.py` counts records newer than the watermark and reminds the
operator at `NUDGE_THRESHOLD` (20 by default). A watermark stamped *after* every
record in its trail makes that count 0 for ever, so the nudge went silent for
~96 repositories on 2026-08-20 and has stayed silent since. Removing the
watermark restores the count and the reminder with it. That is the real, present
harm being repaired — the report below leads with it.

The pruner is deliberately *not* oversold here. `record_stop._maybe_prune`
returns immediately unless a trail exceeds ``PRUNE_SIZE_THRESHOLD`` (1,000,000
bytes) and the largest trail on the machine that prompted this tool was 212 KB,
so nothing was on the verge of being deleted. Claiming otherwise would be a
scare, and the tool would deserve less trust the next time it says something is
urgent.

## What it costs — read this before running with --apply

Deleting the watermark does not merely rewind the review pointer; it **switches
the retention window off** for those records. `prune_lines` keeps a record when
it is within `RETENTION_DAYS` (14) **or** un-harvested, and with no watermark
every parseable record is un-harvested — so the affected trails are now retained
**indefinitely** rather than for 14 days, bounded only by the
``ABSOLUTE_MAX_RECORDS`` (10,000) backstop, and only once a trail is large enough
for the pruner to run at all.

That matters because of what a trail record contains: up to 500 characters of
assistant output (`record_stop.PREVIEW_MAX` / `message_preview`), absolute
filesystem paths, and branch names. `record_stop.redact()` matches credential
*shapes* — API keys, tokens, JWTs, PEM headers — and nothing else. Names, email
addresses, customer identifiers, and anything else a human wrote in prose pass
through untouched. Keeping that data on disk for ever is a genuine trade against
getting the nudges back, it is unresolved at the time of writing, and the
operator is owed the choice rather than the surprise. Re-running a legitimate,
repo-scoped `/harvest-memory` re-stamps the trail and restores the window.

## Usage

    python scripts/unmark_harvested.py --stamp <ISO8601>
    python scripts/unmark_harvested.py --stamp <ISO8601> --keep-repo <path>
    python scripts/unmark_harvested.py --stamp <ISO8601> --keep-repo <path> --apply

Dry run is the default and deletes nothing; `--apply` deletes. That split mirrors
`compute_readiness.py` and the `repo_hygiene_scan.py` / `repo_hygiene_apply.py`
pair, so every destructive tool in this repo is armed the same way. The dry run
is not quite *write*-free: it resolves the trail dir through
`record_stop.trail_dir`, which creates `<config>/learning-trail/` when absent
rather than have this file duplicate that path literal. An empty directory is the
only thing a dry run can leave behind.

`--stamp` is compared as a **parsed instant**, not as a string, so
``2026-08-20T11:30:14.126690+00:00`` and ``2026-08-20T13:30:14.126690+02:00``
select the same watermarks. `--keep-repo` is repeatable and exempts a repository
whose stamp was legitimately earned; it routes through
`_trail_scope.belongs_to_repo`, so the kept repo's linked-worktree trails are
exempt too.

## Why --keep-repo is resolved, and why an unmatched one stops the run

`belongs_to_repo` compares normalised posix strings for **equality**, so an
un-normalised `--keep-repo` matches nothing at all — `.` and `../nescio-ai`, the
two most natural things to type while standing in the repo you mean to protect,
would exempt nothing and the repo would be deleted from under the flag meant to
save it. Every value therefore goes through `resolve_keep_root` before it is
compared, exactly as `begin_harvest.py` resolves its `--repo`.

Resolution cannot make every spelling match, and a silently inert safety flag on
a tool with no undo is the wrong failure mode. So a `--keep-repo` that matches
**no trail on this machine** refuses the run under `--apply` (rc 1, nothing
deleted) and prints a loud warning in the dry run. Matching is checked against
every trail, not only the ones holding the stamp: a kept repo whose watermarks
happen to hold some *other* stamp is legitimately a no-op exemption, and calling
that an error would be a false alarm.

Every step is best-effort per file: an unreadable trail, an unparseable watermark
value, or an undeletable file is reported and the run continues. A `.jsonl` is
never touched, and a trail with no watermark is left exactly as it is.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import record_stop as rs  # noqa: E402
import harvest_nudge  # noqa: E402
import _trail_scope as scope  # noqa: E402

WATERMARK_SUFFIX = ".watermark"

# Group label for a trail whose owning repository cannot be determined — an
# empty or wholly unparseable trail has no record to resolve a root from. Such a
# trail is still a candidate; only its *grouping* is unknown.
UNATTRIBUTED = "(unattributed — no record names a repository)"

# Statuses a scanned trail can carry. Only "candidate" is ever deleted.
CANDIDATE = "candidate"
EXEMPT = "exempt"
OTHER_STAMP = "other-stamp"
UNPARSEABLE = "unparseable"
UNREADABLE = "unreadable"
NO_WATERMARK = "no-watermark"


def parse_stamp(raw: str) -> datetime:
    """Parse an ISO8601 instant, defaulting a naive value to UTC.

    Raises `argparse.ArgumentTypeError` so a bad `--stamp` surfaces as a usage
    error. There is no now() fallback here on purpose: `mark_harvested` may
    degrade a bad `--at` because a mistimed stamp is recoverable, but a mistyped
    stamp on a *deleting* tool would silently select a different set of files.
    """
    try:
        parsed = datetime.fromisoformat(str(raw))
    except (ValueError, TypeError) as exc:
        raise argparse.ArgumentTypeError(
            f"--stamp {raw!r} is not an ISO8601 timestamp ({exc})"
        ) from exc
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def resolve_keep_root(raw: str) -> Path:
    """Absolute, normalised form of one ``--keep-repo`` value.

    `_trail_scope.belongs_to_repo` compares posix strings for **equality** and
    deliberately does not case-fold, so a value that is not already spelled the
    way the trail records spell it exempts nothing. `Path.resolve` is what closes
    most of that gap: it absolutises `.` and `../repo`, drops a trailing slash,
    normalises separators, and — on Windows, for a path that exists — recovers
    the canonical on-disk casing. It is the same call `begin_harvest.py:197`
    makes on its `--repo`, so the two tools scope a repository identically.

    Non-strict on purpose (`resolve()` does not require the path to exist): a
    repository deleted since its trail was written is still a repository whose
    stamp the operator may want kept, and `belongs_to_repo`'s textual worktree
    parse can still match it.
    """
    return Path(raw).resolve()


def unmatched_keep_roots(trail_dir: Path, keep_roots: list[Path]) -> list[Path]:
    """The ``keep_roots`` that own no trail under ``trail_dir``, in input order.

    "Owns no trail" — not "exempts no candidate". A kept repo whose watermarks
    hold a different stamp exempts nothing and that is entirely correct; only a
    root the tool cannot see *at all* means the operator asked to protect
    something this run cannot reason about.
    """
    trail_dir = Path(trail_dir)
    trails = sorted(trail_dir.glob("*.jsonl")) if trail_dir.is_dir() else []
    return [
        root
        for root in keep_roots
        if not any(scope.belongs_to_repo(trail, root) for trail in trails)
    ]


@dataclass
class Finding:
    """One scanned trail: what its watermark is, and what removing it would do."""

    trail: Path
    watermark: Path
    repo: str
    status: str
    detail: str = ""
    returning: int = 0          # records at/below the stamp — would go un-harvested
    already: int = 0            # records above the stamp — un-harvested already
    unparseable_records: int = 0
    trail_unreadable: bool = False

    @property
    def after(self) -> int:
        """Un-harvested count this trail would report once the watermark is gone."""
        return self.returning + self.already

    @property
    def revives_nudge(self) -> bool:
        """True when removal takes this trail from below the nudge threshold to at/above it.

        `harvest_nudge` scopes itself to one trail (the `repo_key` of the cwd's
        worktree root), so the threshold is evaluated per trail rather than per
        repository — summing a repo's trails would claim a revival that the hook
        would not actually produce.
        """
        threshold = harvest_nudge.NUDGE_THRESHOLD
        return self.already < threshold <= self.after


def _count_records(finding: Finding, stamp: datetime) -> None:
    """Fill in the record counts for ``finding`` by reading its trail.

    Classification is delegated to `record_stop._is_unharvested` so this tool and
    the hooks can never disagree about what "un-harvested" means: with a
    watermark of None it answers "is this ``ts`` parseable at all", and with the
    stamp it answers "is this record already newer than the stamp".

    An unreadable trail sets ``trail_unreadable`` and leaves the counts at zero
    rather than aborting — the watermark is still a valid candidate, only its
    impact is unknown.
    """
    try:
        lines = finding.trail.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        finding.trail_unreadable = True
        return
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except ValueError:
            finding.unparseable_records += 1
            continue
        if not isinstance(record, dict):
            finding.unparseable_records += 1
            continue
        ts = str(record.get("ts", ""))
        if not rs._is_unharvested(ts, None):
            finding.unparseable_records += 1
        elif rs._is_unharvested(ts, stamp):
            finding.already += 1
        else:
            finding.returning += 1


def examine(trail: Path, stamp: datetime, keep_roots: list[Path]) -> Finding:
    """Classify one trail against ``stamp`` and the ``--keep-repo`` exemptions.

    Never raises: every failure to read or parse degrades to a reported,
    non-deleting status.
    """
    watermark = rs.watermark_path(trail)
    repo = scope.trail_repo_root(trail) or UNATTRIBUTED

    def make(status: str, detail: str = "") -> Finding:
        return Finding(
            trail=trail, watermark=watermark, repo=repo, status=status, detail=detail
        )

    # Belt and braces. `Path.with_suffix` cannot produce anything else from a
    # `*.jsonl` name, but this tool deletes files, so the guarantee is asserted
    # rather than assumed.
    if watermark.suffix != WATERMARK_SUFFIX:
        return make(NO_WATERMARK, f"paired path is not a {WATERMARK_SUFFIX} file")

    try:
        raw = watermark.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return make(NO_WATERMARK, "never harvested — no watermark to remove")
    except OSError as exc:
        return make(UNREADABLE, f"watermark not readable ({type(exc).__name__}) — left in place")

    try:
        value = datetime.fromisoformat(raw)
    except (ValueError, TypeError):
        return make(
            UNPARSEABLE,
            f"watermark value {raw!r} does not parse as ISO8601 — never a candidate",
        )
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)

    if value != stamp:
        return make(OTHER_STAMP, f"holds {value.isoformat()} — a different stamp")

    for root in keep_roots:
        if scope.belongs_to_repo(trail, root):
            finding = make(EXEMPT, f"kept by --keep-repo {scope.posix_path(root)}")
            _count_records(finding, stamp)
            return finding

    finding = make(CANDIDATE)
    _count_records(finding, stamp)
    return finding


def scan(trail_dir: Path, stamp: datetime, keep_roots: list[Path]) -> list[Finding]:
    """Classify every ``*.jsonl`` trail under ``trail_dir``, in filename order."""
    trail_dir = Path(trail_dir)
    if not trail_dir.is_dir():
        return []
    return [examine(t, stamp, keep_roots) for t in sorted(trail_dir.glob("*.jsonl"))]


def delete_watermarks(findings: list[Finding]) -> tuple[list[Finding], list[Finding], list[tuple[Finding, OSError]]]:
    """Delete the candidates' watermarks. Returns ``(deleted, raced, failed)``.

    A file that vanished between scan and unlink is *not* an error — the desired
    end state (no watermark) is exactly what a concurrent deleter produced — so
    it is reported separately rather than as a failure. Anything else that raises
    is recorded and the loop continues; one locked file must not strand the rest.
    """
    deleted: list[Finding] = []
    raced: list[Finding] = []
    failed: list[tuple[Finding, OSError]] = []
    for finding in findings:
        if finding.status != CANDIDATE:
            continue
        if finding.watermark.suffix != WATERMARK_SUFFIX:
            continue  # unreachable via examine(); the guard is the point
        try:
            finding.watermark.unlink()
        except FileNotFoundError:
            raced.append(finding)
        except OSError as exc:
            failed.append((finding, exc))
        else:
            deleted.append(finding)
    return deleted, raced, failed


# ── reporting ──────────────────────────────────────────────────────────────

def _group(findings: list[Finding], statuses: tuple[str, ...]) -> dict[str, list[Finding]]:
    """Bucket findings with one of ``statuses`` by owning repository."""
    out: dict[str, list[Finding]] = {}
    for finding in findings:
        if finding.status in statuses:
            out.setdefault(finding.repo, []).append(finding)
    return {k: out[k] for k in sorted(out)}


def apply_command(stamp: datetime, keep_roots: list[Path]) -> str:
    """The exact command that turns this dry run into a deletion."""
    parts = ["python scripts/unmark_harvested.py", "--stamp", stamp.isoformat()]
    for root in keep_roots:
        parts += ["--keep-repo", scope.posix_path(root)]
    parts.append("--apply")
    return " ".join(parts)


def _keep_repo_pairs(pairs: list[tuple[str, Path]], indent: str) -> list[str]:
    """One line per unmatched ``--keep-repo``: what was typed, and what it became.

    Both halves are shown because the typed spelling is what the operator will
    correct and the resolved one is what was actually compared; printing only the
    latter would make a working-directory mistake look like a missing repository.

    Quoted rather than `!r`: a Windows path round-trips through `repr` with every
    separator doubled, which reads as a different path than the one that was
    typed — the exact confusion these lines exist to prevent.
    """
    return [
        f'{indent}--keep-repo "{raw}"  ->  {scope.posix_path(resolved)}'
        for raw, resolved in pairs
    ]


def render_unmatched_refusal(pairs: list[tuple[str, Path]], *, stamp: datetime) -> str:
    """The `--apply` refusal for a `--keep-repo` that names no trail this tool can see."""
    lines = [
        "unmark_harvested: REFUSED — nothing has been deleted.",
        "",
        f"stamp: {stamp.isoformat()}",
        "",
        "These --keep-repo path(s) own no trail on this machine:",
        "",
    ]
    lines += _keep_repo_pairs(pairs, "    ")
    lines += [
        "",
        "They exempt nothing, so proceeding would delete watermarks you asked to",
        "keep — and deletion here has no undo (there is no previous value left to",
        "restore). The run stops instead of guessing.",
        "",
        "Run the dry run to see the repository roots the trails actually record,",
        "then pass one of those:",
        "",
        f"    python scripts/unmark_harvested.py --stamp {stamp.isoformat()}",
    ]
    return "\n".join(lines).rstrip("\n") + "\n"


def _impact_lines(finding: Finding, indent: str) -> list[str]:
    """Per-trail impact detail: what returns to un-harvested, and the nudge verdict."""
    lines = [f"{indent}{finding.watermark.name}"]
    if finding.trail_unreadable:
        lines.append(f"{indent}    trail unreadable — impact unknown, watermark still matches")
        return lines
    lines.append(
        f"{indent}    {finding.returning} record(s) return to un-harvested "
        f"(un-harvested now {finding.already} -> {finding.after})"
    )
    threshold = harvest_nudge.NUDGE_THRESHOLD
    if finding.revives_nudge:
        lines.append(
            f"{indent}    nudge REVIVED — crosses the threshold of {threshold}"
        )
    elif finding.after < threshold:
        lines.append(
            f"{indent}    below the nudge threshold of {threshold} — no nudge either way"
        )
    else:
        lines.append(
            f"{indent}    already at/above the threshold of {threshold} — nudge was not silenced"
        )
    if finding.unparseable_records:
        lines.append(
            f"{indent}    {finding.unparseable_records} unparseable record(s) ignored"
        )
    return lines


def render_dry_run(
    findings: list[Finding],
    *,
    stamp: datetime,
    trail_dir: Path,
    keep_roots: list[Path],
    unmatched: list[tuple[str, Path]] | None = None,
) -> str:
    """The read-only report. Leads with the nudge impact, which is the real harm."""
    lines = [
        "unmark_harvested: DRY RUN — nothing has been deleted.",
        "",
        f"stamp being reverted: {stamp.isoformat()}",
        f"trail dir:            {Path(trail_dir).as_posix()}",
        f"trails scanned:       {len(findings)}",
        "",
    ]

    # Before any counts: a --keep-repo that matches nothing makes every "exempt"
    # number below a lie about what is protected, so it is said first and loudly.
    if unmatched:
        lines.append("!! WARNING: --keep-repo matched no trail on this machine.")
        lines += [f"!! {line.lstrip()}" for line in _keep_repo_pairs(unmatched, "")]
        lines.append(
            "!! Nothing is exempt because of it. --apply will REFUSE until the path"
        )
        lines.append("!! names a repository this tool can see.")
        lines.append("")

    candidates = [f for f in findings if f.status == CANDIDATE]
    exempt = [f for f in findings if f.status == EXEMPT]

    if not candidates and not exempt:
        lines.append("No watermark on this machine holds that stamp — nothing to revert.")
        lines.append("")
        lines += _render_non_candidates(findings)
        return "\n".join(lines).rstrip("\n") + "\n"

    lines.append(
        f"{len(candidates) + len(exempt)} watermark(s) match the stamp: "
        f"{len(candidates)} would be DELETED, {len(exempt)} exempt via --keep-repo."
    )
    lines.append("")

    for repo, group in _group(findings, (CANDIDATE,)).items():
        returning = sum(f.returning for f in group)
        revived = sum(1 for f in group if f.revives_nudge)
        lines.append(f"{repo}")
        for finding in group:
            lines += _impact_lines(finding, "    ")
        lines.append(
            f"    subtotal: {len(group)} watermark(s) deleted, {returning} record(s) "
            f"return to un-harvested, {revived} nudge(s) revived"
        )
        lines.append("")

    exempt_groups = _group(findings, (EXEMPT,))
    if exempt_groups:
        lines.append("exempt via --keep-repo (matched the stamp, left untouched):")
        for repo, group in exempt_groups.items():
            lines.append(f"    {repo}: {len(group)} watermark(s)")
        lines.append("")

    lines += _render_non_candidates(findings)

    total_returning = sum(f.returning for f in candidates)
    total_revived = sum(1 for f in candidates if f.revives_nudge)
    lines.append(
        f"TOTAL: {len(candidates)} watermark(s) would be deleted, returning "
        f"{total_returning} record(s) to un-harvested and reviving "
        f"{total_revived} nudge(s)."
    )
    lines.append("")
    lines.append(
        "Those records then fall outside the retention window entirely and are kept\n"
        "indefinitely (see this script's docstring). Re-running a repo-scoped\n"
        "/harvest-memory re-stamps the trail and restores the window."
    )
    lines.append("")
    lines.append("To apply:")
    lines.append(f"    {apply_command(stamp, keep_roots)}")
    return "\n".join(lines).rstrip("\n") + "\n"


def _render_non_candidates(findings: list[Finding]) -> list[str]:
    """Report what was skipped and why — the honest denominator for the counts."""
    other = [f for f in findings if f.status == OTHER_STAMP]
    problems = [f for f in findings if f.status in (UNPARSEABLE, UNREADABLE)]
    none_yet = [f for f in findings if f.status == NO_WATERMARK]

    lines: list[str] = []
    if problems:
        lines.append("skipped (could not be trusted as a match):")
        for finding in problems:
            lines.append(f"    ! {finding.watermark.name}: {finding.detail}")
        lines.append("")
    if other:
        lines.append(f"skipped: {len(other)} watermark(s) hold a different stamp.")
    if none_yet:
        lines.append(f"skipped: {len(none_yet)} trail(s) have no watermark at all.")
    if other or none_yet:
        lines.append("")
    return lines


def render_apply(
    deleted: list[Finding],
    raced: list[Finding],
    failed: list[tuple[Finding, OSError]],
    *,
    stamp: datetime,
    findings: list[Finding],
) -> str:
    """The post-deletion report: one line per file, then the totals."""
    exempt = [f for f in findings if f.status == EXEMPT]
    lines = [
        "unmark_harvested: APPLIED.",
        "",
        f"stamp reverted: {stamp.isoformat()}",
        "",
    ]
    for finding in deleted:
        lines.append(
            f"    deleted {finding.watermark.name} "
            f"({finding.returning} record(s) return to un-harvested) [{finding.repo}]"
        )
    for finding in raced:
        lines.append(
            f"    already gone {finding.watermark.name} — removed concurrently, not an error"
        )
    for finding, exc in failed:
        lines.append(
            f"    FAILED {finding.watermark.name}: {type(exc).__name__}: {exc}"
        )
    if deleted or raced or failed:
        lines.append("")

    total_returning = sum(f.returning for f in deleted)
    total_revived = sum(1 for f in deleted if f.revives_nudge)
    lines.append(
        f"{len(deleted)} watermark(s) deleted, {len(raced)} already gone, "
        f"{len(failed)} failed, {len(exempt)} exempt via --keep-repo."
    )
    lines.append(
        f"{total_returning} record(s) returned to un-harvested; "
        f"{total_revived} nudge(s) revived."
    )
    if failed:
        lines.append("")
        lines.append(
            "Some watermarks could not be removed. Re-run the same command once the\n"
            "cause is cleared; deleting an already-deleted watermark is a no-op."
        )
    return "\n".join(lines).rstrip("\n") + "\n"


# ── CLI ────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="unmark_harvested.py",
        description=(
            "Delete the harvest watermarks written by one bad global stamp, so the "
            "records they covered count as un-harvested again (read-only unless --apply)."
        ),
    )
    ap.add_argument(
        "--stamp",
        required=True,
        type=parse_stamp,
        help="the exact ISO8601 instant the bad stamp wrote; compared as a parsed "
             "datetime, so an equivalent spelling in another offset still matches",
    )
    ap.add_argument(
        "--keep-repo",
        action="append",
        default=[],
        metavar="PATH",
        help="repository whose stamp was legitimately earned; its trails (and its "
             "linked worktrees' trails) are exempt. Resolved to an absolute path, so "
             "'.' works. A path owning no trail refuses the run under --apply. "
             "Repeatable.",
    )
    ap.add_argument(
        "--apply",
        action="store_true",
        help="delete the matching watermarks (default: dry run, prints the plan only)",
    )
    args = ap.parse_args(argv)

    # The report uses em dashes and arrows and echoes repo paths that may carry
    # other non-ASCII; a legacy Windows console defaults to cp1252 and would raise
    # UnicodeEncodeError — on --apply that would land *after* the deletions, so a
    # successful run would look like a crash (#55). Guarded, because a redirected
    # StringIO in tests has no reconfigure.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass

    trail_dir = rs.trail_dir()
    keep_pairs = [(raw, resolve_keep_root(raw)) for raw in args.keep_repo]
    keep_roots = [resolved for _, resolved in keep_pairs]
    findings = scan(trail_dir, args.stamp, keep_roots)

    unmatched = unmatched_keep_roots(trail_dir, keep_roots)
    unmatched_pairs = [(raw, r) for raw, r in keep_pairs if r in unmatched]

    if not args.apply:
        print(
            render_dry_run(
                findings,
                stamp=args.stamp,
                trail_dir=trail_dir,
                keep_roots=keep_roots,
                unmatched=unmatched_pairs,
            ),
            end="",
        )
        return 0

    if unmatched_pairs:
        print(
            render_unmatched_refusal(unmatched_pairs, stamp=args.stamp),
            file=sys.stderr,
            end="",
        )
        return 1

    deleted, raced, failed = delete_watermarks(findings)
    print(
        render_apply(deleted, raced, failed, stamp=args.stamp, findings=findings),
        end="",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
