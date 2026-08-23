# tests/test_apply_theme.py
"""Round-trip and dry-run coverage for `scripts/apply_theme.py`.

The script renames agent files (functional <-> philosophers) and rewrites
cross-references in place, so the property worth pinning is that applying
both directions in sequence is a no-op — the tree returns exactly to what it
started as. Runs only against a temp copy; never against the real `agents/`.
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


def _tree_snapshot(agents_dir: Path) -> dict[str, str]:
    """Filename -> file contents, for comparing a tree before and after."""
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(agents_dir.glob("*.md"))}


class ApplyThemeRoundTripTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.agents_dir = Path(self._tmp.name) / "agents"
        self.agents_dir.mkdir()
        for src in AGENTS_DIR.glob("*.md"):
            (self.agents_dir / src.name).write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        self.original = _tree_snapshot(self.agents_dir)

    def tearDown(self):
        self._tmp.cleanup()

    def test_functional_to_philosophers_and_back_restores_the_tree(self):
        self.assertEqual(apply_theme.detect_theme(self.agents_dir), "functional")

        with contextlib.redirect_stdout(io.StringIO()):
            rc = apply_theme.apply_theme(self.agents_dir, "philosophers")
        self.assertEqual(rc, 0)
        self.assertEqual(apply_theme.detect_theme(self.agents_dir), "philosophers")

        themed_names = {p.name for p in self.agents_dir.glob("*.md")}
        for functional, philosopher in apply_theme.PAIRS:
            self.assertNotIn(f"{functional}.md", themed_names)
            self.assertIn(f"{philosopher}.md", themed_names)

        with contextlib.redirect_stdout(io.StringIO()):
            rc = apply_theme.apply_theme(self.agents_dir, "functional")
        self.assertEqual(rc, 0)
        self.assertEqual(apply_theme.detect_theme(self.agents_dir), "functional")

        self.assertEqual(_tree_snapshot(self.agents_dir), self.original)

    def test_reapplying_the_current_theme_is_a_noop(self):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            rc = apply_theme.apply_theme(self.agents_dir, "functional")
        self.assertEqual(rc, 0)
        self.assertIn("already on the 'functional' theme", out.getvalue())
        self.assertEqual(_tree_snapshot(self.agents_dir), self.original)

    def test_dry_run_reports_without_writing(self):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            rc = apply_theme.apply_theme(self.agents_dir, "philosophers", dry_run=True)
        self.assertEqual(rc, 0)
        self.assertIn("would rename builder.md -> archimedes.md", out.getvalue())
        # nothing on disk actually changed
        self.assertEqual(apply_theme.detect_theme(self.agents_dir), "functional")
        self.assertEqual(_tree_snapshot(self.agents_dir), self.original)


if __name__ == "__main__":
    unittest.main()
