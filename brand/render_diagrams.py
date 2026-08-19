#!/usr/bin/env python3
"""Render the diagram SVGs to 2x PNGs, with the canvas trimmed to the SVG box.

LOCAL-ONLY — deliberately **not** run in CI. Requires a local Chromium binary
and Pillow, neither of which is a dependency of this repo. Point ``$CHROME`` at
your Chromium/Chrome executable if it is not on the default path below.

Reads ``diagram-crew.svg`` / ``diagram-loop.svg`` from the output directory
(run ``make_diagrams.py`` first) and writes the PNGs beside them. Directory,
highest precedence first:
  1. ``--out DIR``
  2. ``$BRAND_OUT``
  3. ``<this file's directory>/dist`` — i.e. ``brand/dist/``, resolved relative
     to this file, not the current working directory.
"""
import argparse
import os
import re
import subprocess
from pathlib import Path

from PIL import Image

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
        src = OUT_DIR / f"diagram-{name}.svg"
        dest = OUT_DIR / f"diagram-{name}.png"
        svg = src.read_text(encoding="utf-8")
        w, h = (int(v) for v in re.search(r'width="(\d+)" height="(\d+)"', svg).groups())

        page = (f'<!doctype html><html><head><meta charset="utf-8">'
                f'<style>html,body{{margin:0;padding:0;background:#fff}}'
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
