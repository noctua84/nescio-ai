# brand/test_rasterisers.py
"""Tests for the two local-only rasterisers.

`make_favicons.py` and `render_diagrams.py` import Pillow and shell out to a
local Chromium, so this module deliberately **does not import them** — it reads
their source. That keeps the test runnable anywhere `palette.py` is, including
the docs workflow, which installs neither Pillow nor a browser.

What it guards is the one thing that can silently rot: the rasterisers must
draw their colours from `palette.py` and declare none of their own. That was the
original defect — three generators, three private palettes, one of them a live
WCAG AA failure.

These live in `brand/`, NOT in `tests/`, for the same reason `test_palette.py`
does: `tests` is on `FRAMEWORK_PATHS` and is copied into every derived instance,
which never receives `brand/`.

    python -m unittest brand.test_rasterisers      # from the repo root
"""

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from brand import palette  # noqa: E402

HERE = Path(__file__).resolve().parent

# The two scripts that need Chromium + Pillow and are never run in CI.
RASTERISERS = ("make_favicons.py", "render_diagrams.py")

# Any `#rgb`, `#rrggbb` or `#rrggbbaa` literal. A colour constant declared
# locally would match; `palette.brand_blue` cannot.
HEX_COLOUR = re.compile(r"#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\b")


def _source(name: str) -> str:
    return (HERE / name).read_text(encoding="utf-8")


class TestNoPrivatePalette(unittest.TestCase):
    def test_no_hex_colour_literal_anywhere(self):
        """Not one hex in either file — comments and docstrings included.

        Deliberately not scoped to code: a retired hex sitting in a comment is
        how the drift documented itself last time.
        """
        for name in RASTERISERS:
            with self.subTest(script=name):
                found = HEX_COLOUR.findall(_source(name))
                self.assertEqual(
                    [], found,
                    f"{name} declares its own colour(s) {found}; "
                    f"import them from brand.palette instead",
                )

    def test_imports_the_shared_palette(self):
        for name in RASTERISERS:
            with self.subTest(script=name):
                self.assertIn("from brand import palette", _source(name))

    def test_uses_palette_attributes(self):
        """A bare import that is never referenced would satisfy the check above."""
        for name in RASTERISERS:
            with self.subTest(script=name):
                self.assertRegex(_source(name), r"\bpalette\.\w+")


class TestFaviconColourMapping(unittest.TestCase):
    """The favicon tile is brand blue; the owl is paper white (spec §2)."""

    def test_tile_and_owl_bind_to_the_right_tokens(self):
        src = _source("make_favicons.py")
        self.assertIn("palette.brand_blue", src)
        self.assertIn("palette.paper", src)

    def test_committed_favicon_svg_matches_the_palette(self):
        """`favicons/favicon.svg` is a committed generator output, so its hexes
        must still be the palette's. Catches a palette edit that was never
        rasterised back into the committed set."""
        svg = (HERE / "favicons" / "favicon.svg").read_text(encoding="utf-8")
        self.assertIn(palette.brand_blue, svg)
        self.assertIn(palette.paper, svg)
        stray = set(HEX_COLOUR.findall(svg)) - {palette.brand_blue, palette.paper}
        self.assertEqual(set(), stray, f"favicon.svg carries off-palette hexes: {stray}")


class TestLocalOnlyIsDocumented(unittest.TestCase):
    """The 'not in CI' contract is load-bearing: these scripts are the only
    place the repo's stdlib-only rule is bent, and it is bent locally, on
    purpose. If the docstring stops saying so, someone will wire them into a
    workflow and add Pillow to a requirements file."""

    def test_docstring_states_the_contract(self):
        for name in RASTERISERS:
            with self.subTest(script=name):
                doc = _source(name).split('"""')[1].lower()
                for phrase in ("local-only", "not run in ci", "chromium", "pillow"):
                    self.assertIn(phrase, doc, f"{name} docstring omits {phrase!r}")


class TestChromeComesFromTheEnvironment(unittest.TestCase):
    def test_no_hardcoded_browser_path(self):
        for name in RASTERISERS:
            with self.subTest(script=name):
                src = _source(name)
                self.assertIn('os.environ.get("CHROME"', src)
                self.assertNotIn("/opt/pw-browsers", src)


if __name__ == "__main__":
    unittest.main()
