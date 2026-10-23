"""A `body`-shaped nomination against an anchored `units` block (#208).

**Gate on #180 stage 2.** Reproduced on `origin/main`: a `body` nomination
against a note whose managed block already carries `<!-- unit:... -->`
anchors is spliced straight over the block, destroying every stored unit's
text in one silent, exit-0 write. Unreachable in production today — nothing
emits a `units` nomination yet — but live the moment stage 2 ships
`commands/harvest-memory.md`'s two sentences of prose.

The decision, recorded on the issue: **refuse, do not convert.** A `body`
nomination against an anchored block is rejected with a
`skip (shape mismatch)` summary line, the note left byte-for-byte untouched,
the run continuing -- the same posture `skip (dedup)` / `skip (contradiction)`
/ `skip (malformed markers)` already have. Once a note is `units`-shaped,
`units` is its only contract from then on; a `body` nomination can never
touch it again, by design.

`test_compose_note_refuses_body_over_anchored_units_block` below is the
direct reproduction from the issue body -- the same fixture shape, the same
call -- and is the test that must fail on `origin/main` and pass here.

Kept in its own file rather than grown into `tests/test_promote_learnings.py`
(982 lines) or `tests/test_promote_learnings_units.py` (792 lines), both
already over the `modular-design` tripwire: this file's whole reason to
change is the shape-mismatch refusal, not any of promote's other facets --
the same reasoning `tests/test_promote_learnings_markers.py` gives for being
its own file.

Hermetic throughout, in the house style of its siblings.
"""

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import promote_learnings as pl  # noqa: E402

LEDGER_SEED = "# Learning log\n\nSeed intro.\n\n## Entries\n"

TARGET = "feedback/sample-learning.md"

# The issue's own reproduction fixture (#208): two anchored units, A and B.
A = "Learning A, the first one."
B = "Learning B, the second one."
H_A = pl.content_hash12(A)
H_B = pl.content_hash12(B)

UNIT_A = pl.Unit(hash12=H_A, text=A, source="empirical", date="2026-07-01")
UNIT_B = pl.Unit(hash12=H_B, text=B, source="empirical", date="2026-07-02")

# A units-shaped note: two anchored units inside the one managed block.
UNITS_NOTE = (
    "---\n"
    "name: feedback-sample-learning\n"
    "description: A one-line description.\n"
    "type: feedback\n"
    "---\n"
    + pl.render_units_block([UNIT_A, UNIT_B])
)


def _seed_repo(repo: Path) -> Path:
    """Create a memory/ tree with a seeded learning-log.md. Returns the ledger."""
    memory = repo / "memory"
    memory.mkdir(parents=True, exist_ok=True)
    ledger = memory / "learning-log.md"
    ledger.write_text(LEDGER_SEED, encoding="utf-8")
    return ledger


def _body_nom(**over) -> dict:
    """A `body`-shaped nomination -- the shape that must not touch an anchored
    block."""
    base = {
        "scope": "feedback",
        "target": TARGET,
        "name": "feedback-sample-learning",
        "description": "A fresher description.",
        "type": "feedback",
        "body": "WIPED - a single replacing body.",
        "source": "empirical",
        "date": "2026-07-03",
    }
    base.update(over)
    return base


