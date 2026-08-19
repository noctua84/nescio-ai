"""MkDocs hook: ship `brand/` binaries into the build without duplicating them.

MkDocs only copies files that live under `docs_dir`. The obvious way to serve
the self-hosted faces and the favicon set would be to copy ~150 KB of binaries
into `docs_site/docs/assets/` — but then the site would carry a *second* copy of
files whose source of truth is `brand/`, and the two would drift the moment
`make_favicons.py` or `subset_fonts.py` is re-run. `brand/` is the source of
truth (design-system.md §8: "the brand is code, not files").

So the binaries stay in `brand/` and this hook copies them straight into the
build output at the paths the CSS and the `<head>` reference:

    brand/fonts/*.woff2      ->  <site_dir>/assets/fonts/
                                 (matches url("../fonts/…") in
                                  docs_site/docs/assets/css/nescio.css)

    brand/favicons/*         ->  <site_dir>/
    brand/site.webmanifest   ->  <site_dir>/site.webmanifest
                                 (matches the absolute /favicon.* + /site.webmanifest
                                  in docs_site/overrides/main.html, which is the
                                  <head> snippet from brand/favicons/README.md
                                  verbatim)

Runs on every build and on `mkdocs serve`, locally and in CI, with no extra
dependency — MkDocs `hooks:` are plain Python modules and this one is stdlib
only.

Registered as `hooks: [hooks/assets.py]` in docs_site/mkdocs.yml. Missing
sources raise, which fails the build: a silently font-less or favicon-less
deploy is worse than a red pipeline.
"""

from __future__ import annotations

import shutil
from pathlib import Path

# docs_site/hooks/assets.py -> docs_site/hooks -> docs_site -> repo root
_REPO_ROOT = Path(__file__).resolve().parents[2]

_FONTS_SRC = _REPO_ROOT / "brand" / "fonts"
_FAVICONS_SRC = _REPO_ROOT / "brand" / "favicons"
_MANIFEST_SRC = _REPO_ROOT / "brand" / "site.webmanifest"

#: Where the woff2 files land in the build. Keep in sync with the @font-face
#: `src` URLs in docs_site/docs/assets/css/nescio.css.
FONT_DEST = "assets/fonts"

#: The favicon <head> snippet uses absolute paths (/favicon.ico, …), so the
#: icons and the manifest go to the site root. The site is served from the root
#: of docs.nescio-ai.org, so absolute is correct here.
FAVICON_DEST = ""

#: brand/favicons/ also holds its own README; that is documentation, not an
#: asset, and must not be published.
_NOT_ASSETS = {"README.md"}


def _copy(src: Path, dest_dir: Path) -> None:
    dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest_dir / src.name)


def on_post_build(config, **kwargs) -> None:
    """Copy the brand binaries into `site_dir` after MkDocs has written it."""
    site_dir = Path(config["site_dir"])

    fonts = sorted(_FONTS_SRC.glob("*.woff2"))
    if not fonts:
        raise FileNotFoundError(
            f"no *.woff2 under {_FONTS_SRC} — the site would silently fall back "
            f"to a system face. Run brand/subset_fonts.py."
        )
    for font in fonts:
        _copy(font, site_dir / FONT_DEST)

    icons = sorted(
        p for p in _FAVICONS_SRC.iterdir()
        if p.is_file() and p.name not in _NOT_ASSETS
    )
    if not icons:
        raise FileNotFoundError(f"no favicon assets under {_FAVICONS_SRC}")
    for icon in icons:
        _copy(icon, site_dir / FAVICON_DEST if FAVICON_DEST else site_dir)

    if not _MANIFEST_SRC.is_file():
        raise FileNotFoundError(f"missing {_MANIFEST_SRC}")
    _copy(_MANIFEST_SRC, site_dir)
