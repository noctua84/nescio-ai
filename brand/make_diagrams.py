#!/usr/bin/env python3
"""Generate the two NescioAI diagrams as SVG — tokenised source plus twins.

Pure string generation — stdlib only, no Pillow and no Chromium. Safe in CI.

Six files per run (spec `docs/design/design-system.md` §6, "The pipeline"):

  diagram-crew.svg        tokenised source — every colour a CSS custom
  diagram-loop.svg        property, **no background rect**. The docs site
                          inlines these so the page's own `--diagram-*`
                          tokens reach them and they follow the scheme
                          toggle live.
  diagram-*-light.svg     the same art with the variables resolved to the
  diagram-*-dark.svg      concrete hexes of the §6 light/dark columns, plus
                          a ground, for contexts that cannot supply CSS
                          variables — GitHub's README, link previews, any
                          bare `<img>`.

The source's defaults are declared on `svg:root`, which matches **only** when
the file is the document root. Inlined into an HTML page the rule does not
match at all, so the page's tokens win and the toggle reaches the art; opened
standalone it does match, so the file still renders in the light scheme.

Colours come from `brand.palette`. Retiring `#8a919b` (3.2:1 on white, below
the 4.5:1 AA floor) in favour of `palette.muted` `#6b727c` (4.9:1) is the WCAG
fix called for in spec §2 — that hex carried every section label, connector
label and deferred annotation in both diagrams.

Output directory, highest precedence first:
  1. ``--out DIR``
  2. ``$BRAND_OUT``
  3. ``<this file's directory>/dist`` — i.e. ``brand/dist/``, resolved relative
     to this file, not the current working directory.
"""
import argparse
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from brand import palette  # noqa: E402

# --- Diagram tokens (spec §6) --------------------------------------------
#
# One custom property per row of the §6 diagram-token table. Nothing in the
# art below names a hex directly; the only hexes in this module are the two
# resolution tables and they map 1:1 onto that table's Light and Dark columns.

NODE_FILL = "var(--diagram-node-fill)"
NODE_STROKE = "var(--diagram-node-stroke)"
NODE_LABEL = "var(--diagram-node-label)"
ACCENT_FILL = "var(--diagram-accent-fill)"
ACCENT = "var(--diagram-accent)"
BODY = "var(--diagram-body)"
MUTED = "var(--diagram-muted)"
CONNECTOR = "var(--diagram-connector)"
ACCENT_CONNECTOR = "var(--diagram-accent-connector)"
DEFERRED = "var(--diagram-deferred)"

LIGHT = {
    "--diagram-accent-fill": palette.tint,             # emphasised node fill
    "--diagram-accent": palette.brand_blue,            # emph. node stroke+label
    "--diagram-node-fill": palette.paper,              # plain node fill
    "--diagram-node-stroke": palette.border,           # plain node stroke
    "--diagram-node-label": palette.text,              # plain node label
    "--diagram-body": palette.body,                    # body text
    "--diagram-muted": palette.muted,                  # caption / conn. label
    "--diagram-connector": palette.border,             # connector
    "--diagram-accent-connector": palette.brand_blue,  # accent connector
    "--diagram-deferred": palette.deferred,            # deferred (dashed)
}

DARK = {
    "--diagram-accent-fill": palette.tint_dark,
    "--diagram-accent": palette.periwinkle,
    "--diagram-node-fill": palette.ink_raised,
    "--diagram-node-stroke": palette.border_dark,
    "--diagram-node-label": palette.text_dark,
    "--diagram-body": palette.deferred,
    "--diagram-muted": palette.muted_dark,
    "--diagram-connector": palette.border_dark,
    "--diagram-accent-connector": palette.periwinkle,
    "--diagram-deferred": palette.deferred,
}

SCHEMES = {"light": LIGHT, "dark": DARK}

# §6 gives the source no ground — the page supplies it. The twins exist for
# consumers that supply nothing, so they carry the canonical page ground of
# their scheme.
GROUND = {"light": palette.paper, "dark": palette.ink_deep}

