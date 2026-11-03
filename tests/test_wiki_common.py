# tests/test_wiki_common.py
import argparse
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import _wiki_common as wc  # noqa: E402
import yaml  # noqa: E402


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


class TestResolveDir(unittest.TestCase):
    """What ``resolve_dir`` returns, against the contract in its docstring.

    The two tests in ``tests/test_wiki_lint.py`` pin a different claim — that
    both CLI modules re-export this function — and between them reach only the
    "store entry exists but has no path" branch. Tracing the suite showed the
    three branches below were never executed at all: the ``--dir`` arm, the
    store-absent arm, and the arm that actually resolves a store's path. They
    had been verified by hand only.

    ``REPO_DIR`` and ``load_stores`` are patched on ``_wiki_common`` because
    that is where ``resolve_dir``'s body looks both up at call time — the same
    object ``wiki_index`` and ``wiki_lint`` re-export.
    """

    def test_dir_resolves_against_the_repo_root(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d).resolve()
            args = argparse.Namespace(dir="vault", store=None)
            with mock.patch.object(wc, "REPO_DIR", root):
                self.assertEqual(wc.resolve_dir(args), root / "vault")

    def test_dir_wins_over_store_without_reading_stores_json(self):
        """The docstring's first clause. stores.json must not even be consulted."""

        def boom(*a, **k):
            raise AssertionError("load_stores called despite --dir")

        with tempfile.TemporaryDirectory() as d:
            root = Path(d).resolve()
            args = argparse.Namespace(dir="from-dir", store="from-store")
            with mock.patch.object(wc, "REPO_DIR", root),                     mock.patch.object(wc, "load_stores", boom):
                self.assertEqual(wc.resolve_dir(args), root / "from-dir")

    def test_store_path_resolves_against_the_repo_root(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d).resolve()
            args = argparse.Namespace(dir=None, store="vault")
            with mock.patch.object(wc, "REPO_DIR", root),                     mock.patch.object(
                        wc, "load_stores", lambda *a, **k: {"vault": {"path": "vault/notes"}}
                    ):
                self.assertEqual(wc.resolve_dir(args), root / "vault" / "notes")

    def test_store_absent_from_stores_json_returns_none(self):
        args = argparse.Namespace(dir=None, store="nope")
        with mock.patch.object(wc, "load_stores", lambda *a, **k: {}):
            self.assertIsNone(wc.resolve_dir(args))


class TestYamlScalar(unittest.TestCase):
    """`yaml_scalar` is the writer half of `split_frontmatter`'s reader."""

    MUST_QUOTE = [
        "a: b", "ends with:", "has #hash", "- dash", "? q", ": c", ", c", "[x]", "{x}",
        "# c", "&a", "*a", "!t", "| p", "> g", "'s", '"d', "%p", "@a", "`b", " lead",
        "trail ", "", "yes", "No", "TRUE", "false", "null", "~", "On", "OFF", "y", "N",
        "1", "-1", "+1", "1.5", ".5", "1e3", "1_000", "0x1F", "0o17", "1:30", ".inf",
        "-.INF", ".nan", "2026-07-12", "=", "<<", "multi\nline", "tab\there", 'q: "x" \\ y',
        "nul\x00", "bell\x07",
    ]
    STAY_PLAIN = [
        "feedback-sample-learning", "A one-line description.", "uses a:no space",
        "path/to/x.md", "mid#no-space", "see [[link]] here", "a-b", "1password",
        "naive — em dash", "nescio-ai", 'say "hi"', "a\\b", "e.g. a, b, and c",
    ]

    def test_must_quote_values_round_trip_through_yaml_and_split_frontmatter(self):
        for v in self.MUST_QUOTE:
            with self.subTest(v=v):
                out = wc.yaml_scalar(v)
                self.assertTrue(out.startswith('"') and out.endswith('"'), out)
                self.assertEqual(yaml.safe_load(f"k: {out}\n"), {"k": v})
                fm, _ = wc.split_frontmatter(f"---\nk: {out}\n---\nbody\n")
                self.assertEqual(fm["k"], v)

    def test_safe_values_are_emitted_verbatim_and_still_parse(self):
        for v in self.STAY_PLAIN:
            with self.subTest(v=v):
                self.assertEqual(wc.yaml_scalar(v), v)
                self.assertEqual(yaml.safe_load(f"k: {v}\n"), {"k": v})

    def test_split_frontmatter_leaves_plain_values_untouched(self):
        fm, _ = wc.split_frontmatter(
            "---\nname: it's fine\ndescription: a \"x\" y\n---\nb\n"
        )
        self.assertEqual(fm["name"], "it's fine")
        self.assertEqual(fm["description"], 'a "x" y')

    def test_split_frontmatter_unescapes_double_quoted(self):
        fm, _ = wc.split_frontmatter('---\nk: "a \\"q\\" \\\\ b"\n---\n')
        self.assertEqual(fm["k"], 'a "q" \\ b')

    def test_split_frontmatter_unescapes_single_quoted(self):
        fm, _ = wc.split_frontmatter("---\nk: 'it''s: ok'\n---\n")
        self.assertEqual(fm["k"], "it's: ok")

    def test_quoted_empty_string_is_a_string_not_an_empty_list(self):
        fm, _ = wc.split_frontmatter('---\nk: ""\n---\n')
        self.assertEqual(fm["k"], "")


if __name__ == "__main__":
    unittest.main()
