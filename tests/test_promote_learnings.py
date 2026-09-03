import io
import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import promote_learnings as pl  # noqa: E402
import _learning_common as lc  # noqa: E402
import wiki_index  # noqa: E402


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


class ManagedBlockTest(unittest.TestCase):
    """Issue #25 (1): promote OWNS a delimited block; content outside it survives."""

    def test_overwrite_preserves_human_content_outside_block(self):
        # (a) A note with a managed block AND human content outside it; a
        # higher-priority nomination updates the block but leaves the human
        # content verbatim.
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            _seed_repo(repo)
            target = "feedback/mixed.md"

            pl.promote(
                [_nom(target=target, source="empirical", date="2026-07-10",
                      body="Original promoted body.")],
                repo_dir=repo,
            )
            note = repo / "memory" / target
            human = "\n## Human notes\n\nHand-written detail that must survive.\n"
            note.write_text(note.read_text(encoding="utf-8") + human, encoding="utf-8")

            rc, summary = pl.promote(
                [_nom(target=target, source="user override", date="2026-07-12",
                      body="Updated promoted body.")],
                repo_dir=repo,
            )
            self.assertEqual(rc, 0, summary)
            out = note.read_text(encoding="utf-8")
            self.assertIn("Updated promoted body.", out)
            self.assertNotIn("Original promoted body.", out)
            # Human content OUTSIDE the block preserved verbatim.
            self.assertIn("## Human notes", out)
            self.assertIn("Hand-written detail that must survive.", out)

    def test_legacy_note_without_block_gets_block_and_keeps_content(self):
        # (b) Legacy migration: existing note with content but NO block markers.
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            _seed_repo(repo)
            target = "feedback/legacy.md"
            note = repo / "memory" / target
            note.parent.mkdir(parents=True, exist_ok=True)
            legacy = (
                "---\nname: legacy\ndescription: old\ntype: feedback\nkeep: me\n---\n"
                "Existing legacy prose that must be preserved.\n"
            )
            note.write_text(legacy, encoding="utf-8")

            rc, summary = pl.promote(
                [_nom(target=target, body="Freshly promoted learning.")],
                repo_dir=repo,
            )
            self.assertEqual(rc, 0, summary)
            out = note.read_text(encoding="utf-8")
            # Nothing deleted.
            self.assertIn("Existing legacy prose that must be preserved.", out)
            # Extra frontmatter key preserved.
            self.assertIn("keep: me", out)
            # A managed block with the new learning was inserted.
            self.assertIn(pl.PROMOTED_BEGIN, out)
            self.assertIn(pl.PROMOTED_END, out)
            self.assertIn("Freshly promoted learning.", out)

    def test_fresh_note_has_frontmatter_then_block(self):
        # (c) Fresh note: frontmatter + block; body+provenance INSIDE the block.
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            _seed_repo(repo)
            nom = _nom()
            rc, summary = pl.promote([nom], repo_dir=repo)
            self.assertEqual(rc, 0, summary)
            out = (repo / "memory" / nom["target"]).read_text(encoding="utf-8")
            self.assertTrue(out.startswith("---\n"))
            self.assertIn(pl.PROMOTED_BEGIN, out)
            self.assertIn(pl.PROMOTED_END, out)
            block = out[out.index(pl.PROMOTED_BEGIN):out.index(pl.PROMOTED_END)]
            self.assertIn("The body of the note.", block)
            self.assertIn(f"[Source: {nom['source']} — {nom['date']}]", block)


class ReindexTest(unittest.TestCase):
    """Issue #25 (2): MEMORY.md indexes regenerated for touched directories."""

    def test_promote_regenerates_memory_index(self):
        # (d) After promote writes a note, that dir's MEMORY.md lists the note.
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            _seed_repo(repo)
            nom = _nom()
            rc, summary = pl.promote([nom], repo_dir=repo)
            self.assertEqual(rc, 0, summary)
            index = repo / "memory" / "feedback" / "MEMORY.md"
            self.assertTrue(index.is_file(), summary)
            idx = index.read_text(encoding="utf-8")
            self.assertIn(nom["name"], idx)
            self.assertIn("sample-learning.md", idx)

    def test_dry_run_writes_no_index_and_prints_would_reindex(self):
        # (e) Dry-run: no note, no MEMORY.md; prints a would-reindex line.
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            _seed_repo(repo)
            nom = _nom()
            rc, summary = pl.promote([nom], repo_dir=repo, dry_run=True)
            self.assertEqual(rc, 0, summary)
            self.assertFalse((repo / "memory" / "feedback" / "sample-learning.md").exists())
            self.assertFalse((repo / "memory" / "feedback" / "MEMORY.md").exists())
            self.assertTrue(any("would reindex" in s for s in summary), summary)