FONT = palette.FONT_SANS
MONO = palette.FONT_MONO


def esc(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def text(x, y, s, size=15, fill=NODE_LABEL, weight="400", anchor="middle",
         family=FONT, spacing=None, opacity=None):
    extra = ""
    if spacing:
        extra += f' letter-spacing="{spacing}"'
    if opacity:
        extra += f' opacity="{opacity}"'
    return (f'<text x="{x}" y="{y}" font-family="{family}" font-size="{size}" '
            f'fill="{fill}" font-weight="{weight}" text-anchor="{anchor}"{extra}>'
            f'{esc(s)}</text>')


def wrap(s, width):
    words, lines, cur = s.split(), [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if len(trial) <= width:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def box(x, y, w, h, fill=NODE_FILL, stroke=NODE_STROKE, r=8, sw=1.2, dash=None):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="{sw}"{d}/>')


def agent_card(x, y, w, name, role, accent=False):
    lines = wrap(role, 38)
    h = 40 + len(lines) * 17 + 8
    out = [box(x, y, w, h, fill=ACCENT_FILL if accent else NODE_FILL,
               stroke=ACCENT if accent else NODE_STROKE)]
    out.append(text(x + w / 2, y + 26, name, size=15.5, weight="700",
                    fill=ACCENT if accent else NODE_LABEL, family=MONO))
    for i, line in enumerate(lines):
        out.append(text(x + w / 2, y + 46 + i * 17, line, size=12.5, fill=BODY))
    return "".join(out), h


def arrow(x1, y1, x2, y2, color=CONNECTOR, sw=1.4, head="end", dash=None):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    m = f' marker-end="url(#head-{head})"'
    return (f'<path d="M {x1} {y1} L {x2} {y2}" fill="none" stroke="{color}" '
            f'stroke-width="{sw}"{d}{m}/>')


def style():
    """`svg:root` defaults — see the module docstring for why not bare `:root`."""
    rows = "\n".join(f"      {name}: {value};" for name, value in LIGHT.items())
    return ("  <style>\n"
            "    /* Light-scheme defaults for standalone rendering. `svg:root`\n"
            "       matches only when this file is the document root, so an\n"
            "       inlining page's own --diagram-* tokens take over and the\n"
            "       scheme toggle reaches the artwork. */\n"
            "    svg:root {\n"
            f"{rows}\n"
            "    }\n"
            "  </style>")


def defs():
    return f"""<defs>
  <marker id="head-end" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7"
          markerHeight="7" orient="auto-start-reverse">
    <path d="M 0 1 L 9 5 L 0 9 z" fill="{MUTED}"/>
  </marker>
  <marker id="head-accent" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7"
          markerHeight="7" orient="auto-start-reverse">
    <path d="M 0 1 L 9 5 L 0 9 z" fill="{ACCENT_CONNECTOR}"/>
  </marker>
  <marker id="head-future" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7"
          markerHeight="7" orient="auto-start-reverse">
    <path d="M 0 1 L 9 5 L 0 9 z" fill="{DEFERRED}"/>
  </marker>
</defs>"""


# --------------------------------------------------------------------------
# Diagram 1 — the crew
# --------------------------------------------------------------------------

def diagram_crew():
    W, H = 1400, 810
    s = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
         f'viewBox="0 0 {W} {H}">', style(), defs()]
    cx = W / 2

    s.append(text(60, 52, "The crew", size=25, weight="700", fill=NODE_LABEL, anchor="start"))
    s.append(text(60, 76, "One orchestrator, nine specialists. Delegation goes down; "
                  "every result comes back through the gate.",
                  size=14.5, fill=BODY, anchor="start"))

    # Request
    s.append(box(cx - 90, 108, 180, 40, r=20))
    s.append(text(cx, 133, "your request", size=14.5, fill=BODY))
    s.append(arrow(cx, 148, cx, 176))

    # Orchestrator
    ow, oh = 470, 84
    s.append(box(cx - ow / 2, 178, ow, oh, fill=ACCENT_FILL, stroke=ACCENT, sw=1.8))
    s.append(text(cx, 208, "orchestrator", size=19, weight="700", fill=ACCENT, family=MONO))
    s.append(text(cx, 231, "coordinates the lifecycle · never writes production code",
                  size=13, fill=BODY))
    s.append(text(cx, 250, "triage → discover → analyze → plan → execute → verify → deliver",
                  size=12, fill=MUTED))

    # Gate band
    gy = 300
    s.append(box(cx - 430, gy, 860, 52, fill=NODE_FILL, stroke=ACCENT, dash="5 4", r=10))
    s.append(text(cx, gy + 22, "ROUTING QUALITY GATE", size=12, weight="700",
                  fill=ACCENT, spacing="1.4"))
    s.append(text(cx, gy + 40, "judge a result before relaying it — never launder a "
                  "low-trust answer", size=13, fill=BODY))

    # down / up arrows through the gate
    s.append(arrow(cx - 150, 262, cx - 150, gy - 6))
    s.append(arrow(cx - 150, gy + 58, cx - 150, 404))
    s.append(text(cx - 168, gy - 14, "delegate", size=11.5, fill=MUTED, anchor="end"))

    s.append(arrow(cx + 150, 404, cx + 150, gy + 58, color=ACCENT_CONNECTOR, head="accent"))
    s.append(arrow(cx + 150, gy - 6, cx + 150, 262, color=ACCENT_CONNECTOR, head="accent"))
    s.append(text(cx + 168, gy - 14, "results", size=11.5, fill=ACCENT, anchor="start"))

    # Groups
    groups = [
        ("TRIAGE & DISCOVERY", [
            ("scout", "risk and intent triage; surfaces hidden assumptions"),
            ("explore", "fast navigation of the codebase"),
            ("librarian", "external research, returned with citations"),
            ("vision", "diagrams, PDFs and images"),
        ]),
        ("PLAN & CHALLENGE", [
            ("planner", "requirement interview, work plan"),
            ("validator", "is the plan executable? biased toward approval"),
            ("critic", "devil's advocate, one bounded pass, pre-execution"),
            ("advisor", "read-only guidance on tradeoffs"),
        ]),
        ("VERIFY", [
            ("reviewer", "audits for bugs, regressions, security"),
        ]),
    ]

    col_w, gap = 380, 44
    total = len(groups) * col_w + (len(groups) - 1) * gap
    x0 = (W - total) / 2
    ytop = 432
    col_bottom = ytop

    for gi, (title, agents) in enumerate(groups):
        gx = x0 + gi * (col_w + gap)
        s.append(text(gx + col_w / 2, ytop - 12, title, size=11.5, weight="700",
                      fill=MUTED, spacing="1.3"))
        s.append(f'<line x1="{gx}" y1="{ytop - 4}" x2="{gx + col_w}" y2="{ytop - 4}" '
                 f'stroke="{NODE_STROKE}" stroke-width="1"/>')
        y = ytop + 16
        for name, role in agents:
            accent = name in ("validator", "critic", "scout")
            card, h = agent_card(gx, y, col_w, name, role, accent=accent)
            s.append(card)
            y += h + 12
        col_bottom = max(col_bottom, y)

    # Note tucked under the sparse VERIFY column
    nx = x0 + 2 * (col_w + gap)
    ny = ytop + 16 + 84
    note = wrap("scout, validator and critic produce no work of their own. They exist "
                "to interrogate the request and the plan before anyone acts on either "
                "— the same ratio any functioning team spends on design review and QA.",
                40)
    tail = wrap("Neither is a blocker by disposition: the critic may conclude the plan "
                "holds, and the validator approves when in doubt.", 40)
    nh = 44 + len(note) * 18 + 14 + len(tail) * 18 + 16
    s.append(box(nx, ny, col_w, nh, fill=NODE_FILL, stroke=NODE_STROKE, dash="4 4"))
    s.append(text(nx + 20, ny + 30, "Why three are highlighted", size=13.5,
                  weight="700", fill=NODE_LABEL, anchor="start"))
    yy = ny + 54
    for l in note:
        s.append(text(nx + 20, yy, l, size=12.5, fill=BODY, anchor="start"))
        yy += 18
    yy += 14
    for l in tail:
        s.append(text(nx + 20, yy, l, size=12.5, fill=MUTED, anchor="start"))
        yy += 18
    col_bottom = max(col_bottom, ny + nh + 12)

    H = int(col_bottom + 36)
    s[0] = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
            f'viewBox="0 0 {W} {H}">')
    s.append("</svg>")
    return "\n".join(s)


