"""The unrouted-nomination outcome and its durable tally (#168).

ADR 0002 made "a harvest pass reports it cannot determine where to file a
learning" a revisit trigger, and `promote_learnings.REQUIRED_FIELDS` made the
condition **unrepresentable**: a nomination with no `target` failed validation
as malformed, so the trigger could never fire however often the condition
occurred. These tests pin the five properties the fix has to have —

  1. writes no note,
  2. does not count as promoted,
  3. never enters `memory/learning-log.md`,
  4. does not fail the run,
  5. is counted durably,

— plus the two that keep it from becoming a hole in the schema: a declaration
missing its reason is still rejected, and a declaration that also names a target
is rejected rather than silently resolved one way or the other.

Hermetic throughout, in the house style of `tests/test_promote_learnings.py`:
a `tempfile.TemporaryDirectory()` repo, and `CLAUDE_CONFIG_DIR` pointed at a
second temp directory so the tally lands there and never touches the operator's
real `~/.claude/learning-trail`.
"""

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import promote_learnings as pl  # noqa: E402
import _unrouted_record as ur  # noqa: E402
from _learning_common import parse_ledger  # noqa: E402

LEDGER_SEED = "# Learning log\n\nSeed intro.\n\n## Entries\n"


def _seed_repo(repo: Path) -> Path:
    memory = repo / "memory"
    memory.mkdir(parents=True, exist_ok=True)
    ledger = memory / "learning-log.md"
    ledger.write_text(LEDGER_SEED, encoding="utf-8", newline="")
    return ledger


def _routed(**over) -> dict:
    base = {
        "scope": "feedback",
        "target": "feedback/sample-learning.md",
        "name": "feedback-sample-learning",
        "description": "A one-line description.",
        "type": "feedback",
        "body": "The body of the note.\n\nMore detail here.",
        "source": "empirical",
        "date": "2026-10-03",
    }
    base.update(over)
    return base


def _unrouted(**over) -> dict:
    base = {
        "unrouted": True,
        "unrouted_reason": "spans payment and booking; no single repo owns it",
        "name": "cross-service-money-protocol",
        "description": "Who owns the refund clock across two services.",
        "body": "The learning text that could not be placed.",
        "source": "empirical",
        "date": "2026-10-03",
    }
    base.update(over)
    return base


class _TempConfig(unittest.TestCase):
    """Base: a temp repo plus a temp CLAUDE_CONFIG_DIR, restored on teardown."""

    def setUp(self):
        self._repo_tmp = tempfile.TemporaryDirectory()
        self._cfg_tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._repo_tmp.name)
        self.ledger = _seed_repo(self.repo)
        self._saved = os.environ.get("CLAUDE_CONFIG_DIR")
        os.environ["CLAUDE_CONFIG_DIR"] = self._cfg_tmp.name

    def tearDown(self):
        if self._saved is None:
            os.environ.pop("CLAUDE_CONFIG_DIR", None)
        else:
            os.environ["CLAUDE_CONFIG_DIR"] = self._saved
        self._repo_tmp.cleanup()
        self._cfg_tmp.cleanup()

    @property
    def record_file(self) -> Path:
        return ur.record_path(self.repo)