class UnattendedReindexTest(unittest.TestCase):
    """Issue #102 / `ai-os#138`: the unattended reindex must not destroy a
    hand-curated MEMORY.md.

    ``promote()`` reindexes every touched directory at
    ``scripts/promote_learnings.py:479`` — inside a ``try/except Exception``
    whose return code is discarded. That call site is where the downstream
    damage actually happened: nine ADR links across four folders, plus
    hand-written prose, replaced by the output of a non-recursive note walk with
    nobody watching. The other tests of this fix drive ``wiki_index`` directly;
    these two drive the real unattended path, end to end.
    """

    # The `ai-os#138` shape: orientation prose plus links into an `adr/`
    # subdirectory, none of which a non-recursive walk of this folder emits.
    CURATED = (
        "# Feedback index\n"
        "\n"
        "Hand-written orientation: read the ADRs before the notes.\n"
        "\n"
        "- [ADR 0007 — retry budgets](adr/0007-retry-budgets.md) — why the cap exists\n"
        "- [ADR 0011 — idempotency keys](adr/0011-idempotency-keys.md) — the payment path\n"
    )

    def _seed_index(self, repo: Path, text: str) -> Path:
        """Write memory/feedback/MEMORY.md with exactly these bytes.

        ``newline=""`` because byte-for-byte survival is the subject here: the
        default translation would write CRLF on Windows and quietly change what
        "unchanged" means.
        """
        index = repo / "memory" / "feedback" / "MEMORY.md"
        index.parent.mkdir(parents=True, exist_ok=True)
        index.write_text(text, encoding="utf-8", newline="")
        return index

    def test_curated_index_survives_a_real_promote(self):
        # (g) The `ai-os#138` reproduction, through promote_learnings.py:479.
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            _seed_repo(repo)
            index = self._seed_index(repo, self.CURATED)

            nom = _nom()
            rc, summary = pl.promote([nom], repo_dir=repo)
            self.assertEqual(rc, 0, summary)

            out = index.read_bytes()
            # Every curated byte survives, and survives as a *prefix*: the
            # generated block is added after the hand-written content, never in
            # place of it. This is the assertion the old generator failed.
            self.assertTrue(
                out.startswith(self.CURATED.encode("utf-8")),
                f"curated content was not preserved verbatim — got {out!r}",
            )
            text = out.decode("utf-8")
            self.assertIn("adr/0007-retry-budgets.md", text)
            self.assertIn("adr/0011-idempotency-keys.md", text)

            # The promoted note is indexed, in a block that sits below the prose.
            self.assertIn(wiki_index.GENERATED_BEGIN, text)
            self.assertIn(wiki_index.GENERATED_END, text)
            block = text[
                text.index(wiki_index.GENERATED_BEGIN):
                text.index(wiki_index.GENERATED_END)
            ]
            self.assertIn("sample-learning.md", block)
            self.assertGreater(
                text.index(wiki_index.GENERATED_BEGIN),
                text.index("adr/0011-idempotency-keys.md"),
            )
            # The append path announces itself rather than acting silently.
            self.assertTrue(
                any("⚠" in s and "appended" in s for s in summary), summary
            )

    def test_malformed_markers_survive_and_keep_the_promote_rc_at_zero(self):
        # (h) A broken index must not fail a promotion, and must not be written.
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            _seed_repo(repo)
            # A begin marker with no end: the block's extent is unknowable, so
            # the generator refuses. Appending would duplicate the block on every
            # run; truncating at EOF would eat the tail prose.
            malformed = (
                "# Feedback index\n"
                "\n"
                f"{wiki_index.GENERATED_BEGIN}\n"
                "\n"
                "- [stale](gone.md) — someone deleted the end marker by hand\n"
                "\n"
                "Hand-written tail that a truncate-at-EOF repair would eat.\n"
            )
            index = self._seed_index(repo, malformed)
            before = index.read_bytes()

            nom = _nom()
            rc, summary = pl.promote([nom], repo_dir=repo)

            # The promote itself succeeds. regenerate()'s rc 2 is deliberately
            # discarded at promote_learnings.py:479 — a broken index is not a
            # failed promotion — and the note and ledger still land.
            self.assertEqual(rc, 0, summary)
            self.assertTrue((repo / "memory" / nom["target"]).is_file())

            # Not one byte of the broken index was touched.
            self.assertEqual(index.read_bytes(), before)

            # The condition reaches the operator as a summary line...
            self.assertTrue(
                any("⚠" in s and "malformed" in s for s in summary), summary
            )
            # ...and not as an exception swallowed by the best-effort handler,
            # which would have reported it as "reindex failed" instead.
            self.assertFalse(
                any("reindex failed" in s for s in summary), summary
            )


