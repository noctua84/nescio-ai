"""A declared frontmatter change defeats the body-hash dedup skip (issue 10).

Promote dedups a nomination by `content_hash12` of its **body** against the
ledger. A corroboration bump - `corroboration: 2` -> `3`, a repo appended to
`seen_in` - changes only frontmatter, so its body hash is already recorded and
it used to be skipped as `skip (dedup)`: the bump silently did not happen.

The exemption is deliberately narrow, and most of this module pins the side of
it that must NOT move:

  * the dedup key stays body-only (`content_hash12` is untouched);
  * a re-nomination of identical text that declares no frontmatter, or declares
    exactly what the note already holds, still dedups;
  * "already holds" is decided on the RENDERED form - `corroboration: 3` is the
    int `3`, while the string `"3"` renders `corroboration: "3"` and differs;
  * a frontmatter-only update appends a ledger line, and the duplicate body hash
    that line carries does not break the dedup set.

Kept apart from `test_promote_frontmatter.py`, which covers how the field is
rendered, refreshed and validated; this module covers only whether a nomination
is let through the dedup gate, which is a separate decision in `promote()`.

Run: PYTHONPATH=scripts python -m unittest tests.test_promote_frontmatter_dedup
"""

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import promote_learnings as pl  # noqa: E402
from _promoted_block import declared_frontmatter_changed  # noqa: E402
from _wiki_common import split_frontmatter  # noqa: E402

LEDGER_SEED = "# Learning log\n\nSeed intro.\n\n## Entries\n"
TARGET = "concepts/backup-first.md"
SEEDED_FM = {"seen_in": ["repo/x", "repo/y"], "corroboration": 2}


def _nom(**over) -> dict:
    base = {
        "scope": "concepts",
        "target": TARGET,
        "name": "backup-first",
        "description": "Back a file up before replacing it with a symlink.",
        "type": "concept",
        "body": "Any installer that swaps a real file for a symlink backs it up first.",
        "source": "empirical",
        "date": "2026-07-12",
    }
    base.update(over)
    return base


class _Repo:
    """A temp repo with a seeded ledger and one already-promoted concept note."""

    def __init__(self, test: unittest.TestCase, d: str, seed: dict | None):
        self.test = test
        self.root = Path(d)
        memory = self.root / "memory"
        memory.mkdir(parents=True)
        self.ledger = memory / "learning-log.md"
        self.ledger.write_text(LEDGER_SEED, encoding="utf-8")
        self.note = memory / TARGET
        if seed is not None:
            self.run(seed)

    def run(self, *noms: dict, dry_run: bool = False) -> list[str]:
        rc, summary = pl.promote(list(noms), repo_dir=self.root, dry_run=dry_run)
        self.test.assertEqual(rc, 0, summary)
        return summary

    def text(self) -> str:
        return self.note.read_text(encoding="utf-8")

    def ledger_text(self) -> str:
        return self.ledger.read_text(encoding="utf-8")

    def entries(self) -> list[str]:
        return [ln for ln in self.ledger_text().splitlines() if ln.startswith("- ")]


def _skipped_dedup(summary: list[str]) -> bool:
    return any(line.startswith("skip (dedup)") for line in summary)


def _list_items(text: str, key: str) -> list[str]:
    lines = text.splitlines()
    i = lines.index(f"{key}:") + 1
    items = []
    while i < len(lines) and lines[i].startswith("  - "):
        items.append(lines[i][4:])
        i += 1
    return items


def _bump(**over) -> dict:
    """The seeded nomination re-submitted later with the same body."""
    over.setdefault("date", "2026-08-01")
    return _nom(**over)


