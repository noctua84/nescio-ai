# brand/test_brand.py
"""Tests for the brand asset generator.

These live in `brand/`, NOT in `tests/`, on purpose. `tests` is on
`FRAMEWORK_PATHS` in `scripts/sync_from_upstream.py` and is copied into every
derived instance; `brand/` deliberately is not. A `tests/` module importing
`brand` would crash `python -m unittest` for every downstream user.

    python -m unittest brand.test_brand        # from the repo root

What is guarded here, in order of how much it would hurt to lose:

1. **The wordmark is outlined, not live text.** The whole point of task T7.
   A `<text>` wordmark renders in an arbitrary fallback on link-preview
   servers, which is where the social card spends its life.
2. **No colour literal survives in the module.** `brand/palette.py` is the
   single source of truth; a stray hex is drift by another name.
3. **The generator stays stdlib-only.** fontTools is local tooling for
   regenerating the outline, never a runtime import.
4. **The owl geometry is untouched.** The mark predates all of this.
"""

import re
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from brand import make_brand, palette  # noqa: E402

SOURCE = Path(make_brand.__file__).read_text(encoding="utf-8")

# `#rrggbb` / `#rgb`, but not the `#` of an XML numeric entity like `&#8220;`.
HEX_LITERAL = re.compile(r"(?<![&\w])#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?\b")

WORDMARKED = {"github-social": make_brand.social, "medium-cover": make_brand.cover}


def texts(svg):
    """Every `<text>` element in an SVG string, as (attrib, content) pairs."""
    return [(el.attrib, "".join(el.itertext()))
            for el in ET.fromstring(svg).iter("{http://www.w3.org/2000/svg}text")]


class TestWordmarkIsOutlined(unittest.TestCase):
    """T7's actual fix: the wordmark ships as `<path>`, everywhere it appears."""

    def test_no_text_element_carries_the_wordmark(self):
        for name, svg in WORDMARKED.items():
            with self.subTest(asset=name):
                for attrib, content in texts(svg):
                    # `github.com/noctua84/nescio-ai` legitimately contains the
                    # word; the wordmark is a text node that *is* the word.
                    self.assertNotEqual(
                        content.strip(), make_brand.WORDMARK_TEXT,
                        f"{name}: wordmark is still live text ({attrib})")

    def test_no_text_element_asks_for_a_mono_wordmark(self):
        """A wordmark set in mono is exactly the fallback bug being fixed."""
        for name, svg in WORDMARKED.items():
            with self.subTest(asset=name):
                for attrib, content in texts(svg):
                    if "mono" in attrib.get("font-family", "").lower():
                        # Remaining mono labels are fine; a *large* one is the
                        # wordmark by another name.
                        self.assertLess(float(attrib["font-size"]), 40, attrib)

    def test_the_outline_is_present_in_both_assets(self):
        for name, svg in WORDMARKED.items():
            with self.subTest(asset=name):
                self.assertIn(make_brand.WORDMARK_PATH, svg)

    def test_assets_are_well_formed_xml(self):
        for name, content in make_brand.ASSETS:
            with self.subTest(asset=name):
                ET.fromstring(content)


class TestWordmarkPathData(unittest.TestCase):
    """The baked outline must be real glyph geometry, not a stub."""

    def test_path_starts_with_a_moveto(self):
        self.assertTrue(make_brand.WORDMARK_PATH.startswith("M"))

    def test_path_has_one_closed_contour_per_letter_at_least(self):
        closes = make_brand.WORDMARK_PATH.count("Z")
        self.assertGreaterEqual(closes, len(make_brand.WORDMARK_TEXT),
                                "fewer closed contours than letters")

    def test_path_has_curves(self):
        """Six letters of a text face are not drawn in straight lines."""
        self.assertTrue(set("CQ") & set(make_brand.WORDMARK_PATH))

    def test_path_coordinates_span_the_full_advance(self):
        numbers = [int(n) for n in re.findall(r"-?\d+", make_brand.WORDMARK_PATH)]
        self.assertGreater(len(numbers), 200, "suspiciously few coordinates")
        # x runs the width of the word; nothing may sit outside the em box.
        self.assertGreater(max(numbers), make_brand.WORDMARK_ADVANCE * 0.9)
        self.assertLessEqual(max(numbers), make_brand.WORDMARK_ADVANCE)
        self.assertGreaterEqual(min(numbers), -make_brand.WORDMARK_UPM)

    def test_metrics_are_sane(self):
        self.assertEqual(make_brand.WORDMARK_UPM, 2048)
        self.assertGreater(make_brand.WORDMARK_ADVANCE, 0)

    def test_source_font_is_committed(self):
        """The outline is regenerable: the glyph source is version-controlled."""
        self.assertTrue(
            (Path(make_brand.__file__).parent / make_brand.WORDMARK_SOURCE).is_file())