class ProvenanceInBlockTest(unittest.TestCase):
    """Issue #25: contradiction check still reads provenance now stored in-block."""

    def test_existing_provenance_reads_source_from_block(self):
        # (f) existing_provenance reads source/date from a note whose provenance
        # lives inside the managed block.
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            _seed_repo(repo)
            nom = _nom(source="empirical", date="2026-07-12")
            pl.promote([nom], repo_dir=repo)
            note = repo / "memory" / nom["target"]

            prov = pl.existing_provenance(note)
            self.assertEqual(prov, ("empirical", "2026-07-12"))

            out = note.read_text(encoding="utf-8")
            block = out[out.index(pl.PROMOTED_BEGIN):out.index(pl.PROMOTED_END)]
            self.assertIn("[Source:", block)

    def test_stale_source_below_block_is_ignored(self):
        # A migrated legacy note keeps its old body (with a stale [Source]) BELOW
        # the managed block. existing_provenance must read the in-block one, not
        # the file-wide last match.
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            _seed_repo(repo)
            target = "feedback/stale-below.md"
            note = repo / "memory" / target
            note.parent.mkdir(parents=True, exist_ok=True)
            note.write_text(
                "---\nname: n\ndescription: d\ntype: feedback\n---\n"
                f"{pl.PROMOTED_BEGIN}\n"
                "Authoritative in-block learning.\n"
                "[Source: user override — 2026-08-01]\n"
                f"{pl.PROMOTED_END}\n"
                "\n## Legacy body\n\n"
                "Old preserved prose.\n"
                "[Source: empirical — 2026-01-01]\n",
                encoding="utf-8",
            )
            self.assertEqual(
                pl.existing_provenance(note), ("user override", "2026-08-01")
            )


