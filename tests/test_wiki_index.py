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
            index = root / "MEMORY.md"
            # The generated bullet now lives inside the owned block rather than
            # being the whole file, so assert containment plus both markers.
            written = index.read_text(encoding="utf-8", newline="")
            self.assertIn("- [alpha](a.md) — first", written)
            self.assertIn(wiki_index.GENERATED_BEGIN, written)
            self.assertIn(wiki_index.GENERATED_END, written)
            rc2, _ = wiki_index.regenerate(root, check=True)
            self.assertEqual(rc2, 0)
            # Idempotency on bytes — a read_text comparison would normalise away
            # a CRLF regression (#83/#84).
            before = index.read_bytes()
            rc3, _ = wiki_index.regenerate(root)
            self.assertEqual(rc3, 0)
            self.assertEqual(index.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
