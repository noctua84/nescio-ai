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
  5. appends a ledger line so the promotion is skipped on future runs.

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
    python scripts/promote_learnings.py nominations.json
    python scripts/promote_learnings.py nominations.json --dry-run
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

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

# Matches the trailing provenance line this script writes, so an existing note's
# recorded source/date can be read back for the contradiction check.
_SOURCE_RE = re.compile(
    r"\[Source:\s*(user override|empirical|agent inference)\s*[—-]\s*"
    r"(\d{4}-\d{2}-\d{2})\s*\]"
)


def render_note(nom: dict) -> str:
    """YAML frontmatter + markdown body + trailing provenance line."""
    frontmatter = (
        "---\n"
        f"name: {nom['name']}\n"
        f"description: {nom['description']}\n"
        f"type: {nom['type']}\n"
        "---\n"
    )
    return frontmatter + nom["body"] + f"\n[Source: {nom['source']} — {nom['date']}]\n"


def existing_provenance(note_path: Path) -> tuple[str, str] | None:
    """Read the last `[Source: <source> — <date>]` line from an existing note.

    Returns (source, date) or None if the file is absent / has no such line.
    """
    if not note_path.is_file():
        return None
    matches = _SOURCE_RE.findall(note_path.read_text(encoding="utf-8"))
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


def promote(
    records: list[dict], repo_dir: Path = REPO_DIR, *, dry_run: bool = False
) -> tuple[int, list[str]]:
    """Promote each nomination. Returns (rc, summary_lines).

    Path-parameterized on ``repo_dir`` so tests can drive a temp repo.
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
    # In --dry-run nothing is appended, so parse_ledger can't see earlier
    # would-writes; track them here so the preview dedups within the manifest.
    would_write: set[str] = set()

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
            summary.append(f"would {verb}  {nom['target']} — {h} ({source})")
            promoted += 1
            continue

        note_path.parent.mkdir(parents=True, exist_ok=True)
        note_path.write_text(render_note(nom), encoding="utf-8")
        _record_ledger(
            ledger_path, nom["target"], h, ledger_line, overwrite=(verb == "overwrite")
        )
        promoted += 1
        summary.append(f"{verb:<9} {nom['target']} — {h} ({source})")

    prefix = "[dry-run] " if dry_run else ""
    summary.append(f"{prefix}promoted {promoted}, skipped {skipped}")

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

    rc, summary = promote(records, dry_run=args.dry_run)
    for line in summary:
        print(line)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
