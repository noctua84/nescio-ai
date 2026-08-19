#!/usr/bin/env python3
"""Favicon set for nescio, generated from the same owl geometry as make_brand.py.

Uses the badge form (white owl on an accent tile) rather than the bare mark:
a browser tab bar may be light or dark, and a dark-blue silhouette on
transparency disappears on dark chrome. A filled tile reads on both.

**This is the generator for the committed ``brand/favicons/`` set.** Running it
regenerates every file in that directory — ``favicon.svg``, the multi-resolution
``favicon.ico``, ``favicon-16/32/48/192/512.png`` and the 180px
``apple-touch-icon.png``. The committed binaries are those outputs; the geometry
below (owl path, tile radius, padding, render sizes) is what makes them
reproducible, so treat it as fixed.

**LOCAL-ONLY — deliberately not run in CI.** It requires a local Chromium binary
and Pillow, and **neither is a dependency of this repo** — the repo is
stdlib-only and stays that way. Install Pillow into your own environment and
point ``$CHROME`` at your Chromium/Chrome executable if it is not on the default
path below. Every other brand generator (``palette.py``, ``make_brand.py``,
``make_diagrams.py``) is pure stdlib string work and does run in CI; only this
script and ``render_diagrams.py`` rasterise, and only they are human-run.

Colour comes from ``palette.py`` — the tile is the brand blue, the owl is paper
white. No hex is declared here.

Writes the favicon set into ``<out>/favicons/``. Directory, highest precedence
first:
  1. ``--out DIR``
  2. ``$BRAND_OUT``
  3. ``<this file's directory>/dist`` — i.e. ``brand/dist/``, resolved relative
     to this file, not the current working directory.

The default is the gitignored ``brand/dist/``, never ``brand/favicons/``: render
there, eyeball the result, then copy it over ``brand/favicons/`` deliberately.

    python brand/make_favicons.py            # or: python -m brand.make_favicons
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from brand import palette  # noqa: E402

CHROME = os.environ.get("CHROME", "chromium")

HEAD = ("M 140 112 C 160 168 176 176 186 186 Q 256 152 326 186 "
        "C 336 176 352 168 372 112 C 394 172 402 262 380 314 "
        "C 350 384 306 408 256 408 C 206 408 162 384 132 314 "
        "C 110 262 118 172 140 112 Z")


def badge(radius=64, pad=0.80, size=512):
    """Owl on a tile. Geometry stays on a 512 grid; `size` sets the render box."""
    tile, owl = palette.brand_blue, palette.paper
    off = (512 - 512 * pad) / 2
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" \
viewBox="0 0 512 512">
  <rect width="512" height="512" rx="{radius}" fill="{tile}"/>
  <g transform="translate({off:.1f},{off:.1f}) scale({pad})">
    <path d="{HEAD}" fill="{owl}"/>
    <circle cx="202" cy="248" r="49" fill="{tile}"/>
    <circle cx="202" cy="248" r="21" fill="{owl}"/>
    <circle cx="310" cy="248" r="49" fill="{tile}"/>
    <circle cx="310" cy="248" r="21" fill="{owl}"/>
    <path d="M 256 296 L 274 318 L 256 340 L 238 318 Z" fill="{tile}"/>
  </g>
</svg>
"""


def render(svg, size, dest):
    """Rasterise the SVG at exactly size x size."""
    dest = Path(dest)
    html = (f'<!doctype html><html><head><meta charset="utf-8">'
            f'<style>html,body{{margin:0;padding:0}}svg{{display:block}}</style>'
            f'</head><body>{svg}</body></html>')
    page = dest.parent / f"_r_{size}.html"
    page.write_text(html, encoding="utf-8")
    subprocess.run([
        CHROME, "--headless", "--disable-gpu", "--no-sandbox", "--hide-scrollbars",
        "--force-device-scale-factor=1", f"--window-size={size},{size + 60}",
        f"--screenshot={dest}", page.resolve().as_uri(),
    ], capture_output=True)
    Image.open(dest).convert("RGB").crop((0, 0, size, size)).save(dest)


def resolve_out_dir(argv=None):
    """--out, else $BRAND_OUT, else brand/dist/ next to this file."""
    ap = argparse.ArgumentParser(description="Generate the nescio favicon set.")
    ap.add_argument("--out", default=os.environ.get("BRAND_OUT"),
                    help="output directory (default: $BRAND_OUT, else brand/dist/)")
    args = ap.parse_args(argv)
    out = (Path(args.out).expanduser() if args.out
           else Path(__file__).resolve().parent / "dist")
    out.mkdir(parents=True, exist_ok=True)
    return out


if __name__ == "__main__":
    OUT = resolve_out_dir() / "favicons"
    OUT.mkdir(parents=True, exist_ok=True)

    # Tab / PWA icons: generous radius, mark fills most of the tile.
    tile = badge(radius=64, pad=0.80)
    # LF endings explicitly, so the committed favicon.svg is byte-identical
    # whichever OS regenerated it.
    with open(OUT / "favicon.svg", "w", encoding="utf-8", newline="\n") as fh:
        fh.write(tile)

    # Rasterise once at 512 and downsample. Rendering a 16x16 window in
    # headless Chromium races the paint and yields half-drawn frames; a
    # Lanczos downscale from 512 is both reliable and sharper at small sizes.
    render(badge(radius=64, pad=0.80, size=512), 512, OUT / "favicon-512.png")
    master = Image.open(OUT / "favicon-512.png")
    for size in (16, 32, 48, 192):
        master.resize((size, size), Image.LANCZOS).save(OUT / f"favicon-{size}.png")

    # Apple touch icon: iOS applies its own mask, so square corners and
    # a smaller mark so nothing important sits near the clipped edge.
    render(badge(radius=0, pad=0.70, size=512), 512, OUT / "_apple512.png")
    Image.open(OUT / "_apple512.png").resize((180, 180), Image.LANCZOS) \
         .save(OUT / "apple-touch-icon.png")
    (OUT / "_apple512.png").unlink()

    # Multi-resolution .ico for legacy browsers.
    ico = Image.open(OUT / "favicon-48.png")
    ico.save(OUT / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])

    print(f"favicons written -> {OUT}")
    for f in sorted(OUT.iterdir()):
        if not f.name.startswith("_"):
            print(f"  {f.stat().st_size:7} {f.name}")