"""The promoted block: its format, parsing, and composition.

Split out of `promote_learnings.py` (#208) along the boundary that review
found during #207: this module answers "what does the managed block contain
and how is it shaped", while `promote_learnings.py` answers "which nomination
gets promoted, with what ledger and receipt". Two reasons to change, so two
files. Pure move — no behaviour here differs from before the split.

`promote_learnings.py` re-exports every name this module defines, so neither
its own internal callers nor the tests that reach into it as `pl.<name>`
(`tests/test_promote_learnings*.py`, which use `pl.PROMOTED_BEGIN`, `pl.Unit`,
`pl._compose_note`, `pl.parse_block_units`, `pl.render_block`,
`pl.render_units_block`, `pl.existing_provenance`, `pl._BLOCK`) needed to
change. `scripts/compute_readiness.py` is unaffected: it carries its own
independent copy of `_split_raw_frontmatter` rather than importing this one.

Two payload shapes land here, matching the two a nomination may carry (ADR
0007 *Decision 2*, #180 stage 1):

  * `body` — a note body. `render_block` / `_compose_note` REPLACE the managed
    block with it, byte for byte, exactly as the pre-#180 code always did.
  * `units` — a list of `Unit`s. `render_units_block` / `plan_units`
    accumulate and curate them by supersession instead of replacing.

See `promote_learnings.py`'s module docstring for the full nomination schema,
the ledger, the receipt contract, and the CLI — none of that lives here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from _learning_common import content_hash12, priority
from _marker_block import MarkerBlock, fenced_line_indices, split_lines

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


# The `units`-payload field names `plan_units` needs. Defined here rather
# than in `promote_learnings.py` because this module must not import back
# from it — that would make the two modules cyclic — while `plan_units`,
# which lives here, needs them. `promote_learnings.py`'s own
# `is_units_shaped` / `validate_units` import these back, the same
# re-export discipline used for every other name this module owns.
UNITS_FIELD = "units"
UNIT_TEXT_FIELD = "text"
UNIT_SUPERSEDES_FIELD = "supersedes"


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
