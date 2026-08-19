# brand/test_palette.py
"""Tests for the canonical palette.

These live in `brand/`, NOT in `tests/`, on purpose. `tests` is on
`FRAMEWORK_PATHS` in `scripts/sync_from_upstream.py` and is copied into every
derived instance; `brand/` deliberately is not. A `tests/` module importing
`brand` would crash `python -m unittest` for every downstream user.

    python -m unittest brand.test_palette      # from the repo root
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from brand import palette  # noqa: E402

# Hexes retired by spec §2. `#8a919b` failed WCAG AA on white (3.2:1) while
# carrying every caption and connector label in both architecture diagrams;
# `#111418` was a second near-black doing the same job as `#16191f`.
RETIRED = ("#8a919b", "#111418")


class TestTokens(unittest.TestCase):
    def test_muted_is_the_accessible_grey(self):
        self.assertEqual(palette.muted, "#6b727c")

    def test_muted_passes_aa_on_paper(self):
        """The AA floor this whole package exists to hold."""
        self.assertGreaterEqual(
            palette.contrast_ratio(palette.muted, palette.paper), 4.5
        )

    def test_retired_hexes_are_absent(self):
        for retired in RETIRED:
            for name, value in palette.TOKENS.items():
                self.assertNotEqual(
                    value.lower(), retired, f"retired hex {retired} resurfaced as {name}"
                )

    def test_tokens_dict_matches_module_constants(self):
        for name, value in palette.TOKENS.items():
            self.assertEqual(getattr(palette, name), value)

    def test_tokens_are_lowercase_six_digit_hex(self):
        for name, value in palette.TOKENS.items():
            with self.subTest(token=name):
                self.assertRegex(value, r"^#[0-9a-f]{6}$")

    def test_expected_tokens_present(self):
        expected = {
            "ink_deep", "ink_raised", "brand_blue", "periwinkle", "tint",
            "tint_dark", "text", "text_dark", "body", "muted", "muted_dark",
            "border", "border_dark", "deferred", "paper",
        }
        self.assertEqual(set(palette.TOKENS), expected)

    def test_no_two_tokens_share_a_value(self):
        """Drift shows up as duplicates; the canonical set has none."""
        self.assertEqual(len(set(palette.TOKENS.values())), len(palette.TOKENS))


class TestFonts(unittest.TestCase):
    def test_self_hosted_faces_are_named_first(self):
        """The shipped subsets carry these internal names, so the stacks must
        ask for them first or every SVG falls through to a system face.
        `brand/test_fonts.py` ties them back to the build recipe."""
        self.assertTrue(palette.FONT_SANS.startswith("'Nescio Sans'"))
        self.assertTrue(palette.FONT_MONO.startswith("'Nescio Mono'"))

    def test_upstream_faces_follow_as_fallbacks(self):
        """A standalone SVG on a machine with the originals installed still
        renders in the right face."""
        self.assertIn("Carlito", palette.FONT_SANS)
        self.assertIn("'Liberation Mono'", palette.FONT_MONO)

    def test_generic_fallbacks_are_present(self):
        self.assertTrue(palette.FONT_SANS.rstrip().endswith("sans-serif"))
        self.assertTrue(palette.FONT_MONO.rstrip().endswith("monospace"))

    def test_stacks_are_safe_inside_an_svg_attribute(self):
        """These land in `font-family="..."`; a double quote would end it."""
        for name in ("FONT_SANS", "FONT_MONO"):
            with self.subTest(constant=name):
                self.assertNotIn('"', getattr(palette, name))


class TestContrastRatio(unittest.TestCase):
    """Validates `contrast_ratio` itself against the table in spec §2."""

    # (fg, bg, documented ratio)
    SPEC_TABLE = [
        ("#8fb0d9", "#0e1319", 8.3),
        ("#8fb0d9", "#ffffff", 2.2),
        ("#2f4d7a", "#ffffff", 8.5),
        ("#5a616b", "#ffffff", 6.3),
        ("#6b727c", "#ffffff", 4.9),
        ("#8a919b", "#ffffff", 3.2),
        ("#8d97a4", "#0e1319", 6.3),
    ]

    def test_matches_spec_table(self):
        for fg, bg, documented in self.SPEC_TABLE:
            with self.subTest(fg=fg, bg=bg):
                self.assertAlmostEqual(
                    palette.contrast_ratio(fg, bg), documented, delta=0.05
                )

    def test_identical_colours_are_one_to_one(self):
        self.assertAlmostEqual(palette.contrast_ratio("#6b727c", "#6b727c"), 1.0)

    def test_black_on_white_is_twenty_one(self):
        self.assertAlmostEqual(palette.contrast_ratio("#000000", "#ffffff"), 21.0)

    def test_symmetric(self):
        self.assertAlmostEqual(
            palette.contrast_ratio(palette.muted, palette.paper),
            palette.contrast_ratio(palette.paper, palette.muted),
        )

    def test_accepts_shorthand_and_bare_hex(self):
        self.assertAlmostEqual(
            palette.contrast_ratio("#fff", "#000"),
            palette.contrast_ratio("ffffff", "000000"),
        )

    def test_rejects_malformed_hex(self):
        for bad in ("#ggghhh", "#12345", "", "rgb(0,0,0)"):
            with self.subTest(value=bad):
                with self.assertRaises(ValueError):
                    palette.contrast_ratio(bad, palette.paper)


class TestAccentRule(unittest.TestCase):
    """Spec §2: periwinkle carries dark mode, brand blue carries light mode."""

    def test_periwinkle_fails_aa_on_paper(self):
        self.assertLess(
            palette.contrast_ratio(palette.periwinkle, palette.paper), 4.5
        )
        self.assertFalse(palette.passes_aa(palette.periwinkle, palette.paper))

    def test_periwinkle_passes_aaa_on_ink_deep(self):
        self.assertGreaterEqual(
            palette.contrast_ratio(palette.periwinkle, palette.ink_deep), 7.0
        )

    def test_brand_blue_passes_aaa_on_paper(self):
        self.assertGreaterEqual(
            palette.contrast_ratio(palette.brand_blue, palette.paper), 7.0
        )

    def test_light_text_tokens_pass_aa_on_paper(self):
        for name in ("text", "body", "muted"):
            with self.subTest(token=name):
                self.assertTrue(palette.passes_aa(palette.TOKENS[name], palette.paper))

    def test_dark_text_tokens_pass_aa_on_ink_deep(self):
        for name in ("periwinkle", "text_dark", "muted_dark", "deferred"):
            with self.subTest(token=name):
                self.assertTrue(
                    palette.passes_aa(palette.TOKENS[name], palette.ink_deep)
                )


if __name__ == "__main__":
    unittest.main()
