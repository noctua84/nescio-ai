import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import promote_learnings as pl  # noqa: E402
import _learning_common as lc  # noqa: E402


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
        "body": "The body of the note.\n\nMore detail here.",
        "source": "empirical",
        "date": "2026-07-12",
    }
    base.update(over)
    return base


class FreshPromotionTest(unittest.TestCase):
    def test_writes_note_and_appends_ledger(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            ledger = _seed_repo(repo)
            nom = _nom()

            rc, summary = pl.promote([nom], repo_dir=repo)
            self.assertEqual(rc, 0, summary)

            note = repo / "memory" / nom["target"]
            self.assertTrue(note.is_file())
            text = note.read_text(encoding="utf-8")

            # Frontmatter fields.
            self.assertIn(f"name: {nom['name']}", text)
            self.assertIn(f"description: {nom['description']}", text)
            self.assertIn(f"type: {nom['type']}", text)
            self.assertTrue(text.startswith("---\n"))
            # Body.
            self.assertIn("The body of the note.", text)
            # Provenance line.
            self.assertIn(f"[Source: {nom['source']} — {nom['date']}]", text)

            # Ledger line appended with the body hash.
            h = lc.content_hash12(nom["body"])
            ledger_text = ledger.read_text(encoding="utf-8")
            self.assertIn(
                f"- {nom['date']} | {nom['target']} | {h} | promoted: {nom['name']}",
                ledger_text,
            )
            self.assertIn(h, lc.parse_ledger(ledger))

    def test_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            ledger = _seed_repo(repo)
            before = ledger.read_text(encoding="utf-8")

            rc, summary = pl.promote([_nom()], repo_dir=repo, dry_run=True)
            self.assertEqual(rc, 0)
            self.assertFalse((repo / "memory" / "feedback" / "sample-learning.md").exists())
            self.assertEqual(ledger.read_text(encoding="utf-8"), before)


class DedupTest(unittest.TestCase):
    def test_same_manifest_twice_does_not_duplicate(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            ledger = _seed_repo(repo)
            nom = _nom()

            pl.promote([nom], repo_dir=repo)
            first = ledger.read_text(encoding="utf-8")

            rc, summary = pl.promote([nom], repo_dir=repo)
            self.assertEqual(rc, 0)
            self.assertEqual(ledger.read_text(encoding="utf-8"), first)
            self.assertTrue(any("dedup" in s for s in summary), summary)

            # Exactly one ledger entry for this hash.
            h = lc.content_hash12(nom["body"])
            count = sum(
                1 for ln in ledger.read_text(encoding="utf-8").splitlines()
                if f"| {h} |" in ln
            )
            self.assertEqual(count, 1)


class ContradictionTest(unittest.TestCase):
    def test_agent_inference_does_not_overwrite_user_override(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            _seed_repo(repo)
            target = "feedback/contested.md"

            # Existing note authored by a user override.
            pl.promote(
                [_nom(target=target, source="user override", date="2026-07-10",
                      body="Original: user override wins.")],
                repo_dir=repo,
            )
            note = repo / "memory" / target
            original = note.read_text(encoding="utf-8")

            # A later agent inference must NOT overwrite it.
            rc, summary = pl.promote(
                [_nom(target=target, source="agent inference", date="2026-07-12",
                      body="Weaker: agent inference should lose.")],
                repo_dir=repo,
            )
            self.assertEqual(rc, 0)
            self.assertEqual(note.read_text(encoding="utf-8"), original)
            self.assertTrue(any("contradiction" in s for s in summary), summary)

    def test_user_override_overwrites_agent_inference(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            _seed_repo(repo)
            target = "feedback/contested.md"

            pl.promote(
                [_nom(target=target, source="agent inference", date="2026-07-10",
                      body="Original: agent inference.")],
                repo_dir=repo,
            )
            note = repo / "memory" / target

            rc, summary = pl.promote(
                [_nom(target=target, source="user override", date="2026-07-12",
                      body="Stronger: user override wins.")],
                repo_dir=repo,
            )
            self.assertEqual(rc, 0)
            text = note.read_text(encoding="utf-8")
            self.assertIn("Stronger: user override wins.", text)
            self.assertIn("[Source: user override — 2026-07-12]", text)


class InvalidSourceTest(unittest.TestCase):
    def test_invalid_source_errors(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            _seed_repo(repo)
            rc, summary = pl.promote(
                [_nom(source="hearsay")], repo_dir=repo
            )
            self.assertEqual(rc, 1)
            self.assertTrue(any("invalid source" in s for s in summary), summary)
            # Nothing written.
            self.assertFalse((repo / "memory" / "feedback" / "sample-learning.md").exists())


class CapWarningTest(unittest.TestCase):
    def test_warns_past_max_ledger_lines(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            ledger = _seed_repo(repo)
            # Pad the ledger past the cap with pre-existing entries.
            padding = "\n".join(
                f"- 2026-01-01 | feedback/old-{i}.md | {i:012x} | promoted: old-{i}"
                for i in range(lc.MAX_LEDGER_LINES + 1)
            )
            ledger.write_text(LEDGER_SEED + padding + "\n", encoding="utf-8")

            rc, summary = pl.promote([_nom()], repo_dir=repo)
            self.assertEqual(rc, 0)
            self.assertTrue(
                any(str(lc.MAX_LEDGER_LINES) in s and "⚠" in s for s in summary),
                summary,
            )


class TargetContainmentTest(unittest.TestCase):
    def _ledger_unchanged_and_no_escape(self, repo, ledger, before):
        # rc 1, ledger untouched, nothing written outside memory/.
        self.assertEqual(ledger.read_text(encoding="utf-8"), before)

    def test_absolute_target_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            ledger = _seed_repo(repo)
            before = ledger.read_text(encoding="utf-8")

            # An absolute POSIX path and a Windows-style one both resolve outside
            # memory/ when joined; either must be rejected.
            rc, summary = pl.promote(
                [_nom(target="/etc/evil.md")], repo_dir=repo
            )
            self.assertEqual(rc, 1)
            self.assertTrue(any("escapes memory/" in s for s in summary), summary)
            self._ledger_unchanged_and_no_escape(repo, ledger, before)

    def test_dotdot_target_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            ledger = _seed_repo(repo)
            before = ledger.read_text(encoding="utf-8")

            rc, summary = pl.promote(
                [_nom(target="../secret.md")], repo_dir=repo
            )
            self.assertEqual(rc, 1)
            self.assertTrue(any("escapes memory/" in s for s in summary), summary)
            # The escaping file was NOT created next to memory/.
            self.assertFalse((repo / "secret.md").exists())
            self._ledger_unchanged_and_no_escape(repo, ledger, before)


class RequiredFieldsTest(unittest.TestCase):
    def _assert_missing(self, field):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            ledger = _seed_repo(repo)
            before = ledger.read_text(encoding="utf-8")

            nom = _nom()
            del nom[field]
            rc, summary = pl.promote([nom], repo_dir=repo)
            self.assertEqual(rc, 1, summary)
            self.assertTrue(
                any("missing required field" in s and field in s for s in summary),
                summary,
            )
            self.assertEqual(ledger.read_text(encoding="utf-8"), before)

    def test_missing_body_rejected(self):
        self._assert_missing("body")

    def test_missing_target_rejected(self):
        self._assert_missing("target")

    def test_missing_date_rejected(self):
        self._assert_missing("date")

    def test_malformed_nom_after_valid_one_writes_nothing(self):
        # A valid nomination followed by a malformed one: because validation runs
        # up front, the valid note must NOT be partially written.
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            ledger = _seed_repo(repo)
            before = ledger.read_text(encoding="utf-8")

            good = _nom(target="feedback/good.md", body="Good note body.")
            bad = _nom(target="feedback/bad.md")
            del bad["body"]

            rc, summary = pl.promote([good, bad], repo_dir=repo)
            self.assertEqual(rc, 1, summary)
            self.assertFalse((repo / "memory" / "feedback" / "good.md").exists())
            self.assertFalse((repo / "memory" / "feedback" / "bad.md").exists())
            self.assertEqual(ledger.read_text(encoding="utf-8"), before)

    def test_invalid_scope_bucket_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            _seed_repo(repo)
            rc, summary = pl.promote(
                [_nom(scope="nonsense")], repo_dir=repo
            )
            self.assertEqual(rc, 1)
            self.assertTrue(any("invalid scope" in s for s in summary), summary)


class SameSourceRefinementTest(unittest.TestCase):
    def _target_line_count(self, ledger, target):
        return sum(
            1
            for ln in ledger.read_text(encoding="utf-8").splitlines()
            if f"| {target} |" in ln
        )

    def test_same_day_same_source_body_edit_overwrites_and_prunes(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            ledger = _seed_repo(repo)
            target = "feedback/refine.md"

            first = _nom(
                target=target,
                source="empirical",
                date="2026-07-12",
                body="First take on the note.",
            )
            pl.promote([first], repo_dir=repo)
            h1 = lc.content_hash12(first["body"])

            # Same source, same day, edited body — must overwrite (not skip as a
            # contradiction) and replace the stale ledger line rather than append.
            second = _nom(
                target=target,
                source="empirical",
                date="2026-07-12",
                body="Corrected take on the note.",
            )
            rc, summary = pl.promote([second], repo_dir=repo)
            self.assertEqual(rc, 0, summary)

            note = repo / "memory" / target
            text = note.read_text(encoding="utf-8")
            self.assertIn("Corrected take on the note.", text)
            self.assertNotIn("First take on the note.", text)

            h2 = lc.content_hash12(second["body"])
            ledger_text = ledger.read_text(encoding="utf-8")
            # Exactly one ledger line for the target, keyed by the NEW body hash.
            self.assertEqual(self._target_line_count(ledger, target), 1)
            self.assertIn(f"| {h2} |", ledger_text)
            self.assertNotIn(f"| {h1} |", ledger_text)


class HashHelperTest(unittest.TestCase):
    def test_content_hash12_returns_twelve_hex(self):
        h = lc.content_hash12("some body text")
        self.assertEqual(len(h), 12)
        self.assertTrue(all(c in "0123456789abcdef" for c in h))
        # Stable across calls.
        self.assertEqual(h, lc.content_hash12("some body text"))

    def test_old_misnamed_helper_is_gone(self):
        self.assertFalse(hasattr(lc, "sha8_text"))


class DryRunManifestDedupTest(unittest.TestCase):
    def test_two_identical_bodies_dedup_in_dry_run(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            _seed_repo(repo)

            a = _nom(target="feedback/a.md", body="Identical body.")
            b = _nom(target="feedback/b.md", body="Identical body.")

            rc, summary = pl.promote([a, b], repo_dir=repo, dry_run=True)
            self.assertEqual(rc, 0, summary)
            # First reports a would-write; the second (same body hash) dedups.
            self.assertTrue(any("would" in s for s in summary), summary)
            self.assertTrue(any("dedup" in s for s in summary), summary)
            self.assertIn("[dry-run] promoted 1, skipped 1", summary)


if __name__ == "__main__":
    unittest.main()
