"""The optional `frontmatter` nomination field: pass-through keys on a promoted note.

A nomination may carry `frontmatter`, a flat dict whose values are scalars or
lists of scalars, to put extra keys (`seen_in`, `corroboration`, ...) on the
note beyond the three promote always manages. Three places each independently
decide "which keys exist", and each gets its own tests here:

  * `render_frontmatter`   - the create path;
  * `_refresh_frontmatter` - the update path (declared keys are rewritten,
    undeclared ones preserved);
  * phase-1 validation in `promote()` - a malformed or unwritable value is
    refused before anything is written.

The cases that matter most are the ones a naive implementation gets wrong
silently: emitting values raw (a value containing `: ` writes unparseable YAML),
dropping the managed-block markers from a created note, and treating the extra
keys as unmanaged on update (a corroboration bump then changes the body and
leaves the old value in the frontmatter, exiting 0).

Run: PYTHONPATH=scripts python -m unittest tests.test_promote_frontmatter
"""

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import promote_learnings as pl  # noqa: E402
from _wiki_common import _unquote_scalar, split_frontmatter  # noqa: E402

LEDGER_SEED = "# Learning log\n\nSeed intro.\n\n## Entries\n"


def _seed_repo(repo: Path) -> Path:
    memory = repo / "memory"
    memory.mkdir(parents=True, exist_ok=True)
    ledger = memory / "learning-log.md"
    ledger.write_text(LEDGER_SEED, encoding="utf-8")
    return ledger


def _nom(**over) -> dict:
    base = {
        "scope": "context",
        "target": "context/concept.md",
        "name": "context-concept",
        "description": "A generalized concept.",
        "type": "context",
        "body": "The concept body.",
        "source": "empirical",
        "date": "2026-07-12",
    }
    base.update(over)
    return base


def _run(repo: Path, *noms: dict) -> tuple[int, list[str]]:
    return pl.promote(list(noms), repo_dir=repo)


def _list_items(text: str, key: str) -> list[str]:
    """The raw `  - ` item lines under ``key:`` in ``text``'s frontmatter."""
    lines = text.splitlines()
    i = lines.index(f"{key}:") + 1
    items = []
    while i < len(lines) and lines[i].startswith("  - "):
        items.append(lines[i][4:])
        i += 1
    return items