class ComposeNoteRefusesShapeMismatchTest(unittest.TestCase):
    """`_compose_note` is the pure composer (#208's chosen fix site), so this
    is the most direct form of the issue's own reproduction: no disk, no
    promote() plumbing, just the fixture that wiped two units going in and a
    refusal, not a splice, coming out."""

    def test_compose_note_refuses_body_over_anchored_units_block(self):
        new_text, disposition = pl._compose_note(UNITS_NOTE, _body_nom())
        # On `origin/main` this assertion fails: `new_text` is the spliced
        # text with both units gone and `disposition` is "spliced".
        self.assertIsNone(new_text, disposition)
        self.assertTrue(disposition.startswith("shape-mismatch:"), disposition)

    def test_anchorless_legacy_block_is_not_a_shape_mismatch(self):
        # Zero anchors is the pre-#180 legacy shape -- a single merged body --
        # and `body` must keep replacing it exactly as before (the stage 1
        # no-op guarantee). This is the boundary `block_is_anchored` draws,
        # pinned directly against the function rather than only indirectly
        # through `_compose_note`'s disposition.
        legacy_note = (
            "---\n"
            "name: feedback-sample-learning\n"
            "description: An older description.\n"
            "type: feedback\n"
            "---\n"
            f"{pl.PROMOTED_BEGIN}\n"
            "The previously promoted body.\n"
            "[Source: empirical — 2026-07-01]\n"
            f"{pl.PROMOTED_END}\n"
        )
        _, rest = pl._split_raw_frontmatter(legacy_note)
        self.assertFalse(pl.block_is_anchored(pl._BLOCK.inner(rest)))

        new_text, disposition = pl._compose_note(legacy_note, _body_nom())
        self.assertEqual(disposition, "spliced")
        self.assertIsNotNone(new_text)
        self.assertNotIn("<!-- unit:", new_text)

    def test_refusal_does_not_depend_on_the_last_units_provenance(self):
        # Unit B (rendered last) carries 'user override' -- the highest
        # priority source. If the overwrite were still adjudicated by
        # `existing_provenance`'s "whichever unit renders last" value (the
        # value ADR 0007 D7 itself calls arbitrary), an 'empirical' body would
        # lose to it and be skipped as a *contradiction*, not a shape
        # mismatch. The shape check must pre-empt that gate entirely -- it
        # runs first, inside `_compose_note`, before `existing_provenance` is
        # ever consulted.
        note = (
            "---\n"
            "name: feedback-sample-learning\n"
            "description: A one-line description.\n"
            "type: feedback\n"
            "---\n"
            + pl.render_units_block(
                [UNIT_A, pl.Unit(hash12=H_B, text=B, source="user override", date="2026-07-02")]
            )
        )
        new_text, disposition = pl._compose_note(note, _body_nom(source="empirical"))
        self.assertIsNone(new_text)
        self.assertTrue(disposition.startswith("shape-mismatch:"), disposition)


class PromoteRefusesShapeMismatchTest(unittest.TestCase):
    """The same refusal, end to end through `promote()` -- disk, ledger,
    summary, dry-run, and a later nomination in the same manifest."""

    def test_promote_leaves_units_note_byte_for_byte_unchanged_and_reports_skip(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            _seed_repo(repo)
            note = repo / "memory" / TARGET
            note.parent.mkdir(parents=True, exist_ok=True)
            note.write_text(UNITS_NOTE, encoding="utf-8")
            before = note.read_bytes()

            rc, summary = pl.promote([_body_nom()], repo_dir=repo)

            self.assertEqual(rc, 0, summary)
            # Not one byte of the units note was touched -- assert on bytes,
            # not merely "the units are still present".
            self.assertEqual(note.read_bytes(), before)
            self.assertTrue(
                any("skip (shape mismatch)" in s for s in summary), summary
            )
            self.assertTrue(any("skipped 1" in s for s in summary), summary)
            # Nothing reached the ledger -- no write happened at all.
            ledger = (repo / "memory" / "learning-log.md").read_text(encoding="utf-8")
            self.assertNotIn("WIPED", ledger)

    def test_shape_mismatch_does_not_block_a_later_good_nomination(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            _seed_repo(repo)
            note = repo / "memory" / TARGET
            note.parent.mkdir(parents=True, exist_ok=True)
            note.write_text(UNITS_NOTE, encoding="utf-8")

            bad = _body_nom()
            good = _body_nom(
                target="feedback/good.md",
                name="feedback-good",
                description="A different note entirely.",
                body="A perfectly good learning.",
            )
            rc, summary = pl.promote([bad, good], repo_dir=repo)
            self.assertEqual(rc, 0, summary)

            good_note = repo / "memory" / "feedback" / "good.md"
            self.assertTrue(good_note.is_file(), summary)
            self.assertIn(
                "A perfectly good learning.",
                good_note.read_text(encoding="utf-8"),
            )
            self.assertIn("promoted 1, skipped 1", summary)
            # The units note is still untouched regardless of what else ran.
            self.assertEqual(
                note.read_text(encoding="utf-8"), UNITS_NOTE
            )

    def test_shape_mismatch_refused_identically_under_dry_run(self):
        # A preview must not promise a write a real run would go on to
        # refuse, and must not promise a refusal a real run would not also
        # give -- both must land on exactly the same decision.
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            _seed_repo(repo)
            note = repo / "memory" / TARGET
            note.parent.mkdir(parents=True, exist_ok=True)
            note.write_text(UNITS_NOTE, encoding="utf-8")
            before = note.read_bytes()

            rc, summary = pl.promote([_body_nom()], repo_dir=repo, dry_run=True)

            self.assertEqual(rc, 0, summary)
            self.assertEqual(note.read_bytes(), before)
            self.assertFalse(
                any(s.startswith("would") and TARGET in s for s in summary),
                summary,
            )
            self.assertTrue(
                any("skip (shape mismatch)" in s for s in summary), summary
            )


if __name__ == "__main__":
    unittest.main()
