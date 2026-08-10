# tests/test_wiki_lint.py
import argparse
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import wiki_index  # noqa: E402
import wiki_lint  # noqa: E402


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
            # A note (has a frontmatter block) missing the required 'name' field.
            _w(root, "a.md", "---\ndescription: x\ntype: concept\n---\nbody\n")
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

    def test_no_false_positives_on_non_notes(self):
        """Operational (non-note) files produce zero findings of their own."""
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            # A real note that is inbound-linked so it isn't an orphan.
            _w(root, "concept.md", "---\nname: concept\ndescription: c\ntype: concept\n---\nbody\n")
            _w(
                root,
                "hub.md",
                "---\nname: hub\ndescription: h\ntype: concept\n---\nsee [[concept]]\n",
            )
            _w(root, "MEMORY.md", "- [hub](hub.md) — h\n")
            # Operational files: no frontmatter; CONVENTIONS carries prose wikilinks.
            _w(root, "CONVENTIONS.md", "Operational notes.\n\n↑[[somenote]] is prose.\n")
            _w(root, "glossary.md", "# Glossary\n\nterms\n")
            _w(root, "readiness.md", "# Readiness\n\nchecklist\n")
            findings = wiki_lint.lint(root)
            op_files = {"CONVENTIONS.md", "glossary.md", "readiness.md"}
            offending = [
                f for f in findings if any(f.startswith(str(root / name)) for name in op_files)
            ]
            self.assertEqual(offending, [], f"non-note files were flagged: {offending}")
            # And the CONVENTIONS prose link must not dangle from anywhere.
            self.assertFalse(any("dangling link [[somenote]]" in f for f in findings))

    def test_real_note_missing_type_still_flagged(self):
        """A note WITH a frontmatter block but missing 'type' is still flagged."""
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _w(root, "a.md", "---\nname: a\ndescription: x\n---\nbody\n")
            findings = wiki_lint.lint(root)
            self.assertTrue(
                any("missing frontmatter field 'type'" in f for f in findings),
                f"expected missing-type finding, got: {findings}",
            )

    def test_link_to_non_note_does_not_dangle(self):
        """A note linking [[glossary]] (a non-note file that exists) is not dangling."""
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            _w(root, "glossary.md", "# Glossary\n\nterms\n")
            _w(
                root,
                "a.md",
                "---\nname: a\ndescription: x\ntype: concept\n---\nsee [[glossary]]\n",
            )
            findings = wiki_lint.lint(root)
            self.assertFalse(any("dangling" in f for f in findings), f"unexpected dangling: {findings}")


class TestResolveDirRobustness(unittest.TestCase):
    def test_wiki_lint_resolve_dir_missing_path(self):
        # A truthy store entry that lacks "path" must not raise KeyError.
        args = argparse.Namespace(dir=None, store="x")
        with mock.patch.object(wiki_lint, "load_stores", return_value={"x": {"name": "y"}}):
            self.assertIsNone(wiki_lint._resolve_dir(args))

    def test_wiki_index_resolve_dir_missing_path(self):
        args = argparse.Namespace(dir=None, store="x")
        with mock.patch.object(wiki_index, "load_stores", return_value={"x": {"name": "y"}}):
            self.assertIsNone(wiki_index._resolve_dir(args))


if __name__ == "__main__":
    unittest.main()
