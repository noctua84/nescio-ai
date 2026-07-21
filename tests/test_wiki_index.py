import tempfile
import unittest
from pathlib import Path

import wiki_index


def _note(dir_path, fname, name, desc):
    (dir_path / fname).write_text(
        f"---\nname: {name}\ndescription: {desc}\ntype: concept\n---\nbody\n",
        encoding="utf-8",
    )


class TestBuildIndex(unittest.TestCase):
    def test_lines_from_frontmatter(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _note(root, "b.md", "beta", "second")
            _note(root, "a.md", "alpha", "first")
            self.assertEqual(
                wiki_index.build_index(root),
                "- [alpha](a.md) — first\n- [beta](b.md) — second\n",
            )


class TestRegenerate(unittest.TestCase):
    def test_check_flags_stale(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _note(root, "a.md", "alpha", "first")
            rc, _ = wiki_index.regenerate(root, check=True)
            self.assertEqual(rc, 1)

    def test_write_then_check_clean(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _note(root, "a.md", "alpha", "first")
            rc, _ = wiki_index.regenerate(root)
            self.assertEqual(rc, 0)
            self.assertEqual(
                (root / "MEMORY.md").read_text(encoding="utf-8"),
                "- [alpha](a.md) — first\n",
            )
            rc2, _ = wiki_index.regenerate(root, check=True)
            self.assertEqual(rc2, 0)


if __name__ == "__main__":
    unittest.main()
