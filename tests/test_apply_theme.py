# tests/test_apply_theme.py
"""Round-trip and dry-run coverage for `scripts/apply_theme.py`.

The script renames agent files (functional <-> philosophers) and rewrites
cross-references in place, so the property worth pinning is that applying
both directions in sequence is a no-op — the tree returns exactly to what it
started as. Runs only against a temp copy; never against the real `agents/`.

The temp copy is seeded from the real `agents/`, and these tests ship to
instances that may already be themed. So the starting theme is *detected*, not
assumed, and every expectation (rename direction, no-op message, dry-run
report) is derived from it. The property under test is unchanged: the tests
still round-trip a real crew through the other theme and back and demand a
byte-for-byte restore — only the direction is now read off the tree.
"""

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import apply_theme  # noqa: E402

AGENTS_DIR = ROOT / "agents"


def _tree_snapshot(agents_dir: Path) -> dict[str, bytes]:
    """Filename -> raw file bytes, for comparing a tree before and after.

    Bytes, not text: `read_text` normalises line endings on the way in, which
    would make the round-trip comparison blind to the rewrite changing them.
    """
    return {p.name: p.read_bytes() for p in sorted(agents_dir.glob("*.md"))}


def _other_theme(theme: str) -> str:
    """The theme that is not `theme`."""
    return next(t for t in apply_theme.THEMES if t != theme)


def _expected_renames(target: str) -> list[tuple[str, str]]:
    """(src, dst) filenames apply_theme renames when switching to `target`."""
    if target == "philosophers":
        return [(f"{f}.md", f"{p}.md") for f, p in apply_theme.PAIRS]
    return [(f"{p}.md", f"{f}.md") for f, p in apply_theme.PAIRS]


class ApplyThemeRoundTripTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.agents_dir = Path(self._tmp.name) / "agents"
        self.agents_dir.mkdir()
        for src in AGENTS_DIR.glob("*.md"):
            (self.agents_dir / src.name).write_bytes(src.read_bytes())
        self.original = _tree_snapshot(self.agents_dir)
        self.start = apply_theme.detect_theme(self.agents_dir)
        self.assertIn(self.start, apply_theme.THEMES,
                      "could not detect a theme in the seeded agents/ copy")
        self.other = _other_theme(self.start)

    def tearDown(self):
        self._tmp.cleanup()

    def test_switching_to_the_other_theme_and_back_restores_the_tree(self):
        with contextlib.redirect_stdout(io.StringIO()):
            rc = apply_theme.apply_theme(self.agents_dir, self.other)
        self.assertEqual(rc, 0)
        self.assertEqual(apply_theme.detect_theme(self.agents_dir), self.other)

        switched_names = {p.name for p in self.agents_dir.glob("*.md")}
        for src, dst in _expected_renames(self.other):
            self.assertNotIn(src, switched_names)
            self.assertIn(dst, switched_names)
        # The outbound leg must actually have rewritten content, otherwise the
        # restore below would be vacuously true.
        self.assertNotEqual(_tree_snapshot(self.agents_dir), self.original)

        with contextlib.redirect_stdout(io.StringIO()):
            rc = apply_theme.apply_theme(self.agents_dir, self.start)
        self.assertEqual(rc, 0)
        self.assertEqual(apply_theme.detect_theme(self.agents_dir), self.start)

        self.assertEqual(_tree_snapshot(self.agents_dir), self.original)

    def test_line_endings_survive_the_round_trip(self):
        """Regression: the rewrite must not normalise line endings.

        `Path.write_text` expands "\\n" to os.linesep, so on Windows every
        rewritten charter came back as CRLF — dirtying a tree `.gitattributes`
        pins to `eol=lf`. os.linesep is "\\n" on Linux CI, so the bug is
        invisible there unless the fixture supplies CRLF explicitly.
        """
        for p in self.agents_dir.glob("*.md"):
            p.write_bytes(p.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
        crlf = _tree_snapshot(self.agents_dir)

        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(apply_theme.apply_theme(self.agents_dir, self.other), 0)
        for name, body in _tree_snapshot(self.agents_dir).items():
            with self.subTest(agent=name):
                self.assertNotIn(b"\n", body.replace(b"\r\n", b""),
                                 f"{name}: line endings were rewritten to LF")

        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(apply_theme.apply_theme(self.agents_dir, self.start), 0)
        self.assertEqual(_tree_snapshot(self.agents_dir), crlf)

    def test_reapplying_the_current_theme_is_a_noop(self):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            rc = apply_theme.apply_theme(self.agents_dir, self.start)
        self.assertEqual(rc, 0)
        self.assertIn(f"already on the '{self.start}' theme", out.getvalue())
        self.assertEqual(_tree_snapshot(self.agents_dir), self.original)

    def test_dry_run_reports_without_writing(self):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            rc = apply_theme.apply_theme(self.agents_dir, self.other, dry_run=True)
        self.assertEqual(rc, 0)
        report = out.getvalue()
        for src, dst in _expected_renames(self.other):
            self.assertIn(f"would rename {src} -> {dst}", report)
        # nothing on disk actually changed
        self.assertEqual(apply_theme.detect_theme(self.agents_dir), self.start)
        self.assertEqual(_tree_snapshot(self.agents_dir), self.original)


if __name__ == "__main__":
    unittest.main()
