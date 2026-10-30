"""Render the "## The philosopher theme" fragment appended to docs/agents.md.

The philosopher theme is an opt-in cosmetic rename
(``scripts/apply_theme.py``) over a fixed word-pair table
(``scripts/_crew_common.PAIRS``) plus two per-pair rationale constants
(``scripts/_crew_common.PAIR_RATIONALE``). This module turns that data into
one rendered fragment -- names *and* why, both sourced from
``scripts/_crew_common`` -- so the table can never drift the way README's old
hand-written copy could (it used ditto marks and had no test behind it).

Reversing a documented stance
------------------------------
``docs_site/`` used to avoid importing anything from ``scripts/`` so the docs
build needed nothing from ``scripts/`` on ``PYTHONPATH`` (see the amended
comment in ``docs_site/test_gen_catalog.py``). This module imports
``scripts._crew_common`` anyway, and that is a deliberate, approved reversal,
not an oversight:

* The reason the old stance protected against -- a ``PYTHONPATH=scripts``
  requirement -- does not apply to a **top-level** ``sys.path.insert(0,
  str(REPO_DIR))`` against the repository root. It needs no environment
  variable at all: ``scripts/__init__.py`` exists, so inserting the repo root
  is sufficient for ``from scripts import _crew_common`` to resolve.
* ``scripts/_crew_common.py`` is itself stdlib-only, pure data, with no I/O
  and no further ``scripts/`` imports of its own -- importing it buys no new
  runtime dependency.
* The dependency direction is the safe one: ``scripts/`` is on
  ``FRAMEWORK_PATHS`` and ships on every checkout docs_site/ builds from
  (including CI, which always has a full checkout). ``docs_site/`` never
  needs something ``scripts/`` lacks.

The MkDocs hook ``sys.path`` fact (verified against mkdocs 1.6.1,
``mkdocs.config.config_options.Hooks._load_hook``): the hook loader puts a
hook file's own directory on ``sys.path`` only *around* module exec and
restores it afterward. That is why both the ``catalog_core`` import style in
``gen_catalog.py`` and the ``sys.path.insert`` below must stay at module top
level -- a function-level version would work from the CLI (its directory is
already on ``sys.path`` via the usual script rules) but fail inside a build,
after the window has closed.

Hard constraint on the fragment
--------------------------------
``catalog_core.ITEM_HEADING_RE`` (``^### ```) drives the agents-page
count-guard by counting ``### `name` `` headings in the *rendered* page. The
fragment this module appends after that guard runs must never introduce a
heading of that shape, or it would corrupt the count. Table rows plus ``##``/
``####`` headings are fine; a backtick-leading ``### `` is not, and is not
used here.
"""

from __future__ import annotations

import sys

from catalog_core import CatalogError, REPO_DIR

# MUST stay a top-level import -- see the MkDocs hook sys.path fact in the
# module docstring above. A function-level sys.path.insert()/import here would
# work when gen_theme is driven from the CLI but fail when gen_catalog.py (the
# registered mkdocs hook) imports this module during a build.
sys.path.insert(0, str(REPO_DIR))
try:
    from scripts import _crew_common
except ImportError as exc:  # pragma: no cover - only on a partial checkout
    raise CatalogError(
        "docs_site/gen_theme.py could not import scripts/_crew_common.py "
        f"({exc}). The philosopher theme table needs scripts/_crew_common.py "
        "on the repo root; is this a partial checkout missing scripts/?"
    ) from exc


def render_theme_section() -> str:
    """The "## The philosopher theme" fragment appended to agents.md.

    Every name, count and invocation below is derived from
    ``scripts/_crew_common`` -- nothing here is typed as a literal that could
    drift from the roster it describes.
    """
    pairs = _crew_common.PAIRS
    rationale = _crew_common.PAIR_RATIONALE
    tiered = _crew_common.TIERED_AGENTS
    invariant = sorted(_crew_common.THEME_INVARIANT_ROSTER)

    rows = [
        f"| `{functional}` | `{philosopher}` | {rationale[functional]} |"
        for functional, philosopher in pairs
    ]
    renamed_total = len(pairs) + len(tiered)
    invariant_names = ", ".join(f"`{name}`" for name in invariant)
    tiered_names = " and ".join(f"`{name}`" for name in tiered)

    lines = [
        "## The philosopher theme",
        "",
        "The agent names used throughout this site are functional on purpose. If "
        "you'd like personality, an optional theme renames the thinker, builder "
        "and craft agents after Graeco-Roman philosophers -- the same renaming "
        "`scripts/apply_theme.py` applies to the agent files, their `name:` "
        "frontmatter, and every cross-reference in the crew.",
        "",
        "| functional | philosopher | why |",
        "| --- | --- | --- |",
        *rows,
        "",
        f"The two builder cost tiers ({tiered_names}) follow `builder`, so "
        f"{renamed_total} files are renamed in all: the {len(pairs)} pairs above "
        f"plus the two builder tiers.",
        "",
        f"The remaining agents -- {invariant_names} -- keep their functional "
        "names under both themes.",
        "",
        "Apply it with `python scripts/apply_theme.py philosophers` (and "
        "`python scripts/apply_theme.py functional` to revert). It renames the "
        "agent files, frontmatter, and all cross-references; it's idempotent "
        "and reversible. `--dry-run` prints what it would do without touching "
        "anything.",
        "",
    ]
    return "\n".join(lines).rstrip() + "\n"
