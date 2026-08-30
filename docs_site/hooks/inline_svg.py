"""MkDocs hook: inline a tokenised diagram SVG into a page, verbatim.

USAGE — put this on its own line in any Markdown page:

    <!-- diagram: crew -->
    <!-- diagram: loop -->

The hook replaces that comment with

    <div class="nescio-diagram">
      <button class="nescio-diagram__trigger" …>…the SVG, byte for byte…</button>
    </div>

The `<div>` is the block docs/assets/css/nescio.css sizes: the artwork is capped
to the content column so it never overflows and the page body never scrolls
sideways (design-system.md §5).

WHY THE ARTWORK SITS INSIDE A `<button>`
----------------------------------------
Fitting the diagram to the column costs legibility — the smallest labels land
around 8px on a 1440px window. The compensation is a full-size view one click
away, which docs/assets/js/diagram-lightbox.js opens. That view has to be
reachable by keyboard, so the activator is a real `<button type="button">`: it
is focusable, it is announced as a button, and Enter *and* Space fire `click`
for free. A `<div>` with a click handler would need `tabindex`, `role` and a
hand-written keydown branch to reach the same place, and would still be one
refactor away from losing them.

The button carries an `aria-label` naming what it opens ("Open the crew diagram
full size") rather than relying on the SVG for its accessible name — the
artwork has no `<title>` and its text nodes would otherwise be flattened into a
paragraph-long button name.

`data-diagram-title` is the human name of the artwork ("The crew diagram"). The
script reuses it as the dialog's own label, so the two strings are derived here,
once, instead of being half in Python and half in JavaScript.

Nothing is HTML-escaped on the way in because `_MARKER` only admits
`[A-Za-z0-9._-]`, so no attribute-breaking character can reach the template.
Widen that character class and this needs escaping.

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
TRIGGER_CLASS = "nescio-diagram__trigger"


def _title(name: str) -> str:
    """The human name of a diagram: `diagram-crew.svg` -> `The crew diagram`.

    Accepts every spelling `_resolve` does, so the label never depends on which
    form the page's marker happened to use.
    """
    stem = name[:-4] if name.lower().endswith(".svg") else name
    if stem.startswith("diagram-"):
        stem = stem[len("diagram-"):]
    words = re.sub(r"[-_.]+", " ", stem).strip()
    return f"The {words} diagram"


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
        name = match.group(1)
        svg = _resolve(name).read_text(encoding="utf-8").strip()
        title = _title(name)
        # `aria-hidden` is NOT set on the SVG: it is the button's only content,
        # and hiding it would leave the button with no rendered subtree at all
        # in some engines. The explicit aria-label already wins the name.
        return (
            f'<div class="{WRAPPER_CLASS}">\n'
            f'<button type="button" class="{TRIGGER_CLASS}"'
            f' data-diagram-title="{title}"'
            f' aria-label="Open {title.lower()} full size">\n'
            f"{svg}\n"
            f"</button>\n"
            f"</div>"
        )

    return _MARKER.sub(_replace, html)
