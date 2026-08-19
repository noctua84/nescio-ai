#!/usr/bin/env python3
"""Canonical Nescio colour and type constants — the single source of truth.

Every brand generator (`make_brand.py`, `make_diagrams.py`, `make_favicons.py`,
`render_diagrams.py`) imports from here instead of declaring its own constants.
That is the whole point of the module: the kit previously carried three
near-identical greys and two near-blacks doing the same job across three files,
one of which (`#8a919b`) failed WCAG AA on white and shipped that way in both
architecture diagrams.

Authoritative spec: `docs/design/design-system.md` §2 (colour) and §3 (type).
Retired hexes — `#8a919b` (AA failure) and `#111418` (drifted near-black) —
must never reappear here; `test_palette.py` enforces that.

Stdlib only. This module has no dependencies and must keep it that way.
"""

from __future__ import annotations

# --- Canonical tokens (spec §2) ------------------------------------------

# Dark grounds
ink_deep = "#0e1319"  # Dark page ground
ink_raised = "#141b24"  # Header, cards, raised surfaces on dark

# Accents. The accent rule is non-negotiable: periwinkle carries dark mode,
# brand blue carries light mode. Neither crosses over for text or links —
# periwinkle on white measures 2.2:1 and fails AA. On a light ground it is
# permitted as a fill or border only.
brand_blue = "#2f4d7a"  # Primary. Light-mode accent and links
periwinkle = "#8fb0d9"  # Dark-mode accent and links

# Tinted surfaces
tint = "#eef2f8"  # Highlighted cards, admonition fills (light)
tint_dark = "#182333"  # Same role on dark

# Type colours
text = "#16191f"  # Headings on light
text_dark = "#e9edf2"  # Headings and labels on dark — the counterpart to `text`
body = "#5a616b"  # Running text on light — 6.3:1 on white
muted = "#6b727c"  # Captions and labels on light — 4.9:1 on white, passes AA
muted_dark = "#8d97a4"  # Captions and labels on dark — 6.3:1 on ink_deep

# Rules and outlines
border = "#c9cfd8"  # Card outlines, rules (light)
border_dark = "#26313f"  # Same role on dark

# Convention: planned-but-not-shipped is drawn dashed in this colour (spec §7)
deferred = "#a8b0ba"

# Light ground
paper = "#ffffff"

TOKENS: dict[str, str] = {
    "ink_deep": ink_deep,
    "ink_raised": ink_raised,
    "brand_blue": brand_blue,
    "periwinkle": periwinkle,
    "tint": tint,
    "tint_dark": tint_dark,
    "text": text,
    "text_dark": text_dark,
    "body": body,
    "muted": muted,
    "muted_dark": muted_dark,
    "border": border,
    "border_dark": border_dark,
    "deferred": deferred,
    "paper": paper,
}

# --- Typography (spec §3) ------------------------------------------------

# The currently self-hosted faces, named first with generic fallbacks.
#
# `Nescio Mono` / `Nescio Sans` are the *internal* family names carried by the
# four `woff2` subsets in `brand/fonts/`, and therefore the names the site's
# `@font-face` rules declare. They are renamed rather than called `Liberation
# Mono` / `Carlito` because SIL OFL clause 3 forbids a Reserved Font Name on a
# Modified Version, and a Latin-only subset is a modification (OFL-FAQ 2.6-2.8).
# See `brand/fonts/README.md` § "Naming". Do not "fix" these back.
#
# They must come first: whatever the generated SVGs ask for is what the browser
# looks up, so if these did not match the shipped `@font-face` family names,
# every diagram would silently fall through to a system face. The upstream
# names follow as fallbacks so a standalone SVG still renders correctly on a
# machine that has Liberation Mono / Carlito installed.
#
# These strings land inside SVG `font-family="..."` attributes, so every quoted
# family name here uses **single** quotes — a double quote would close the
# attribute and produce malformed XML.
#
# Spec §3 settles on IBM Plex Sans + IBM Plex Mono as the target pairing; the
# migration (task T16) is deliberately a one-line edit to each of these two
# constants plus a `wrap()` width retune in `make_diagrams.py`, because Plex
# Sans is wider than Carlito at the same size.
FONT_SANS = "'Nescio Sans', Carlito, Calibri, Helvetica, Arial, sans-serif"
FONT_MONO = "'Nescio Mono', 'Liberation Mono', 'DejaVu Sans Mono', 'Courier New', monospace"

#: The internal family names of the shipped subsets, mono/sans. Kept beside the
#: stacks above so `test_palette.py` can assert the stacks name them first.
SUBSET_FAMILY_MONO = "Nescio Mono"
SUBSET_FAMILY_SANS = "Nescio Sans"

# --- Contrast (WCAG 2.1) -------------------------------------------------

_AA_NORMAL = 4.5
_AA_LARGE = 3.0
_AAA_NORMAL = 7.0


def _parse_hex(value: str) -> tuple[int, int, int]:
    """Return (r, g, b) 0-255 from `#rgb` or `#rrggbb` (leading `#` optional)."""
    s = value.strip().lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    if len(s) != 6:
        raise ValueError(f"not a hex colour: {value!r}")
    try:
        return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
    except ValueError:
        raise ValueError(f"not a hex colour: {value!r}") from None


def _linearise(channel: int) -> float:
    """sRGB channel (0-255) to linear-light, per WCAG 2.1."""
    c = channel / 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(colour: str) -> float:
    """WCAG 2.1 relative luminance of a hex colour, in [0, 1]."""
    r, g, b = (_linearise(c) for c in _parse_hex(colour))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(fg: str, bg: str) -> float:
    """WCAG 2.1 contrast ratio between two hex colours, in [1, 21].

    Symmetric in its arguments: the lighter colour always takes the numerator.

        >>> round(contrast_ratio("#6b727c", "#ffffff"), 1)
        4.9
    """
    a, b = relative_luminance(fg), relative_luminance(bg)
    light, dark = (a, b) if a > b else (b, a)
    return (light + 0.05) / (dark + 0.05)


def passes_aa(fg: str, bg: str, large: bool = False) -> bool:
    """True if the pair clears the WCAG AA floor (4.5:1, or 3:1 for large text)."""
    return contrast_ratio(fg, bg) >= (_AA_LARGE if large else _AA_NORMAL)