# --------------------------------------------------------------------------
# Diagram 2 — the learning loop
# --------------------------------------------------------------------------

def diagram_loop():
    W, H = 1400, 800
    s = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
         f'viewBox="0 0 {W} {H}">', style(), defs()]

    s.append(text(60, 52, "The learning loop", size=25, weight="700", fill=NODE_LABEL,
                  anchor="start"))
    s.append(text(60, 76, "Memory is not a bigger prompt. It is the residue of finished "
                  "work, curated on purpose and loaded on demand.",
                  size=14.5, fill=BODY, anchor="start"))

    bw, bh = 300, 132
    left, right = 150, W - 150 - bw
    top, bottom = 150, 460

    # 1 — session
    s.append(box(left, top, bw, bh, fill=ACCENT_FILL, stroke=ACCENT, sw=1.8))
    s.append(text(left + bw / 2, top + 30, "1 · session", size=16.5, weight="700",
                  fill=ACCENT, family=MONO))
    for i, l in enumerate(wrap("The crew works a task through the lifecycle. "
                               "Triage decides which phases run at all.", 40)):
        s.append(text(left + bw / 2, top + 54 + i * 17, l, size=13, fill=BODY))
    s.append(text(left + bw / 2, top + 112, "memory is read here, on demand",
                  size=12, fill=ACCENT))

    # 2 — trail
    s.append(box(right, top, bw, bh))
    s.append(text(right + bw / 2, top + 30, "2 · activity trail", size=16.5,
                  weight="700", fill=NODE_LABEL, family=MONO))
    for i, l in enumerate(wrap("A Stop hook records what actually happened, "
                               "locally, when the session ends.", 40)):
        s.append(text(right + bw / 2, top + 54 + i * 17, l, size=13, fill=BODY))
    s.append(text(right + bw / 2, top + 112, "raw, uncurated", size=12, fill=MUTED))

    # 3 — harvest
    s.append(box(right, bottom, bw, bh))
    s.append(text(right + bw / 2, bottom + 30, "3 · /harvest-memory", size=16.5,
                  weight="700", fill=NODE_LABEL, family=MONO))
    for i, l in enumerate(["source precedence decides who wins",
                           "contradictions surface as decisions",
                           "a dedup ledger stops repetition"]):
        s.append(text(right + bw / 2, bottom + 54 + i * 19, line_dot(l), size=13, fill=BODY))

    # 4 — memory
    s.append(box(left, bottom, bw, bh))
    s.append(text(left + bw / 2, bottom + 30, "4 · memory/", size=16.5, weight="700",
                  fill=NODE_LABEL, family=MONO))
    for i, l in enumerate(["per-repo and per-project notes",
                           "standing feedback · glossary",
                           "ships as structure, not content"]):
        s.append(text(left + bw / 2, bottom + 54 + i * 19, line_dot(l), size=13, fill=BODY))

    # arrows around the cycle
    s.append(arrow(left + bw + 14, top + bh / 2, right - 14, top + bh / 2))
    s.append(arrow(right + bw / 2, top + bh + 14, right + bw / 2, bottom - 14))
    s.append(arrow(right - 14, bottom + bh / 2, left + bw + 14, bottom + bh / 2))
    s.append(arrow(left + bw / 2, bottom - 14, left + bw / 2, top + bh + 14,
                   color=ACCENT_CONNECTOR, head="accent"))

    s.append(text(W / 2, top + bh / 2 - 12, "session ends", size=12, fill=MUTED))
    s.append(text(right + bw / 2 + 14, (top + bh + bottom) / 2, "you curate, deliberately",
                  size=12, fill=MUTED, anchor="start"))
    s.append(text(W / 2, bottom + bh / 2 - 12, "durable notes written", size=12, fill=MUTED))
    s.append(text(left + bw / 2 - 14, (top + bh + bottom) / 2, "loaded on demand",
                  size=12, fill=ACCENT, anchor="end"))

    # readiness branch
    ry = bottom + bh + 60
    s.append(arrow(left + bw + 60, bottom + bh - 10, left + bw + 130, ry + 20,
                   color=DEFERRED, head="future", dash="5 4"))
    s.append(box(left + bw + 140, ry, 420, 74, stroke=DEFERRED, dash="5 4"))
    s.append(text(left + bw + 350, ry + 28, "readiness.md → autonomy dial",
                  size=15, weight="700", fill=DEFERRED, family=MONO))
    s.append(text(left + bw + 350, ry + 50, "per-repo session outcomes. Planned, not shipped.",
                  size=12.5, fill=MUTED))

    s.append("</svg>")
    return "\n".join(s)


