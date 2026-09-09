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
``theme_representatives``, ``detect_theme``, ``_frontmatter_name`` and
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
_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)


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


def _frontmatter_name(text: str) -> str | None:
    """The ``name:`` a charter declares, or None if it declares none."""
    block = _FRONTMATTER_RE.match(text)
    if block is None:
        return None
    for line in block.group(1).splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip() == "name":
            return value.strip()
    return None


def desynced_agents(agents_dir: Path) -> list[tuple[str, str | None]]:
    """(filename, declared name) for every charter whose ``name:`` != its stem.

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
    """
    out: list[tuple[str, str | None]] = []
    for md in sorted(agents_dir.glob("*.md")):
        declared = _frontmatter_name(md.read_text(encoding="utf-8", newline=""))
        if declared != md.stem:
            out.append((md.name, declared))
    return out
