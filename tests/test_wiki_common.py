# tests/test_wiki_common.py
import unittest
import _wiki_common as wc


class TestExtractWikilinks(unittest.TestCase):
    def test_plain_and_aliased_links(self):
        text = "See [[Concept A]] and [[repo/x|the note]] but not [single]."
        self.assertEqual(wc.extract_wikilinks(text), ["Concept A", "repo/x"])

    def test_no_links(self):
        self.assertEqual(wc.extract_wikilinks("nothing here"), [])


class TestSplitFrontmatter(unittest.TestCase):
    def test_scalars_and_body(self):
        text = "---\nname: foo\ndescription: a note\ntype: concept\n---\nBody line.\n"
        fm, body = wc.split_frontmatter(text)
        self.assertEqual(fm["name"], "foo")
        self.assertEqual(fm["description"], "a note")
        self.assertEqual(fm["type"], "concept")
        self.assertEqual(body, "Body line.\n")

    def test_list_field(self):
        text = "---\nname: foo\nseen_in:\n  - repo/x\n  - repo/y\n---\nb\n"
        fm, _ = wc.split_frontmatter(text)
        self.assertEqual(fm["seen_in"], ["repo/x", "repo/y"])

    def test_no_frontmatter(self):
        self.assertEqual(wc.split_frontmatter("just text"), ({}, "just text"))

    def test_unclosed_frontmatter(self):
        self.assertEqual(wc.split_frontmatter("---\nname: x\n"), ({}, "---\nname: x\n"))


import json
import tempfile
from pathlib import Path


class TestIterNotes(unittest.TestCase):
    def test_skips_index_and_dotdirs(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "a.md").write_text("---\nname: a\n---\nbody\n", encoding="utf-8")
            (root / "MEMORY.md").write_text("- index\n", encoding="utf-8")
            (root / ".obsidian").mkdir()
            (root / ".obsidian" / "x.md").write_text("hidden\n", encoding="utf-8")
            names = sorted(p.name for p, _, _ in wc.iter_notes(root))
            self.assertEqual(names, ["a.md"])


class TestLoadStores(unittest.TestCase):
    def test_absent_returns_empty(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(wc.load_stores(Path(d)), {})

    def test_reads_stores_key(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "stores.json").write_text(
                json.dumps({"stores": {"vault": {"path": "vault"}}}), encoding="utf-8"
            )
            self.assertEqual(wc.load_stores(root), {"vault": {"path": "vault"}})


if __name__ == "__main__":
    unittest.main()