class CreateTest(unittest.TestCase):
    def test_no_frontmatter_field_leaves_output_byte_identical(self):
        self.assertEqual(
            pl.render_frontmatter(_nom()),
            "---\nname: context-concept\ndescription: A generalized concept.\n"
            "type: context\n---\n",
        )

    def test_empty_or_null_frontmatter_is_the_same_as_absent(self):
        plain = pl.render_frontmatter(_nom())
        self.assertEqual(pl.render_frontmatter(_nom(frontmatter={})), plain)
        self.assertEqual(pl.render_frontmatter(_nom(frontmatter=None)), plain)

    def test_extras_follow_managed_keys_in_insertion_order(self):
        fm = {"seen_in": ["repo-a", "repo-b"], "corroboration": 2, "tier": "general"}
        out = pl.render_frontmatter(_nom(frontmatter=fm))
        self.assertEqual(
            out,
            "---\nname: context-concept\ndescription: A generalized concept.\n"
            "type: context\nseen_in:\n  - repo-a\n  - repo-b\n"
            'corroboration: "2"\ntier: general\n---\n',
        )

    def test_created_note_still_carries_both_promoted_block_markers(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            _seed_repo(repo)
            rc, summary = _run(repo, _nom(frontmatter={"seen_in": ["a", "b"]}))
            self.assertEqual(rc, 0, summary)
            text = (repo / "memory" / "context/concept.md").read_text(encoding="utf-8")
            self.assertIn(pl.PROMOTED_BEGIN + "\n", text)
            self.assertIn(pl.PROMOTED_END + "\n", text)
            self.assertEqual(pl._BLOCK.classify(split_frontmatter(text)[1])[0], "ok")

    def test_units_shaped_nomination_also_gets_extras(self):
        unit = {"text": "A unit.", "source": "empirical", "date": "2026-07-12"}
        nom = _nom(frontmatter={"seen_in": ["a"]})
        del nom["body"]
        nom["units"] = [unit]
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            _seed_repo(repo)
            rc, summary = _run(repo, nom)
            self.assertEqual(rc, 0, summary)
            text = (repo / "memory" / "context/concept.md").read_text(encoding="utf-8")
            self.assertEqual(split_frontmatter(text)[0]["seen_in"], ["a"])


class RoundTripTest(unittest.TestCase):
    """Every value and list item goes through `yaml_scalar`."""

    SCALARS = ["a: b", "no", "yes", "42", "2026-07-12", "has # comment? x #y", ""]

    def _written(self, fm: dict) -> str:
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            _seed_repo(repo)
            rc, summary = _run(repo, _nom(frontmatter=fm))
            self.assertEqual(rc, 0, summary)
            return (repo / "memory" / "context/concept.md").read_text(encoding="utf-8")

    def test_scalar_values_round_trip_through_split_frontmatter(self):
        for value in self.SCALARS:
            with self.subTest(value=value):
                parsed, _ = split_frontmatter(self._written({"k": value}))
                self.assertEqual(parsed["k"], value)

    def test_list_items_are_written_in_yaml_scalar_form(self):
        """What lands on disk is exactly `yaml_scalar` of each item, and
        unquoting it recovers the original."""
        items = ["plain", "a: b", "no", "7"]
        text = self._written({"seen_in": items})
        raw = _list_items(text, "seen_in")
        self.assertEqual(raw, ["plain", '"a: b"', '"no"', '"7"'])
        self.assertEqual([_unquote_scalar(r) for r in raw], items)

    @unittest.expectedFailure
    def test_list_items_round_trip_through_split_frontmatter(self):
        """KNOWN GAP in the reader, not the writer: `split_frontmatter` appends
        list items as `raw[4:].strip()` without `_unquote_scalar`, so a quoted
        item comes back with its quotes. Remove the decorator when the reader
        unquotes list items (one line in `_wiki_common.split_frontmatter`)."""
        items = ["plain", "a: b", "no", "7"]
        parsed, _ = split_frontmatter(self._written({"seen_in": items}))
        self.assertEqual(parsed["seen_in"], items)


class UpdateTest(unittest.TestCase):
    def _seed_note(self, repo: Path, nom: dict) -> Path:
        _seed_repo(repo)
        rc, summary = _run(repo, nom)
        self.assertEqual(rc, 0, summary)
        return repo / "memory" / nom["target"]

    def test_corroboration_bump_rewrites_declared_values(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            note = self._seed_note(
                repo,
                _nom(frontmatter={"seen_in": ["a", "b"], "corroboration": 2}),
            )
            rc, summary = _run(
                repo,
                _nom(
                    body="The concept body, now corroborated.",
                    date="2026-08-01",
                    frontmatter={"seen_in": ["a", "b", "c"], "corroboration": 3},
                ),
            )
            self.assertEqual(rc, 0, summary)
            text = note.read_text(encoding="utf-8")
            parsed, _ = split_frontmatter(text)
            self.assertEqual(parsed["corroboration"], "3")
            self.assertEqual(_list_items(text, "seen_in"), ["a", "b", "c"])
            self.assertEqual(text.count("corroboration:"), 1)
            self.assertEqual(text.count("seen_in:"), 1)
            self.assertIn("now corroborated", text)

    def test_undeclared_extra_key_is_preserved_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            note = self._seed_note(repo, _nom())
            text = note.read_text(encoding="utf-8")
            hand_edited = text.replace(
                "type: context\n",
                "type: context\nowner: markus\nreviewed:\n  - 2026-01-01\n  - 2026-02-01\n",
                1,
            )
            note.write_text(hand_edited, encoding="utf-8")
            rc, summary = _run(
                repo,
                _nom(
                    body="A changed body.",
                    date="2026-08-01",
                    frontmatter={"corroboration": 3},
                ),
            )
            self.assertEqual(rc, 0, summary)
            out = note.read_text(encoding="utf-8")
            self.assertIn("owner: markus\nreviewed:\n  - 2026-01-01\n  - 2026-02-01\n", out)
            self.assertIn('corroboration: "3"\n', out)

    def test_declared_key_missing_from_the_note_is_inserted(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            note = self._seed_note(repo, _nom())
            rc, summary = _run(
                repo,
                _nom(body="Another body.", date="2026-08-01", frontmatter={"seen_in": ["a"]}),
            )
            self.assertEqual(rc, 0, summary)
            parsed, _ = split_frontmatter(note.read_text(encoding="utf-8"))
            self.assertEqual(parsed["seen_in"], ["a"])

    def test_refresh_is_idempotent_with_a_list_valued_extra_key(self):
        nom = _nom(frontmatter={"seen_in": ["a", "b: c", "no"], "corroboration": 3})
        start = (
            "---\nname: old\ndescription: old\ntype: context\nowner: markus\n"
            "seen_in:\n  - stale\n  - stale-too\n---\n"
        )
        once = pl._refresh_frontmatter(start, nom)
        twice = pl._refresh_frontmatter(once, nom)
        self.assertEqual(once, twice)
        self.assertNotIn("stale", once)
        self.assertIn("owner: markus\n", once)
        self.assertEqual(once.count("seen_in:"), 1)

    def test_indentless_yaml_list_is_replaced_whole(self):
        """`key:` followed by column-0 `- item` lines is valid YAML a human may
        have written; rewriting the key must not orphan the items."""
        start = (
            "---\nname: n\ndescription: d\ntype: context\n"
            "seen_in:\n- stale\n- stale-too\nowner: markus\n---\n"
        )
        out = pl._refresh_frontmatter(start, _nom(frontmatter={"seen_in": ["a"]}))
        self.assertNotIn("stale", out)
        self.assertEqual(split_frontmatter(out + "x\n")[0]["seen_in"], ["a"])
        self.assertIn("owner: markus\n", out)


class ValidationTest(unittest.TestCase):
    def _reject(self, nom: dict, *needles: str):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            ledger = _seed_repo(repo)
            rc, summary = _run(repo, nom)
            self.assertEqual(rc, 1, summary)
            for needle in needles:
                self.assertIn(needle, "\n".join(summary))
            self.assertFalse((repo / "memory" / nom["target"]).exists())
            self.assertEqual(ledger.read_text(encoding="utf-8"), LEDGER_SEED)

    def test_non_dict_frontmatter_is_rejected_naming_the_key(self):
        for bad in (["seen_in"], "seen_in: a", 3, True):
            with self.subTest(bad=bad):
                self._reject(_nom(frontmatter=bad), "frontmatter")

    def test_nested_member_is_rejected_naming_the_key(self):
        self._reject(
            _nom(frontmatter={"nested": {"a": 1}}), "frontmatter", "nested"
        )
        self._reject(
            _nom(frontmatter={"seen_in": [["a"]]}), "frontmatter", "seen_in"
        )
        self._reject(
            _nom(frontmatter={"seen_in": [{"a": 1}]}), "frontmatter", "seen_in"
        )

    def test_none_member_is_rejected_rather_than_written_as_the_word_none(self):
        self._reject(_nom(frontmatter={"tier": None}), "frontmatter", "tier")

    def test_lone_surrogate_in_extra_value_or_list_item_is_rejected(self):
        self._reject(
            _nom(frontmatter={"tier": "bad\ud800"}), "frontmatter", "tier", "surrogate"
        )
        self._reject(
            _nom(frontmatter={"seen_in": ["ok", "bad\udc00"]}),
            "frontmatter",
            "seen_in",
            "surrogate",
        )

    def test_key_that_would_not_write_valid_yaml_is_rejected(self):
        for key in ("", "a: b", "two words", "line\nbreak", "#c", "bad\ud800"):
            with self.subTest(key=key):
                self._reject(_nom(frontmatter={key: "v"}), "frontmatter")

    def test_managed_key_in_frontmatter_is_rejected_not_duplicated(self):
        for key in pl.MANAGED_KEYS:
            with self.subTest(key=key):
                self._reject(_nom(frontmatter={key: "v"}), "frontmatter", key)

    def test_validation_runs_before_any_nomination_is_written(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            _seed_repo(repo)
            good = _nom(target="context/good.md", name="context-good", body="Good body.")
            bad = _nom(frontmatter={"nested": {"a": 1}})
            rc, _ = _run(repo, good, bad)
            self.assertEqual(rc, 1)
            self.assertFalse((repo / "memory" / "context/good.md").exists())


if __name__ == "__main__":
    unittest.main()
