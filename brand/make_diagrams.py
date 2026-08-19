#!/usr/bin/env python3
"""Generate the two NescioAI diagrams as SVG.

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

INK = "#16191f"
INK2 = "#5a616b"
MUTED = "#8a919b"
ACCENT = "#2f4d7a"
ACCENT_FILL = "#eef2f8"
LINE = "#c9cfd8"
FUTURE = "#a8b0ba"
SURFACE = "#ffffff"
FONT = "Carlito, 'Liberation Sans', 'Helvetica Neue', Arial, sans-serif"
MONO = "'Liberation Mono', 'SF Mono', Menlo, monospace"


def esc(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def text(x, y, s, size=15, fill=INK, weight="400", anchor="middle",
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


def box(x, y, w, h, fill=SURFACE, stroke=LINE, r=8, sw=1.2, dash=None):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" '
            f'fill="{fill}" stroke="{stroke}" stroke-width="{sw}"{d}/>')


def agent_card(x, y, w, name, role, accent=False):
    lines = wrap(role, 38)
    h = 40 + len(lines) * 17 + 8
    out = [box(x, y, w, h, fill=ACCENT_FILL if accent else SURFACE,
               stroke=ACCENT if accent else LINE)]
    out.append(text(x + w / 2, y + 26, name, size=15.5, weight="700",
                    fill=ACCENT if accent else INK, family=MONO))
    for i, line in enumerate(lines):
        out.append(text(x + w / 2, y + 46 + i * 17, line, size=12.5, fill=INK2))
    return "".join(out), h


def arrow(x1, y1, x2, y2, color=LINE, sw=1.4, head="end", dash=None):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    m = f' marker-end="url(#head-{head})"'
    return (f'<path d="M {x1} {y1} L {x2} {y2}" fill="none" stroke="{color}" '
            f'stroke-width="{sw}"{d}{m}/>')


def defs():
    return f"""<defs>
  <marker id="head-end" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7"
          markerHeight="7" orient="auto-start-reverse">
    <path d="M 0 1 L 9 5 L 0 9 z" fill="{MUTED}"/>
  </marker>
  <marker id="head-accent" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7"
          markerHeight="7" orient="auto-start-reverse">
    <path d="M 0 1 L 9 5 L 0 9 z" fill="{ACCENT}"/>
  </marker>
  <marker id="head-future" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7"
          markerHeight="7" orient="auto-start-reverse">
    <path d="M 0 1 L 9 5 L 0 9 z" fill="{FUTURE}"/>
  </marker>
