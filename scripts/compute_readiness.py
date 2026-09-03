#!/usr/bin/env python3
"""Compute the generated portion of `memory/repo/<repo>/readiness.md` (#42).

Turns the machine-local learning trail (`<config>/learning-trail/*.jsonl`, written
by the `record_stop.py` Stop hook) plus the promotion ledger
(`memory/learning-log.md`) into a deterministic activity block inside each repo's
`readiness.md`. Read-only by default; `--apply` performs the write.

**The invariant this script exists to keep:**

    Only bytes between the generated markers are ever rewritten. A file lacking
    markers gains them. Nothing else in the file changes.

Real `readiness.md` files run 34-269 lines against a 24-line template — they are
overwhelmingly hand-written prose, and a generator that overwrites destroys human
work. This repo already shipped that bug once (#25, fixed in #45); the marker
discipline below is how this script avoids being its second occurrence. The one
permitted edit outside the markers is the `last_updated` frontmatter field, and
even that is a targeted single-line replacement applied *only* when the generated
block actually changed — never a frontmatter rewrite, and never churn on a re-run.

Placement: on a file that has no markers yet, the block is appended at the end —
the least intrusive spot for a mostly-prose file. Placement is a one-time
decision: once the markers exist, they can be moved anywhere in the file by hand
and every later run rewrites them in place.

Malformed markers (issue #121). `compose()` classifies before it splices, and
**refuses** — writes nothing, returns `None`, surfaces a `⚠` — whenever the
block's extent is unknowable: a begin without an end, an end without a begin,
reversed markers, or duplicates. Testing marker *presence* and splicing with
`.index()` was the original defect: an orphaned begin marker fell to the append
branch, and the *next* run spliced from that orphan through the appended block,
destroying every hand-written byte in between. Two runs to lose the content, and
the file then looked healthy, so it was never re-reported. Recognition is
whole-line and fence-aware, shared with `wiki_index.py` via `_marker_block.py`,
so a file that merely *documents* the markers — quoted inline, or shown in a
```-fenced example — is not mistaken for the block itself.

## Repo attribution

`git_root` is the *worktree* root, so grouping on it raw yields ~86 buckets for
~10 repositories. Each record is normalised in this order:

  1. `repo_root` if present — recorded at source since #66, authoritative.
  2. Worktree-pattern parse — a path matching `<repo>/.claude/worktrees/<name>`
     belongs to `<repo>`. Works on paths that no longer exist on disk, which is
     what recovers records from already-deleted worktrees.
  3. Live git resolution — only for a path that still exists and matched neither
     of the above. Costs a subprocess, so each distinct path is resolved at most
     once and cached.

Otherwise `git_root` is used unchanged. Path separators are normalised to posix
*before* any comparison or grouping: git emits forward slashes while `pathlib`
emits backslashes on Windows, and the ~2,100 legacy records predate #66's fix at
the write site, so they carry whichever convention applied when they were written.

## The outcome summary

`readiness.md`'s headline section asks how many sessions ended clean vs. flagged.
**That signal does not exist**, so this script emits an explicit insufficient-data
state naming why. It is never inferred from `message_preview` (blanked wholesale
to `[redacted]` on any secret match) or from promotion counts (the ledger records
only what landed, never what went wrong). Deriving a real verdict from
`transcript_path` is a later issue; fabricating one here would silently miscalibrate
the autonomy dial (#32), which is specified to read this file.

Usage:
    python scripts/compute_readiness.py                      # dry run, all repos
    python scripts/compute_readiness.py --repo myrepo        # one repo
    python scripts/compute_readiness.py --json               # machine-readable plan
    python scripts/compute_readiness.py --apply              # perform the write
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))

import record_stop as rs  # noqa: E402
from _learning_common import parse_ledger  # noqa: E402
from _marker_block import MarkerBlock  # noqa: E402

# Path normalisation and repo attribution live in `_trail_scope`, so every tool
# that has to decide which repo a trail belongs to buckets it identically. On the
# harvest side the consumer is now `begin_harvest`, which records that decision in
# `read.json`; `mark_harvested` no longer resolves scope at all — it stamps the
# trails the manifest names. They are re-exported here because this module is
# where they were introduced (#42) and callers — including this script's tests —
# import them from it.
from _trail_scope import (  # noqa: F401  (re-exported)
    WORKTREE_MARKER,
    posix_path,
    resolve_repo_root,
    strip_worktree,
)

REPO_DIR = Path(__file__).resolve().parent.parent
DEFAULT_MEMORY_ROOT = REPO_DIR / "memory"

# Markers delimiting the block this script OWNS. Everything between them is
# rewritten on each run; everything outside is left byte-for-byte alone.
GENERATED_BEGIN = "<!-- readiness:generated start -->"
GENERATED_END = "<!-- readiness:generated end -->"

# The whole-line, fence-aware marker machinery, bound to this script's pair.
# `_marker_block` owns the recognition rules and the `none`/`ok`/`malformed`
# classification — shared with `wiki_index.py` so the two generators cannot
# drift into disagreeing about what a marker is; everything below owns what goes
# *inside* the block. Module-level because the marker-line regex is compiled in
# the constructor.
_BLOCK = MarkerBlock(GENERATED_BEGIN, GENERATED_END)

# Structure mirrors memory/repo/EXAMPLE/readiness.md minus its example-only
# blockquote. Used only when an existing memory/repo/<name>/ dir has no
# readiness.md yet; directories are never created.
SEED_TEMPLATE = """---
last_updated: {today}
---