def line_dot(s):
    return "· " + s


# --------------------------------------------------------------------------
# Twin generation — resolve the variables to concrete hexes
# --------------------------------------------------------------------------

_STYLE_RE = re.compile(r"[ \t]*<style>.*?</style>\n?", re.DOTALL)
_VAR_RE = re.compile(r"var\((--[a-z0-9-]+)\)")
_OPEN_RE = re.compile(r"<svg\b[^>]*>")


def resolve(svg, scheme):
    """Return `svg` with every `var(--…)` replaced by its `scheme` hex.

    Also drops the `<style>` defaults block — nothing references the variables
    any more — and adds the scheme's ground, because the twins exist precisely
    for consumers that cannot supply one.
    """
    try:
        table = SCHEMES[scheme]
    except KeyError:
        raise ValueError(f"unknown scheme {scheme!r}") from None

    def substitute(match):
        name = match.group(1)
        if name not in table:
            raise KeyError(f"no {scheme} value for {name}")
        return table[name]

    out = _VAR_RE.sub(substitute, _STYLE_RE.sub("", svg))

    open_tag = _OPEN_RE.match(out)
    if open_tag is None:
        raise ValueError("no opening <svg> tag")
    w = re.search(r'width="([\d.]+)"', open_tag.group(0)).group(1)
    h = re.search(r'height="([\d.]+)"', open_tag.group(0)).group(1)
    ground = f'\n<rect width="{w}" height="{h}" fill="{GROUND[scheme]}"/>'
    return out[:open_tag.end()] + ground + out[open_tag.end():]


def resolve_out_dir(argv=None):
    """--out, else $BRAND_OUT, else brand/dist/ next to this file."""
    ap = argparse.ArgumentParser(description="Generate the NescioAI diagram SVGs.")
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


DIAGRAMS = {"diagram-crew": diagram_crew, "diagram-loop": diagram_loop}


def build(out_dir):
    """Write the tokenised source and both twins for every diagram."""
    written = []
    for stem, make in DIAGRAMS.items():
        source = make()
        write(out_dir / f"{stem}.svg", source)
        written.append(out_dir / f"{stem}.svg")
        for scheme in SCHEMES:
            path = out_dir / f"{stem}-{scheme}.svg"
            write(path, resolve(source, scheme))
            written.append(path)
    return written


if __name__ == "__main__":
    OUT_DIR = resolve_out_dir()
    files = build(OUT_DIR)
    print(f"{len(files)} svgs written -> {OUT_DIR}")
