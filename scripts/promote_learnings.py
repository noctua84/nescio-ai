#!/usr/bin/env python3
"""Promote vetted learning nominations into the synced repo memory/ tree.

The learning loop's mechanical committer — analogous to `mark_adopted.py` for the
adopt flow. Given a JSON manifest of nominations (see below), for each one it:

  1. validates the declared source is one of user override | empirical | agent
     inference;
  2. dedups by a content hash against `memory/learning-log.md` — of the note
     body on the `body` shape, of each learning unit on the `units` shape (a
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

**Two payload shapes, and exactly one per nomination** (#180 stage 1,
ADR 0007 *Decision 2*). The schema above is the canonical, agent-facing one and
is unchanged: ``commands/harvest-memory.md`` and ``memory/CONVENTIONS.md`` still
describe ``body``, and this script still accepts it. What follows is the second
shape this script understands. It is deliberately **not** yet part of the
agent-facing contract — the three canonical schema copies move together in
stage 2, after the scripts have been reviewed — so the ``units`` path is
unexercised in production until then. That is intended, not a gap.

  * ``body`` — a note body. **It REPLACES the managed block, byte for byte as
    it always has.** Stated here because it is what makes stage 1 a no-op: the
    un-migrated harvest command keeps emitting ``body``, so nothing about its
    behaviour may move, and replacement is not an accident to be discovered
    later. It is the documented behaviour of this shape.
  * ``units`` — a list of learning units. Each carries its own ``text``,
    ``source`` and ``date``, and may carry ``supersedes``::

        {
          "scope": ..., "target": ..., "name": ..., "description": ...,
          "type": ..., "source": ..., "date": ...,
          "units": [
            {
              "text":   "<markdown for ONE learning>",
              "source": "user override" | "empirical" | "agent inference",
              "date":   "YYYY-MM-DD",
              "supersedes": ["<hash12>", ...]        # optional
            },
            ...
          ]
        }

**Neither shape is rc 1, and BOTH shapes is rc 1.** A nomination carrying
``body`` and ``units`` together declares two different things for one note, and
silently preferring either reading would make the record untrue in whichever
direction the harvest did not mean — the same discipline
``UNROUTED_FORBIDDEN_FIELDS`` applies to a declaration that also names a target.

What the ``units`` path does differently, and why:

  * **Supersession, not replacement.** Units accumulate; an incoming unit may
    name hashes it ``supersedes``, and the renderer then **omits the superseded
    unit's text entirely** — not demoted, not commented out, not moved below a
    fold. For the ``people`` and ``feedback`` buckets that is a hard
    requirement: those notes are dated, attributed observations about
    identifiable individuals, and supersession is the only erasure path
    ``memory/CONVENTIONS.md`` leaves open. The unit survives in the ledger, so
    ADR 0007 *Decision 4*'s "nothing is lost" still holds — the view is
    curated, the record is not.
  * **Insertion order, never precedence order.** See ``render_units``:
    ``PRIORITY`` ranks ``user override`` highest, so a precedence sort would
    put a late override at the TOP and rewrite the block from its first line,
    turning the reviewable git diff from "the new unit" into "the whole block,
    find the change". The diff IS the review gate.
  * **One marker pair, one anchor per unit.** ``<!-- unit:<hash12> -->``, with
    a ``legacy`` flag on a unit imported from a pre-#180 merged body. The
    anchor is mandatory, so a ``units`` note is the ``body`` note's output plus
    one line per unit rather than byte-identical to it.
  * **Legacy blocks import as one unit, lazily.** A managed block with no
    anchors parses as exactly one ``legacy`` unit on its next promotion. No
    eager corpus rewrite, and no guess at a merged body's internal boundaries.
  * **Per-unit ledger lines, and supersession as an event.** One
    ``promoted:`` line per unit, plus a ``superseded:`` line when a unit's text
    is retracted. A superseded unit's hash therefore STAYS in the dedup set and
    re-submitting retracted text is refused as "already promoted" — it *was*
    promoted, and silently re-adding text a human retracted is worse than
    refusing it. See ``LEDGER_VERB_SUPERSEDED``.
  * **No note-level contradiction check.** It compares only ``source`` and
    ``date`` and never looks at content, so against a block of units it would
    fire as a near-pure false positive. The rule is kept where it still means
    something — per unit, gating supersession, which is the only operation here
    that deletes. See ``_supersession_allowed``.
  * **The ledger is append-only on this path.** ``_prune_target_lines`` runs
    for ``body`` only; pruning a target on the ``units`` path would delete the
    per-unit history supersession exists to keep.

**One nomination may instead declare that it could not be routed** (#168):

    {
      "unrouted": true,
      "unrouted_reason": "<why no target could be determined>",
      "name": "<slug>", "description": "<one-line>",
      "body": "<markdown>", "source": "...", "date": "YYYY-MM-DD"
    }

ADR 0002 made "a harvest pass reports it cannot determine where to file a
learning" a trigger for revisiting the memory architecture, and that trigger
could never fire: ``target`` was unconditionally required, so the *only* way to
express "I could not place this" was to submit a nomination that failed
validation as **malformed**. The condition was unrepresentable, not merely
unmeasured, which is why ADR 0005 superseded 0002 still blind to it.

The declaration is per-nomination rather than a new top-level manifest key
because the manifest is a bare JSON list; adding a key would mean changing its
container type, which every existing manifest and every reader would have to be
migrated for. A declaring nomination:

  * writes **no note** — there is no path to write one to, which is the point;
  * does **not** count as promoted, and is reported on its own summary line;
  * never enters ``memory/learning-log.md`` — the ledger is a record of
    *promotions*, and its entries are keyed by target and consumed by
    ``compute_readiness.count_promotions`` as "notes this repo has". A ledger
    line for a note that does not exist would inflate that count and give the
    dedup hash a target it could never resolve;
  * does **not** fail the run. A harvest that found one unroutable learning
    among nine good ones must still promote the nine. Refusing the pass would
    punish the honest report and teach the next one to invent a target instead,
    which is how the signal went missing in the first place;
  * is counted in the durable per-repo tally
    (``scripts/_unrouted_record.py``), which is what
    ``scripts/check_memory_triggers.py`` reads. ``receipt.json`` is per-run and
    cannot answer a question about accumulated history.

``scope`` and ``target`` are **rejected** on a declaring nomination rather than
ignored: a nomination carrying both a target and a claim that it has none is
ambiguous, and silently preferring one reading would make the record untrue in
whichever direction the harvest did not mean. Partial routing ("I know the
bucket but not the note") is deliberately not expressible — it is a different
feature, and guessing at its semantics here is how the original required-field
rule came to erase this signal.

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
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import wiki_index

import _unrouted_record

from _marker_block import MarkerBlock, fenced_line_indices, split_lines

from _learning_common import (
    REPO_DIR,
    VALID_SOURCES,
    content_hash12,
    parse_ledger,
    priority,
)

# `READ_NAME` belongs to begin_harvest.py because that is what writes the file.
# Imported rather than repeated here so the stamp command printed at the end of a
# promote cannot drift from the filename the read manifest actually has.
from begin_harvest import READ_NAME  # noqa: E402

# Every nomination must carry these before anything is written — a malformed
# object fails its own line cleanly (rc 1) instead of raising KeyError mid-run
# after earlier notes already wrote.
#
# `body` is NOT in this tuple: it is one of the two mutually exclusive payload
# shapes (see `BODY_FIELD` / `UNITS_FIELD` below), and which one a nomination
# carries is a separate question from whether the fields common to both are
# present. The validator still reports a nomination with neither as
# ``missing required field(s): body or units``, so the message a harvest sees
# for an omitted body is unchanged in substance.
REQUIRED_FIELDS = (
    "scope",
    "target",
    "name",
    "description",
    "type",
    "source",
    "date",
)

# The two payload shapes, and the whole of stage 1's dual-shape discipline
# (#180). Exactly one must be present:
#
#   * ``body``  — a note body. **It REPLACES the managed block, byte for byte
#                 as it always has.** This is deliberate and is what makes
#                 stage 1 a no-op for the un-migrated `commands/harvest-memory.md`,
#                 which still emits this shape. It is not an accident waiting
#                 to be discovered: replacement is the documented behaviour of
#                 this shape and stays that way.
#   * ``units`` — a list of learning units, each with its own text, `source`
#                 and `date`, and optionally `supersedes`. Units accumulate in
#                 insertion order and supersession curates the view.
#
# **Neither is rc 1, and BOTH is rc 1.** A nomination carrying both declares
# two different things for one note and silently preferring either reading
# would make the record untrue in the direction the harvest did not mean —
# the same discipline `UNROUTED_FORBIDDEN_FIELDS` applies to a declaration
# that also names a target.
BODY_FIELD = "body"
UNITS_FIELD = "units"

# What each learning unit must carry. `source`/`date` are per unit and
# REQUIRED (ADR 0007 Decision 2, D7): inheriting them from the nomination
# would silently backdate and re-attribute every unit in it, and precedence is
# only readable from the rendered block if each unit states its own.
UNIT_TEXT_FIELD = "text"
UNIT_SUPERSEDES_FIELD = "supersedes"
UNIT_REQUIRED_FIELDS = (UNIT_TEXT_FIELD, "source", "date")

# A unit hash as `content_hash12` produces it. `supersedes` entries are matched
# against it before anything is written: a hash that cannot possibly match an
# anchor is a retraction that silently does not happen, which for the `people`
# and `feedback` buckets is an unmet erasure obligation rather than a typo.
_HASH12_RE = re.compile(r"[0-9a-f]{12}")

# The per-nomination declaration that routing failed (#168). Truthy `unrouted`
# switches the nomination onto the unrouted path; see the module docstring.
UNROUTED_FIELD = "unrouted"
UNROUTED_REASON_FIELD = "unrouted_reason"

# What an unrouted nomination must still carry. `target`, `scope` and `type`
# are all absent by construction — the first two are rejected outright (see
# `UNROUTED_FORBIDDEN_FIELDS`) and `type` is the *note's* frontmatter type, of
# which there is no note. `body` stays required: a record that the harvest could
# not place a learning, without the learning, is a count with nothing behind it,
# and the operator reading the trigger has no way to recover what was lost.
UNROUTED_REQUIRED_FIELDS = (
    UNROUTED_REASON_FIELD,
    "name",
    "description",
    "body",
    "source",
    "date",
)

# Fields whose presence contradicts the declaration. See the module docstring on
# why these are rejected rather than ignored.
UNROUTED_FORBIDDEN_FIELDS = ("target", "scope")

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

# The whole-line, fence-aware marker machinery, bound to this script's pair —
# the same shared module `compute_readiness.py` and `wiki_index.py` use for
# their own generated blocks (issue #121). Recognition is line-anchored and
# skips fenced code, so a note that merely *documents* the block shape — e.g.
# quoting both markers inside a ```-fenced example, the shape
# `memory/CONVENTIONS.md` itself teaches — is not mistaken for owning a real
# block and spliced accordingly. `_marker_block` owns the recognition and
# `none`/`ok`/`malformed` classification; everything below owns what goes
# *inside* the block and what a malformed one does to this script's run.
_BLOCK = MarkerBlock(PROMOTED_BEGIN, PROMOTED_END)

# One marker PAIR for the block, one single-line ANCHOR per unit inside it
# (ADR 0007 Decision 2, D2/D3). The anchor is a single line on purpose: it is
# not a pair, so it cannot trip `MarkerBlock.classify`'s "more than one begin
# marker is malformed" rule, and the #102/#121 semantics that rule protects
# stay intact for the outer pair.
#
# The anchor is **mandatory**, including for a one-unit block, and that is why
# the `units` path is not byte-identical to the `body` path's output — it is
# the same text plus one anchor line per unit. Dropping it for the one-unit
# case would make a new-shape note indistinguishable on disk from a legacy
# merged body and leave the `legacy` flag nowhere to live: `_refresh_frontmatter`
# manages exactly three frontmatter keys, and a ledger line has exactly four
# fields.
#
# The hash is stored explicitly rather than derived on read (D8). Rendering
# normalises trailing blank lines, so a recomputed hash would silently stop
# joining a retrieved passage to its ledger line; a written-down hash cannot.
UNIT_LEGACY_FLAG = "legacy"
_UNIT_ANCHOR_RE = re.compile(
    r"^[ \t]*<!--[ \t]*unit:(?P<hash>[0-9a-f]{12})"
    r"(?P<flags>(?:[ \t]+[a-z][a-z0-9-]*)*)[ \t]*-->[ \t]*$"
)

# The ledger's fourth field is `<verb> <name>`. `promoted:` has always been the
# only verb; `superseded:` is the second, and it exists so that supersession is
# a recorded EVENT rather than something inferred from a line's absence.
#
# This is the open decision #180 asked to be made and stated rather than
# buried. A superseded unit's hash **stays in the dedup set**: `parse_ledger`
# keys by hash and both lines carry the same hash, so the later `superseded:`
# line overwrites the earlier `promoted:` entry with the same target and the
# supersession date — the hash remains present, which is what `promote()`'s
# dedup check actually tests. Re-submitting retracted text is therefore
# refused as "already promoted", which is the intended outcome: it *was*
# promoted, and silently re-adding text a human retracted is worse than
# refusing it. The cost is that re-adding a retracted unit needs its text to
# differ, and the gain is that `memory/learning-log.md` states what happened
# instead of implying it by omission.
#
# `parse_ledger`'s return contract is unchanged — `{hash12: (date, target)}`
# for any `- a | b | c | ...` line — and its only other caller,
# `compute_readiness.count_promotions`, counts DISTINCT TARGETS and discards
# the date, so neither the extra line nor the newer date moves its number.
LEDGER_VERB_PROMOTED = "promoted:"
LEDGER_VERB_SUPERSEDED = "superseded:"

# The promotion receipt. Filename is fixed and lives beside the manifest so the
# next step in the harvest flow can find it from the manifest path alone, with no
# extra bookkeeping to lose. ``RECEIPT_VERSION`` is bumped only on a breaking
# schema change — `mark_harvested.py` will not guess at a version it does not
# recognise; it says so and stamps on the manifest's authority instead.
RECEIPT_NAME = "receipt.json"
# 2 since #180 stage 1: a nomination may now carry `units` instead of `body`,
# so a receipt no longer describes passes of one single schema. Bumping it is
# bookkeeping, not a coupling — `mark_harvested.check_receipt` is advisory and
# its docstring says "the return value is never a refusal", so an older
# `mark_harvested.py` warns about the version and stamps anyway.
RECEIPT_VERSION = 2


def is_unrouted(nom: object) -> bool:
    """True when ``nom`` declares it could not be routed.

    Truthiness rather than ``is True`` so a manifest written by hand with
    ``"unrouted": 1`` behaves as its author plainly meant. An explicitly false
    or absent flag is an ordinary nomination, so adding the key with a falsey
    value to every nomination is harmless — which is what keeps a generator that
    emits the field unconditionally from breaking the normal path.
    """
    return isinstance(nom, dict) and bool(nom.get(UNROUTED_FIELD))


def validate_unrouted(nom: dict, label: str) -> str | None:
    """Error message for a malformed unrouted declaration, or None if it is sound.

    Kept beside the ordinary required-field check rather than folded into it:
    the two have disjoint field sets and opposite expectations about ``target``,
    and a single function that branched on the flag would read as though the
    rules were one rule with exceptions. They are two shapes.
    """
    missing = [f for f in UNROUTED_REQUIRED_FIELDS if not nom.get(f)]
    if missing:
        return (
            f"error: {label}: unrouted nomination missing required field(s): "
            f"{', '.join(missing)}"
        )
    present = [f for f in UNROUTED_FORBIDDEN_FIELDS if nom.get(f)]
    if present:
        return (
            f"error: {label}: unrouted nomination must not carry "
            f"{', '.join(present)} — it declares that no target could be "
            f"determined, so naming one contradicts the declaration. Drop the "
            f"field, or drop '{UNROUTED_FIELD}' and promote it normally."
        )
    if nom["source"] not in VALID_SOURCES:
        return (
            f"error: {label}: invalid source {nom['source']!r} "
            f"(expected one of {sorted(VALID_SOURCES)})"
        )
    return None


def is_units_shaped(nom: object) -> bool:
    """True when ``nom`` carries the `units` payload rather than a `body`.

    Presence is ``is not None``, not truthiness — unlike `is_unrouted`, and the
    difference is deliberate. ``"units": []`` is a malformed units nomination
    (it declares the new shape and supplies no learning), and
    `validate_units` must be able to say so; truthiness would quietly route it
    to the body path and then report a missing `body`, which names the wrong
    problem. ``"units": null`` still reads as absent, so a generator that emits
    the key unconditionally keeps working on the body path.
    """
    return isinstance(nom, dict) and nom.get(UNITS_FIELD) is not None


def validate_units(nom: dict, label: str) -> str | None:
    """Error message for a malformed `units` payload, or None if it is sound.

    Kept beside `validate_unrouted` and the ordinary required-field check for
    the same reason those two are separate: three shapes, three field sets.

    Every check here runs in `promote()`'s phase 1, before anything is
    written, so a bad unit cannot leave earlier notes half-written.
    """
    units = nom[UNITS_FIELD]
    if not isinstance(units, list) or not units:
        return (
            f"error: {label}: '{UNITS_FIELD}' must be a non-empty JSON list of "
            f"learning units — a nomination declaring the units shape with no "
            f"units records a promotion with nothing in it."
        )
    for i, unit in enumerate(units):
        where = f"{label}: unit #{i}"
        if not isinstance(unit, dict):
            return f"error: {where}: learning unit must be a JSON object"
        missing = [f for f in UNIT_REQUIRED_FIELDS if not unit.get(f)]
        if missing:
            return (
                f"error: {where}: missing required field(s): "
                f"{', '.join(missing)}"
            )
        if unit["source"] not in VALID_SOURCES:
            return (
                f"error: {where}: invalid source {unit['source']!r} "
                f"(expected one of {sorted(VALID_SOURCES)})"
            )
        supersedes = unit.get(UNIT_SUPERSEDES_FIELD)
        if supersedes is None:
            continue
        if not isinstance(supersedes, list):
            return (
                f"error: {where}: '{UNIT_SUPERSEDES_FIELD}' must be a JSON list "
                f"of 12-hex unit hashes"
            )
        for h in supersedes:
            if not isinstance(h, str) or not _HASH12_RE.fullmatch(h):
                return (
                    f"error: {where}: '{UNIT_SUPERSEDES_FIELD}' entry {h!r} is "
                    f"not a 12-hex unit hash. Rejected rather than warned "
                    f"about: a hash that cannot match any anchor is a "
                    f"retraction that silently does not happen, and for the "
                    f"'people' and 'feedback' buckets that is an unmet "
                    f"erasure obligation."
                )
    return None


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


@dataclass(frozen=True)
class Unit:
    """One learning unit: its own text, its own provenance, its own identity.

    ``hash12`` is `content_hash12` of ``text`` for an incoming unit and the
    value read off the anchor for a stored one — never recomputed on read (D8).

    ``source``/``date`` are required on an incoming unit and may be ``None``
    only for a stored one: a hand-made managed block can carry prose with no
    `[Source: ...]` line at all, and inventing provenance for it would be
    worse than rendering it without.

    ``legacy`` marks a unit that was imported from a managed block that had no
    anchors — i.e. a pre-#180 merged body, read back as a single unit. It is
    evidence about the unit's origin, not about its content, and it is the
    reason the anchor cannot be optional: there is nowhere else for it to live.
    """

    hash12: str
    text: str
    source: str | None = None
    date: str | None = None
    legacy: bool = False


def unit_anchor(unit: Unit) -> str:
    """The one-line `<!-- unit:<hash12> -->` anchor, `legacy` flag included."""
    flag = f" {UNIT_LEGACY_FLAG}" if unit.legacy else ""
    return f"<!-- unit:{unit.hash12}{flag} -->"


def render_units(units: list[Unit]) -> str:
    """The inside of a managed block: anchor, text and provenance per unit.

    Rendered in the order given — **insertion order, never precedence order**
    (ADR 0007 Decision 2, D4). Sorting by precedence was proposed so the file
    shows the winner first, but `PRIORITY` ranks `user override` highest, so a
    late override would sort to the TOP and rewrite the block from its first
    line. That turns the reviewable git diff from "the new unit" into "the
    whole block, find the change", and the diff IS the review gate. Precedence
    is already readable from the per-unit `[Source: ...]` lines, and a markdown
    sort order is not an adjudicator.

    Units are separated by one blank line so the block reads as markdown. The
    parser strips trailing blank lines from each unit's text, so parse → render
    is a fixed point for anything this function wrote.
    """
    chunks: list[str] = []
    for unit in units:
        chunk = f"{unit_anchor(unit)}\n{unit.text}\n"
        if unit.source and unit.date:
            chunk += f"[Source: {unit.source} — {unit.date}]\n"
        chunks.append(chunk)
    return "\n".join(chunks)


def render_units_block(units: list[Unit]) -> str:
    """`render_units` wrapped in the single owned marker pair."""
    return f"{PROMOTED_BEGIN}\n" + render_units(units) + f"{PROMOTED_END}\n"


def _split_unit_chunk(chunk: str) -> tuple[str, str | None, str | None]:
    """Split one unit's region into (text, source, date).

    The provenance line is the LAST thing `render_units` writes for a unit, so
    the scan starts at the bottom and stops at the first non-blank line: if
    that line is a `[Source: ...]` line and nothing else, it is the unit's
    provenance and comes off; otherwise the unit has none and the whole region
    is text. Scanning the whole region instead would let a unit whose prose
    quotes the provenance shape lose its last paragraph.
    """
    lines = chunk.splitlines()
    source = date = None
    for i in range(len(lines) - 1, -1, -1):
        if not lines[i].strip():
            continue
        m = _SOURCE_RE.search(lines[i])
        if m and lines[i].strip() == m.group(0).strip():
            source, date = m.group(1), m.group(2)
            del lines[i:]
        break
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines), source, date


def parse_block_units(inner: str) -> list[Unit]:
    """Read a managed block's content back into units, in document order.

    ``inner`` is `MarkerBlock.inner(...)` — the text between the marker lines,
    both excluded — so this never has to locate the block itself.

    **A block with no unit anchors parses as exactly one `legacy` unit.** That
    is how the 175 blocks that exist today import: lazily, on their next
    promotion, with no eager rewrite of the corpus and no guess at internal
    boundaries. Paragraph-splitting a merged body was considered and rejected
    (ADR 0007 Decision 2, D6): in a merged body a paragraph break is
    formatting, not a learning boundary, and the synthesised units would
    inherit provenance they never earned. One unit understates the structure;
    a wrong guess invents it.

    Anchor recognition is whole-line and fence-aware, reusing `_marker_block`'s
    own scans — a block whose prose documents the anchor shape inside a
    ```-fenced example must not have that example read as a unit boundary,
    which is the outer pair's #102/#121 failure class one level down.

    Content before the first anchor is kept as a leading `legacy` unit rather
    than dropped. `render_units` never produces that shape, so it can only come
    from a hand edit — and losing hand-written prose silently is the worst
    outcome available to the learning loop's only sanctioned writer.
    """
    lines = split_lines(inner)
    fenced = fenced_line_indices(lines)
    anchors: list[tuple[int, str, bool]] = []
    for i, (_, _, raw) in enumerate(lines):
        if i in fenced:
            continue
        m = _UNIT_ANCHOR_RE.match(raw.rstrip("\r\n"))
        if m:
            flags = (m.group("flags") or "").split()
            anchors.append((i, m.group("hash"), UNIT_LEGACY_FLAG in flags))

    units: list[Unit] = []
    head_stop = anchors[0][0] if anchors else len(lines)
    head = "".join(raw for _, _, raw in lines[:head_stop])
    if head.strip():
        text, source, date = _split_unit_chunk(head)
        units.append(
            Unit(
                hash12=content_hash12(text),
                text=text,
                source=source,
                date=date,
                legacy=True,
            )
        )
    for n, (at, h, legacy) in enumerate(anchors):
        stop = anchors[n + 1][0] if n + 1 < len(anchors) else len(lines)
        text, source, date = _split_unit_chunk(
            "".join(raw for _, _, raw in lines[at + 1:stop])
        )
        units.append(
            Unit(hash12=h, text=text, source=source, date=date, legacy=legacy)
        )
    return units


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


def _splice_block(
    existing_text: str | None, nom: dict, new_block: str
) -> tuple[str | None, str]:
    """Put ``new_block`` where this script's managed block belongs.

    The one place that decides *where* a block goes, shared by both payload
    shapes: `_compose_note` passes `render_block(nom)` for a `body`
    nomination and `plan_units` passes `render_units_block(...)` for a `units`
    one. Extracted rather than duplicated because this is the destructive
    half — the splice — and two copies of it is how #102 and #121 happened.

    See `_compose_note` for the full disposition contract; it is unchanged.
    """
    if existing_text is None:
        return render_frontmatter(nom) + new_block, "created"

    fm_raw, rest = _split_raw_frontmatter(existing_text)

    kind, reason = _BLOCK.classify(rest)
    if kind == "malformed":
        return None, f"malformed:{reason}"

    if kind == "ok":
        start, stop = _BLOCK.span(rest)
        new_fm = _refresh_frontmatter(fm_raw, nom) if fm_raw else fm_raw
        return new_fm + rest[:start] + new_block + rest[stop:], "spliced"

    # kind == "none" — legacy note without a managed block. Migrate without
    # losing anything.
    if fm_raw:
        return _refresh_frontmatter(fm_raw, nom) + new_block + rest, "migrated"
    return new_block + existing_text, "migrated"


def _compose_note(existing_text: str | None, nom: dict) -> tuple[str | None, str]:
    """Return (new_text_or_None, disposition) for ``existing_text`` + ``nom``.

    **The `body` path, and it REPLACES the managed block.** That is the whole
    of stage 1's no-op guarantee (#180): `commands/harvest-memory.md` still
    emits `body`, and a `body`-shaped nomination therefore produces
    byte-identical output to the code before units existed. The `units` path
    is `plan_units`, which supersedes rather than replaces; the two never mix,
    because a nomination carrying both fields is rejected in phase 1.

    Mirrors `compute_readiness.compose` / `wiki_index.compose`: disposition is
    one of `created` / `spliced` / `migrated` / `malformed:<reason>`, and
    `None` means "write nothing" — the caller must treat the nomination as
    skipped, not written, exactly as it already treats a dedup or a lost
    contradiction.

    - Absent file  → fresh frontmatter + block ("created").
    - Markers `ok` → replace the block's inner content, refresh managed
                     frontmatter keys, leave everything else untouched
                     ("spliced").
    - Markers `malformed` → **refuse**. An orphan begin, an orphan end, or a
                     duplicate make the block's extent unknowable, so splicing
                     would have to guess — appending duplicates it forever,
                     truncating at EOF can eat trailing prose. That guess is
                     exactly #102 / #121's destructive failure class, so the
                     caller skips this nomination instead ("malformed:<reason>").
    - Markers `none` → legacy note with no real block (including one whose
                     body only *mentions* the markers inside a fenced code
                     example — `_marker_block`'s fence-aware scan does not
                     count that as a block). Preserve all content and insert a
                     managed block immediately after the frontmatter, or at
                     the top ("migrated").

    Classification happens on ``rest`` — the text after any frontmatter is
    split off — matching the scope the original bare-substring check used;
    the frontmatter block itself is never searched for these markers.
    """
    return _splice_block(existing_text, nom, render_block(nom))


def existing_provenance(note_path: Path) -> tuple[str, str] | None:
    """Read the authoritative `[Source: <source> — <date>]` line from a note.

    When the note carries a well-formed managed block, only the provenance
    INSIDE the block is authoritative — a migrated legacy note keeps its old
    body (and any stale `[Source]` line it contains) below the block, so a
    file-wide last-match would read the stale one. Falls back to the file-wide
    last match for a legacy note with no real block — including one whose body
    only *mentions* the markers inside a fenced code example, which
    `_marker_block`'s fence-aware scan does not count as a block either.

    Returns None outright for a note whose markers are malformed: the block's
    extent is unknowable, and reading across it would make the same guess this
    script's splice sites exist to avoid. `promote()` is the one place that
    turns that condition into a skip-and-report decision for the whole
    nomination; this function's job is only to read, safely, when there is
    something unambiguous to read.
    """
    if not note_path.is_file():
        return None
    text = note_path.read_text(encoding="utf-8")
    kind, _ = _BLOCK.classify(text)
    if kind == "malformed":
        return None
    if kind == "ok":
        start, stop = _BLOCK.span(text)
        text = text[start:stop]  # restrict the scan to the managed block
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


@dataclass(frozen=True)
class UnitsPlan:
    """What a `units` nomination would do to one note. Decided before writing.

    `plan_units` is pure — it never touches disk — so `promote()` can compute
    the whole decision under ``--dry-run`` and a preview can never promise a
    write a real run would go on to refuse. Same property `_compose_note`
    already has, and the same reason.

    ``new_text`` is None for both refusals: `malformed:<reason>` markers and
    `dedup` (nothing to add and nothing to supersede). ``recorded`` is the
    units that need a ledger `promoted:` line; ``removed`` is the stored units
    whose text supersession dropped, each of which gets a `superseded:` event.
    ``warnings`` are operator-facing lines that do not stop the write.
    """

    new_text: str | None
    disposition: str
    added: tuple[Unit, ...] = ()
    removed: tuple[Unit, ...] = ()
    recorded: tuple[Unit, ...] = ()
    warnings: tuple[str, ...] = ()


def _supersession_allowed(incoming: Unit, stored: Unit) -> bool:
    """May ``incoming`` remove ``stored``'s text from the rendered block?

    Supersession is the one operation on the `units` path that **deletes**, so
    it is the one that needs the precedence rule. Adding a unit clobbers
    nothing — both units render, each with its own Source line, and ADR 0007
    Decision 4 has the deterministic layer adjudicate at read time — so
    additions are deliberately NOT precedence-gated, and the note-level
    contradiction check is skipped entirely for this shape. That check compares
    only `source` and `date` and never looks at content; against a block of
    units `existing_provenance` would read "the last unit's" provenance, which
    is arbitrary, and the check would fire as a near-pure false positive.

    But `memory/CONVENTIONS.md` states the rule's actual purpose — "without
    it, an `agent inference` could silently clobber a `user override`" — and an
    `agent inference` unit erasing a `user override` unit is exactly that
    clobber, one level down. So the rule is kept where it still means
    something: per unit, against the unit being removed (ADR 0007 Decision 2,
    D7), using the same two branches the body path uses — same-source
    refinement is allowed outright, otherwise `incoming_wins`.

    A stored unit with no parseable provenance is freely supersedable. There is
    nothing to outrank, and refusing would make a hand-made block permanently
    un-curatable — including in the `people` and `feedback` buckets, where
    removal is an obligation rather than a convenience.
    """
    if not stored.source or not stored.date:
        return True
    if incoming.source == stored.source:
        return True
    return incoming_wins(
        incoming.source or "", incoming.date or "", stored.source, stored.date
    )


def plan_units(
    existing_text: str | None, nom: dict, *, already_promoted: set[str]
) -> UnitsPlan:
    """Decide what a `units` nomination does to ``existing_text``. Writes nothing.

    The supersession path (ADR 0007 Decision 2, D1): stored units accumulate,
    an incoming unit may name hashes it ``supersedes``, and **the renderer
    omits a superseded unit's text entirely** — it is not demoted, not
    commented out, not moved below a fold. For the `people` and `feedback`
    buckets that is a hard requirement rather than a preference: those notes
    are dated, attributed observations about identifiable individuals, and
    supersession is the only erasure path `memory/CONVENTIONS.md` leaves open.
    The unit survives in the ledger and in the store, so Decision 4's "nothing
    is lost" still holds — the view is curated, the record is not.

    Order is insertion order: kept units stay exactly where they were and new
    units append. See `render_units` for why precedence order was rejected.

    ``already_promoted`` is the dedup set — `parse_ledger`'s keys plus this
    run's would-writes. A unit already in it is not added again, and that
    deliberately includes a unit some earlier pass superseded: its hash stays
    in the ledger because it *was* promoted, and silently re-adding text a
    human retracted is worse than refusing it.
    """
    target = nom["target"]
    raw_units: list[dict] = nom[UNITS_FIELD]
    incoming = [
        Unit(
            hash12=content_hash12(raw[UNIT_TEXT_FIELD]),
            text=raw[UNIT_TEXT_FIELD],
            source=raw["source"],
            date=raw["date"],
        )
        for raw in raw_units
    ]

    # Every supersession this nomination asks for, mapped to the unit asking.
    # Collected from ALL incoming units, including ones that go on to dedup: a
    # retraction is an instruction about the note's state, and refusing to
    # honour it because the superseding text was seen before would leave
    # retracted text on disk. Replaying a manifest stays idempotent — the
    # second pass finds the unit already gone and removes nothing.
    requested: dict[str, Unit] = {}
    for unit, raw in zip(incoming, raw_units):
        for h in raw.get(UNIT_SUPERSEDES_FIELD) or ():
            requested.setdefault(str(h), unit)

    if existing_text is None:
        stored: list[Unit] = []
    else:
        _, rest = _split_raw_frontmatter(existing_text)
        kind, reason = _BLOCK.classify(rest)
        if kind == "malformed":
            # The same refusal `_compose_note` gives: the block's extent is
            # unknowable, so reading units out of it would have to guess.
            return UnitsPlan(None, f"malformed:{reason}")
        stored = parse_block_units(_BLOCK.inner(rest)) if kind == "ok" else []

    by_hash = {unit.hash12: unit for unit in stored}
    removed: list[Unit] = []
    warnings: list[str] = []
    for h, asker in requested.items():
        victim = by_hash.get(h)
        if victim is None:
            warnings.append(
                f"⚠  {target}: supersedes {h} — no unit with that hash in "
                f"the managed block, so NOTHING WAS REMOVED. Check the hash "
                f"against the note's unit anchors."
            )
            continue
        if not _supersession_allowed(asker, victim):
            warnings.append(
                f"⚠  {target}: refused to supersede {h} — incoming "
                f"'{asker.source}' ({asker.date}) does not outrank stored "
                f"'{victim.source}' ({victim.date}), so its text was KEPT. "
                f"Both units render; precedence is readable from their Source "
                f"lines."
            )
            continue
        removed.append(victim)

    dropped = {unit.hash12 for unit in removed}
    kept = [unit for unit in stored if unit.hash12 not in dropped]
    present = {unit.hash12 for unit in kept}
    added: list[Unit] = []
    for unit in incoming:
        if unit.hash12 in dropped:
            warnings.append(
                f"⚠  {target}: unit {unit.hash12} supersedes its own text "
                f"— not added, and the stored copy was removed."
            )
            continue
        if unit.hash12 in present:
            continue  # already in the block, at its existing position (D4)
        if unit.hash12 in already_promoted:
            continue  # dedup — see the docstring on retracted text
        added.append(unit)
        present.add(unit.hash12)

    if not added and not removed:
        # Nothing to add and nothing to retract. Reported as a dedup rather
        # than written: re-anchoring a legacy block on its own is a diff with
        # no learning in it, and the lazy import is meant to ride along with a
        # promotion that had something to say.
        return UnitsPlan(None, "dedup", warnings=tuple(warnings))

    # A legacy unit gains an anchor on this write. If its hash has no ledger
    # line — the parsed text differs from the body that was hashed, e.g. a
    # trailing blank line inside the old block — record one, so that D8's
    # anchor-to-ledger join holds for every anchor the file now carries.
    imported = [u for u in kept if u.legacy and u.hash12 not in already_promoted]

    new_text, disposition = _splice_block(
        existing_text, nom, render_units_block(kept + added)
    )
    return UnitsPlan(
        new_text,
        disposition,
        added=tuple(added),
        removed=tuple(removed),
        recorded=tuple(imported + added),
        warnings=tuple(warnings),
    )


def _prune_target_lines(lines: list[str], target: str) -> list[str]:
    """Drop ledger entries whose ``<target>`` field equals ``target``.

    Used when a note is overwritten: its old body hashed to a different value, so
    the superseded ledger line would otherwise linger as a second entry for one
    note. That is not cosmetic — ``compute_readiness.count_promotions`` reports
    how many notes a repo has, and two lines for one note reads as two notes.

    Only an overwrite prunes, because only an overwrite has provenance to compare
    against. A note whose ``[Source: ...]`` line is missing or unparseable takes
    the ``verb = "write"`` path instead, appends rather than replaces, and so
    accumulates a second line every time its body changes. Deduping the ledger
    therefore does not survive a harvest unless provenance coverage is fixed too.

    **This runs on the `body` path only, and it is still here on purpose**
    (#180 stage 1, ADR 0007 Decision 2 D5). Deleting it interacts with exactly
    the question of how supersession is recorded, and that decision is
    deliberately separable: the `units` path never prunes, because one ledger
    line per unit is the correct shape there and pruning the target would
    delete the per-unit history supersession exists to keep. So the two shapes
    have two ledger disciplines — replace-and-prune for `body`, append-only for
    `units` — and the pruner stays until the body path is retired.
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


def _append_ledger_event(ledger_path: Path, line: str) -> None:
    """Append a ledger EVENT line verbatim, never updating an existing one.

    Separate from `_record_ledger` and it has to be. That function is
    update-last-else-append **by hash**, which is right for a promotion — a
    re-nomination of the same body is the same fact, recorded once. A
    `superseded:` event carries the hash of the unit being retracted, which
    already has a `promoted:` line under that hash, so going through
    `_record_ledger` would *overwrite the promotion record with the
    retraction* and lose the fact that the unit was ever promoted. Two facts,
    two lines.

    Exact duplicates are skipped so a replayed manifest cannot stack identical
    events. `parse_ledger` reads both lines — same hash, same target — so the
    hash stays in the dedup set and the later event supplies the date; see
    ``LEDGER_VERB_SUPERSEDED`` for why that is the intended outcome.
    """
    lines = ledger_path.read_text(encoding="utf-8").splitlines()
    if line in lines:
        return
    lines.append(line)
    ledger_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def stamp_command(staging_dir: Path, receipt_path: Path | None = None) -> str:
    """The paste-ready `mark_harvested.py` invocation for this run's staging dir.

    The read manifest and the receipt share one staging dir, so both paths are
    derivable here without the operator transcribing either.

    This exists because the chain otherwise breaks at exactly the step that cannot
    fail loudly. `begin_harvest.py` prints a paste-ready `next:` line, but until
    now `promote_learnings.py` printed only `receipt <path>` and left the stamp
    command to be hand-assembled — and `mark_harvested.py` treats a missing or
    wrong `--read` as a *refusal that still returns 0* and drops a pending marker.
    A typo there is a silently unstamped harvest, not an error: the records stay
    protected, the next session start nudges again, and nothing says why.
    """
    cmd = (
        "python scripts/mark_harvested.py "
        f'--read "{staging_dir / READ_NAME}"'
    )
    if receipt_path is not None:
        cmd += f' --receipt "{receipt_path}"'
    return cmd


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

        # An unrouted declaration is validated against its own shape and skips
        # every check below — all of which reason about a target it does not
        # have. Still a hard rc 1 when malformed: "I could not route this" is a
        # claim with a required payload (the reason), and a declaration missing
        # it records that something was unroutable without recording what.
        if is_unrouted(nom):
            problem = validate_unrouted(nom, label)
            if problem is not None:
                return 1, [problem]
            continue

        # Dual-shape admission (#180 stage 1). `REQUIRED_FIELDS` holds what
        # both shapes need; the payload is `body` XOR `units`.
        missing = [f for f in REQUIRED_FIELDS if not nom.get(f)]
        has_body = bool(nom.get(BODY_FIELD))
        has_units = is_units_shaped(nom)
        if not has_body and not has_units:
            missing.append(f"{BODY_FIELD} or {UNITS_FIELD}")
        if missing:
            return 1, [
                f"error: {label}: missing required field(s): {', '.join(missing)}"
            ]
        if has_body and has_units:
            return 1, [
                f"error: {label}: nomination carries both '{BODY_FIELD}' and "
                f"'{UNITS_FIELD}' — the two are different payload shapes with "
                f"different semantics ('{BODY_FIELD}' replaces the managed "
                f"block, '{UNITS_FIELD}' supersedes within it), so a "
                f"nomination carrying both is ambiguous. Silently preferring "
                f"one reading would make the note untrue in whichever "
                f"direction the harvest did not mean. Drop one."
            ]
        if has_units:
            problem = validate_units(nom, label)
            if problem is not None:
                return 1, [problem]

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
    promoted = skipped = unrouted = 0
    # Targets actually written or overwritten, in manifest order — the receipt's
    # audit trail of what this pass put on disk (skips are counted, not listed).
    promoted_targets: list[str] = []
    # In --dry-run nothing is appended, so parse_ledger can't see earlier
    # would-writes; track them here so the preview dedups within the manifest.
    would_write: set[str] = set()
    # Distinct directories that had a note written/updated — reindexed once each.
    touched_dirs: set[Path] = set()

    for nom in records:
        # The unrouted path: tally it and move on. Deliberately *before* the
        # dedup lookup — the dedup set is keyed by body hash against the ledger,
        # and an unrouted learning never reaches the ledger, so consulting it
        # here could only ever produce a false skip against some unrelated note
        # that happened to share a body.
        if is_unrouted(nom):
            unrouted += 1
            reason = str(nom[UNROUTED_REASON_FIELD])
            if dry_run:
                summary.append(f"would record unrouted  {nom['name']} — {reason}")
                continue
            try:
                record = _unrouted_record.append_unrouted(
                    _unrouted_record.record_path(repo_dir),
                    reason=reason,
                    name=str(nom["name"]),
                    date=str(nom["date"]),
                )
                summary.append(
                    f"unrouted  {nom['name']} — {reason} "
                    f"(no note written; tally now {record['count']})"
                )
            except OSError as e:
                # Same best-effort discipline as the receipt and the reindex
                # below. Nothing was half-written — an unrouted nomination
                # produces no note and no ledger line — so there is nothing to
                # roll back, and failing the run would discard the promotions
                # that did land for the sake of a counter.
                summary.append(
                    f"⚠  unrouted {nom['name']} not tallied: {e} — the learning "
                    f"was still not routed; only the durable count is missing, "
                    f"so check_memory_triggers.py will under-report trigger 3."
                )
            continue

        # The `units` path (#180 stage 1). Kept as its own branch rather than
        # folded into the body path below: the two shapes share validation,
        # containment and the splice site, and share nothing else. `body`
        # REPLACES the managed block and is gated by the note-level
        # contradiction check; `units` accumulates, curates by supersession,
        # hashes and dedups per unit, and records one ledger line per unit
        # plus a `superseded:` event per retraction. A single function
        # branching on the shape would read as one rule with exceptions.
        if is_units_shaped(nom):
            note_path = memory_dir / nom["target"]
            existing = (
                note_path.read_text(encoding="utf-8")
                if note_path.is_file()
                else None
            )
            ledger = parse_ledger(ledger_path)
            plan = plan_units(
                existing, nom, already_promoted=set(ledger) | would_write
            )
            # Warnings first and unconditionally: a refused or unmatched
            # supersession means text the harvest meant to retract is still on
            # disk, and that must be visible whatever happens to the write.
            summary.extend(plan.warnings)

            if plan.disposition.startswith("malformed:"):
                skipped += 1
                reason = plan.disposition.partition(":")[2]
                summary.append(
                    f"skip (malformed markers) {nom['target']} — {reason}"
                )
                continue
            if plan.new_text is None:
                skipped += 1
                summary.append(
                    f"skip (dedup)   {nom['target']} — "
                    f"{len(nom[UNITS_FIELD])} unit(s) already promoted, "
                    f"nothing to add or supersede"
                )
                continue

            verb = "update" if plan.disposition == "spliced" else "write"
            detail = (
                f"+{len(plan.added)} unit(s), -{len(plan.removed)} superseded"
            )
            if dry_run:
                would_write.update(u.hash12 for u in plan.recorded)
                touched_dirs.add(note_path.parent)
                summary.append(f"would {verb}  {nom['target']} — {detail}")
                promoted += 1
                promoted_targets.append(nom["target"])
                continue

            note_path.parent.mkdir(parents=True, exist_ok=True)
            note_path.write_text(plan.new_text, encoding="utf-8")
            touched_dirs.add(note_path.parent)
            for unit in plan.recorded:
                _record_ledger(
                    ledger_path,
                    nom["target"],
                    unit.hash12,
                    f"- {unit.date} | {nom['target']} | {unit.hash12} | "
                    f"{LEDGER_VERB_PROMOTED} {nom['name']}",
                    # Never prune on this path: one line per unit is the
                    # correct shape, and pruning the target would delete the
                    # per-unit history supersession exists to preserve.
                    overwrite=False,
                )
            for unit in plan.removed:
                # The supersession EVENT, dated by the nomination that caused
                # it rather than by the unit it retires.
                _append_ledger_event(
                    ledger_path,
                    f"- {nom['date']} | {nom['target']} | {unit.hash12} | "
                    f"{LEDGER_VERB_SUPERSEDED} {nom['name']}",
                )
            promoted += 1
            promoted_targets.append(nom["target"])
            summary.append(f"{verb:<9} {nom['target']} — {detail}")
            continue

        source = nom["source"]
        h = content_hash12(nom[BODY_FIELD])
        ledger = parse_ledger(ledger_path)
        if h in ledger or h in would_write:
            skipped += 1
            summary.append(f"skip (dedup)   {nom['target']} — {h} already promoted")
            continue

        note_path = memory_dir / nom["target"]
        existing = note_path.read_text(encoding="utf-8") if note_path.is_file() else None

        # Compute what writing would produce before deciding anything else
        # about this nomination. `_compose_note` never touches disk — it only
        # reports what IT would write — so this is safe to run under
        # ``--dry-run`` too, which means a preview can never promise a write a
        # real run would go on to refuse.
        new_text, disposition = _compose_note(existing, nom)
        if new_text is None:
            # `_compose_note`'s one and only refusal path (mirrors
            # `compute_readiness.compose` / `wiki_index.compose`): the managed
            # block's markers are malformed, so the block's extent is
            # unknowable and writing would have to guess — splicing from the
            # wrong marker or duplicating on append, the destructive failure
            # class #102 / #121 exist to prevent. Skip this nomination and
            # report it; one bad file must not discard the promotions that
            # did land, the same posture as the dedup and contradiction skips.
            skipped += 1
            reason = disposition.partition(":")[2]
            summary.append(f"skip (malformed markers) {nom['target']} — {reason}")
            continue

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

        ledger_line = (
            f"- {nom['date']} | {nom['target']} | {h} | "
            f"{LEDGER_VERB_PROMOTED} {nom['name']}"
        )

        if dry_run:
            would_write.add(h)
            touched_dirs.add(note_path.parent)
            summary.append(f"would {verb}  {nom['target']} — {h} ({source})")
            promoted += 1
            promoted_targets.append(nom["target"])
            continue

        note_path.parent.mkdir(parents=True, exist_ok=True)
        note_path.write_text(new_text, encoding="utf-8")
        touched_dirs.add(note_path.parent)
        _record_ledger(
            ledger_path, nom["target"], h, ledger_line, overwrite=(verb == "overwrite")
        )
        promoted += 1
        promoted_targets.append(nom["target"])
        summary.append(f"{verb:<9} {nom['target']} — {h} ({source})")

    prefix = "[dry-run] " if dry_run else ""
    tail = f", unrouted {unrouted}" if unrouted else ""
    summary.append(f"{prefix}promoted {promoted}, skipped {skipped}{tail}")

    # Regenerate the MEMORY.md index for each touched directory so it never drifts
    # from the notes on disk. A single reindex failure must not fail the promote.
    #
    # `regenerate` returns (rc, summary_lines) and its rc is DELIBERATELY discarded
    # here. Since #102 it can return 2 — malformed index markers, meaning the owned
    # block's extent is unknowable and the file was left byte-identical. That is a
    # refusal to write, not a failed promote: the notes and the ledger are already
    # on disk, so failing the promote would report a write that did happen as a
    # write that did not. Because `regenerate` never raises on that condition, it
    # arrives as a `⚠ malformed index markers:` line in `idx_summary` and is
    # surfaced to the operator through the summary rather than swallowed by the
    # `except` below — which stays reserved for genuine, unexpected failures.
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
            # No `next:` stamp line here, deliberately. A dry run promoted
            # nothing, so nothing was reviewed, and stamping would assert a read
            # that did not happen. Printing the command would invite exactly the
            # unstamped-harvest bug in reverse: a watermark over unread records.
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
                summary.append(f"next: {stamp_command(receipt_dir, receipt_path)}")
            except OSError as e:
                summary.append(
                    f"⚠  receipt not written to {receipt_dir / RECEIPT_NAME}: {e} "
                    f"— the promote succeeded; only the audit record is missing. "
                    f"mark_harvested.py warns about that and stamps anyway, so fix "
                    f"the path if you want the record, not to unblock the stamp."
                )
                # --receipt is advisory, so the stamp is still the right next
                # step; omit it rather than point at a file that does not exist.
                summary.append(f"next: {stamp_command(receipt_dir)}")

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