# {repo} — readiness

## Outcome summary

Rolling view of recent harvested sessions — how many ended clean vs. flagged.
_(none yet)_

## Recurring flags

Patterns that have tripped more than once — the input that argues for a *lower*
autonomy cap.
_(none yet)_

## Notes

Updated during `/harvest-memory`.
"""

# Why no clean-vs-flagged count exists. Rendered verbatim into every generated
# block so the gap is stated in the file the autonomy dial reads, not just here.
INSUFFICIENT_OUTCOME = (
    "**Insufficient data — no clean-vs-flagged verdict is available.** The trail\n"
    "records carry no outcome field; `message_preview` is blanked wholesale to\n"
    "`[redacted]` on any secret match; and `memory/learning-log.md` records only\n"
    "what was promoted, never what went wrong. Promotion counts are a different\n"
    "signal and are not a substitute.\n"
    "\n"
    "Resolving this needs a verdict derived from the session transcript\n"
    "(`transcript_path`, recorded on trail records since #66). That derivation is\n"
    "a separate piece of work; until it lands, this section stays empty rather\n"
    "than guessing."
)


# ── path + attribution ─────────────────────────────────────────────────────

def repo_name(repo_root_posix: str) -> str:
    """Basename of a repository root — the `memory/repo/<name>/` key.

    Matches how `assess_repo_readiness.py` names a repo. A root with no usable
    basename degrades to the full path rather than to an empty key.
    """
    tail = repo_root_posix.rsplit("/", 1)[-1]
    return tail or repo_root_posix


# ── trail reading ──────────────────────────────────────────────────────────

def _parse_ts(raw) -> datetime | None:
    """Parse a record `ts` to an aware datetime, or None if unparseable."""
    try:
        parsed = datetime.fromisoformat(str(raw))
    except (ValueError, TypeError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def iter_trail_records(trail_dir: Path):
    """Yield `(record, watermark)` for every parseable record under `trail_dir`.

    One watermark per trail file, read once via `record_stop.read_watermark`. It
    travels with each record because normalisation collapses several trail files
    (each with its own watermark) into a single repository.
    """
    if not Path(trail_dir).is_dir():
        return
    for trail in sorted(Path(trail_dir).glob("*.jsonl")):
        watermark = rs.read_watermark(rs.watermark_path(trail))
        try:
            text = trail.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                yield record, watermark


def collect_activity(
    trail_dir: Path,
    *,
    resolve_live: bool = True,
) -> dict[str, dict]:
    """Aggregate the whole trail into `{repo_name: activity}`.

    Keyed on the repo *name* rather than the root path, because that is what
    `memory/repo/<name>/` is keyed on: two distinct roots sharing a basename must
    merge into one bucket or they would race on one output file.
    """
    cache: dict[str, str] = {}
    buckets: dict[str, dict] = {}

    for record, watermark in iter_trail_records(trail_dir):
        root = resolve_repo_root(record, resolve_live=resolve_live, cache=cache)
        if not root:
            continue
        name = repo_name(root)
        bucket = buckets.setdefault(
            name,
            {
                "repo": name,
                "roots": set(),
                "turns": 0,
                "sessions": set(),
                "first_ts": None,
                "last_ts": None,
                "unharvested": 0,
            },
        )
        bucket["roots"].add(root)
        bucket["turns"] += 1

        session = str(record.get("session_id") or "")
        if session:
            bucket["sessions"].add(session)

        ts_raw = record.get("ts")
        parsed = _parse_ts(ts_raw)
        if parsed is not None:
            if bucket["first_ts"] is None or parsed < bucket["first_ts"]:
                bucket["first_ts"] = parsed
            if bucket["last_ts"] is None or parsed > bucket["last_ts"]:
                bucket["last_ts"] = parsed

        # Un-harvested = strictly newer than this trail's watermark; a watermark
        # of None means nothing was ever harvested, so everything counts.
        # Delegated to record_stop so the comparison lives in exactly one place.
        if rs._is_unharvested(str(ts_raw or ""), watermark):
            bucket["unharvested"] += 1

    return buckets


def count_promotions(ledger: dict[str, tuple[str, str]], name: str) -> int:
    """Ledger entries whose target falls under `repo/<name>/`."""
    prefix = f"repo/{name}/"
    return sum(
        1 for _, target in ledger.values()
        if posix_path(target).startswith(prefix)
    )


def summarise(
    trail_dir: Path,
    memory_root: Path,
    *,
    resolve_live: bool = True,
    today: date | None = None,
) -> list[dict]:
    """Per-repo stats, sorted by repo name — the pure core of this script."""
    today = today or datetime.now(timezone.utc).date()
    ledger = parse_ledger(Path(memory_root) / "learning-log.md")

    out: list[dict] = []
    for name, bucket in collect_activity(trail_dir, resolve_live=resolve_live).items():
        first = bucket["first_ts"]
        last = bucket["last_ts"]
        out.append(
            {
                "repo": name,
                "roots": sorted(bucket["roots"]),
                "turns": bucket["turns"],
                "sessions": len(bucket["sessions"]),
                "first_date": first.date().isoformat() if first else None,
                "last_date": last.date().isoformat() if last else None,
                "recency_days": (today - last.date()).days if last else None,
                "unharvested": bucket["unharvested"],
                "promotions": count_promotions(ledger, name),
            }
        )
    return sorted(out, key=lambda s: s["repo"])


# ── rendering ──────────────────────────────────────────────────────────────

def render_block(stats: dict) -> str:
    """The generated block, markers included, ending in a newline.

    Deterministic in `stats` alone — nothing here reads the clock, so an unchanged
    trail renders byte-identical text.
    """
    span = (
        f"{stats['first_date']} → {stats['last_date']}"
        if stats["first_date"] and stats["last_date"]
        else "_no dated records_"
    )
    recency = (
        f"{stats['recency_days']} day(s) since the last recorded turn"
        if stats["recency_days"] is not None
        else "_unknown_"
    )
    roots = ", ".join(f"`{r}`" for r in stats["roots"]) or "_none_"

    lines = [
        GENERATED_BEGIN,
        "",
        "<!-- Generated by scripts/compute_readiness.py. Edits between these",
        "     markers are overwritten; everything outside them is preserved. -->",
        "",
        "### Activity (computed from the learning trail)",
        "",
        f"- Turns recorded: {stats['turns']}",
        f"- Distinct sessions: {stats['sessions']}",
        f"- Span: {span}",
        f"- Recency: {recency}",
        f"- Un-harvested turns: {stats['unharvested']}",
        f"- Promotions into `memory/repo/{stats['repo']}/`: {stats['promotions']}",
        f"- Repository roots: {roots}",
        "",
        "### Outcome summary (generated)",
        "",
        INSUFFICIENT_OUTCOME,
        "",
        GENERATED_END,
        "",
    ]
    return "\n".join(lines)


# ── file composition (the invariant lives here) ────────────────────────────

def _split_raw_frontmatter(text: str) -> tuple[str, str]:
    """Split `text` into (frontmatter, rest), preserving both verbatim.

    Mirrors `promote_learnings._split_raw_frontmatter`: the frontmatter keeps its
    enclosing `---` lines and trailing newline, and is `""` when none opens the
    file.

    LF-delimited frontmatter only. A CRLF file therefore reports "no
    frontmatter" and its `last_updated` is left alone — which is the safe
    outcome, not a gap: `_bump_last_updated` rejoins with `\\n`, so firing it on
    CRLF frontmatter would rewrite those bytes outside the markers, and the
    invariant forbids that far more strongly than it requires a date bump.
    """
    if not text.startswith("---\n"):
        return "", text
    end = text.find("\n---\n", 4)
    if end == -1:
        return "", text
    return text[: end + 5], text[end + 5:]


def _bump_last_updated(fm_raw: str, today: str) -> str:
    """Replace only the `last_updated:` line in `fm_raw`; keep every other byte.

    A targeted field replacement, never a frontmatter rewrite: extra keys, key
    order, comments, and formatting all survive. When the key is absent it is
    inserted before the closing `---`. An empty `fm_raw` (no frontmatter at all)
    is returned unchanged — inventing a frontmatter block would be a structural
    edit outside the markers, which the invariant forbids.
    """
    if not fm_raw:
        return fm_raw
    lines = fm_raw.splitlines()
    for i, line in enumerate(lines):
        if line.split(":", 1)[0].strip() == "last_updated" and ":" in line:
            lines[i] = f"last_updated: {today}"
            return "\n".join(lines) + "\n"
    if lines and lines[-1].strip() == "---":
        lines.insert(len(lines) - 1, f"last_updated: {today}")
        return "\n".join(lines) + "\n"
    return fm_raw


def compose(
    existing_text: str | None, stats: dict, today: str
) -> tuple[str | None, str]:
    """Merge the generated block into `existing_text`; `None` means "write nothing".

    Returns (new_text_or_None, disposition) where disposition is one of
    `created` / `spliced` / `appended` / `malformed:<reason>` — the same shape
    `wiki_index.compose` returns, because the two scripts now share a marker
    module and having them express refusal differently is where the next
    divergence would start.

    Four cases:
      - absent file → seeded template + block appended
      - markers `ok` → the block between them is replaced in place
      - markers `none` → the block is appended, everything else untouched
      - markers `malformed` → **refuse**: return `None` and let the caller
        surface it. The block's extent is unknowable, appending would duplicate
        it forever, and truncating could delete prose, so a human resolves it.

    Classification happens *before* any position is located: the counts decide,
    and only then is a span taken. That ordering is the fix for #121 — the
    version that tested marker presence and spliced with `.index()` mis-handled
    orphaned, duplicated, reversed and nested markers without complaint.

    `last_updated` is bumped only when the composed text would otherwise differ
    from `existing_text`, so a second run on unchanged input is a no-op.
    """
    block = render_block(stats)

    if existing_text is None:
        seeded = SEED_TEMPLATE.format(today=today, repo=stats["repo"])
        return seeded + "\n" + block, "created"

    kind, reason = _BLOCK.classify(existing_text)
    if kind == "malformed":
        return None, f"malformed:{reason}"

    if kind == "ok":
        start, stop = _BLOCK.span(existing_text)
        merged = existing_text[:start] + block + existing_text[stop:]
        disposition = "spliced"
    else:
        prefix = existing_text
        # `\r` as well as `\n`: with newline="" on the read a CRLF file arrives
        # with its terminators intact, and a lone `\r` is a line ending too.
        if prefix and not prefix.endswith(("\n", "\r")):
            prefix += "\n"
        merged = prefix + "\n" + block
        disposition = "appended"

    # Bump last_updated only if something else actually changed, so re-running on
    # an unchanged trail leaves the file byte-identical instead of churning it.
    if merged == existing_text:
        return merged, disposition
    fm_raw, rest = _split_raw_frontmatter(merged)
    return _bump_last_updated(fm_raw, today) + rest, disposition


def plan_repo(stats: dict, memory_root: Path, today: str) -> dict:
    """Decide what would happen to one repo's readiness.md — no writes.

    Statuses: `skipped-no-dir` (memory/repo/<name>/ absent — never created),
    `seed` (dir exists, file missing), `update`, `unchanged`,
    `skipped-unreadable`, and `skipped-malformed` (#121 — `compose` refused;
    `reason` names why). Every skipped status carries `new_text: None`, which is
    the second condition `apply_plan` checks before writing anything.

    `reason` is present on every entry and empty except on `skipped-malformed`,
    so a `--json` consumer sees one shape rather than an optional key.
    """
    repo_dir = Path(memory_root) / "repo" / stats["repo"]
    path = repo_dir / "readiness.md"
    base = {**stats, "path": str(path), "reason": ""}

    if not repo_dir.is_dir():
        return {**base, "status": "skipped-no-dir", "new_text": None}

    if not path.is_file():
        new_text, _ = compose(None, stats, today)
        return {**base, "status": "seed", "new_text": new_text}

    try:
        # newline="" on the read AND the write disables universal-newline
        # translation, so the comparison below is against what is actually on
        # disk and "\n" is never expanded to os.linesep on Windows (issues
        # #83/#84). `MarkerBlock.span` bounds whole lines, so it stays exact
        # under `\n`, `\r\n` and a lone `\r` alike.
        existing = path.read_text(encoding="utf-8", newline="")
    except OSError:
        return {**base, "status": "skipped-unreadable", "new_text": None}

    new_text, disposition = compose(existing, stats, today)
    if new_text is None:  # #121: the one and only refusal path
        return {**base, "status": "skipped-malformed", "new_text": None,
                "reason": disposition.partition(":")[2]}
    status = "unchanged" if new_text == existing else "update"
    return {**base, "status": status, "new_text": new_text}


def plan(
    trail_dir: Path,
    memory_root: Path,
    *,
    repo: str | None = None,
    resolve_live: bool = True,
    today: date | None = None,
) -> list[dict]:
    """Full read-only plan: one entry per repository found in the trail."""
    today = today or datetime.now(timezone.utc).date()
    stamp = today.isoformat()
    stats = summarise(trail_dir, memory_root, resolve_live=resolve_live, today=today)
    if repo:
        stats = [s for s in stats if s["repo"] == repo]
    return [plan_repo(s, memory_root, stamp) for s in stats]


def apply_plan(entries: list[dict]) -> list[dict]:
    """Write the planned text for every `seed`/`update` entry; return them.

    The only path ever written is `memory/repo/<name>/readiness.md`, and only for
    a directory that already exists. A `skipped-malformed` entry is excluded
    twice over — by its status and by its `new_text is None` — so a refusal
    cannot reach the disk through either half of this guard.
    """
    written: list[dict] = []
    for entry in entries:
        if entry["status"] not in ("seed", "update") or entry["new_text"] is None:
            continue
        Path(entry["path"]).write_text(entry["new_text"], encoding="utf-8", newline="")
        written.append(entry)
    return written


# ── CLI ────────────────────────────────────────────────────────────────────

_STATUS_LABEL = {
    "seed": "+ seed  ",
    "update": "~ update",
    "unchanged": "= same  ",
    "skipped-no-dir": "- skip  ",
    "skipped-unreadable": "! skip  ",
    "skipped-malformed": "⚠ refuse",
}


def render_report(entries: list[dict], *, applied: bool) -> str:
    """Human-readable plan/result report."""
    if not entries:
        return (
            "no learning-trail data found — nothing to compute.\n"
            "This is the honest empty state, not an error: the trail fills as the\n"
            "Stop hook records turns.\n"
        )

    lines: list[str] = []
    verb = "wrote" if applied else "would write"
    changed = sum(1 for e in entries if e["status"] in ("seed", "update"))
    refused = [e for e in entries if e["status"] == "skipped-malformed"]
    lines.append(f"{len(entries)} repo(s) in the trail; {verb} {changed}.")
    if refused:
        # Loud at the top as well as beside the entry: a refusal needs a human,
        # and main() deliberately still exits 0 (this script runs from
        # /harvest-memory, not CI), so the report is the whole signal.
        lines.append(
            f"⚠ {len(refused)} refused: malformed readiness markers; "
            "nothing was written for those repos."
        )
    lines.append("")
    for entry in entries:
        label = _STATUS_LABEL.get(entry["status"], entry["status"])
        lines.append(f"  {label}  {entry['repo']}")
        lines.append(
            f"             turns={entry['turns']} sessions={entry['sessions']} "
            f"span={entry['first_date']}..{entry['last_date']} "
            f"recency={entry['recency_days']}d "
            f"un-harvested={entry['unharvested']} "
            f"promotions={entry['promotions']}"
        )
        if entry["status"] == "skipped-no-dir":
            lines.append(
                f"             (no {Path(entry['path']).parent.as_posix()}/ — "
                "skipped; directories are never created)"
            )
        if entry["status"] == "skipped-malformed":
            lines.append(
                f"             ⚠ malformed readiness markers: {entry['path']} "
                f"({entry['reason']}); refusing to write — the block's extent "
                "is unknowable, so a human resolves it"
            )
    lines.append("")
    lines.append(
        "Outcome summary is emitted as INSUFFICIENT DATA — the clean-vs-flagged "
        "verdict\nis not captured anywhere in the trail or the ledger and is never "
        "inferred."
    )
    if not applied:
        lines.append("")
        lines.append("(dry run — re-run with --apply to write)")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Compute the generated block of memory/repo/<repo>/readiness.md "
                    "from the learning trail (read-only unless --apply).",
    )
    ap.add_argument("--trail-dir", default=None,
                    help="learning-trail dir (default: $CLAUDE_CONFIG_DIR/learning-trail "
                         "or ~/.claude/learning-trail)")
    ap.add_argument("--memory-root", default=str(DEFAULT_MEMORY_ROOT),
                    help="path to the brain's memory/ root (default: this repo's memory/)")
    ap.add_argument("--repo", default=None,
                    help="limit to a single repository name")
    ap.add_argument("--apply", action="store_true",
                    help="perform the write (default: dry run, prints the plan only)")
    ap.add_argument("--json", action="store_true",
                    help="print the plan as JSON instead of a report")
    args = ap.parse_args(argv)

    # The report uses → and — glyphs; a legacy Windows console defaults to cp1252
    # and would raise UnicodeEncodeError. Guarded — a redirected StringIO in tests
    # has no reconfigure.
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass

    trail_dir = Path(args.trail_dir) if args.trail_dir else rs.trail_dir()
    memory_root = Path(args.memory_root)

    entries = plan(trail_dir, memory_root, repo=args.repo)
    if args.apply:
        apply_plan(entries)

    if args.json:
        payload = {
            "trail_dir": Path(trail_dir).as_posix(),
            "memory_root": memory_root.as_posix(),
            "applied": bool(args.apply),
            "outcome_summary": {
                "available": False,
                "reason": "no clean-vs-flagged verdict is captured by the trail or "
                          "the ledger; deriving one from transcript_path is separate work",
            },
            # Every refusal is already visible per-repo as
            # status=skipped-malformed plus its reason; this is the same fact
            # hoisted to the top level so a consumer cannot miss it by only
            # looking at counts. main() still exits 0 — see render_report.
            "refused": [
                {"repo": e["repo"], "path": e["path"], "reason": e["reason"]}
                for e in entries if e["status"] == "skipped-malformed"
            ],
            "repos": [
                {k: v for k, v in e.items() if k != "new_text"} for e in entries
            ],
        }
        print(json.dumps(payload, indent=2))
    else:
        print(render_report(entries, applied=bool(args.apply)), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