class BumpIsNotSkippedTest(unittest.TestCase):
    def test_changed_corroboration_with_unchanged_body_is_written(self):
        with tempfile.TemporaryDirectory() as d:
            repo = _Repo(self, d, _nom(frontmatter=SEEDED_FM))
            self.assertIn("corroboration: 2\n", repo.text())
            summary = repo.run(
                _bump(frontmatter={"seen_in": ["repo/x", "repo/y"], "corroboration": 3})
            )
            self.assertFalse(_skipped_dedup(summary), summary)
            self.assertIn("promoted 1, skipped 0", "\n".join(summary))
            text = repo.text()
            self.assertIn("corroboration: 3\n", text)
            self.assertNotIn("corroboration: 2", text)
            self.assertEqual(text.count("corroboration:"), 1)

    def test_seen_in_gaining_an_entry_is_written(self):
        with tempfile.TemporaryDirectory() as d:
            repo = _Repo(self, d, _nom(frontmatter=SEEDED_FM))
            summary = repo.run(
                _bump(frontmatter={"seen_in": ["repo/x", "repo/y", "repo/z"]})
            )
            self.assertFalse(_skipped_dedup(summary), summary)
            text = repo.text()
            self.assertEqual(_list_items(text, "seen_in"), ["repo/x", "repo/y", "repo/z"])
            self.assertEqual(text.count("seen_in:"), 1)
            # Undeclared on this run, so the seeded value is preserved.
            self.assertIn("corroboration: 2\n", text)

    def test_declared_key_absent_from_the_note_is_a_change(self):
        with tempfile.TemporaryDirectory() as d:
            repo = _Repo(self, d, _nom())
            summary = repo.run(_bump(frontmatter={"corroboration": 1}))
            self.assertFalse(_skipped_dedup(summary), summary)
            self.assertEqual(split_frontmatter(repo.text())[0]["corroboration"], "1")

    def test_body_is_unchanged_and_provenance_follows_the_bump(self):
        with tempfile.TemporaryDirectory() as d:
            repo = _Repo(self, d, _nom(frontmatter=SEEDED_FM))
            repo.run(_bump(frontmatter={"corroboration": 3}))
            text = repo.text()
            self.assertEqual(text.count(_nom()["body"]), 1)
            self.assertIn("[Source: empirical — 2026-08-01]", text)
            self.assertNotIn("2026-07-12", text)

    def test_string_three_against_stored_int_three_is_a_change(self):
        """Compared rendered-to-stored, not after read-back: `split_frontmatter`
        reads both `3` and `"3"` as the string "3", but they render differently
        and emission is type-aware on purpose."""
        with tempfile.TemporaryDirectory() as d:
            repo = _Repo(self, d, _nom(frontmatter={"corroboration": 3}))
            summary = repo.run(_bump(frontmatter={"corroboration": "3"}))
            self.assertFalse(_skipped_dedup(summary), summary)
            self.assertIn('corroboration: "3"\n', repo.text())


