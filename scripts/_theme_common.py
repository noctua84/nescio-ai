# scripts/_theme_common.py
"""The philosopher theme's *classifier*, shared by ``apply_theme.py`` and
``scripts/sync_from_upstream.py``.

Detecting which theme an ``agents/`` tree is on, and whether that tree is
internally consistent, is a fact two consumers need: the theme script itself
(to decide whether it is repairing or switching) and the overlay sync (to
decide whether it must materialise a themed copy of upstream before
comparing). This is ``_crew_common.py``'s own argument applied one level
down — a fact needed by two consumers must not live inside the deletable
script that only one of them owns. So the four functions below —
``theme_representatives``, ``detect_theme``, ``_frontmatter_block`` (née
``_frontmatter_name`` — see ``desynced_agents`` for why it split) and
``desynced_agents`` — moved out of ``apply_theme.py`` into this module, and
``apply_theme.py`` re-exports them so its own call sites, and the tests that
reach them through it, do not change.

The *renderer* — ``_mappings``, ``_transform`` and ``apply_theme`` itself —
deliberately did **not** move here, and is not a two-consumer fact in the same
sense: only ``apply_theme.py``'s own CLI calls it directly. ``sync_from_upstream.py``
needs it too, but only inside its themed branch, and it gets it by importing
``apply_theme.apply_theme`` — the module's **public** entry point — lazily, at
the point of use. That is a legitimate API use, the same way any script may
import another script's public function. It is *not* the same act as an
earlier design that reached into ``apply_theme``'s privates (``_mappings``,
``_transform``) to assemble a lens of its own; reaching into another module's
underscored names from outside is what makes an import look like a dependency
inversion. Calling its public function does not. So the renderer stays behind,
and this module stays a classifier, not a second renderer.

**Rejected: hosting this in ``_crew_common.py``.** That module's own docstring
says it is "Stdlib-only, no I/O: pure data, one small value type describing
it, and derivations over it" — and ``detect_theme`` / ``desynced_agents`` both
read files off disk to answer their question. Putting I/O-performing functions
in a module that advertises itself as I/O-free would falsify that contract for
every existing consumer of ``_crew_common``. This module makes the opposite
promise instead: it explicitly permits I/O, because classifying a tree's theme
has no meaning without reading the tree.

**Rejected: a graceful-degradation import with an identity fallback.** A
design that imports this module and, on failure, falls back to treating the
tree as unthemed would make every classification failure silent. On a themed
sync instance that fallback's failure mode is not a smaller feature working
less well — it is the exact destructive 11-added/11-deleted plan this module
exists to prevent, because an unthemed classification of a themed tree is
precisely the bug. A fallback whose failure mode is destruction is not
degradation, so there is no fallback here: an import failure downstream must
refuse loudly, not degrade quietly.

**R9 — the mapping is many-to-one, and that makes some upstream edits
invisible to a themed instance, by choice.** ``planner``, ``Planner`` and
``PLANNER`` all rename to ``plato``, ``Plato`` and ``PLATO`` — and so, on the
rendering side, does a literal upstream ``plato``. An upstream edit that
changes exactly the word ``planner`` to the word ``plato`` therefore renders
identically before and after, and a themed instance's sync sees no change.
Practical impact is nil (the instance's own rendering genuinely did not
change), but it is worth stating here, at the source of the mapping, as a
chosen property of a many-to-one rename rather than a bug a future reader
might otherwise "fix".

This module imports nothing from ``_crew_common`` — it needs no roster facts,
only the two theme names and one representative filename per theme — and
nothing else. Keep it dependency-free.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# Works whether this file is run as a script, imported by the tests (which put
# scripts/ on the path themselves), or collected under PYTHONPATH=scripts in CI.
sys.path.insert(0, str(Path(__file__).resolve().parent))

# The YAML frontmatter block at the top of every agent charter.
#
# The closing fence may be followed by a newline *or by end-of-text*: a
# charter whose last line is the closing `---` with no trailing newline is a
# complete, loadable charter, and demanding the `\n` made it invisible to the
# oracle. `\s*` before the terminator is what keeps CRLF working — the `\r` of
# a CRLF fence line is whitespace, so `---\r\n` matches on both fences.
_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*(?:\n|\Z)", re.DOTALL)

# An *opening* fence on its own: `---` as the entire first line. Matching this
# without matching `_FRONTMATTER_RE` is the shape of an unterminated block.
_OPENING_FENCE_RE = re.compile(r"\A---\s*(?:\n|\Z)")

# A UTF-8 byte-order mark, as the str it decodes to. Editors on Windows add
# one; Claude Code loads such a charter fine, so the oracle must see past it.
_BOM = "﻿"


class _UnterminatedFence:
    """Marker: the charter opens a ``---`` fence and never closes it.

    A distinct object rather than a third meaning for ``None``, because
    ``None`` already carries one meaning per function here (``_frontmatter_block``:
    no fence at all; ``_declared_name`` / a ``desynced_agents`` tuple: block
    present, no ``name:`` key), and this module's history — see
    ``desynced_agents`` — is the story of what happens when two different
    faults share one ``None``. A single instance, ``UNTERMINATED_FENCE``, is
    threaded from ``_frontmatter_block`` through the ``desynced_agents`` tuple
    to ``desync_reason``, which is the one place operator wording is chosen.
    """
    __slots__ = ()

    def __repr__(self) -> str:
        return "UNTERMINATED_FENCE"


UNTERMINATED_FENCE = _UnterminatedFence()


# The file whose presence is taken as evidence that the tree is on a theme.
#
# One file per theme, not the whole roster: this is a *classifier*, and
# ``desynced_agents`` is the consistency oracle. Kept as data rather than two
# ``if`` branches so the check can be order-independent — see ``detect_theme``.
THEME_REPRESENTATIVES = {
    "functional": "planner.md",
    "philosophers": "plato.md",
}


def theme_representatives(agents_dir: Path) -> dict[str, str]:
    """{theme: representative filename} for every theme with evidence on disk.

    Normally one entry. Zero means the crew is not here at all; **two** means the
    tree carries representatives of both themes at once, which is not a theme to
    detect but a broken tree to report — see ``detect_theme``.
    """
    return {theme: name for theme, name in THEME_REPRESENTATIVES.items()
            if (agents_dir / name).exists()}


def detect_theme(agents_dir: Path) -> str | None:
    """Which theme is currently on disk (by a representative agent file)?

    A *representative* file, deliberately: this answers "which direction did the
    last run go", not "is the tree consistent". A tree half-converted by an
    older build of this script still answers "philosophers" here — see
    ``desynced_agents``, which is what the no-op path must consult before
    believing this.

    Returns None when the evidence does not single one theme out — both when
    *neither* representative exists and when *both* do. The second case used to
    answer "philosophers", not because the tree was philosophical but because
    that branch was written first: a classification decided by source order
    rather than by evidence. A tree holding both ``planner.md`` and ``plato.md``
    has no answer to give, and saying so is what lets ``apply_theme`` refuse it
    instead of guessing. Callers that need to tell the two None cases apart
    consult ``theme_representatives``.

    Note this is *not* the partially-renamed state the repair path converges.
    That tree has exactly one representative — the earlier run renamed the file,
    it did not duplicate it — so it still classifies, and ``desynced_agents``
    picks up the stragglers from there.
    """
    found = theme_representatives(agents_dir)
    if len(found) == 1:
        return next(iter(found))
    return None


def _frontmatter_block(text: str) -> str | None | _UnterminatedFence:
    """The raw text between a charter's opening and closing ``---`` fences.

    Three answers, and the line between them is *what the file claims*:

    - a ``str`` — both fences present; this is the block, ``name:`` unparsed.
    - ``None`` — **no opening fence at all.** The file is documentation
      (``agents/README.md``, prose, never claiming to be a charter). That is a
      fact about the file's shape, established before any ``name:`` parsing
      is attempted, and it is the fact ``desynced_agents`` needs in order to
      leave such a file alone. See ``desynced_agents`` for why collapsing
      this case into "broken charter" was once harmless and stopped being.
    - ``UNTERMINATED_FENCE`` — the first line **is** a ``---`` fence and no
      closing fence follows. This is not documentation: opening a fence is a
      claim to be a charter, and an unfulfilled claim is exactly what this
      oracle exists to report. The obvious simplification — "any regex miss
      is None" — quietly reclassified a hand-mangled charter as prose, so a
      broken charter that does not load was reported to nobody, which is the
      original #137 shape all over again.

    A leading UTF-8 BOM is stripped before matching. A BOM-prefixed charter
    loads, and a BOM-prefixed charter declaring the *wrong* ``name:`` does
    not, so treating the BOM as "not a fence" hid a real desync behind a
    byte the operator cannot see.

    Deliberately returns the raw block text, not a bool, so a caller who wants
    the declared name still has to go through ``_declared_name`` and cannot
    shortcut past the "is there a block at all" question by accident.
    """
    text = text.removeprefix(_BOM)
    match = _FRONTMATTER_RE.match(text)
    if match:
        return match.group(1)
    if _OPENING_FENCE_RE.match(text):
        return UNTERMINATED_FENCE
    return None


def _declared_name(block: str) -> str | None:
    """The ``name:`` value inside an *already-confirmed* frontmatter block.

    Call this only after ``_frontmatter_block`` has returned non-None — it has
    no way to say "there was no block here", only "this block has no ``name:``
    key" (also None, but a different fault). A file whose frontmatter fences
    are present is asserting "I am a charter"; one that asserts that without a
    ``name:`` genuinely does not load, and that None must not be mistaken for
    ``_frontmatter_block``'s None, which asserts nothing about the file at
    all.
    """
    for line in block.splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip() == "name":
            return value.strip()
    return None


def desync_reason(declared: str | None | _UnterminatedFence) -> str:
    """The operator-facing fragment describing *why* a charter is desynced.

    Shared by both consumers (``apply_theme.py``'s repair/residue output and
    ``sync_from_upstream.py``'s warning in ``main()``) so the wording only
    needs fixing in one place. ``declared`` is always the second element of a
    ``desynced_agents`` tuple — by the time this is called, ``_frontmatter_block``
    has already confirmed an opening fence exists (see ``desynced_agents``),
    so None here can only mean "the block has no ``name:`` key", never "no
    frontmatter at all". Printing that None with ``{declared}`` would leak
    Python's repr of it into operator-facing text — a real word, ``None``,
    that reads as a value the charter declared rather than as the absence of
    one — and the fix-with command it accompanied could not fix it anyway.

    ``UNTERMINATED_FENCE`` is the third shape: the file opened a fence and
    never closed it. It gets its own sentence rather than borrowing the
    "declares no ``name:``" one, because that would be false — the block may
    well contain a ``name:`` line; the fault is that nothing terminates it.
    """
    if declared is UNTERMINATED_FENCE:
        return "opens a `---` frontmatter fence that is never closed"
    if declared is None:
        return "declares no `name:` at all"
    return f"declares `name: {declared}`"


def desynced_agents(agents_dir: Path) -> list[tuple[str, str | None | _UnterminatedFence]]:
    """(filename, declared name) for every *charter* whose ``name:`` != its stem.

    The second element is the declared name; ``None`` when the block has no
    ``name:`` key; ``UNTERMINATED_FENCE`` when the file opened a fence and
    never closed it. Hand it to ``desync_reason`` for wording.

    A charter whose frontmatter name disagrees with its filename does not load
    at all, so this is the tree's real consistency oracle — per file, against
    itself, with no roster constant taking part.

    Its purpose is to keep ``apply_theme`` from trusting ``detect_theme`` alone.
    An older build of this script renamed only five of the seven files, so a
    tree it touched has ``builder-simple.md`` declaring ``archimedes-simple``
    while ``plato.md`` sits next to it. ``detect_theme`` reports "philosophers"
    and the no-op path used to short-circuit on that — reporting success while
    leaving two agents silently non-loading, with re-running the *fixed* script
    the obvious remedy that also did nothing.

    **Not every ``.md`` in ``agents/`` is a charter.** ``README.md``, design
    notes, anything documentation-shaped has always been free to live
    alongside the charters, and carries no frontmatter at all. Those files are
    skipped here — ``_frontmatter_block`` returns None for them, and that None
    is treated as "not a charter", not as "a broken one". The line is drawn
    at the *opening fence*: no fence at all is documentation and is ignored;
    a fence that opens is a claim to be a charter, and a claim the file does
    not fulfil — no closing fence, no ``name:`` key, a ``name:`` that
    disagrees with the stem — is exactly what this oracle exists to report.

    **Why this used to be one collapsed check, and why that broke.** A single
    earlier helper, ``_frontmatter_name``, returned plain ``None`` for *both*
    "no frontmatter block" and "frontmatter block present, no ``name:`` key",
    and this function compared that ``None`` against the stem exactly like any
    other declared name. So a stem-less ``None != "README"`` reported
    ``("README.md", None)`` as desynced — indistinguishable, to any caller,
    from a charter that is genuinely broken.

    That was harmless for a long time, by circumstance rather than by design:
    this function's only caller ran it exclusively inside ``apply_theme.py``'s
    ``repairing`` branch (``current == target``), and only printed the result
    as advisory chatter ahead of a ``return 0`` — on a repair the operator had
    deliberately asked for. A stray doc file inflating that chatter by one
    line, on a path nobody scripted around, was noise nobody acted on.

    It stopped being harmless when two independent, individually-correct
    widenings both started treating this function's output as gating rather
    than advisory. Issue #137 moved ``apply_theme.py``'s residue check out of
    ``if repairing:`` so it now runs after *every* non-dry-run pass and exits
    2 on any non-empty result — including a plain ``README.md``, turning a
    successful theme switch into a hard failure. And the sync's own warning in
    ``sync_from_upstream.py::main()`` moved above the theme classification so
    it runs on *every* sync, printing an operator-facing "declares `name:
    None`" for a file that declares nothing, ahead of a suggested
    ``apply_theme.py`` command that could not fix it — permanent, unactionable
    noise standing between an operator and a destructive ``--apply``. Two
    correct widenings landing on top of one collapsed ``None`` is what turned
    "advisory chatter nobody read" into "a hard failure and permanent noise,
    both wrong". Keep the two cases apart at the source — ``_frontmatter_block``
    answers "is this even a charter", ``_declared_name`` answers "what does it
    claim, given that it is one" — so a third consumer cannot rediscover this
    bug by trusting a docstring's "harmless" clause after it has stopped being
    true.

    **An entry this function cannot even read is not a charter either.** A
    directory that happens to be named ``notes.md``, a file that is not UTF-8
    text (a Latin-1 scratch note), a file the process may not open — none of
    these can be a charter, because a charter is by definition UTF-8 text
    with a frontmatter block, and Claude Code would not load them as one.
    They are skipped, by the same argument that skips a frontmatter-less
    ``README.md`` above: the oracle's question is "does this charter's
    ``name:`` agree with its filename", and an entry that is not a charter has
    no answer to give.

    Why this is guarded here rather than left to raise: since the desync
    warning in ``sync_from_upstream.py::main()`` moved above the theme
    classification, this function runs on **every** sync — including the
    untheme'd path, whose entire contract (P1 in that module's docstring) is
    "literally today's behaviour". Today's ``plan_sync`` lists such a stray
    file under ``- delete`` and carries on; a ``UnicodeDecodeError`` escaping
    from a classifier that was never going to classify the file anyway turned
    that plan into a traceback, on the one path that promised not to change.
    The tempting alternative — catch it in ``main()`` and print a warning —
    would put theme-flavoured output on the untheme'd path for a file the
    plan already reports correctly, so the skip lives here, silently, where
    the "not a charter" decision is made for every other non-charter shape.
    """
    out: list[tuple[str, str | None | _UnterminatedFence]] = []
    for md in sorted(agents_dir.glob("*.md")):
        if not md.is_file():
            continue  # a directory named `x.md` is not a charter
        try:
            text = md.read_text(encoding="utf-8", newline="")
        except (OSError, UnicodeDecodeError):
            continue  # unreadable, or not UTF-8 text — not a charter either
        block = _frontmatter_block(text)
        if block is None:
            continue  # not a charter at all — e.g. agents/README.md
        if block is UNTERMINATED_FENCE:
            out.append((md.name, UNTERMINATED_FENCE))  # claimed to be one, and is broken
            continue
        declared = _declared_name(block)
        if declared != md.stem:
            out.append((md.name, declared))
    return out
