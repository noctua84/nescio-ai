"""Where the hand-written site's sources live, and the copy it must carry.

Shared by the `test_site_*.py` modules, which between them guard the
hand-written site content: hero, inlined diagrams, 404, footer. Read-only
constants and one pure helper -- no state.

Lives in `docs_site/`, NOT `tests/`. `tests/` is on FRAMEWORK_PATHS and syncs
into derived instances, which never receive `docs_site/` -- a test there
importing this module would break `python -m unittest` for every downstream
user. Same rule as test_gen_catalog.py.

Deliberately not named `test_*`, so `unittest discover` never collects it.
"""

from __future__ import annotations

from pathlib import Path

_DOCS_SITE = Path(__file__).resolve().parent
_REPO_ROOT = _DOCS_SITE.parent

_INDEX = _DOCS_SITE / "docs" / "index.md"
_DIAGRAMS = _DOCS_SITE / "docs" / "assets" / "diagrams"
_CSS = _DOCS_SITE / "docs" / "assets" / "css" / "nescio.css"
_JS = _DOCS_SITE / "docs" / "assets" / "js" / "diagram-lightbox.js"
_MKDOCS_YML = _DOCS_SITE / "mkdocs.yml"
_OVERRIDES = _DOCS_SITE / "overrides"

#: design-system.md §7, verbatim. Whitespace is normalised before comparing so
#: the template may wrap the line however it likes.
_404_COPY = (
    "I do not know where this page is. The owl of Minerva flies at dusk; "
    "this one appears to have flown off entirely."
)
_FOOTER_TAGLINE = "The owl of Minerva flies at dusk."


def _squash(text: str) -> str:
    return " ".join(text.split())