class UnroutedOutcomeTest(_TempConfig):
    def test_writes_no_note_is_not_promoted_and_not_in_the_ledger(self):
        rc, summary = pl.promote([_unrouted()], repo_dir=self.repo)

        # 4. does not fail the run
        self.assertEqual(rc, 0, summary)
        # 1. no note anywhere under memory/ beyond the seeded ledger
        notes = [
            p
            for p in (self.repo / "memory").rglob("*.md")
            if p.name != "learning-log.md"
        ]
        self.assertEqual(notes, [], f"expected no note to be written, got {notes}")
        # 2. not counted as promoted
        self.assertIn("promoted 0, skipped 0, unrouted 1", "\n".join(summary))
        # 3. the ledger is byte-identical to its seed
        self.assertEqual(
            self.ledger.read_text(encoding="utf-8", newline=""), LEDGER_SEED
        )
        self.assertEqual(len(parse_ledger(self.ledger)), 0)

    def test_counted_durably_in_the_trail_directory(self):
        rc, summary = pl.promote([_unrouted()], repo_dir=self.repo)
        self.assertEqual(rc, 0, summary)

        # 5. accumulates durably, outside the per-run staging dir
        self.assertTrue(self.record_file.is_file(), f"no tally at {self.record_file}")
        record = json.loads(self.record_file.read_text(encoding="utf-8", newline=""))
        self.assertEqual(record["count"], 1)
        self.assertEqual(record["version"], ur.RECORD_VERSION)
        self.assertEqual(
            record["entries"][0]["reason"],
            "spans payment and booking; no single repo owns it",
        )

    def test_the_tally_accumulates_across_separate_runs(self):
        """The property `receipt.json` structurally cannot have."""
        for i in range(3):
            rc, summary = pl.promote(
                [_unrouted(name=f"learning-{i}")], repo_dir=self.repo
            )
            self.assertEqual(rc, 0, summary)
        record = json.loads(self.record_file.read_text(encoding="utf-8", newline=""))
        self.assertEqual(record["count"], 3)

    def test_the_tally_lands_outside_the_repo(self):
        """Machine-local state must not become a tracked file in a public repo."""
        pl.promote([_unrouted()], repo_dir=self.repo)
        self.assertFalse(
            str(self.record_file).startswith(str(self.repo)),
            "the unrouted tally must live in the trail dir, not inside the repo",
        )

    def test_the_tally_is_not_swept_up_as_a_session_trail(self):
        """`.jsonl` would be: four callers glob the trail dir for `*.jsonl`."""
        pl.promote([_unrouted()], repo_dir=self.repo)
        self.assertFalse(self.record_file.name.endswith(".jsonl"))
        swept = list(self.record_file.parent.glob("*.jsonl"))
        self.assertEqual(swept, [], f"tally visible to a *.jsonl sweep: {swept}")


class MixedManifestTest(_TempConfig):
    def test_a_routed_nomination_alongside_an_unrouted_one_still_promotes(self):
        """An honest unroutable report must not cost the pass its good work."""
        rc, summary = pl.promote(
            [_unrouted(), _routed()], repo_dir=self.repo
        )
        self.assertEqual(rc, 0, summary)
        note = self.repo / "memory" / "feedback" / "sample-learning.md"
        self.assertTrue(note.is_file(), summary)
        self.assertIn("promoted 1, skipped 0, unrouted 1", "\n".join(summary))
        self.assertEqual(len(parse_ledger(self.ledger)), 1)
        self.assertEqual(
            json.loads(self.record_file.read_text(encoding="utf-8", newline=""))["count"],
            1,
        )

    def test_an_unrouted_body_matching_a_promoted_one_is_not_deduped_away(self):
        """The dedup set is keyed by body hash against the ledger, which an
        unrouted learning never reaches. Consulting it could only ever produce a
        false `skip` against an unrelated note that shared a body."""
        shared = "Identical body text in both nominations."
        rc, summary = pl.promote(
            [_routed(body=shared), _unrouted(body=shared)], repo_dir=self.repo
        )
        self.assertEqual(rc, 0, summary)
        self.assertIn("promoted 1, skipped 0, unrouted 1", "\n".join(summary))
        self.assertEqual(
            json.loads(self.record_file.read_text(encoding="utf-8", newline=""))["count"],
            1,
        )


class DryRunTest(_TempConfig):
    def test_dry_run_records_nothing(self):
        rc, summary = pl.promote([_unrouted()], repo_dir=self.repo, dry_run=True)
        self.assertEqual(rc, 0, summary)
        self.assertIn("would record unrouted", "\n".join(summary))
        self.assertFalse(
            self.record_file.exists(),
            "a dry run must leave no durable record behind",
        )


class MalformedDeclarationTest(_TempConfig):
    def test_a_declaration_without_a_reason_is_rejected(self):
        rc, summary = pl.promote(
            [_unrouted(unrouted_reason="")], repo_dir=self.repo
        )
        self.assertEqual(rc, 1)
        self.assertIn("unrouted_reason", "\n".join(summary))
        self.assertFalse(self.record_file.exists())

    def test_a_declaration_naming_a_target_is_rejected_not_resolved(self):
        rc, summary = pl.promote(
            [_unrouted(target="feedback/x.md")], repo_dir=self.repo
        )
        self.assertEqual(rc, 1)
        joined = "\n".join(summary)
        self.assertIn("must not carry", joined)
        self.assertIn("target", joined)

    def test_a_declaration_naming_a_scope_is_rejected(self):
        rc, summary = pl.promote([_unrouted(scope="feedback")], repo_dir=self.repo)
        self.assertEqual(rc, 1)
        self.assertIn("scope", "\n".join(summary))

    def test_a_declaration_with_an_invalid_source_is_rejected(self):
        rc, summary = pl.promote([_unrouted(source="vibes")], repo_dir=self.repo)
        self.assertEqual(rc, 1)
        self.assertIn("invalid source", "\n".join(summary))

    def test_a_malformed_declaration_after_a_valid_note_writes_nothing(self):
        """Phase 1 validates everything before anything is written."""
        rc, summary = pl.promote(
            [_routed(), _unrouted(unrouted_reason="")], repo_dir=self.repo
        )
        self.assertEqual(rc, 1)
        self.assertFalse((self.repo / "memory" / "feedback").exists(), summary)
        self.assertEqual(
            self.ledger.read_text(encoding="utf-8", newline=""), LEDGER_SEED
        )


