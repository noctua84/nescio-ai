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
from datetime import datetime, timezone
from pathlib import Path

import wiki_index

import _unrouted_record

from _learning_common import (
    REPO_DIR,
    VALID_SOURCES,
    content_hash12,
    parse_ledger,
)

# `READ_NAME` belongs to begin_harvest.py because that is what writes the file.
# Imported rather than repeated here so the stamp command printed at the end of a
# promote cannot drift from the filename the read manifest actually has.
from begin_harvest import READ_NAME  # noqa: E402

# The managed block's format, parsing and composition — a second, independent
# reason to change from the nomination validation / ledger / receipt / CLI
# this file keeps (#208 split). Re-exported wholesale (`noqa: F401` on the
# names this file never calls directly) so every existing caller — this
# module's own code below, and `tests/test_promote_learnings*.py`, which
# reach these as `pl.<name>` — keeps working unchanged.
from _promoted_block import (  # noqa: F401  (re-exported)
    PROMOTED_BEGIN,
    PROMOTED_END,
    Unit,
    UnitsPlan,
    UNIT_LEGACY_FLAG,
    UNIT_SUPERSEDES_FIELD,
    UNIT_TEXT_FIELD,
    UNITS_FIELD,
    _BLOCK,
    _SOURCE_RE,
    _UNIT_ANCHOR_RE,
    _compose_note,
    _refresh_frontmatter,
    _splice_block,
    _split_raw_frontmatter,
    _split_unit_chunk,
    _supersession_allowed,
    existing_provenance,
    incoming_wins,
    plan_units,
    render_block,
    render_frontmatter,
    render_note,
    render_units,
    render_units_block,
    unit_anchor,
    parse_block_units,
)

# Every nomination must carry these before anything is written — a malformed
# object fails its own line cleanly (rc 1) instead of raising KeyError mid-run
# after earlier notes already wrote.
#
# `body` is NOT in this tuple: it is one of the two mutually exclusive payload
# shapes (see `BODY_FIELD` below and `UNITS_FIELD`, imported above), and which
# one a nomination carries is a separate question from whether the fields
# common to both are present. The validator still reports a nomination with
# neither as
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
#
# `UNITS_FIELD`, `UNIT_TEXT_FIELD` and `UNIT_SUPERSEDES_FIELD` are all
# imported above from `_promoted_block.py` rather than defined here: that
# module's `plan_units` needs them and must not import back from this file,
# so the shared field-name constants live on its side of the #208 split.
BODY_FIELD = "body"

# What each learning unit must carry. `source`/`date` are per unit and
# REQUIRED (ADR 0007 Decision 2, D7): inheriting them from the nomination
# would silently backdate and re-attribute every unit in it, and precedence is
# only readable from the rendered block if each unit states its own.
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