class ReceiptTest(unittest.TestCase):
    """The promotion receipt: an advisory audit record of one promote pass.

    It states what the pass wrote, what it skipped, and when it hit the disk. It
    does not gate `mark_harvested.py`'s watermark — see the module docstrings of
    both scripts for why a same-flow receipt can only prove ordering.
    """

    def _receipt(self, manifest_dir: Path) -> dict:
        path = manifest_dir / "receipt.json"
        self.assertTrue(path.is_file(), f"no receipt at {path}")
        return json.loads(path.read_text(encoding="utf-8"))

    def test_receipt_written_beside_manifest_on_success(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d) / "repo"
            _seed_repo(repo)
            run_dir = Path(d) / "eval" / "learnings" / "20260820T224011"
            run_dir.mkdir(parents=True)
            manifest = run_dir / "manifest.json"

            nom = _nom()
            rc, summary = pl.promote(
                [nom],
                repo_dir=repo,
                receipt_dir=run_dir,
                manifest_arg=str(manifest),
            )
            self.assertEqual(rc, 0, summary)

            data = self._receipt(run_dir)
            self.assertEqual(data["version"], 1)
            self.assertEqual(data["manifest"], str(manifest))
            self.assertEqual(data["promoted"], 1)
            self.assertEqual(data["skipped"], 0)
            self.assertEqual(data["targets"], [nom["target"]])
            # The path is named in the summary so the operator can hand it on.
            self.assertTrue(
                any("receipt" in s and "receipt.json" in s for s in summary), summary
            )

    def test_counts_and_targets_match_what_happened(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d) / "repo"
            _seed_repo(repo)
            run_dir = Path(d) / "run"
            run_dir.mkdir()

            already = _nom(target="feedback/already.md", body="Previously promoted.")
            pl.promote([already], repo_dir=repo)  # no receipt_dir — pure setup

            fresh = _nom(target="feedback/fresh.md", body="Brand new learning.")
            rc, summary = pl.promote(
                [already, fresh],
                repo_dir=repo,
                receipt_dir=run_dir,
                manifest_arg="run/manifest.json",
            )
            self.assertEqual(rc, 0, summary)
            self.assertIn("promoted 1, skipped 1", summary)

            data = self._receipt(run_dir)
            self.assertEqual(data["promoted"], 1)
            self.assertEqual(data["skipped"], 1)
            # Only the written target is listed; the deduped one is absent.
            self.assertEqual(data["targets"], [fresh["target"]])
            self.assertNotIn(already["target"], data["targets"])

    def test_written_at_is_timezone_aware_iso8601(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d) / "repo"
            _seed_repo(repo)
            run_dir = Path(d) / "run"
            run_dir.mkdir()

            rc, summary = pl.promote([_nom()], repo_dir=repo, receipt_dir=run_dir)
            self.assertEqual(rc, 0, summary)

            stamp = datetime.fromisoformat(self._receipt(run_dir)["written_at"])
            self.assertIsNotNone(stamp.tzinfo)
            self.assertIsNotNone(stamp.utcoffset())

    def test_dry_run_writes_no_receipt(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d) / "repo"
            _seed_repo(repo)
            run_dir = Path(d) / "run"
            run_dir.mkdir()

            rc, summary = pl.promote(
                [_nom()], repo_dir=repo, dry_run=True, receipt_dir=run_dir
            )
            self.assertEqual(rc, 0, summary)
            self.assertFalse((run_dir / "receipt.json").exists())
            # The preview stays honest about what it would have written.
            self.assertTrue(any("would write receipt" in s for s in summary), summary)

    def test_no_receipt_when_validation_fails(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d) / "repo"
            _seed_repo(repo)
            run_dir = Path(d) / "run"
            run_dir.mkdir()

            bad = _nom()
            del bad["body"]
            rc, summary = pl.promote([bad], repo_dir=repo, receipt_dir=run_dir)
            self.assertEqual(rc, 1, summary)
            self.assertFalse((run_dir / "receipt.json").exists())

    def test_receipt_written_when_everything_was_skipped(self):
        # promoted 0 is still a factual record of a pass — "read it, promoted
        # nothing new" — and suppressing it would hide the run rather than
        # report it.
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d) / "repo"
            _seed_repo(repo)
            run_dir = Path(d) / "run"
            run_dir.mkdir()

            nom = _nom()
            pl.promote([nom], repo_dir=repo)  # first pass promotes it

            rc, summary = pl.promote([nom], repo_dir=repo, receipt_dir=run_dir)
            self.assertEqual(rc, 0, summary)

            data = self._receipt(run_dir)
            self.assertEqual(data["promoted"], 0)
            self.assertEqual(data["skipped"], 1)
            self.assertEqual(data["targets"], [])

    def test_receipt_write_failure_is_non_fatal(self):
        # A directory sitting where receipt.json belongs makes write_text raise
        # OSError on both POSIX (IsADirectoryError) and Windows (PermissionError).
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d) / "repo"
            _seed_repo(repo)
            run_dir = Path(d) / "run"
            (run_dir / "receipt.json").mkdir(parents=True)

            nom = _nom()
            rc, summary = pl.promote([nom], repo_dir=repo, receipt_dir=run_dir)

            # The notes and ledger already landed — the promote did succeed.
            self.assertEqual(rc, 0, summary)
            self.assertTrue((repo / "memory" / nom["target"]).is_file())
            self.assertTrue(
                any("⚠" in s and "receipt" in s for s in summary), summary
            )

    def test_receipt_failure_warning_does_not_claim_the_stamp_is_blocked(self):
        # The receipt stopped being a gate; the warning used to say otherwise
        # ("mark_harvested.py will refuse to stamp without it"). Pinned as a
        # string so the dead model cannot creep back into the operator-facing
        # text — that drift is what caused the original scope bug.
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d) / "repo"
            _seed_repo(repo)
            run_dir = Path(d) / "run"
            (run_dir / "receipt.json").mkdir(parents=True)

            rc, summary = pl.promote([_nom()], repo_dir=repo, receipt_dir=run_dir)
            self.assertEqual(rc, 0, summary)

            warning = next(s for s in summary if "⚠" in s and "receipt" in s)
            self.assertNotIn("refuse", warning)
            self.assertNotIn("will refuse to stamp without it", warning)
            # The useful half survives: the promote itself succeeded...
            self.assertIn("the promote succeeded", warning)
            # ...and the honest downstream behaviour is named.
            self.assertIn("stamps anyway", warning)

    def test_module_docstring_describes_the_receipt_as_advisory(self):
        # promote_learnings.py and mark_harvested.py must not describe the same
        # object in contradictory terms.
        doc = pl.__doc__ or ""
        self.assertIn("audit record, not a gate", doc)
        self.assertIn("does **not** authorise", doc)
        self.assertNotIn("must not be\nstampable on trust alone", doc)

    def test_write_receipt_helper_emits_the_schema(self):
        # The helper is the single source of the shape mark_harvested.py parses.
        with tempfile.TemporaryDirectory() as d:
            path = pl.write_receipt(
                Path(d) / "nested",
                manifest="eval/learnings/x/manifest.json",
                promoted=3,
                skipped=0,
                targets=["repo/holo-mind/foo.md", "repo/holo-mind/bar.md"],
            )
            self.assertEqual(path.name, "receipt.json")
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(
                sorted(data),
                ["manifest", "promoted", "skipped", "targets", "version", "written_at"],
            )
            self.assertEqual(data["version"], 1)
            self.assertEqual(data["manifest"], "eval/learnings/x/manifest.json")
            self.assertEqual(data["promoted"], 3)
            self.assertEqual(data["skipped"], 0)
            self.assertEqual(
                data["targets"], ["repo/holo-mind/foo.md", "repo/holo-mind/bar.md"]
            )
            # Indented JSON with a trailing newline, so it diffs readably.
            self.assertTrue(path.read_text(encoding="utf-8").endswith("\n"))
            self.assertIn('\n  "version": 1', path.read_text(encoding="utf-8"))

    def test_manifest_falls_back_to_empty_string(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d) / "repo"
            _seed_repo(repo)
            run_dir = Path(d) / "run"
            run_dir.mkdir()

            rc, summary = pl.promote([_nom()], repo_dir=repo, receipt_dir=run_dir)
            self.assertEqual(rc, 0, summary)
            self.assertEqual(self._receipt(run_dir)["manifest"], "")

    def test_default_receipt_dir_none_writes_nothing(self):
        # Every pre-existing caller passes no receipt_dir and must stay unchanged.
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            _seed_repo(repo)
            rc, summary = pl.promote([_nom()], repo_dir=repo)
            self.assertEqual(rc, 0, summary)
            self.assertEqual(list(repo.rglob("receipt.json")), [])


