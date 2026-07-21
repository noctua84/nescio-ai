import tempfile
import unittest
from pathlib import Path

import wiki_lint


def _w(dir_path, fname, text):
    p = dir_path / fname
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


class TestLint(unittest.TestCase):
    def test_dangling_link(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _w(root, "a.md", "---\nname: a\ndescription: x\ntype: concept\n---\n[[nope]]\n")
            findings = wiki_lint.lint(root)
            self.assertTrue(any("dangling link [[nope]]" in f for f in findings))

    def test_missing_frontmatter(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _w(root, "a.md", "no frontmatter here\n")
            findings = wiki_lint.lint(root)
            self.assertTrue(any("missing frontmatter field 'name'" in f for f in findings))

    def test_orphan_and_resolved_link(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _w(root, "a.md", "---\nname: a\ndescription: x\ntype: concept\n---\n[[b]]\n")
            _w(root, "b.md", "---\nname: b\ndescription: y\ntype: concept\n---\nplain\n")
            findings = wiki_lint.lint(root)
            # a links to b, so b is not an orphan and [[b]] is not dangling;
            # a has no inbound link and is in no MEMORY.md -> orphan.
            self.assertFalse(any("dangling" in f for f in findings))
            self.assertTrue(any(f.endswith("a.md: orphan") or "a.md: orphan" in f for f in findings))
            self.assertFalse(any("b.md: orphan" in f for f in findings))

    def test_memory_reference_suppresses_orphan(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _w(root, "a.md", "---\nname: a\ndescription: x\ntype: concept\n---\nplain\n")
            _w(root, "MEMORY.md", "- [a](a.md) — x\n")
            findings = wiki_lint.lint(root)
            self.assertFalse(any("orphan" in f for f in findings))


if __name__ == "__main__":
    unittest.main()