class FlagSemanticsTest(unittest.TestCase):
    def test_absent_or_falsey_flag_is_an_ordinary_nomination(self):
        self.assertFalse(pl.is_unrouted(_routed()))
        self.assertFalse(pl.is_unrouted(_routed(unrouted=False)))
        self.assertFalse(pl.is_unrouted(_routed(unrouted=None)))
        self.assertFalse(pl.is_unrouted("not a dict"))

    def test_truthy_flag_switches_paths(self):
        self.assertTrue(pl.is_unrouted(_unrouted()))
        self.assertTrue(pl.is_unrouted(_unrouted(unrouted=1)))


class RecordDegradationTest(_TempConfig):
    """A damaged tally must read as `unknown`, never as a count of zero."""

    def test_unreadable_and_absent_tallies_both_read_as_none(self):
        self.assertIsNone(ur.read_record(self.record_file))

        self.record_file.parent.mkdir(parents=True, exist_ok=True)
        for bad in ("not json at all", "[]", '{"count": "many"}', '"a string"'):
            self.record_file.write_text(bad, encoding="utf-8", newline="")
            self.assertIsNone(ur.read_record(self.record_file), bad)

    def test_an_unrecognised_version_is_not_guessed_at(self):
        self.record_file.parent.mkdir(parents=True, exist_ok=True)
        self.record_file.write_text(
            json.dumps({"version": ur.RECORD_VERSION + 99, "count": 7}),
            encoding="utf-8",
            newline="",
        )
        self.assertIsNone(ur.read_record(self.record_file))

    def test_a_damaged_tally_restarts_rather_than_losing_the_signal(self):
        self.record_file.parent.mkdir(parents=True, exist_ok=True)
        self.record_file.write_text("corrupt", encoding="utf-8", newline="")
        record = ur.append_unrouted(
            self.record_file, reason="r", name="n", date="2026-10-03"
        )
        self.assertEqual(record["count"], 1)

    def test_the_entry_tail_is_bounded_while_the_count_is_not(self):
        for i in range(ur.MAX_ENTRIES + 5):
            record = ur.append_unrouted(
                self.record_file, reason=f"r{i}", name=f"n{i}", date="2026-10-03"
            )
        self.assertEqual(record["count"], ur.MAX_ENTRIES + 5)
        self.assertEqual(len(record["entries"]), ur.MAX_ENTRIES)

    def test_the_record_is_written_without_translating_newlines(self):
        """#83/#84: `.gitattributes` pins `eol=lf`; a CRLF rewrite is the defect."""
        ur.append_unrouted(
            self.record_file,
            reason="r",
            name="n",
            date="2026-10-03",
            now=datetime(2026, 10, 3, tzinfo=timezone.utc),
        )
        self.assertNotIn(b"\r\n", self.record_file.read_bytes())


class PromoteFailureIsNotFatalTest(_TempConfig):
    def test_a_tally_that_cannot_be_written_warns_and_keeps_rc_zero(self):
        """Nothing is half-written on the unrouted path, so there is nothing to
        roll back — and failing would discard promotions that did land."""
        # A directory where the tally file belongs makes the write fail.
        self.record_file.parent.mkdir(parents=True, exist_ok=True)
        self.record_file.mkdir()

        rc, summary = pl.promote([_unrouted(), _routed()], repo_dir=self.repo)
        joined = "\n".join(summary)
        self.assertEqual(rc, 0, joined)
        self.assertIn("not tallied", joined)
        self.assertTrue(
            (self.repo / "memory" / "feedback" / "sample-learning.md").is_file(), joined
        )


if __name__ == "__main__":
    unittest.main()
