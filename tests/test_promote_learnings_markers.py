"""`promote_learnings.py`'s adoption of `_marker_block.MarkerBlock` (#180, stage 1a).

A standalone companion to `tests/test_promote_learnings.py`'s `ManagedBlockTest`
and `ProvenanceInBlockTest`, kept in its own file rather than grown into that
~1000-line one (see the `modular-design` skill) — this file's whole reason to
change is marker recognition, not any of promote's other facets.

Before this fix, both `_compose_note` and `existing_provenance` located the
`<!-- promoted:begin -->` / `<!-- promoted:end -->` pair with bare substring
search (`in` / `.index()`). That recognises the markers anywhere in the text,
including inside a fenced code example that merely *documents* the block shape
— exactly the shape `memory/CONVENTIONS.md` teaches downstream notes to write
(and the same failure class `_marker_block.py` itself cites as #102 / #121).
`test_fenced_mention_of_both_markers_is_not_spliced_as_a_real_block` below is
that regression: on `origin/main` it fails (the fenced content is silently
spliced away at rc 0); after adopting `MarkerBlock`'s fence-aware, line-anchored
scan it passes.

The remaining tests here cover the other half of the adoption: a note whose
*real* managed-block markers are malformed (an orphan begin, in this case) must
be skipped and reported — not guessed at — while the rest of the run still
lands, mirroring the refusal `compute_readiness.compose` / `wiki_index.compose`
already give a malformed generated block.
"""

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import promote_learnings as pl  # noqa: E402


LEDGER_SEED = (
    "# Learning log\n\n"
    "Seed intro.\n\n"
    "## Entries\n"
)


def _seed_repo(repo: Path) -> Path:
    """Create a memory/ tree with a seeded learning-log.md. Returns the ledger."""
    memory = repo / "memory"
    memory.mkdir(parents=True, exist_ok=True)
    ledger = memory / "learning-log.md"
    ledger.write_text(LEDGER_SEED, encoding="utf-8")
    return ledger


def _nom(**over) -> dict:
    base = {
        "scope": "feedback",
        "target": "feedback/sample-learning.md",
        "name": "feedback-sample-learning",
        "description": "A one-line description.",
        "type": "feedback",
        "body": "The body of the note.",
        "source": "empirical",
        "date": "2026-07-12",
    }
    base.update(over)
    return base


