# brand/test_favicons.py
"""Regression guard for the committed `brand/favicons/` binaries.

These live in `brand/`, NOT in `tests/`, on purpose. `tests` is on
`FRAMEWORK_PATHS` in `scripts/sync_from_upstream.py` and is copied into every
derived instance; `brand/` deliberately is not. A `tests/` module importing
`brand` would crash `python -m unittest` for every downstream user.

    python -m unittest brand.test_favicons     # from the repo root

The defect this exists to catch: the first committed set was rendered in a
sandbox that lost the paint race `make_favicons.py`'s own comment warns about,
and shipped **clipped at the bottom** — 27 unpainted rows on `favicon-512.png`,
7 on `apple-touch-icon.png`. Nothing caught it, because a truncated PNG is a
perfectly valid PNG of the right dimensions.

A correct tile always paints its bottom row: with a rounded corner the row is
white at the ends and brand blue across the middle, and with square corners
(the Apple icon) it is brand blue end to end. So *every pixel of the bottom row
being unpainted* is only ever the paint race, never the artwork.

The dimension check is stdlib (PNG IHDR) and runs everywhere. The pixel check
needs Pillow, which is **not a repo dependency** — `make_favicons.py` is
local-only for exactly that reason — so it skips rather than failing when
Pillow is absent.
"""

import struct
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from brand import palette  # noqa: E402

try:
    from PIL import Image
except ImportError:  # Pillow is local-only; CI installs neither it nor Chromium.
    Image = None

FAVICONS = Path(__file__).resolve().parent / "favicons"

# The committed set, as documented in `favicons/README.md`.
EXPECTED_SIZES = {
    "favicon-16.png": 16,
    "favicon-32.png": 32,
    "favicon-48.png": 48,
    "favicon-192.png": 192,
    "favicon-512.png": 512,
    "apple-touch-icon.png": 180,
}

_PAPER = tuple(int(palette.paper.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))


def _png_size(path: Path) -> tuple[int, int]:
    """(width, height) from the PNG IHDR chunk. Stdlib only."""
    header = path.read_bytes()[:24]
    if header[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"{path.name} is not a PNG")
    return struct.unpack(">II", header[16:24])


def _blank_bottom_rows(path: Path) -> int:
    """Count trailing rows in which every pixel is unpainted.

    "Unpainted" means fully transparent, or the paper white the headless page
    ground flattens to. Counts up from the last row and stops at the first row
    carrying any tile colour.
    """
    im = Image.open(path).convert("RGBA")
    width, height = im.size
    px = im.load()
    blank = 0
    for y in range(height - 1, -1, -1):
        row = (px[x, y] for x in range(width))
        if all(p[3] == 0 or p[:3] == _PAPER for p in row):
            blank += 1
        else:
            break
    return blank


class TestCommittedSetIsComplete(unittest.TestCase):
    def test_every_expected_file_is_present(self):
        for name in EXPECTED_SIZES:
            with self.subTest(favicon=name):
                self.assertTrue((FAVICONS / name).is_file(), f"{name} is missing")

    def test_dimensions_are_square_and_as_documented(self):
        for name, size in EXPECTED_SIZES.items():
            with self.subTest(favicon=name):
                self.assertEqual((size, size), _png_size(FAVICONS / name))


@unittest.skipUnless(Image is not None, "Pillow is not installed (local-only)")
class TestNoTruncatedRender(unittest.TestCase):
    """The paint-race guard. See the module docstring for the shipped defect."""

    def test_no_favicon_png_has_blank_bottom_rows(self):
        for path in sorted(FAVICONS.glob("*.png")):
            with self.subTest(favicon=path.name):
                blank = _blank_bottom_rows(path)
                self.assertEqual(
                    0, blank,
                    f"{path.name} has {blank} unpainted bottom row(s) — the "
                    f"render lost the paint race; re-run make_favicons.py and "
                    f"copy the result over brand/favicons/",
                )


if __name__ == "__main__":
    unittest.main()
