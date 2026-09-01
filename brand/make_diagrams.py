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
import math
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


# --- Text fitting ---------------------------------------------------------
#
# `wrap` counts characters; boxes are measured in pixels. Every call site used
# to carry a hand-tuned character count that did not derive from the box it
# wrapped into — so narrowing a column silently pushed text out through the
# card's right edge, with nothing in the tests to catch it. `chars_wide` closes
# that: ask for the box's usable width in pixels and get the character budget
# back, so the two can no longer drift apart.
#
# EM_PER_CHAR is a *budget*, not an average — a line of exactly N characters
# must fit in N * EM_PER_CHAR * size pixels whatever it says. Measured advance
# widths for the prose in this artwork, at 2048 upem:
#
#   Nescio Sans / Carlito 1.104   0.406-0.441 em/char   (avg lowercase 0.456)
#   Calibri                       metrically identical to Carlito
#   Arial / Helvetica             0.441 em/char         (avg lowercase 0.490)
#
# Arial is the widest face in FONT_SANS and the one a reader without the
# webfont most likely lands on, so it sets the floor. 0.5 em/char clears its
# bare-lowercase average — the worst case for text with no spaces to dilute it
# — which makes the budget sound for any string, not just the ones here today.
EM_PER_CHAR = 0.5

# Insets from a box's edge to its text. Cards centre their text and so spend
# the pad twice; the note box sets ragged-right from a +20 left margin and must
# still reserve the same gutter on the right, or the longest line touches the
# stroke.
CARD_PAD = 16
NOTE_PAD = 20


def chars_wide(px, size):
    """Characters of `size`px sans that fit in `px` of usable width."""
    return max(1, int(px / (size * EM_PER_CHAR)))


def px_wide(s, size):
    """Width budget for `s` at `size`px — the inverse of `chars_wide`."""
    return len(s) * size * EM_PER_CHAR


def centre_width(authored, scale, *lines):
    """Scale an authored box width, but never below the text it has to hold.

    `lines` are `(string, size)` pairs. The floor is the widest of them on the
    EM_PER_CHAR budget plus a `CARD_PAD` gutter either side — the same budget
    the wrap widths use, so a box and its contents can never be sized by two
    different rules.

    The ratio serves the composition; it does not get to clip a label, and
    shrinking type to make a target fit is not on the table. Where the two
    disagree the text wins and the box is held wider than the ratio asks.
    """
    floor = max(px_wide(s, size) for s, size in lines) + 2 * CARD_PAD
    return max(round(authored * scale), math.ceil(floor))


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
    lines = wrap(role, chars_wide(w - 2 * CARD_PAD, 12.5))
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

# The specialist roster the crew diagram draws, in lifecycle order, headings
# already upper-cased for the artwork. `orchestrator` is deliberately absent:
# the diagram renders it as the centre stack, not as one of the columns, so
# this list is the roster *minus* the coordinator.
#
# Module level rather than a local, so a test can read the roster the artwork
# is drawn from without re-parsing rendered SVG text. This list and
# `gen_catalog.AGENT_GROUPS` are two independent hardcoded copies of one fact —
# both drifted behind `agents/` once already — and
# `docs_site/test_site_content.py::CrewRosterTest` is what now ties the three
# together. Blurbs are one-line paraphrases of each agent's `description`
# frontmatter.
CREW_GROUPS = [
    ("DISCOVER", [
        ("scout", "risk and intent triage; surfaces hidden assumptions"),
        ("explore", "fast navigation of the codebase"),
        ("librarian", "external research, returned with citations"),
        ("vision", "diagrams, PDFs and images"),
    ]),
    ("PLAN AND CHALLENGE", [
        ("planner", "requirement interview, work plan"),
        ("validator", "is the plan executable? biased toward approval"),
        ("critic", "devil's advocate, one bounded pass, pre-execution"),
        ("advisor", "read-only guidance on tradeoffs"),
    ]),
    ("BUILD", [
        ("builder", "executes one scoped task; the only writer of production code"),
        ("builder-standard", "same contract on Sonnet; 50-200 lines, one or two design calls"),
        ("builder-simple", "same contract on Haiku; mechanical work under 50 lines"),
    ]),
    ("DOCUMENT", [
        ("doc-researcher", "maps existing docs: coverage, gaps, update targets"),
        ("doc-writer", "writes the docs; may not touch implementation files"),
    ]),
    ("VERIFY", [
        ("test-writer", "writes tests for the intended interface, not the current output"),
        ("qa-guard", "runs the project's CI checks; fixes mechanical failures"),
        ("reviewer", "audits for bugs, regressions, security"),
    ]),
]


