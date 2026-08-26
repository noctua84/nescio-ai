#!/usr/bin/env python3
"""Promote vetted learning nominations into the synced repo memory/ tree.

The learning loop's mechanical committer — analogous to `mark_adopted.py` for the
adopt flow. Given a JSON manifest of nominations (see below), for each one it:

  1. validates the declared source is one of user override | empirical | agent
     inference;
  2. dedups by a hash of the note body against `memory/learning-log.md` (a
     nomination already promoted is skipped);
  3. resolves contradictions when the target note already exists — the incoming
     source overwrites only if it is strictly higher priority, or equal priority
     AND a newer date (user override > empirical > agent inference);
  4. writes the note (YAML frontmatter + body + a `[Source: … — date]` line);
  5. appends a ledger line so the promotion is skipped on future runs;
  6. drops a `receipt.json` next to the manifest recording what this pass did.

The `receipt.json` is an **audit record, not a gate**. It states what one promote
pass did — which targets were written, how many were deduped, and when the file
actually reached the disk — and it lands beside the manifest so the rest of the
harvest flow can find it from the manifest path alone, with no extra bookkeeping
to lose.

It deliberately does **not** authorise `mark_harvested.py`'s watermark, and the
reasoning is worth keeping because an earlier draft of this file asserted the
opposite. A receipt is produced and consumed inside a single flow, so the most it
can ever prove is *ordering* — that promote ran before mark — never diligence.
And the only property a gate could actually test, ``promoted >= 1``, is satisfied
completely by a pass that read 500 records and promoted one; it would meanwhile
*refuse* the honest re-run whose nominations all dedup to `promoted: 0`. Scope
and permission to stamp therefore come from `begin_harvest.py`'s `read.json`,
which answers the per-trail question that is answerable — *was this trail read*.
`mark_harvested.py` treats the receipt as advisory throughout: a missing,
unreadable, unrecognised, or zero-promotion receipt warns, and it stamps anyway.

What the receipt is genuinely good for is the condition under which it is
written: only after the notes and the ledger have really landed on disk. A
`--dry-run` leaves none, a failed validation leaves none, so its presence and its
``written_at`` are a truthful after-the-fact account of a pass that wrote.

Manifest = a JSON list of objects. All fields are required; the canonical schema
is shared with `commands/harvest-memory.md` and `memory/CONVENTIONS.md`:

    {
      "scope":       "repo/<name>" | "projects/<name>" | "context" | "feedback"
                     | "people" | "glossary",   # mirrors the top-level memory/ bucket
      "target":      "<real path under memory/, e.g. repo/myrepo/foo.md"
                     "or feedback/bar.md>",
      "name":        "<slug>",
      "description": "<one-line>",
      "type":        "feedback" | "context" | "adr" | ...,  # the note's frontmatter type
      "body":        "<markdown>",
      "source":      "user override" | "empirical" | "agent inference",
      "date":        "YYYY-MM-DD"
    }

``scope`` mirrors the top-level ``memory/`` bucket the note lands in; ``target``
is the real relative path under ``memory/``; ``type`` is the note's frontmatter
type. ``scope``'s bucket is validated against the canonical set; ``type`` is
open-ended and only checked for presence.

Usage:
    # writes <manifest dir>/receipt.json on success; pass it to mark_harvested.py
    python scripts/promote_learnings.py nominations.json
    # previews only — names the receipt path but writes no receipt
    python scripts/promote_learnings.py nominations.json --dry-run
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import wiki_index

from _learning_common import (
    MAX_LEDGER_LINES,
    REPO_DIR,
    VALID_SOURCES,
    content_hash12,
    parse_ledger,
    priority,
)

# Every nomination must carry these before anything is written — a malformed
# object fails its own line cleanly (rc 1) instead of raising KeyError mid-run
# after earlier notes already wrote.
REQUIRED_FIELDS = (
    "scope",
    "target",
    "name",
    "description",
    "type",
    "body",
    "source",
    "date",
)

# Canonical top-level ``memory/`` buckets a nomination's ``scope`` may name. The
# bucket is the part before any ``/`` (``repo/myrepo`` -> ``repo``); ``type`` is
# left open-ended by design (frontmatter types grow over time).
VALID_SCOPE_BUCKETS = {
    "repo",
    "projects",
    "context",
    "feedback",
    "people",
    "glossary",
    "concepts",
}

# Matches the provenance line this script writes (now inside the managed block),
# so an existing note's recorded source/date can be read back for the
# contradiction check.
_SOURCE_RE = re.compile(
    r"\[Source:\s*(user override|empirical|agent inference)\s*[—-]\s*"
    r"(\d{4}-\d{2}-\d{2})\s*\]"
)

# Markers delimiting the block promote OWNS. Everything inside is rewritten on
# each promotion; everything outside (human edits, extra sections) is left alone.
PROMOTED_BEGIN = "<!-- promoted:begin -->"
PROMOTED_END = "<!-- promoted:end -->"

# The promotion receipt. Filename is fixed and lives beside the manifest so the
# next step in the harvest flow can find it from the manifest path alone, with no
# extra bookkeeping to lose. ``RECEIPT_VERSION`` is bumped only on a breaking
# schema change — `mark_harvested.py` will not guess at a version it does not
# recognise; it says so and stamps on the manifest's authority instead.
RECEIPT_NAME = "receipt.json"
RECEIPT_VERSION = 1


def render_frontmatter(nom: dict) -> str:
    """The YAML frontmatter block promote manages (name/description/type)."""
    return (
        "---\n"
        f"name: {nom['name']}\n"
        f"description: {nom['description']}\n"
        f"type: {nom['type']}\n"
        "---\n"
    )


def render_block(nom: dict) -> str:
    """The managed promoted block: markers wrapping the body + provenance line."""
    return (
        f"{PROMOTED_BEGIN}\n"
        + nom["body"]
        + f"\n[Source: {nom['source']} — {nom['date']}]\n"
        + f"{PROMOTED_END}\n"
    )


def render_note(nom: dict) -> str:
    """A fresh note: managed frontmatter followed by the managed block."""
    return render_frontmatter(nom) + render_block(nom)


def _split_raw_frontmatter(text: str) -> tuple[str, str]:
    """Split ``text`` into (frontmatter, rest).

    ``frontmatter`` keeps its enclosing ``---`` lines and trailing newline; it is
    ``""`` when no frontmatter block opens at the start (mirrors
    ``_wiki_common.split_frontmatter`` but preserves the raw text verbatim).
    """
    if not text.startswith("---\n"):
        return "", text
    end = text.find("\n---\n", 4)
    if end == -1:
        return "", text
    return text[: end + 5], text[end + 5:]


def _refresh_frontmatter(fm_raw: str, nom: dict) -> str:
    """Update name/description/type in ``fm_raw``, preserving every other line.

    Extra keys, ordering, and formatting are kept; managed keys absent from the
    block are inserted before the closing ``---``.
    """
    managed = {"name": nom["name"], "description": nom["description"], "type": nom["type"]}
    lines = fm_raw.splitlines()
    seen: set[str] = set()
    out: list[str] = []
    for ln in lines:
        stripped = ln.strip()
        if ":" in ln and not stripped.startswith("- ") and stripped != "---":
            key = ln.split(":", 1)[0].strip()
            if key in managed:
                out.append(f"{key}: {managed[key]}")
                seen.add(key)
                continue
        out.append(ln)
    missing = [k for k in ("name", "description", "type") if k not in seen]
    if missing and out and out[-1].strip() == "---":
        insert_at = len(out) - 1
        for k in missing:
            out.insert(insert_at, f"{k}: {managed[k]}")
            insert_at += 1
    return "\n".join(out) + "\n"


def _compose_note(existing_text: str | None, nom: dict) -> str:
    """Return the note's new full text, touching only the managed block.

    - Absent file  → fresh frontmatter + block.
    - Has a block  → replace the block's inner content, refresh managed
                     frontmatter keys, leave everything else untouched.
    - Legacy (no block) → preserve all content and insert a managed block
                     immediately after the frontmatter (or at the top).
    """
    new_block = render_block(nom)
    if existing_text is None:
        return render_note(nom)

    fm_raw, rest = _split_raw_frontmatter(existing_text)

    if PROMOTED_BEGIN in rest and PROMOTED_END in rest:
        b = rest.index(PROMOTED_BEGIN)
        e = rest.index(PROMOTED_END) + len(PROMOTED_END)
        if e < len(rest) and rest[e] == "\n":
            e += 1  # consume the marker's own trailing newline
        new_fm = _refresh_frontmatter(fm_raw, nom) if fm_raw else fm_raw
        return new_fm + rest[:b] + new_block + rest[e:]

    # Legacy note without a managed block — migrate without losing anything.
    if fm_raw:
        return _refresh_frontmatter(fm_raw, nom) + new_block + rest
    return new_block + existing_text


def existing_provenance(note_path: Path) -> tuple[str, str] | None:
    """Read the authoritative `[Source: <source> — <date>]` line from a note.

    When the note carries a managed block, only the provenance INSIDE the block
    is authoritative — a migrated legacy note keeps its old body (and any stale
    `[Source]` line it contains) below the block, so a file-wide last-match would
    read the stale one. Falls back to the file-wide last match only for a pure
    legacy note with no block. Returns (source, date) or None.
    """
    if not note_path.is_file():
        return None
    text = note_path.read_text(encoding="utf-8")
    if PROMOTED_BEGIN in text and PROMOTED_END in text:
        b = text.index(PROMOTED_BEGIN)
        e = text.index(PROMOTED_END) + len(PROMOTED_END)
        text = text[b:e]  # restrict the scan to the managed block
    matches = _SOURCE_RE.findall(text)
    if not matches:
        return None
    source, date = matches[-1]
    return source, date


def incoming_wins(
    new_source: str, new_date: str, old_source: str, old_date: str
) -> bool:
    """Contradiction rule: higher priority wins; ties break to the newer date."""
    new_p, old_p = priority(new_source), priority(old_source)
    if new_p != old_p:
        return new_p > old_p
    return new_date > old_date


def _prune_target_lines(lines: list[str], target: str) -> list[str]:
    """Drop ledger entries whose ``<target>`` field equals ``target``.

    Used when a note is overwritten: its old body hashed to a different value, so
    the superseded ledger line would otherwise linger and count toward the cap.
    """
    kept: list[str] = []
    for ln in lines:
        s = ln.strip()
        if s.startswith("- "):
            parts = [p.strip() for p in s[2:].split("|")]
            if len(parts) >= 4 and parts[1] == target:
                continue  # superseded by the new body for this target
        kept.append(ln)
    return kept


def _record_ledger(
    ledger_path: Path, target: str, sha: str, line: str, *, overwrite: bool
) -> None:
    """Record a promotion line.

    On overwrite, first prune any prior lines for ``target`` (the superseded
    body's entry) so a note edited over time keeps exactly one ledger line.
    Then update-last-else-append by ``sha``, mirroring mark_adopted.py's ledger
    discipline for idempotent re-runs of the same body.
    """
    lines = ledger_path.read_text(encoding="utf-8").splitlines()
    if overwrite:
        lines = _prune_target_lines(lines, target)
    tag = f"| {sha} |"
    for i in range(len(lines) - 1, -1, -1):
        if tag in lines[i]:
            lines[i] = line  # update the LAST existing entry (canonical)
            break
    else:
        lines.append(line)  # new content — append
    ledger_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_receipt(
    receipt_dir: Path,
    *,
    manifest: str,
    promoted: int,
    skipped: int,
    targets: list[str],
) -> Path:
    """Write the promotion receipt into ``receipt_dir``. Returns its path.

    Kept module-level and free of promote()'s state so the schema — the one thing
    `mark_harvested.py` parses — can be unit-tested on its own, and so the single
    place that decides the shape of a receipt is obvious to whoever changes it.

    ``written_at`` is stamped here rather than passed in: the receipt is an audit
    record, so its time must be the instant it actually hit the disk, not an
    earlier moment the caller happened to have to hand. Raises ``OSError`` — the
    caller decides whether that is fatal (it is not; the notes are already
    written by then, and nothing downstream is gated on the receipt).
    """
    receipt_dir.mkdir(parents=True, exist_ok=True)
    path = receipt_dir / RECEIPT_NAME
    payload = {
        "version": RECEIPT_VERSION,
        "manifest": manifest,
        "promoted": promoted,
        "skipped": skipped,
        "targets": targets,
        "written_at": datetime.now(timezone.utc).isoformat(),
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def promote(
    records: list[dict],
    repo_dir: Path = REPO_DIR,
    *,
    dry_run: bool = False,
    receipt_dir: Path | None = None,
    manifest_arg: str | None = None,
) -> tuple[int, list[str]]:
    """Promote each nomination. Returns (rc, summary_lines).

    Path-parameterized on ``repo_dir`` so tests can drive a temp repo.

    ``receipt_dir`` defaults to ``None`` — no receipt — so every existing caller
    and test keeps working unchanged; only ``main()``, which knows where the
    manifest came from, opts in. ``manifest_arg`` is the manifest path exactly as
    the operator typed it, recorded verbatim so the receipt can be matched back
    to the command that produced it.
    """
    memory_dir = repo_dir / "memory"
    ledger_path = memory_dir / "learning-log.md"
    if not ledger_path.exists():
        return 1, [f"error: {ledger_path} missing — create the ledger first."]

    memory_root = memory_dir.resolve()

    # Phase 1 — validate every nomination before writing anything, so a malformed
    # object can't leave earlier notes half-written (no partial writes).
    for i, nom in enumerate(records):
        label = (isinstance(nom, dict) and (nom.get("name") or nom.get("target"))) or f"#{i}"
        if not isinstance(nom, dict):
            return 1, [f"error: {label}: nomination must be a JSON object"]

        missing = [f for f in REQUIRED_FIELDS if not nom.get(f)]
        if missing:
            return 1, [
                f"error: {label}: missing required field(s): {', '.join(missing)}"
            ]

        source = nom["source"]
        if source not in VALID_SOURCES:
            return 1, [
                f"error: {label}: invalid source {source!r} "
                f"(expected one of {sorted(VALID_SOURCES)})"
            ]

        bucket = str(nom["scope"]).split("/", 1)[0]
        if bucket not in VALID_SCOPE_BUCKETS:
            return 1, [
                f"error: {label}: invalid scope {nom['scope']!r} "
                f"(bucket must be one of {sorted(VALID_SCOPE_BUCKETS)})"
            ]

        # Containment: reject an absolute target or one that escapes memory/ via
        # ``..`` — either would let a nomination write outside the memory tree.
        note_path = memory_dir / nom["target"]
        try:
            note_path.resolve().relative_to(memory_root)
        except ValueError:
            return 1, [
                f"error: {label}: target {nom['target']!r} escapes memory/ "
                f"(must be a relative path inside memory/)"
            ]

    summary: list[str] = []
    promoted = skipped = 0
    # Targets actually written or overwritten, in manifest order — the receipt's
    # audit trail of what this pass put on disk (skips are counted, not listed).
    promoted_targets: list[str] = []
    # In --dry-run nothing is appended, so parse_ledger can't see earlier
    # would-writes; track them here so the preview dedups within the manifest.
    would_write: set[str] = set()
    # Distinct directories that had a note written/updated — reindexed once each.
    touched_dirs: set[Path] = set()

    for nom in records:
        source = nom["source"]
        h = content_hash12(nom["body"])
        ledger = parse_ledger(ledger_path)
        if h in ledger or h in would_write:
            skipped += 1
            summary.append(f"skip (dedup)   {nom['target']} — {h} already promoted")
            continue

        note_path = memory_dir / nom["target"]

        prov = existing_provenance(note_path)
        if prov is not None:
            old_source, old_date = prov
            # Same-source refinement: the same source correcting its own note
            # (body already differs — dedup let it through). Allow it even at
            # equal priority / same day, which incoming_wins would reject.
            if old_source == source or incoming_wins(
                source, nom["date"], old_source, old_date
            ):
                verb = "overwrite"
            else:
                skipped += 1
                summary.append(
                    f"skip (contradiction) {nom['target']} — incoming "
                    f"'{source}' ({nom['date']}) does not outrank existing "
                    f"'{old_source}' ({old_date})"
                )
                continue
        else:
            verb = "write"

        ledger_line = f"- {nom['date']} | {nom['target']} | {h} | promoted: {nom['name']}"

        if dry_run:
            would_write.add(h)
            touched_dirs.add(note_path.parent)
            summary.append(f"would {verb}  {nom['target']} — {h} ({source})")
            promoted += 1
            promoted_targets.append(nom["target"])
            continue

        note_path.parent.mkdir(parents=True, exist_ok=True)
        existing = note_path.read_text(encoding="utf-8") if note_path.is_file() else None
        note_path.write_text(_compose_note(existing, nom), encoding="utf-8")
        touched_dirs.add(note_path.parent)
        _record_ledger(
            ledger_path, nom["target"], h, ledger_line, overwrite=(verb == "overwrite")
        )
        promoted += 1
        promoted_targets.append(nom["target"])
        summary.append(f"{verb:<9} {nom['target']} — {h} ({source})")

    prefix = "[dry-run] " if dry_run else ""
    summary.append(f"{prefix}promoted {promoted}, skipped {skipped}")

    # Regenerate the MEMORY.md index for each touched directory so it never drifts
    # from the notes on disk. A single reindex failure must not fail the promote.
    for d in sorted(touched_dirs):
        if dry_run:
            summary.append(f"would reindex {d}/MEMORY.md")
            continue
        try:
            _, idx_summary = wiki_index.regenerate(d)
            summary.extend(idx_summary)
        except Exception as e:  # noqa: BLE001 — reindex is best-effort
            summary.append(f"⚠  reindex failed for {d}/MEMORY.md: {e}")

    # The promotion receipt. A dry-run must never leave one behind — the receipt
    # records writes that happened — so the preview only names where it would go.
    # A receipt IS written when promoted == 0 but rc is 0 (everything deduped):
    # "read it, promoted nothing new" is a real outcome of a real pass, and
    # suppressing the record of it would hide the run rather than report it.
    if receipt_dir is not None:
        if dry_run:
            summary.append(f"would write receipt {receipt_dir / RECEIPT_NAME}")
        else:
            # Notes and ledger are already on disk; a receipt we cannot write is
            # a lost proof, not a failed promote. Warn and keep rc 0 — same
            # best-effort discipline as the reindex above.
            try:
                receipt_path = write_receipt(
                    receipt_dir,
                    manifest=manifest_arg or "",
                    promoted=promoted,
                    skipped=skipped,
                    targets=promoted_targets,
                )
                summary.append(f"receipt   {receipt_path}")
            except OSError as e:
                summary.append(
                    f"⚠  receipt not written to {receipt_dir / RECEIPT_NAME}: {e} "
                    f"— the promote succeeded; only the audit record is missing. "
                    f"mark_harvested.py warns about that and stamps anyway, so fix "
                    f"the path if you want the record, not to unblock the stamp."
                )

    if not dry_run:
        file_lines = len(ledger_path.read_text(encoding="utf-8").splitlines())
        if file_lines > MAX_LEDGER_LINES:
            summary.append(
                f"\n⚠  {ledger_path.name} is {file_lines} lines (> {MAX_LEDGER_LINES}). "
                f"Compact the oldest entries into a one-line summary to stay under the cap."
            )
    return 0, summary


def main() -> int:
    ap = argparse.ArgumentParser(description="Promote learning nominations into memory/.")
    ap.add_argument("manifest", help="path to a JSON nominations file")
    ap.add_argument("--dry-run", action="store_true", help="print actions, write nothing")
    args = ap.parse_args()

    # The summary uses a ⚠ glyph and echoes note targets that may carry other
    # non-ASCII; a legacy Windows console defaults to cp1252 and would raise
    # UnicodeEncodeError on them — after every note was already written, turning
    # a fully successful promote into a non-zero exit. Reconfigure to UTF-8 when
    # possible (guarded — a redirected StringIO in tests has no reconfigure).
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass

    manifest = Path(args.manifest)
    if not manifest.is_file():
        print(f"error: no such manifest: {manifest}")
        return 1
    try:
        records = json.loads(manifest.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"error: {manifest} is not valid JSON: {e}")
        return 1
    if not isinstance(records, list):
        print(f"error: {manifest} must contain a JSON list of nominations.")
        return 1

    # The receipt lands beside the manifest it consumed: the harvest flow stages
    # each run under eval/learnings/<timestamp>/, so manifest and proof-of-promote
    # stay in the same directory and cannot drift apart.
    rc, summary = promote(
        records,
        dry_run=args.dry_run,
        receipt_dir=manifest.parent,
        manifest_arg=args.manifest,
    )
    for line in summary:
        print(line)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
