"""Guard the committed self-hosted web faces in ``brand/fonts/``.

**Stdlib only.** ``fonttools`` is local-only tooling for *building* the
subsets; it must never become a dependency of running the test suite. So this
module parses the woff2 header itself — it is 48 fixed bytes, fully specified
by the W3C WOFF2 recommendation, and enough to prove a file is a real woff2
carrying a real font rather than something with the right extension.

Deep verification (glyph coverage, name table, OpenType tables) lives in
``brand/subset_fonts.py --verify``, which may use fontTools because it is not
part of the suite.

Lives in ``brand/`` rather than ``tests/`` for the reason spelled out in
``brand/README.md``: ``tests/`` is on ``FRAMEWORK_PATHS`` and syncs into
derived instances that never receive ``brand/``.

Run from the repo root::

    python -m unittest brand.test_fonts
"""

from __future__ import annotations

import re
import struct
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from brand import palette  # noqa: E402

FONTS = Path(__file__).resolve().parent / "fonts"

#: subset -> the source .ttf it is cut from
SUBSETS = {
    "nescio-mono-400.woff2": "LiberationMono-Regular.ttf",
    "nescio-mono-700.woff2": "LiberationMono-Bold.ttf",
    "nescio-sans-400.woff2": "Carlito-Regular.ttf",
    "nescio-sans-700.woff2": "Carlito-Bold.ttf",
}

#: One OFL text per face — an OFL font may not be redistributed without it.
LICENCES = (
    "LiberationMono-LICENSE.txt",
    "Carlito-LICENSE.txt",
)

#: Upstream attribution shipped alongside, not itself a licence.
CREDITS = ("LiberationMono-AUTHORS.txt",)

#: The internal family names the subsets carry, keyed by the ``palette``
#: constant whose stack must name them first.
#:
#: **Hardcoded on purpose.** Reading the real ``name`` table out of a ``woff2``
#: means brotli-decompressing the sfnt payload, and neither ``brotli`` nor
#: ``fontTools`` is in the stdlib or a repo dependency — see this module's
#: docstring. So the literals below are cross-checked two ways instead, and
#: both checks are stdlib-only:
#:
#: 1. against the ``FACES`` table in ``brand/subset_fonts.py``, which is the
#:    recipe that wrote those name records (``_rename``); and
#: 2. against ``brand/fonts/README.md``, which documents them for CSS authors.
#:
#: The binaries themselves are checked against ``FACES`` by
#: ``python brand/subset_fonts.py --verify``, which may use fontTools because
#: it is not part of this suite.
EXPECTED_FAMILIES = {
    "FONT_MONO": "Nescio Mono",
    "FONT_SANS": "Nescio Sans",
}


def _faces_table() -> list[tuple[str, str]]:
    """(woff2 filename, family) parsed out of ``subset_fonts.py``'s FACES."""
    script = (FONTS.parent / "subset_fonts.py").read_text(encoding="utf-8")
    block = script.split("FACES = (", 1)[1].split("\n)", 1)[0]
    rows = re.findall(
        r'\(\s*"[^"]+\.ttf"\s*,\s*"([^"]+\.woff2)"\s*,\s*"([^"]+)"', block
    )
    return [(out, family) for out, family in rows]


def _first_family(stack: str) -> str:
    """The first family named by a CSS ``font-family`` stack, unquoted."""
    return stack.split(",", 1)[0].strip().strip("'\"")

#: WOFF2 header: signature, flavor, length, numTables, reserved, totalSfntSize,
#: totalCompressedSize, majorVersion, minorVersion, metaOffset, metaLength,
#: metaOrigLength, privOffset, privLength.
_WOFF2_HEADER = struct.Struct(">4sIIHHIIHHIIIII")


def _woff2_header(path: Path) -> dict[str, int | bytes]:
    raw = path.read_bytes()[: _WOFF2_HEADER.size]
    fields = _WOFF2_HEADER.unpack(raw)
    keys = (
        "signature",
        "flavor",
        "length",
        "num_tables",
        "reserved",
        "total_sfnt_size",
        "total_compressed_size",
        "major_version",
        "minor_version",
        "meta_offset",
        "meta_length",
        "meta_orig_length",
        "priv_offset",
        "priv_length",
    )
    return dict(zip(keys, fields))