class FencedMarkerMentionTest(unittest.TestCase):
    """The live hazard the task brief calls out: a documented example of the
    block shape, inside a ```-fenced code block, must not be mistaken for the
    block itself."""

    # A legacy note (no real managed block yet) that documents the block shape
    # in a fenced example — the same thing `memory/CONVENTIONS.md` teaches
    # downstream notes to do. "ANCHOR-BETWEEN-MARKERS" stands in for whatever
    # prose a real example would show between the two marker lines; bare
    # substring search deletes it, fence-aware search does not.
    LEGACY_WITH_FENCED_EXAMPLE = (
        "---\n"
        "name: conventions\n"
        "description: explains the managed-block shape\n"
        "type: context\n"
        "---\n"
        "# Promoted-note shape\n"
        "\n"
        "A promoted note's managed block looks like this:\n"
        "\n"
        "```\n"
        f"{pl.PROMOTED_BEGIN}\n"
        "ANCHOR-BETWEEN-MARKERS\n"
        f"{pl.PROMOTED_END}\n"
        "```\n"
        "\n"
        "Everything outside the real block is yours to edit by hand.\n"
    )

    def test_fenced_mention_of_both_markers_is_not_spliced_as_a_real_block(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            _seed_repo(repo)
            target = "context/conventions.md"
            note = repo / "memory" / target
            note.parent.mkdir(parents=True, exist_ok=True)
            note.write_text(self.LEGACY_WITH_FENCED_EXAMPLE, encoding="utf-8")

            nom = _nom(
                scope="context",
                target=target,
                name="context-conventions",
                type="context",
                body="Freshly promoted learning.",
            )
            rc, summary = pl.promote([nom], repo_dir=repo)
            self.assertEqual(rc, 0, summary)

            out = note.read_text(encoding="utf-8")

            # The fenced example is prose the note merely documents, and its
            # content must survive — it is not the block this promote run owns.
            self.assertIn(
                "ANCHOR-BETWEEN-MARKERS", out,
                "fenced example content was spliced away — the fence-aware "
                "scan did not treat the quoted markers as non-markers",
            )
            self.assertIn(
                "A promoted note's managed block looks like this:", out
            )
            self.assertIn(
                "Everything outside the real block is yours to edit by hand.",
                out,
            )

            # A REAL managed block was additionally inserted (legacy-migration
            # path — the fenced mention does not count as an existing block),
            # carrying the new nomination's body.
            self.assertIn("Freshly promoted learning.", out)
            self.assertEqual(out.count(pl.PROMOTED_BEGIN), 2)
            self.assertEqual(out.count(pl.PROMOTED_END), 2)


class MalformedMarkerSkipTest(unittest.TestCase):
    """A note whose managed-block markers are malformed is skipped, not guessed
    at, and the rest of the run still lands (the task brief's expected shape)."""

    # An orphan begin marker: the block's extent is unknowable. Splicing would
    # have to guess where it ends — appending duplicates it forever, truncating
    # at EOF eats the tail prose — so this must be refused, the same posture
    # `compute_readiness.compose` / `wiki_index.compose` already take.
    MALFORMED = (
        "---\nname: broken\ndescription: a stray begin marker\ntype: feedback\n---\n"
        f"{pl.PROMOTED_BEGIN}\n"
        "Someone deleted the end marker by hand.\n"
        "Hand-written tail that a guess-and-splice repair would eat.\n"
    )

    def test_malformed_markers_are_skipped_reported_and_leave_the_note_untouched(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            _seed_repo(repo)
            target = "feedback/broken.md"
            note = repo / "memory" / target
            note.parent.mkdir(parents=True, exist_ok=True)
            note.write_text(self.MALFORMED, encoding="utf-8")
            before = note.read_bytes()

            nom = _nom(target=target, body="Would-be new learning.")
            rc, summary = pl.promote([nom], repo_dir=repo)

            # One bad note does not fail the whole pass.
            self.assertEqual(rc, 0, summary)
            # Not one byte of the malformed note was touched.
            self.assertEqual(note.read_bytes(), before)
            # The condition reaches the operator, in the established
            # "skip (...)" summary shape used by dedup/contradiction skips.
            self.assertTrue(
                any("skip (malformed markers)" in s for s in summary), summary
            )
            # It is not silently folded into "promoted" or left uncounted.
            self.assertTrue(any("skipped 1" in s for s in summary), summary)
            # It must not have reached the ledger — nothing was written.
            ledger = (repo / "memory" / "learning-log.md").read_text(encoding="utf-8")
            self.assertNotIn("Would-be new learning.", ledger)

    def test_malformed_note_does_not_block_a_later_good_nomination(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            _seed_repo(repo)
            broken_target = "feedback/broken.md"
            broken = repo / "memory" / broken_target
            broken.parent.mkdir(parents=True, exist_ok=True)
            broken.write_text(self.MALFORMED, encoding="utf-8")

            bad = _nom(target=broken_target, body="Would-be new learning.")
            good = _nom(target="feedback/good.md", body="A perfectly good learning.")

            rc, summary = pl.promote([bad, good], repo_dir=repo)
            self.assertEqual(rc, 0, summary)

            # The good nomination still landed...
            good_note = repo / "memory" / "feedback" / "good.md"
            self.assertTrue(good_note.is_file(), summary)
            self.assertIn("A perfectly good learning.", good_note.read_text(encoding="utf-8"))
            # ...and the summary accounts for exactly one skip, one promotion.
            self.assertIn("promoted 1, skipped 1", summary)

    def test_malformed_markers_detected_in_dry_run_too(self):
        # A preview must not promise a write a real run would refuse.
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            _seed_repo(repo)
            target = "feedback/broken.md"
            note = repo / "memory" / target
            note.parent.mkdir(parents=True, exist_ok=True)
            note.write_text(self.MALFORMED, encoding="utf-8")

            nom = _nom(target=target, body="Would-be new learning.")
            rc, summary = pl.promote([nom], repo_dir=repo, dry_run=True)

            self.assertEqual(rc, 0, summary)
            self.assertFalse(any(s.startswith("would") and "broken.md" in s for s in summary), summary)
            self.assertTrue(
                any("skip (malformed markers)" in s for s in summary), summary
            )


if __name__ == "__main__":
    unittest.main()