def diagram_crew():
    # 1000px, down from 1400. The docs article column is 938px at a 1440
    # viewport and 1032px at 1920, so the old canvas overhung the text column
    # by half again and no amount of CSS could seat it — two attempts at
    # break-outs and scroll-wraps failed before the width itself was named as
    # the bug. 1000 sits one notch above the 1440 column so the wrapper still
    # scrolls a little there, and inside it at 1920; scaling to fit was never
    # on the table, because 12px labels do not survive it.
    W, H = 1000, 810
    s = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
         f'viewBox="0 0 {W} {H}">', style(), defs()]
    cx = W / 2

    # The three-column block of cards, stated here because the centre stack is
    # sized against it and gets drawn first. 3 x 280 + 2 x 44 = 928, leaving
    # 36px either side. The gap stays at 44: it separates groups, and shrinking
    # it with the columns would blur the three-band reading the section labels
    # set up.
    ncols, col_w, gap = 3, 280, 44
    col_block = ncols * col_w + (ncols - 1) * gap

    # The centre stack — request pill, orchestrator, gate band — was authored
    # against the 1228px block of the old 1400px canvas, so it scales by the
    # ratio of the two blocks and keeps the proportion it was drawn in. Holding
    # those boxes at their old pixel widths while the columns narrowed was the
    # visible cost of the reflow: the gate band went from 70% of the block to
    # 93% and the middle read far too heavy.
    centre_scale = col_block / (ncols * 380 + (ncols - 1) * gap)

    # The caption's count is DERIVED from the roster it labels, never typed.
    # It read "nine specialists" over ten drawn cards for as long as the roster
    # was sixteen — a hardcoded number in a caption is a claim about artwork it
    # cannot see, and it goes stale the first time a card is added. Spelled as a
    # word to match the sentence; the table covers any roster this canvas can
    # physically hold.
    specialists = sum(len(agents) for _, agents in CREW_GROUPS)
    ones = ("zero", "one", "two", "three", "four", "five", "six", "seven",
            "eight", "nine", "ten", "eleven", "twelve", "thirteen", "fourteen",
            "fifteen", "sixteen", "seventeen", "eighteen", "nineteen", "twenty")
    count_word = ones[specialists] if specialists < len(ones) else str(specialists)

    s.append(text(60, 52, "The crew", size=25, weight="700", fill=NODE_LABEL, anchor="start"))
    s.append(text(60, 76, f"One orchestrator, {count_word} specialists. Delegation goes "
                  "down; every result comes back through the gate.",
                  size=14.5, fill=BODY, anchor="start"))

    # Request
    pill_label = "your request"
    pw = centre_width(180, centre_scale, (pill_label, 14.5))
    s.append(box(cx - pw / 2, 108, pw, 40, r=20))
    s.append(text(cx, 133, pill_label, size=14.5, fill=BODY))
    s.append(arrow(cx, 148, cx, 176))

    # Orchestrator. The flow line is the widest string in the whole centre
    # stack and holds this box above the ratio's target — see `centre_width`.
    orch_sub = "coordinates the lifecycle · never writes production code"
    orch_flow = "triage → discover → analyze → plan → execute → verify → deliver"
    ow, oh = centre_width(470, centre_scale, (orch_sub, 13), (orch_flow, 12)), 84
    s.append(box(cx - ow / 2, 178, ow, oh, fill=ACCENT_FILL, stroke=ACCENT, sw=1.8))
    s.append(text(cx, 208, "orchestrator", size=19, weight="700", fill=ACCENT, family=MONO))
    s.append(text(cx, 231, orch_sub, size=13, fill=BODY))
    s.append(text(cx, 250, orch_flow, size=12, fill=MUTED))

    # Gate band
    gy = 300
    gate_line = ("judge a result before relaying it — never launder a "
                 "low-trust answer")
    gw = centre_width(860, centre_scale, (gate_line, 13))
    s.append(box(cx - gw / 2, gy, gw, 52, fill=NODE_FILL, stroke=ACCENT, dash="5 4", r=10))
    s.append(text(cx, gy + 22, "ROUTING QUALITY GATE", size=12, weight="700",
                  fill=ACCENT, spacing="1.4"))
    s.append(text(cx, gy + 40, gate_line, size=13, fill=BODY))

    # Down / up arrows through the gate. The offsets ride the same ratio as the
    # boxes, so the pair stays inside the band and keeps landing on the
    # orchestrator's lower edge instead of drifting off its corners.
    arm = round(150 * centre_scale)
    label_arm = round(168 * centre_scale)
    s.append(arrow(cx - arm, 262, cx - arm, gy - 6))
    s.append(arrow(cx - arm, gy + 58, cx - arm, 404))
    s.append(text(cx - label_arm, gy - 14, "delegate", size=11.5, fill=MUTED, anchor="end"))

    s.append(arrow(cx + arm, 404, cx + arm, gy + 58, color=ACCENT_CONNECTOR, head="accent"))
    s.append(arrow(cx + arm, gy - 6, cx + arm, 262, color=ACCENT_CONNECTOR, head="accent"))
    s.append(text(cx + label_arm, gy - 14, "results", size=11.5, fill=ACCENT, anchor="start"))

    # Groups — see CREW_GROUPS above for the roster and why it lives there.
    groups = CREW_GROUPS

    # `col_w` / `gap` / `col_block` are set at the top of this function — the
    # centre stack is sized against the block and is drawn before we get here.
    #
    # The guard is now about capacity, not an exact fit: the roster is laid out
    # as two bands of `ncols`, so it may run a column short — it does, band 2 is
    # DOCUMENT, VERIFY and an empty third slot — but never a column long, which
    # would silently drop a whole bucket off the canvas with nothing rendered to
    # show for it.
    assert len(groups) <= 2 * ncols, "the roster no longer fits two bands of columns"
    x0 = (W - col_block) / 2
    ytop = 432

    # Vertical air between the bottom of band 1's tallest column and band 2's
    # heading row. The card loop already leaves 12px of trailing gap, so this
    # reads as ~56px of separation between the two bands.
    band_gap = 44

    def draw_band(band, band_top):
        """Draw one row of up to `ncols` groups; return each column's bottom y."""
        bottoms = []
        for gi, (title, agents) in enumerate(band):
            gx = x0 + gi * (col_w + gap)
            s.append(text(gx + col_w / 2, band_top - 12, title, size=11.5, weight="700",
                          fill=MUTED, spacing="1.3"))
            s.append(f'<line x1="{gx}" y1="{band_top - 4}" x2="{gx + col_w}" '
                     f'y2="{band_top - 4}" stroke="{NODE_STROKE}" stroke-width="1"/>')
            y = band_top + 16
            for name, role in agents:
                accent = name in ("validator", "critic", "scout")
                card, h = agent_card(gx, y, col_w, name, role, accent=accent)
                s.append(card)
                y += h + 12
            bottoms.append(y)
        return bottoms

    band1 = draw_band(groups[:ncols], ytop)
    # Band 2's top is *derived* from the tallest column of band 1. A literal y
    # here would hold until the first card that gains a line of wrapped text,
    # and then quietly draw band 2 through the bottom of band 1.
    band2_top = max(band1) + band_gap
    band2 = draw_band(groups[ncols:], band2_top)
    col_bottom = max(band1 + band2)

    # The note fills band 2's empty third slot. Five buckets in a six-slot grid
    # leave exactly one hole, bottom-right — which is where the note sat before
    # the reflow — so it costs no canvas height at all: it ends level with the
    # columns beside it instead of below them.
    #
    # Under DOCUMENT (band 2, column 1) was tried and measured first, on the
    # theory that DOCUMENT had become the sparsest column. It is only 77px
    # sparser than VERIFY and the note is 254px tall, so 185px of it hung below
    # every card on the canvas with the 514px void sitting right beside it, and
    # the canvas grew 196px to hold that air. Rejected on the rendering.
    #
    # `band2_top` is shared with the draw_band call above rather than recomputed,
    # and `+ 16` is the card loop's own top offset — so the note starts level
    # with the first card of its band, not with the headings, and cannot drift
    # away from the band it belongs to.
    nx = x0 + 2 * (col_w + gap)
    ny = band2_top + 16
    note_chars = chars_wide(col_w - 2 * NOTE_PAD, 12.5)
    note = wrap("scout, validator and critic produce no work of their own. They exist "
                "to interrogate the request and the plan before anyone acts on either "
                "— the same ratio any functioning team spends on design review and QA.",
                note_chars)
    tail = wrap("Neither is a blocker by disposition: the critic may conclude the plan "
                "holds, and the validator approves when in doubt.", note_chars)
    nh = 44 + len(note) * 18 + 14 + len(tail) * 18 + 16
    s.append(box(nx, ny, col_w, nh, fill=NODE_FILL, stroke=NODE_STROKE, dash="4 4"))
    s.append(text(nx + NOTE_PAD, ny + 30, "Why three are highlighted", size=13.5,
                  weight="700", fill=NODE_LABEL, anchor="start"))
    yy = ny + 54
    for l in note:
        s.append(text(nx + NOTE_PAD, yy, l, size=12.5, fill=BODY, anchor="start"))
        yy += 18
    yy += 14
    for l in tail:
        s.append(text(nx + NOTE_PAD, yy, l, size=12.5, fill=MUTED, anchor="start"))
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
    # Same 1000px canvas as the crew — the two hang one above the other on the
    # homepage and a width mismatch reads as a mistake. The old 1400 was mostly
    # air: drawn content stopped at x=1250, so 150px of the overhang bought
    # nothing at all.
    W, H = 1000, 800
    s = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
         f'viewBox="0 0 {W} {H}">', style(), defs()]

    s.append(text(60, 52, "The learning loop", size=25, weight="700", fill=NODE_LABEL,
                  anchor="start"))
    s.append(text(60, 76, "Memory is not a bigger prompt. It is the residue of finished "
                  "work, curated on purpose and loaded on demand.",
                  size=14.5, fill=BODY, anchor="start"))

    # The boxes keep their 300px width — the cycle's four labels are sized for
    # it and the readiness box downstream is positioned off it. Only the side
    # margin gives, 150 -> 90, which is what pulls the right column in from
    # 1250 to 910 and leaves the annotation beside it room inside the canvas.
    bw, bh = 300, 132
    margin = 90
    left, right = margin, W - margin - bw
    top, bottom = 150, 460

    # 1 — session
    s.append(box(left, top, bw, bh, fill=ACCENT_FILL, stroke=ACCENT, sw=1.8))
    s.append(text(left + bw / 2, top + 30, "1 · session", size=16.5, weight="700",
                  fill=ACCENT, family=MONO))
    body_chars = chars_wide(bw - 2 * CARD_PAD, 13)
    for i, l in enumerate(wrap("The crew works a task through the lifecycle. "
                               "Triage decides which phases run at all.", body_chars)):
        s.append(text(left + bw / 2, top + 54 + i * 17, l, size=13, fill=BODY))
    s.append(text(left + bw / 2, top + 112, "memory is read here, on demand",
                  size=12, fill=ACCENT))

    # 2 — trail
    s.append(box(right, top, bw, bh))
    s.append(text(right + bw / 2, top + 30, "2 · activity trail", size=16.5,
                  weight="700", fill=NODE_LABEL, family=MONO))
    for i, l in enumerate(wrap("A Stop hook records what actually happened, "
                               "locally, when the session ends.", body_chars)):
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

    # readiness branch. Its width is derived, not authored: the right edge sits
    # flush with the cycle's right column so the deferred annotation reads as
    # tucked under the loop. The old fixed 420 was slack at 1400 and overhung
    # that column by 40px at 1000 — the sort of drift a hardcoded width invites.
    ry = bottom + bh + 60
    rx = left + bw + 140
    rw = right + bw - rx
    s.append(arrow(left + bw + 60, bottom + bh - 10, rx - 10, ry + 20,
                   color=DEFERRED, head="future", dash="5 4"))
    s.append(box(rx, ry, rw, 74, stroke=DEFERRED, dash="5 4"))
    s.append(text(rx + rw / 2, ry + 28, "readiness.md → autonomy dial",
                  size=15, weight="700", fill=DEFERRED, family=MONO))
    s.append(text(rx + rw / 2, ry + 50, "per-repo session outcomes. Planned, not shipped.",
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