class TestWordmarkLayout(unittest.TestCase):
    """`wordmark()` must land where the `<text>` element it replaced landed."""

    def test_width_is_the_advance_width(self):
        # Six monospaced glyphs; the live text occupied exactly this much.
        self.assertAlmostEqual(make_brand.wordmark_width(104), 7374 * 104 / 2048)

    def test_width_scales_linearly(self):
        self.assertAlmostEqual(make_brand.wordmark_width(152),
                               2 * make_brand.wordmark_width(76))

    def test_start_anchor_puts_the_origin_at_x(self):
        self.assertIn("translate(392,300)", make_brand.wordmark(392, 300, 104, "none"))

    def test_middle_anchor_centres_on_the_advance_width(self):
        out = make_brand.wordmark(750, 470, 76, "none", anchor="middle")
        offset = float(re.search(r"translate\((-?[\d.]+),", out).group(1))
        self.assertAlmostEqual(offset, 750 - make_brand.wordmark_width(76) / 2,
                               places=2)

    def test_end_anchor_ends_at_x(self):
        out = make_brand.wordmark(750, 470, 76, "none", anchor="end")
        offset = float(re.search(r"translate\((-?[\d.]+),", out).group(1))
        self.assertAlmostEqual(offset + make_brand.wordmark_width(76), 750, places=2)

    def test_y_flip_is_applied(self):
        """Font units point up; SVG points down. Without the flip it renders
        upside down and nothing else in the file would notice."""
        out = make_brand.wordmark(0, 0, 104, "none")
        sx, sy = re.search(r"scale\((-?[\d.]+),(-?[\d.]+)\)", out).groups()
        self.assertGreater(float(sx), 0)
        self.assertLess(float(sy), 0)
        self.assertAlmostEqual(float(sx), -float(sy))


class TestNoColourLiterals(unittest.TestCase):
    """Every colour resolves through `brand.palette` — that is why it exists."""

    def test_module_source_has_no_hex_literal(self):
        found = HEX_LITERAL.findall(SOURCE)
        self.assertEqual(found, [], f"colour literals left in make_brand.py: {found}")

    def test_generated_svgs_use_only_palette_values(self):
        allowed = {v.lower() for v in palette.TOKENS.values()}
        for name, content in make_brand.ASSETS:
            for colour in re.findall(r'(?:fill|stroke)="(#[0-9a-fA-F]+)"', content):
                with self.subTest(asset=name, colour=colour):
                    self.assertIn(colour.lower(), allowed)

    def test_retired_hexes_are_gone(self):
        for retired in ("#8a919b", "#111418"):
            self.assertNotIn(retired, SOURCE.lower())
            for name, content in make_brand.ASSETS:
                with self.subTest(asset=name, hex=retired):
                    self.assertNotIn(retired, content.lower())

    def test_fonts_come_from_the_palette(self):
        self.assertEqual(make_brand.FONT, palette.FONT_SANS)
        self.assertEqual(make_brand.MONO, palette.FONT_MONO)

    def test_running_text_defaults_to_the_sans(self):
        self.assertIn(palette.FONT_SANS, make_brand.text(0, 0, "x"))


class TestStdlibOnly(unittest.TestCase):
    """`python brand/make_brand.py` must run in CI with nothing installed."""

    def test_importing_the_module_does_not_pull_in_fonttools(self):
        self.assertNotIn("fontTools", sys.modules)

    def test_fonttools_is_never_imported_at_module_level(self):
        for line in SOURCE.splitlines():
            if "fontTools" in line and line.lstrip().startswith(("import ", "from ")):
                self.assertTrue(line.startswith((" ", "\t")),
                                f"fontTools imported at module level: {line!r}")

    def test_running_the_script_writes_all_five_assets(self):
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(
                [sys.executable, str(Path(make_brand.__file__)), "--out", tmp],
                check=True, capture_output=True)
            written = sorted(p.name for p in Path(tmp).glob("*.svg"))
        self.assertEqual(written, sorted(
            f"nescio-{name}.svg" for name, _ in make_brand.ASSETS))
        self.assertEqual(len(written), 5)


class TestOwlGeometryUntouched(unittest.TestCase):
    """T7 changes colour and type. The mark itself is not in scope."""

    HEAD_START = "M 140 112 C 160 168 176 176 186 186"

    def test_head_outline_is_unchanged(self):
        self.assertIn(self.HEAD_START, make_brand.owl())

    def test_mark_still_has_two_eyes_two_pupils_and_a_beak(self):
        root = ET.fromstring(make_brand.mark)
        ns = "{http://www.w3.org/2000/svg}"
        self.assertEqual(len(root.findall(f".//{ns}circle")), 4)
        self.assertEqual(len(root.findall(f".//{ns}path")), 2)

    def test_size_sheet_still_covers_the_avatar_sizes(self):
        for px in (128, 64, 48, 32, 24, 16):
            self.assertIn(f">{px}px<", make_brand.sheet)


if __name__ == "__main__":
    unittest.main()
