"""The `body` payload shape, and stage 1 of #180 being a no-op for it.

**This file certifies the OLD path and nothing else.** Its sibling
`tests/test_promote_learnings_units.py` gates the new `units` path on its own
fixtures, and the two are deliberately separate files. A single byte-identity
test was the false confidence in the first version of #180's plan: it proves
the shape that was already working still works, while the shape that actually
changed ships unexercised. Nothing here may be cited as coverage of `units`.

What stage 1 claims, and what each test below pins:

  1. A `body`-shaped nomination against an existing managed block renders
     **byte-identically** to the code before `units` existed. That holds
     *because* the `body` shape still REPLACES the block — see
     `promote_learnings._compose_note`. The expected text and its SHA-256 were
     captured by running the same fixture on `origin/main` at d72376a (#206,
     stage 1a) and are pinned verbatim, so the claim is checkable rather than
     asserted.
  2. Admission is exclusive: `body` alone works, `units` alone is the new
     path, **neither is rc 1, and both is rc 1**. The last of those mirrors
     `UNROUTED_FORBIDDEN_FIELDS`: a nomination that declares two payload
     shapes is ambiguous, and resolving it silently would make the note untrue
     in whichever direction the harvest did not mean.

Hermetic throughout, in the house style of `tests/test_promote_learnings.py`:
a `tempfile.TemporaryDirectory()` repo and a seeded ledger.
"""

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import promote_learnings as pl  # noqa: E402

LEDGER_SEED = "# Learning log\n\nSeed intro.\n\n## Entries\n"

TARGET = "feedback/sample-learning.md"


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
        "target": TARGET,
        "name": "feedback-sample-learning",
        "description": "A fresher one-line description.",
        "type": "feedback",
        "body": "The newly promoted body.\n\nWith a second paragraph.",
        "source": "empirical",
        "date": "2026-07-12",
    }
    base.update(over)
    return base


# A note that is already promotion-owned and also hand-edited: an extra
# frontmatter key promote does not manage, prose above the block and prose
# below it. Every one of those is something a replace could destroy.
EXISTING = (
    "---\n"
    "name: feedback-sample-learning\n"
    "description: An older one-line description.\n"
    "type: feedback\n"
    "owner: a-human\n"
    "---\n"
    "# Hand-written heading\n"
    "\n"
    "Prose above the block that must survive.\n"
    "\n"
    f"{pl.PROMOTED_BEGIN}\n"
    "The previously promoted body.\n"
    "[Source: empirical — 2026-07-01]\n"
    f"{pl.PROMOTED_END}\n"
    "\n"
    "## Hand-written tail\n"
    "\n"
    "More prose below the block.\n"
)

# Captured from `origin/main` at d72376a by running this exact fixture through
# `promote_learnings._compose_note`. Pinned as text AND as a digest: the text
# is what a reader needs to see, the digest is what makes "identical to main" a
# measurement rather than a claim.
GOLDEN = (
    "---\n"
    "name: feedback-sample-learning\n"
    "description: A fresher one-line description.\n"
    "type: feedback\n"
    "owner: a-human\n"
    "---\n"
    "# Hand-written heading\n"
    "\n"
    "Prose above the block that must survive.\n"
    "\n"
    "<!-- promoted:begin -->\n"
    "The newly promoted body.\n"
    "\n"
    "With a second paragraph.\n"
    "[Source: empirical — 2026-07-12]\n"
    "<!-- promoted:end -->\n"
    "\n"
    "## Hand-written tail\n"
    "\n"
    "More prose below the block.\n"
)
GOLDEN_SHA256 = "63f3ac41e99a1c4eef6485682a94819883aa4a806f7471e853b5708c4fd0b251"

GOLDEN_LEDGER_LINE = (
    "- 2026-07-12 | feedback/sample-learning.md | 010bc388f2c5 "
    "| promoted: feedback-sample-learning"
)