</defs>"""


# --------------------------------------------------------------------------
# Diagram 1 — the crew
# --------------------------------------------------------------------------

def diagram_crew():
    W, H = 1400, 810
    s = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
         f'viewBox="0 0 {W} {H}">', defs(),
         f'<rect width="{W}" height="{H}" fill="{SURFACE}"/>']
    cx = W / 2

    s.append(text(60, 52, "The crew", size=25, weight="700", fill=INK, anchor="start"))
    s.append(text(60, 76, "One orchestrator, nine specialists. Delegation goes down; "
                  "every result comes back through the gate.",
                  size=14.5, fill=INK2, anchor="start"))

    # Request
    s.append(box(cx - 90, 108, 180, 40, r=20))
    s.append(text(cx, 133, "your request", size=14.5, fill=INK2))
    s.append(arrow(cx, 148, cx, 176))

    # Orchestrator
    ow, oh = 470, 84
    s.append(box(cx - ow / 2, 178, ow, oh, fill=ACCENT_FILL, stroke=ACCENT, sw=1.8))
    s.append(text(cx, 208, "orchestrator", size=19, weight="700", fill=ACCENT, family=MONO))
    s.append(text(cx, 231, "coordinates the lifecycle · never writes production code",
                  size=13, fill=INK2))
    s.append(text(cx, 250, "triage → discover → analyze → plan → execute → verify → deliver",
                  size=12, fill=MUTED))

    # Gate band
    gy = 300
    s.append(box(cx - 430, gy, 860, 52, fill="#fbfcfd", stroke=ACCENT, dash="5 4", r=10))
    s.append(text(cx, gy + 22, "ROUTING QUALITY GATE", size=12, weight="700",
                  fill=ACCENT, spacing="1.4"))
    s.append(text(cx, gy + 40, "judge a result before relaying it — never launder a "
                  "low-trust answer", size=13, fill=INK2))

    # down / up arrows through the gate
    s.append(arrow(cx - 150, 262, cx - 150, gy - 6))
    s.append(arrow(cx - 150, gy + 58, cx - 150, 404))
    s.append(text(cx - 168, gy - 14, "delegate", size=11.5, fill=MUTED, anchor="end"))

    s.append(arrow(cx + 150, 404, cx + 150, gy + 58, color=ACCENT, head="accent"))
    s.append(arrow(cx + 150, gy - 6, cx + 150, 262, color=ACCENT, head="accent"))
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
                 f'stroke="{LINE}" stroke-width="1"/>')
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
    s.append(box(nx, ny, col_w, nh, fill="#fbfcfd", stroke=LINE, dash="4 4"))
    s.append(text(nx + 20, ny + 30, "Why three are highlighted", size=13.5,
                  weight="700", fill=INK, anchor="start"))
    yy = ny + 54
    for l in note:
        s.append(text(nx + 20, yy, l, size=12.5, fill=INK2, anchor="start"))
        yy += 18
    yy += 14
    for l in tail:
        s.append(text(nx + 20, yy, l, size=12.5, fill=MUTED, anchor="start"))
        yy += 18
    col_bottom = max(col_bottom, ny + nh + 12)

    H = int(col_bottom + 36)
    s[0] = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
            f'viewBox="0 0 {W} {H}">')
    s[2] = f'<rect width="{W}" height="{H}" fill="{SURFACE}"/>'
    s.append("</svg>")
    return "\n".join(s)


# --------------------------------------------------------------------------
# Diagram 2 — the learning loop
# --------------------------------------------------------------------------

def diagram_loop():
    W, H = 1400, 800
    s = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
         f'viewBox="0 0 {W} {H}">', defs(),
         f'<rect width="{W}" height="{H}" fill="{SURFACE}"/>']

    s.append(text(60, 52, "The learning loop", size=25, weight="700", fill=INK, anchor="start"))
    s.append(text(60, 76, "Memory is not a bigger prompt. It is the residue of finished "
                  "work, curated on purpose and loaded on demand.",
                  size=14.5, fill=INK2, anchor="start"))

    bw, bh = 300, 132
    left, right = 150, W - 150 - bw
    top, bottom = 150, 460

    # 1 — session
    s.append(box(left, top, bw, bh, fill=ACCENT_FILL, stroke=ACCENT, sw=1.8))
    s.append(text(left + bw / 2, top + 30, "1 · session", size=16.5, weight="700",
                  fill=ACCENT, family=MONO))
    for i, l in enumerate(wrap("The crew works a task through the lifecycle. "
                               "Triage decides which phases run at all.", 40)):
        s.append(text(left + bw / 2, top + 54 + i * 17, l, size=13, fill=INK2))
    s.append(text(left + bw / 2, top + 112, "memory is read here, on demand",
                  size=12, fill=ACCENT))

    # 2 — trail
    s.append(box(right, top, bw, bh))
    s.append(text(right + bw / 2, top + 30, "2 · activity trail", size=16.5,
                  weight="700", fill=INK, family=MONO))
    for i, l in enumerate(wrap("A Stop hook records what actually happened, "
                               "locally, when the session ends.", 40)):
        s.append(text(right + bw / 2, top + 54 + i * 17, l, size=13, fill=INK2))
    s.append(text(right + bw / 2, top + 112, "raw, uncurated", size=12, fill=MUTED))

    # 3 — harvest
    s.append(box(right, bottom, bw, bh))
    s.append(text(right + bw / 2, bottom + 30, "3 · /harvest-memory", size=16.5,
                  weight="700", fill=INK, family=MONO))
    for i, l in enumerate(["source precedence decides who wins",
                           "contradictions surface as decisions",
                           "a dedup ledger stops repetition"]):
        s.append(text(right + bw / 2, bottom + 54 + i * 19, line_dot(l), size=13, fill=INK2))

    # 4 — memory
    s.append(box(left, bottom, bw, bh))
    s.append(text(left + bw / 2, bottom + 30, "4 · memory/", size=16.5, weight="700",
                  fill=INK, family=MONO))
    for i, l in enumerate(["per-repo and per-project notes",
                           "standing feedback · glossary",
                           "ships as structure, not content"]):
        s.append(text(left + bw / 2, bottom + 54 + i * 19, line_dot(l), size=13, fill=INK2))

    # arrows around the cycle
    s.append(arrow(left + bw + 14, top + bh / 2, right - 14, top + bh / 2))
    s.append(arrow(right + bw / 2, top + bh + 14, right + bw / 2, bottom - 14))
    s.append(arrow(right - 14, bottom + bh / 2, left + bw + 14, bottom + bh / 2))
    s.append(arrow(left + bw / 2, bottom - 14, left + bw / 2, top + bh + 14,
                   color=ACCENT, head="accent"))

    s.append(text(W / 2, top + bh / 2 - 12, "session ends", size=12, fill=MUTED))
    s.append(text(right + bw / 2 + 14, (top + bh + bottom) / 2, "you curate, deliberately",
                  size=12, fill=MUTED, anchor="start"))
    s.append(text(W / 2, bottom + bh / 2 - 12, "durable notes written", size=12, fill=MUTED))
    s.append(text(left + bw / 2 - 14, (top + bh + bottom) / 2, "loaded on demand",
                  size=12, fill=ACCENT, anchor="end"))

    # readiness branch
    ry = bottom + bh + 60
    s.append(arrow(left + bw + 60, bottom + bh - 10, left + bw + 130, ry + 20,
                   color=FUTURE, head="future", dash="5 4"))
    s.append(box(left + bw + 140, ry, 420, 74, stroke=FUTURE, dash="5 4"))
    s.append(text(left + bw + 350, ry + 28, "readiness.md → autonomy dial",
                  size=15, weight="700", fill=FUTURE, family=MONO))
    s.append(text(left + bw + 350, ry + 50, "per-repo session outcomes. Planned, not shipped.",
                  size=12.5, fill=MUTED))

    s.append("</svg>")
    return "\n".join(s)


def line_dot(s):
    return "· " + s


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


if __name__ == "__main__":
    OUT_DIR = resolve_out_dir()
    write(OUT_DIR / "diagram-crew.svg", diagram_crew())
    write(OUT_DIR / "diagram-loop.svg", diagram_loop())
    print(f"svgs written -> {OUT_DIR}")