class StillDedupsTest(unittest.TestCase):
    """The property to protect: identical text with no real frontmatter change."""

    def _assert_untouched_skip(self, repo: _Repo, nom: dict) -> None:
        before_note, before_ledger = repo.text(), repo.ledger_text()
        summary = repo.run(nom)
        self.assertTrue(_skipped_dedup(summary), summary)
        self.assertIn("promoted 0, skipped 1", "\n".join(summary))
        self.assertEqual(repo.text(), before_note)
        self.assertEqual(repo.ledger_text(), before_ledger)

    def test_identical_renomination_without_frontmatter(self):
        for seed_fm in (None, SEEDED_FM):
            with self.subTest(seed_fm=seed_fm), tempfile.TemporaryDirectory() as d:
                repo = _Repo(self, d, _nom(frontmatter=seed_fm))
                self._assert_untouched_skip(repo, _bump())
                self._assert_untouched_skip(repo, _bump(frontmatter={}))
                self._assert_untouched_skip(repo, _bump(frontmatter=None))

    def test_renomination_declaring_what_is_already_on_disk(self):
        with tempfile.TemporaryDirectory() as d:
            repo = _Repo(self, d, _nom(frontmatter=SEEDED_FM))
            self._assert_untouched_skip(repo, _bump(frontmatter=SEEDED_FM))

    def test_declaring_a_matching_subset_of_the_stored_keys(self):
        with tempfile.TemporaryDirectory() as d:
            repo = _Repo(self, d, _nom(frontmatter=SEEDED_FM))
            self._assert_untouched_skip(repo, _bump(frontmatter={"corroboration": 2}))

    def test_every_value_type_compares_in_rendered_form(self):
        fm = {
            "corroboration": 3,
            "ratio": 0.5,
            "as_text": "3",
            "flag": True,
            "off": False,
            "colon": "a: b",
            "word": "no",
            "seen_in": ["plain", "a: b", "no", "7", 3, True],
        }
        with tempfile.TemporaryDirectory() as d:
            repo = _Repo(self, d, _nom(frontmatter=fm))
            self._assert_untouched_skip(repo, _bump(frontmatter=fm))

    def test_trailing_whitespace_on_a_stored_line_is_not_a_change(self):
        with tempfile.TemporaryDirectory() as d:
            repo = _Repo(self, d, _nom(frontmatter=SEEDED_FM))
            repo.note.write_text(
                repo.text().replace("corroboration: 2\n", "corroboration: 2   \n"),
                encoding="utf-8",
            )
            self._assert_untouched_skip(repo, _bump(frontmatter={"corroboration": 2}))

    def test_body_promoted_to_another_target_still_dedups(self):
        """The exemption is for a frontmatter-only update of the note the body
        was promoted to. Letting it through for a different target would write a
        body the ledger says is already promoted elsewhere into that note."""
        with tempfile.TemporaryDirectory() as d:
            repo = _Repo(self, d, _nom(frontmatter=SEEDED_FM))
            other = _nom(
                target="concepts/other.md", name="other", body="A different body."
            )
            repo.run(other)
            other_path = repo.root / "memory" / "concepts/other.md"
            before = other_path.read_text(encoding="utf-8")
            summary = repo.run(
                _bump(target="concepts/other.md", name="other", frontmatter={"corroboration": 9})
            )
            self.assertTrue(_skipped_dedup(summary), summary)
            self.assertEqual(other_path.read_text(encoding="utf-8"), before)

    def test_deleted_note_is_not_resurrected_by_a_frontmatter_change(self):
        with tempfile.TemporaryDirectory() as d:
            repo = _Repo(self, d, _nom(frontmatter=SEEDED_FM))
            repo.note.unlink()
            before_ledger = repo.ledger_text()
            summary = repo.run(_bump(frontmatter={"corroboration": 3}))
            self.assertTrue(_skipped_dedup(summary), summary)
            self.assertFalse(repo.note.exists())
            self.assertEqual(repo.ledger_text(), before_ledger)

    def test_note_without_a_frontmatter_block_still_dedups(self):
        """The update path never writes frontmatter onto a note that has none,
        so a declared key there could never land: letting the nomination
        through would rewrite nothing and add a ledger line on every run."""
        with tempfile.TemporaryDirectory() as d:
            repo = _Repo(self, d, _nom())
            _, rest = pl._split_raw_frontmatter(repo.text())
            repo.note.write_text(rest, encoding="utf-8")
            self._assert_untouched_skip(repo, _bump(frontmatter={"corroboration": 3}))


class LedgerTest(unittest.TestCase):
    def test_frontmatter_only_update_appends_a_ledger_line_and_set_membership_holds(self):
        with tempfile.TemporaryDirectory() as d:
            repo = _Repo(self, d, _nom(frontmatter=SEEDED_FM))
            h = pl.content_hash12(_nom()["body"])
            first = repo.entries()
            self.assertEqual(len(first), 1)

            bump = _bump(frontmatter={"corroboration": 3})
            repo.run(bump)
            after = repo.entries()
            self.assertEqual(len(after), 2, after)
            self.assertEqual(after[0], first[0], "the original promotion line survives")
            self.assertEqual(
                after[1],
                f"- 2026-08-01 | {TARGET} | {h} | {pl.LEDGER_VERB_PROMOTED} backup-first",
            )

            note_before, ledger_before = repo.text(), repo.ledger_text()
            summary = repo.run(bump)
            self.assertTrue(_skipped_dedup(summary), summary)
            self.assertEqual(repo.text(), note_before)
            self.assertEqual(repo.ledger_text(), ledger_before)

    def test_successive_bumps_each_record_a_line(self):
        with tempfile.TemporaryDirectory() as d:
            repo = _Repo(self, d, _nom(frontmatter=SEEDED_FM))
            repo.run(_bump(date="2026-08-01", frontmatter={"corroboration": 3}))
            repo.run(_bump(date="2026-09-01", frontmatter={"corroboration": 4}))
            self.assertEqual(len(repo.entries()), 3)
            self.assertIn("corroboration: 4\n", repo.text())