class BodyShapeIsByteIdenticalTest(unittest.TestCase):
    """Gating test 1 of 2 for #180 stage 1: the no-op guarantee."""

    def test_compose_note_is_byte_identical_to_main(self):
        # `_compose_note` is the pure composer, so this compares the exact
        # string the writer is handed -- no platform newline translation in the
        # way, which is what makes it a byte comparison rather than a textual
        # one.
        text, disposition = pl._compose_note(EXISTING, _nom())
        self.assertEqual(disposition, "spliced")
        self.assertEqual(text, GOLDEN)
        self.assertEqual(
            hashlib.sha256(text.encode("utf-8")).hexdigest(), GOLDEN_SHA256
        )

    def test_render_block_still_emits_no_unit_anchor(self):
        # The one difference between the two shapes' output, stated from the
        # `body` side: the block it renders has no `<!-- unit:... -->` line.
        # If it ever gains one, the no-op claim is void.
        block = pl.render_block(_nom())
        self.assertNotIn("<!-- unit:", block)
        self.assertEqual(
            block,
            f"{pl.PROMOTED_BEGIN}\n"
            "The newly promoted body.\n"
            "\n"
            "With a second paragraph.\n"
            "[Source: empirical — 2026-07-12]\n"
            f"{pl.PROMOTED_END}\n",
        )

    def test_promote_writes_the_golden_note_and_one_ledger_line(self):
        # The same guarantee end to end, through the real writer. Compared with
        # `read_text`, which normalises the CRLF `write_text` produces on
        # Windows -- the content is byte-for-byte the golden, under whatever
        # line ending the platform writes.
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            ledger = _seed_repo(repo)
            note = repo / "memory" / TARGET
            note.parent.mkdir(parents=True, exist_ok=True)
            note.write_text(EXISTING, encoding="utf-8")

            rc, summary = pl.promote([_nom()], repo_dir=repo)
            self.assertEqual(rc, 0, summary)
            self.assertEqual(note.read_text(encoding="utf-8"), GOLDEN)
            self.assertIn(
                GOLDEN_LEDGER_LINE,
                ledger.read_text(encoding="utf-8").splitlines(),
            )
            # The verb and the per-body hash the summary reports are part of
            # the operator-facing contract, so they are pinned too.
            self.assertIn(
                "overwrite feedback/sample-learning.md — 010bc388f2c5 (empirical)",
                summary,
            )

    def test_body_path_still_prunes_the_targets_superseded_ledger_line(self):
        # `_prune_target_lines` is still here on purpose (#180 defers deleting
        # it), and the `body` path still uses it: one note, one ledger line,
        # exactly as before. The `units` path is append-only instead -- see
        # `test_promote_learnings_units.py`.
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            ledger = _seed_repo(repo)

            rc, summary = pl.promote([_nom(body="First body.")], repo_dir=repo)
            self.assertEqual(rc, 0, summary)
            rc, summary = pl.promote([_nom(body="Second body.")], repo_dir=repo)
            self.assertEqual(rc, 0, summary)

            lines = [
                ln
                for ln in ledger.read_text(encoding="utf-8").splitlines()
                if TARGET in ln
            ]
            self.assertEqual(len(lines), 1, lines)
            self.assertIn(pl.content_hash12("Second body."), lines[0])


class DualShapeAdmissionTest(unittest.TestCase):
    """`body` XOR `units`. Neither is rc 1; both is rc 1."""

    def _promote(self, nom):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            ledger = _seed_repo(repo)
            before = ledger.read_text(encoding="utf-8")
            rc, summary = pl.promote([nom], repo_dir=repo)
            # Phase 1 validates everything before writing, so a rejected
            # nomination must leave the ledger untouched.
            if rc != 0:
                self.assertEqual(ledger.read_text(encoding="utf-8"), before)
            return rc, summary

    def test_neither_body_nor_units_is_rc_1(self):
        nom = _nom()
        del nom["body"]
        rc, summary = self._promote(nom)
        self.assertEqual(rc, 1, summary)
        self.assertTrue(
            any("missing required field" in s and "body or units" in s for s in summary),
            summary,
        )

    def test_both_body_and_units_is_rc_1(self):
        nom = _nom(
            units=[{"text": "A unit.", "source": "empirical", "date": "2026-07-12"}]
        )
        rc, summary = self._promote(nom)
        self.assertEqual(rc, 1, summary)
        self.assertTrue(any("carries both" in s for s in summary), summary)
        # The message has to name both fields -- the remedy is "drop one", and
        # an operator cannot act on it without knowing which two.
        self.assertTrue(
            any("'body'" in s and "'units'" in s for s in summary), summary
        )

    def test_body_alone_takes_the_body_path(self):
        rc, summary = self._promote(_nom())
        self.assertEqual(rc, 0, summary)
        # Per-body hash in the summary, not a unit count: the body path.
        self.assertTrue(
            any("010bc388f2c5 (empirical)" in s for s in summary), summary
        )

    def test_null_units_reads_as_absent_and_the_body_path_still_runs(self):
        # A generator that emits the key unconditionally must not be pushed
        # onto the new path by a null. Same tolerance `is_unrouted` gives a
        # falsey `unrouted` flag, and for the same reason.
        rc, summary = self._promote(_nom(units=None))
        self.assertEqual(rc, 0, summary)
        self.assertTrue(
            any("010bc388f2c5 (empirical)" in s for s in summary), summary
        )
        self.assertFalse(pl.is_units_shaped(_nom(units=None)))

    def test_empty_body_is_still_a_missing_field(self):
        rc, summary = self._promote(_nom(body=""))
        self.assertEqual(rc, 1, summary)
        self.assertTrue(
            any("missing required field" in s and "body or units" in s for s in summary),
            summary,
        )


if __name__ == "__main__":
    unittest.main()
