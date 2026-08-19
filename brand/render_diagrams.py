#!/usr/bin/env python3
"""Render the diagram SVGs to 2x PNGs, with the canvas trimmed to the SVG box.

**This is the generator for the 2x diagram PNGs.** Running it regenerates
``diagram-crew.png`` and ``diagram-loop.png`` from the SVGs ``make_diagrams.py``
emits — the raster twins for contexts that will not render an SVG. The scale
factor and the crop-to-SVG-box behaviour below are what keep those PNGs
reproducible, so treat them as fixed.

**LOCAL-ONLY — deliberately not run in CI.** It requires a local Chromium binary
and Pillow, and **neither is a dependency of this repo** — the repo is
stdlib-only and stays that way. Install Pillow into your own environment and
point ``$CHROME`` at your Chromium/Chrome executable if it is not on the default
path below. ``make_diagrams.py``, which produces the SVGs this reads, is pure
stdlib string work and does run in CI; only this script and ``make_favicons.py``
rasterise, and only they are human-run.

Colour comes from ``palette.py`` — the page ground behind the render is the
paper white. No hex is declared here; the diagram's own colours live in its SVG.

**Reads the generated light twin, not the tokenised source.** The source SVG
carries no ground and every colour as a ``var(--diagram-*)``, resolved only by
a ``svg:root`` block that a browser applies at its own discretion — so
rasterising it makes the output depend on Chromium's CSS-default resolution
flattened onto whatever ground the page happens to supply. The light twin has
concrete hexes and an explicit ground ``<rect>`` baked in by ``make_diagrams.py``
and cannot render ambiguously, which is what makes these PNGs deterministic.

Reads ``diagram-crew-light.svg`` / ``diagram-loop-light.svg`` from the output
directory (run ``make_diagrams.py`` first) and writes ``diagram-crew.png`` /
``diagram-loop.png`` beside them. Directory, highest precedence first:
  1. ``--out DIR``
  2. ``$BRAND_OUT``
  3. ``<this file's directory>/dist`` — i.e. ``brand/dist/``, resolved relative
     to this file, not the current working directory.

    python brand/render_diagrams.py          # or: python -m brand.render_diagrams
"""
import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from brand import palette  # noqa: E402

CHROME = os.environ.get("CHROME", "chromium")
SCALE = 2


def resolve_out_dir(argv=None):
    """--out, else $BRAND_OUT, else brand/dist/ next to this file."""
    ap = argparse.ArgumentParser(description="Rasterise the diagram SVGs to 2x PNGs.")
    ap.add_argument("--out", default=os.environ.get("BRAND_OUT"),
                    help="directory holding the SVGs (default: $BRAND_OUT, else brand/dist/)")
    args = ap.parse_args(argv)
    out = (Path(args.out).expanduser() if args.out
           else Path(__file__).resolve().parent / "dist")
    out.mkdir(parents=True, exist_ok=True)
    return out


if __name__ == "__main__":
    OUT_DIR = resolve_out_dir()

    for name in ("crew", "loop"):
        src = OUT_DIR / f"diagram-{name}-light.svg"
        dest = OUT_DIR / f"diagram-{name}.png"
        svg = src.read_text(encoding="utf-8")
        w, h = (int(v) for v in re.search(r'width="(\d+)" height="(\d+)"', svg).groups())

        page = (f'<!doctype html><html><head><meta charset="utf-8">'
                f'<style>html,body{{margin:0;padding:0;'
                f'background:{palette.paper}}}'
                f'svg{{display:block}}</style></head><body>{svg}</body></html>')
        page_path = OUT_DIR / f"_r_{name}.html"
        page_path.write_text(page, encoding="utf-8")

        # Render with headroom, then crop to the true SVG box — avoids any
        # viewport/layout rounding clipping the last row.
        subprocess.run([
            CHROME, "--headless", "--disable-gpu", "--no-sandbox", "--hide-scrollbars",
            f"--force-device-scale-factor={SCALE}",
            f"--window-size={w},{h + 120}",
            f"--screenshot={dest}",
            page_path.resolve().as_uri(),
        ], capture_output=True)

        im = Image.open(dest).convert("RGB")
        im = im.crop((0, 0, w * SCALE, h * SCALE))
        im.save(dest)
        print(f"{name}: {im.size[0]}x{im.size[1]} (svg {w}x{h})")