class ConsoleEncodingTest(unittest.TestCase):
    """Issue #55: a cp1252 console must not turn a successful promote into a crash.

    ``promote()`` writes every note, then ``main()`` prints the summary — which
    carries ``→`` (U+2192) and ``⚠`` (U+26A0). Neither maps to cp1252, the
    default console encoding on Windows, so an unguarded ``print`` raised
    UnicodeEncodeError *after* all the writes had already landed and the caller
    saw a non-zero exit for a run that fully succeeded.
    """

    # A summary shaped like the real one, carrying both offending glyphs. The ⚠
    # line is the receipt-failure warning promote() emits at the end of a
    # succeeded-but-unrecorded run — the surviving non-ASCII warning now that the
    # ledger-cap warning is gone.
    GLYPH_SUMMARY = [
        "wrote     feedback/sample.md — abc123abc123 (empirical)",
        "reindexed memory/feedback/MEMORY.md → 3 notes",
        "promoted 1, skipped 0",
        "⚠  receipt not written to eval/learnings/20260101-000000/receipt.json: "
        "[Errno 13] Permission denied — the promote succeeded; only the audit "
        "record is missing.",
    ]

    def _run_main(self, manifest: Path):
        """Drive main() with a stdout that really is cp1252-backed.

        A TextIOWrapper over BytesIO behaves like the legacy console: it raises
        on unencodable characters, and — unlike the StringIO used elsewhere in
        the suite — it does have ``reconfigure``, so the guard is exercised for
        real rather than swallowed by the try/except.
        """
        stream = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
        argv = ["promote_learnings.py", str(manifest)]
        with mock.patch.object(sys, "stdout", stream), \
                mock.patch.object(sys, "argv", argv), \
                mock.patch.object(
                    pl, "promote",
                    lambda records, **kw: (0, self.GLYPH_SUMMARY)):
            rc = pl.main()
        stream.flush()
        return rc, stream.buffer.getvalue().decode(stream.encoding)

    def test_main_prints_summary_glyphs_on_a_cp1252_console(self):
        with tempfile.TemporaryDirectory() as d:
            manifest = Path(d) / "manifest.json"
            manifest.write_text("[]", encoding="utf-8")

            rc, out = self._run_main(manifest)

            self.assertEqual(rc, 0)
            # Both glyphs actually reached the stream — not dropped, not replaced.
            self.assertIn("⚠", out)
            self.assertIn("→", out)
            # And the whole warning line came through, not just its glyph.
            self.assertIn("receipt not written to", out)


if __name__ == "__main__":
    unittest.main()