class SubsetFontsTest(unittest.TestCase):
    """The four ``woff2`` files the documentation site serves."""

    def test_every_subset_is_present(self) -> None:
        for name in SUBSETS:
            with self.subTest(font=name):
                self.assertTrue((FONTS / name).is_file(), f"missing {name}")

    def test_every_subset_is_really_woff2(self) -> None:
        """Not just the extension — parse the header and check it is coherent."""
        for name in SUBSETS:
            with self.subTest(font=name):
                path = FONTS / name
                head = _woff2_header(path)
                self.assertEqual(head["signature"], b"wOF2", "bad woff2 signature")
                # TrueType outlines: sfnt version 0x00010000.
                self.assertEqual(head["flavor"], 0x00010000, "not a TrueType-flavoured font")
                self.assertEqual(
                    head["length"],
                    path.stat().st_size,
                    "header length disagrees with the file size — truncated?",
                )
                self.assertEqual(head["reserved"], 0, "reserved field must be zero")
                self.assertGreater(head["num_tables"], 10, "implausibly few sfnt tables")
                self.assertGreater(
                    head["total_sfnt_size"],
                    path.stat().st_size,
                    "decompressed font should be larger than the woff2",
                )

    def test_subset_is_smaller_than_its_source(self) -> None:
        for subset, source in SUBSETS.items():
            with self.subTest(font=subset):
                sub = (FONTS / subset).stat().st_size
                src = (FONTS / source).stat().st_size
                self.assertLess(
                    sub,
                    src // 4,
                    f"{subset} ({sub:,} B) is not meaningfully smaller than "
                    f"{source} ({src:,} B) — did the subset actually run?",
                )

    def test_source_ttfs_are_committed(self) -> None:
        """T7 outlines the wordmark from these; they are not disposable."""
        for source in set(SUBSETS.values()):
            with self.subTest(font=source):
                path = FONTS / source
                self.assertTrue(path.is_file(), f"missing source {source}")
                self.assertEqual(
                    path.read_bytes()[:4],
                    b"\x00\x01\x00\x00",
                    "source is not a TrueType sfnt",
                )

    def test_licence_text_ships_with_every_face(self) -> None:
        for name in LICENCES:
            with self.subTest(licence=name):
                text = (FONTS / name).read_text(encoding="utf-8")
                self.assertIn("SIL OPEN FONT LICENSE", text.upper())
        for name in CREDITS:
            with self.subTest(credits=name):
                self.assertTrue((FONTS / name).is_file(), f"missing {name}")

    def test_readme_documents_the_recipe(self) -> None:
        """A file nobody can rebuild is a binary blob, not an asset."""
        readme = (FONTS / "README.md").read_text(encoding="utf-8")
        self.assertIn("fontTools.subset", readme)
        self.assertIn("--flavor=woff2", readme)
        for name in SUBSETS:
            self.assertIn(name, readme, f"{name} is undocumented")

    def test_readme_unicode_ranges_match_the_build_script(self) -> None:
        """The documented range list must not drift from the one that ran."""
        script = (FONTS.parent / "subset_fonts.py").read_text(encoding="utf-8")
        block = script.split("UNICODE_RANGES = (", 1)[1].split("\n)", 1)[0]
        ranges = re.findall(r'"(U\+[0-9A-F]{4}-[0-9A-F]{4})"', block)
        self.assertGreater(len(ranges), 5, "could not parse UNICODE_RANGES")
        readme = (FONTS / "README.md").read_text(encoding="utf-8")
        documented = readme.split("--unicodes=", 1)[1].split(" ", 1)[0].rstrip("\\").strip()
        self.assertEqual(documented, ",".join(ranges))


class PaletteMatchesShippedFacesTest(unittest.TestCase):
    """The palette's stacks must name the families the ``woff2`` files carry.

    This is the integration seam: the site serves ``@font-face { font-family:
    "Nescio Mono" }`` while every generated SVG asks for whatever
    ``palette.FONT_MONO`` names first. If the two drift apart nothing errors —
    the diagrams just quietly render in a system fallback with the suite green.
    """

    def test_palette_records_the_subset_family_names(self) -> None:
        self.assertEqual(palette.SUBSET_FAMILY_MONO, EXPECTED_FAMILIES["FONT_MONO"])
        self.assertEqual(palette.SUBSET_FAMILY_SANS, EXPECTED_FAMILIES["FONT_SANS"])

    def test_expected_families_match_the_build_script(self) -> None:
        """``EXPECTED_FAMILIES`` cannot drift from the recipe that renamed them."""
        faces = _faces_table()
        self.assertEqual(len(faces), len(SUBSETS), "could not parse FACES")
        by_output = dict(faces)
        self.assertEqual(set(by_output), set(SUBSETS), "FACES/SUBSETS disagree")
        for out, family in faces:
            with self.subTest(font=out):
                key = "FONT_MONO" if "mono" in out else "FONT_SANS"
                self.assertEqual(family, EXPECTED_FAMILIES[key])

    def test_palette_stacks_name_the_shipped_family_first(self) -> None:
        for const, family in EXPECTED_FAMILIES.items():
            with self.subTest(constant=const):
                self.assertEqual(_first_family(getattr(palette, const)), family)

    def test_upstream_names_survive_as_fallbacks(self) -> None:
        """A standalone SVG on a machine with the real faces must still work."""
        self.assertIn("Carlito", palette.FONT_SANS)
        self.assertIn("'Liberation Mono'", palette.FONT_MONO)

    def test_stacks_use_single_quotes_only(self) -> None:
        """These strings go inside SVG ``font-family="..."`` — a double quote
        there closes the attribute and produces malformed XML."""
        for const in EXPECTED_FAMILIES:
            with self.subTest(constant=const):
                self.assertNotIn('"', getattr(palette, const))

    def test_readme_documents_the_family_names(self) -> None:
        readme = (FONTS / "README.md").read_text(encoding="utf-8")
        for family in EXPECTED_FAMILIES.values():
            self.assertIn(family, readme, f"{family} is undocumented")


if __name__ == "__main__":
    unittest.main()
