"""MkDocs hook: inline a tokenised diagram SVG into a page, verbatim.

USAGE — put this on its own line in any Markdown page:

    <!-- diagram: crew -->
    <!-- diagram: loop -->

The hook replaces that comment with

    <div class="nescio-diagram">…the SVG file, byte for byte…</div>

The `<div>` is what docs/assets/css/nescio.css hangs `overflow-x: auto` on, so a
wide diagram scrolls inside its own container and the page body never scrolls
sideways (design-system.md §5).

WHY A HOOK AND NOT `pymdownx.snippets`
--------------------------------------
Snippets was the obvious candidate and it does not work here. It is a *Markdown
preprocessor*: the file it pulls in is then parsed as Markdown. `svg` is not in
Python-Markdown's `BLOCK_LEVEL_ELEMENTS`, so the parser treats the artwork as an
inline HTML run and mangles it. Measured against mkdocs-material 9.7.7 with the
real brand/dist/diagram-loop.svg, snippets produced:

    <p><svg xmlns="…" width="1400" …>
    <br />
    <style> … </style></p>
    <p><defs> …

— a `<p>` wrapper around the root element, a stray `<br />` injected *inside* the
SVG, and the element tree split in two at the `<style>` block. Wrapping the
snippet in `<div markdown>` made it worse, not better.

There is no snippets option that turns this off, because the mangling happens
after snippets has done its job. `on_page_content` runs *after* Markdown
rendering, so the SVG never meets the parser at all — which is the only way to
guarantee the artwork reaches the page byte for byte.

Two smaller wins fall out of the same choice:

  * Snippets' `base_path` resolves against the **current working directory**,
    not the config file, so `mkdocs build -f docs_site/mkdocs.yml` and
    `cd docs_site && mkdocs build` would need different config. This hook
    resolves from `__file__` and does not care where it was invoked from.
  * The diagrams must never be `<img>` (spec §6): inlining is what lets the
    page's own `--diagram-*` custom properties reach the artwork so the scheme
    toggle repaints it live. A hook makes that structural rather than a
    convention someone can forget.

An HTML comment is used as the marker because Python-Markdown preserves a
block-level comment verbatim — it survives to `on_page_content` unchanged.

WHERE THE FILES COME FROM
-------------------------
`SEARCH_DIRS`, in order:

  1. docs_site/docs/assets/diagrams/  — the committed location. CI only has this
     one.
  2. brand/dist/                      — generator output. Gitignored, so it is
     absent in CI; locally it lets you inline straight from a fresh
     `python brand/make_diagrams.py` without copying anything.

Use the **tokenised** source (`diagram-crew.svg`), never the generated twins
(`diagram-crew-light.svg` / `-dark.svg`): the twins carry concrete hexes and
cannot follow the toggle. The twins exist for GitHub and link previews, which
cannot supply CSS variables.

An unresolvable name raises, which fails the build. `mkdocs build --strict`
catches broken links, not a diagram that silently rendered as nothing.
"""

from __future__ import annotations

import re
from pathlib import Path

# docs_site/hooks/inline_svg.py -> docs_site/hooks -> docs_site -> repo root
_REPO_ROOT = Path(__file__).resolve().parents[2]

SEARCH_DIRS = (
    _REPO_ROOT / "docs_site" / "docs" / "assets" / "diagrams",
    _REPO_ROOT / "brand" / "dist",
)

#: `<!-- diagram: crew -->`
_MARKER = re.compile(r"<!--\s*diagram:\s*([A-Za-z0-9._-]+)\s*-->")

WRAPPER_CLASS = "nescio-diagram"


def _resolve(name: str) -> Path:
    """Find the SVG for `name`, accepting `crew`, `diagram-crew` or a filename."""
    stems = [name]
    if not name.startswith("diagram-"):
        stems.append(f"diagram-{name}")
    candidates = [s if s.endswith(".svg") else f"{s}.svg" for s in stems]

    for directory in SEARCH_DIRS:
        for candidate in candidates:
            path = directory / candidate
            if path.is_file():
                return path

    searched = ", ".join(str(d) for d in SEARCH_DIRS)
    raise FileNotFoundError(
        f"inline_svg: no diagram matching {candidates!r} under {searched}. "
        f"Generate them with `python brand/make_diagrams.py`, or copy the "
        f"tokenised sources into docs_site/docs/assets/diagrams/."
    )


def on_page_content(html: str, page=None, config=None, files=None, **kwargs) -> str:
    """Replace every `<!-- diagram: … -->` marker with the SVG itself."""
    if "<!--" not in html:
        return html

    def _replace(match: re.Match) -> str:
        svg = _resolve(match.group(1)).read_text(encoding="utf-8").strip()
        return f'<div class="{WRAPPER_CLASS}">\n{svg}\n</div>'

    return _MARKER.sub(_replace, html)