class UndeclaredKeysTest(unittest.TestCase):
    def test_hand_added_keys_survive_a_frontmatter_only_update(self):
        with tempfile.TemporaryDirectory() as d:
            repo = _Repo(self, d, _nom(frontmatter=SEEDED_FM))
            hand = "owner: someone\nreviewed:\n  - 2026-01-01\n  - 2026-02-01\n"
            repo.note.write_text(
                repo.text().replace("type: concept\n", "type: concept\n" + hand, 1),
                encoding="utf-8",
            )
            summary = repo.run(_bump(frontmatter={"corroboration": 3}))
            self.assertFalse(_skipped_dedup(summary), summary)
            text = repo.text()
            self.assertIn("type: concept\n" + hand, text)
            self.assertEqual(_list_items(text, "seen_in"), ["repo/x", "repo/y"])
            self.assertIn("corroboration: 3\n", text)


class GatesStillApplyTest(unittest.TestCase):
    def test_contradiction_rule_still_gates_a_frontmatter_only_update(self):
        with tempfile.TemporaryDirectory() as d:
            repo = _Repo(self, d, _nom(frontmatter=SEEDED_FM))
            before = repo.text()
            summary = repo.run(
                _bump(source="agent inference", frontmatter={"corroboration": 3})
            )
            self.assertTrue(
                any(s.startswith("skip (contradiction)") for s in summary), summary
            )
            self.assertEqual(repo.text(), before)

    def test_dry_run_previews_the_update_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            repo = _Repo(self, d, _nom(frontmatter=SEEDED_FM))
            before_note, before_ledger = repo.text(), repo.ledger_text()
            bump = _bump(frontmatter={"corroboration": 3})
            summary = repo.run(bump, bump, dry_run=True)
            self.assertTrue(any(s.startswith("would ") for s in summary), summary)
            self.assertIn("[dry-run] promoted 1, skipped 1", "\n".join(summary))
            self.assertEqual(repo.text(), before_note)
            self.assertEqual(repo.ledger_text(), before_ledger)


class DeclaredFrontmatterChangedTest(unittest.TestCase):
    """The pure comparison `promote()` consults, in isolation."""

    NOTE = (
        "---\nname: n\ndescription: d\ntype: concept\n"
        "seen_in:\n  - repo/x\n  - \"a: b\"\ncorroboration: 2\n---\nBody.\n"
    )

    def test_cases(self):
        cases = [
            ({}, False),
            ({"corroboration": 2}, False),
            ({"seen_in": ["repo/x", "a: b"]}, False),
            ({"corroboration": 3}, True),
            ({"corroboration": "2"}, True),
            ({"seen_in": ["repo/x"]}, True),
            ({"seen_in": ["repo/x", "a: b", "repo/z"]}, True),
            ({"tier": "general"}, True),
        ]
        for fm, expected in cases:
            with self.subTest(fm=fm):
                self.assertIs(
                    declared_frontmatter_changed(self.NOTE, _nom(frontmatter=fm)),
                    expected,
                )

    def test_no_existing_note_or_no_frontmatter_block_is_no_change(self):
        nom = _nom(frontmatter={"corroboration": 3})
        self.assertFalse(declared_frontmatter_changed(None, nom))
        self.assertFalse(declared_frontmatter_changed("Body only.\n", nom))

    def test_indentless_stored_list_differs_from_the_canonical_rendering(self):
        """A column-0 `- item` list is rewritten once into the canonical shape,
        which is what the update path would write anyway; after that it is
        stable and dedups."""
        note = "---\nname: n\ndescription: d\ntype: concept\nseen_in:\n- a\n---\nB.\n"
        nom = _nom(frontmatter={"seen_in": ["a"]})
        self.assertTrue(declared_frontmatter_changed(note, nom))
        fm_raw, rest = pl._split_raw_frontmatter(note)
        refreshed = pl._refresh_frontmatter(fm_raw, nom) + rest
        self.assertFalse(declared_frontmatter_changed(refreshed, nom))


if __name__ == "__main__":
    unittest.main()
