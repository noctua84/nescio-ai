#!/usr/bin/env python3
"""NescioAI brand mark: a geometric little owl (noctua), plus derived assets.

Pure string generation — stdlib only, no Pillow and no Chromium. Safe in CI.

Output directory, highest precedence first:
  1. ``--out DIR``
  2. ``$BRAND_OUT``
  3. ``<this file's directory>/dist`` — i.e. ``brand/dist/``, resolved relative
     to this file, not the current working directory.
"""
import argparse
import os
from pathlib import Path

INK = "#111418"
ACCENT = "#2f4d7a"
ACCENT_LIGHT = "#8fb0d9"
PAPER = "#ffffff"
DARK = "#0e1319"
MUTED_D = "#8d97a4"
FONT = "Carlito, 'Liberation Sans', 'Helvetica Neue', Arial, sans-serif"
MONO = "'Liberation Mono', monospace"


def owl(color=ACCENT, eye=PAPER, pupil=ACCENT, scale=1.0, dx=0, dy=0,
        pupil_shift=0):
    """The mark, drawn on a nominal 512x512 grid."""
    head = ("M 140 112 "
            "C 160 168 176 176 186 186 "
            "Q 256 152 326 186 "
            "C 336 176 352 168 372 112 "
            "C 394 172 402 262 380 314 "
            "C 350 384 306 408 256 408 "
            "C 206 408 162 384 132 314 "
            "C 110 262 118 172 140 112 Z")
    g = [f'<g transform="translate({dx},{dy}) scale({scale})">']
    g.append(f'<path d="{head}" fill="{color}"/>')
    for cx in (202, 310):
        g.append(f'<circle cx="{cx}" cy="248" r="49" fill="{eye}"/>')
        g.append(f'<circle cx="{cx + pupil_shift}" cy="248" r="21" fill="{pupil}"/>')
    # beak: a small chevron, pointing down
    g.append(f'<path d="M 256 296 L 274 318 L 256 340 L 238 318 Z" fill="{eye}"/>')
    g.append("</g>")
    return "".join(g)


def svg(w, h, body, bg=None):
    b = f'<rect width="{w}" height="{h}" fill="{bg}"/>' if bg else ""
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
            f'viewBox="0 0 {w} {h}">{b}{body}</svg>')


def text(x, y, s, size=16, fill=INK, weight="400", anchor="start",
         family=FONT, spacing=None):
    sp = f' letter-spacing="{spacing}"' if spacing else ""
    return (f'<text x="{x}" y="{y}" font-family="{family}" font-size="{size}" '
            f'fill="{fill}" font-weight="{weight}" text-anchor="{anchor}"{sp}>{s}</text>')


# --- 1. the bare mark -------------------------------------------------------
mark = svg(512, 512, owl())

# --- 2. badge (rounded square, for avatars) ---------------------------------
badge = svg(512, 512,
            f'<rect width="512" height="512" rx="112" fill="{ACCENT}"/>'
            + owl(color=PAPER, eye=ACCENT, pupil=PAPER, scale=0.78, dx=56, dy=56))

# --- 3. GitHub social preview, 1280x640 -------------------------------------
sp = [f'<rect width="1280" height="640" fill="{DARK}"/>']
sp.append(f'<circle cx="1150" cy="120" r="420" fill="#141b24"/>')
sp.append(owl(color=ACCENT_LIGHT, eye=DARK, pupil=ACCENT_LIGHT,
              scale=0.52, dx=96, dy=176))
sp.append(text(392, 300, "nescio", size=104, fill=PAPER, weight="700", family=MONO))
sp.append(text(392, 356, "an agent crew for Claude Code", size=30, fill=MUTED_D))
sp.append(f'<rect x="392" y="392" width="86" height="3" fill="{ACCENT_LIGHT}"/>')
sp.append(text(392, 452, "&#8220;I don&#8217;t know&#8221; is a first-class answer.",
               size=34, fill=ACCENT_LIGHT))
sp.append(text(392, 500, "github.com/noctua84/nescio-ai", size=24, fill=MUTED_D,
               family=MONO))
social = svg(1280, 640, "".join(sp))

# --- 4. Medium cover, 1500x750 ----------------------------------------------
mc = [f'<rect width="1500" height="750" fill="{DARK}"/>']
for i in range(9):
    x = 150 + i * 150
    mc.append(f'<circle cx="{x}" cy="690" r="3" fill="#1d2732"/>')
mc.append(owl(color=ACCENT_LIGHT, eye=DARK, pupil=ACCENT_LIGHT,
              scale=0.58, dx=602, dy=140))
mc.append(text(750, 470, "nescio", size=76, fill=PAPER, weight="700",
               family=MONO, anchor="middle"))
mc.append(text(750, 522, "an agent is allowed to say &#8220;I don&#8217;t know&#8221;",
               size=30, fill=MUTED_D, anchor="middle"))
cover = svg(1500, 750, "".join(mc))

# --- 5. legibility contact sheet --------------------------------------------
cs = [f'<rect width="900" height="300" fill="{PAPER}"/>']
x = 80
for px in (128, 64, 48, 32, 24, 16):
    s = px / 512
    cs.append(f'<g transform="translate({x},{150 - px / 2})">'
              + owl(scale=s) + "</g>")
    cs.append(text(x + px / 2, 220, f"{px}px", size=13, fill="#6b727c",
                   anchor="middle"))
    x += px + 56
cs.append(text(80, 60, "Legibility check — the mark must survive the avatar size",
               size=17, fill=INK, weight="700"))
sheet = svg(900, 300, "".join(cs))

ASSETS = [("logo-mark", mark), ("logo-badge", badge),
          ("github-social", social), ("medium-cover", cover),
          ("logo-sizes", sheet)]


def resolve_out_dir(argv=None):
    """--out, else $BRAND_OUT, else brand/dist/ next to this file."""
    ap = argparse.ArgumentParser(description="Generate the NescioAI brand SVGs.")
    ap.add_argument("--out", default=os.environ.get("BRAND_OUT"),
                    help="output directory (default: $BRAND_OUT, else brand/dist/)")
    args = ap.parse_args(argv)
    out = (Path(args.out).expanduser() if args.out
           else Path(__file__).resolve().parent / "dist")
    out.mkdir(parents=True, exist_ok=True)
    return out


def write(path, content):
    """Write UTF-8 with LF endings, so output is byte-identical on any OS."""
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(content)


if __name__ == "__main__":
    OUT_DIR = resolve_out_dir()
    for name, content in ASSETS:
        write(OUT_DIR / f"nescio-{name}.svg", content)
    print(f"brand svgs written -> {OUT_DIR}")