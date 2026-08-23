import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "hooks"))
sys.path.insert(0, str(ROOT / "scripts"))
import record_stop as rs  # noqa: E402
import compute_readiness as cr  # noqa: E402

# `tests/` is synced to instances by scripts/sync_from_upstream.py; `memory/` is
# deliberately not. So a framework test may only depend on framework-owned
# content — the fixture, not the shipped example note it mirrors.
EXAMPLE_READINESS_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "example_readiness.md"
EXAMPLE_READINESS_SHIPPED = ROOT / "memory" / "repo" / "EXAMPLE" / "readiness.md"


# ── helpers ────────────────────────────────────────────────────────────────

def _rec(ts, git_root, *, session="s1", repo_root=None, branch="main",
         prompt_id="p1", preview="hello"):
    """A trail record.

    Without ``repo_root`` this is exactly the legacy six-field shape that all
    2,101 pre-#66 records carry — no ``repo_root``, no ``transcript_path``.
    """
    rec = {
        "ts": ts,
        "session_id": session,
        "git_root": git_root,
        "git_branch": branch,
        "prompt_id": prompt_id,
        "message_preview": preview,
    }
    if repo_root is not None:
        rec["repo_root"] = repo_root
    return rec


def _seed_trail(trail_dir: Path, name: str, records, *, watermark=None):
    """Write a real ``<name>.jsonl`` trail (+ optional watermark); return its path."""
    trail_dir.mkdir(parents=True, exist_ok=True)
    path = trail_dir / f"{name}.jsonl"
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records),
        encoding="utf-8",
    )
    if watermark is not None:
        rs.write_watermark(rs.watermark_path(path), watermark)
    return path


def _make_repo_mem(memory_root: Path, name: str, *, readiness: str | None = None):
    """Build ``memory_root/repo/<name>/``, optionally with a readiness.md."""
    repo_mem = memory_root / "repo" / name
    repo_mem.mkdir(parents=True, exist_ok=True)
    if readiness is not None:
        (repo_mem / "readiness.md").write_text(readiness, encoding="utf-8")
    return repo_mem


def _ledger(memory_root: Path, lines):
    """Write a learning-log.md ledger with the given ``- date | target | hash | ...`` lines."""
    memory_root.mkdir(parents=True, exist_ok=True)
    body = "# learning log\n\n" + "".join(f"{ln}\n" for ln in lines)
    (memory_root / "learning-log.md").write_text(body, encoding="utf-8")


TODAY = date(2026, 8, 20)


# ── path normalisation + attribution ───────────────────────────────────────

class PosixPathTest(unittest.TestCase):
    def test_backslashes_become_slashes(self):
        self.assertEqual(cr.posix_path("C:\\a\\b"), "C:/a/b")

    def test_trailing_slash_stripped(self):
        self.assertEqual(cr.posix_path("C:/a/b/"), "C:/a/b")

    def test_none_is_empty(self):
        self.assertEqual(cr.posix_path(None), "")


class StripWorktreeTest(unittest.TestCase):
    def test_matches_worktree_layout(self):
        self.assertEqual(
            cr.strip_worktree("C:/p/repo/.claude/worktrees/feat-x"), "C:/p/repo"
        )

    def test_plain_path_is_none(self):
        self.assertIsNone(cr.strip_worktree("C:/p/repo"))

    def test_container_dir_without_name_is_none(self):
        # `<repo>/.claude/worktrees` is the container, not a checkout.
        self.assertIsNone(cr.strip_worktree("C:/p/repo/.claude/worktrees/"))

    def test_nested_worktree_resolves_to_outermost_repo(self):
        self.assertEqual(
            cr.strip_worktree("C:/p/repo/.claude/worktrees/a/.claude/worktrees/b"),
            "C:/p/repo",
        )


class ResolveRepoRootTest(unittest.TestCase):
    def test_repo_root_wins_over_worktree_parse(self):
        # #66 records the durable identity at source; it must beat any parse.
        rec = _rec("2026-08-01T00:00:00+00:00",
                   "C:/p/wrong/.claude/worktrees/w",
                   repo_root="C:/p/right")
        self.assertEqual(cr.resolve_repo_root(rec, resolve_live=False), "C:/p/right")

    def test_legacy_six_field_record_attributes_via_pattern(self):
        rec = _rec("2026-08-01T00:00:00+00:00", "C:/p/repo/.claude/worktrees/feat-x")
        self.assertNotIn("repo_root", rec)
        self.assertNotIn("transcript_path", rec)
        self.assertEqual(cr.resolve_repo_root(rec, resolve_live=False), "C:/p/repo")

    def test_deleted_worktree_still_attributes(self):
        # The path does not exist on disk; live resolution cannot help, and the
        # textual pattern must still recover the repository. resolve_live=True
        # proves the pattern runs *before* the subprocess.
        ghost = "C:/nope/never-existed/.claude/worktrees/gone-42"
        self.assertFalse(Path(ghost).exists())
        rec = _rec("2026-08-01T00:00:00+00:00", ghost)
        self.assertEqual(
            cr.resolve_repo_root(rec, resolve_live=True), "C:/nope/never-existed"
        )

    def test_unresolvable_path_falls_back_to_git_root(self):
        rec = _rec("2026-08-01T00:00:00+00:00", "C:/nope/plain-repo")
        self.assertEqual(
            cr.resolve_repo_root(rec, resolve_live=False), "C:/nope/plain-repo"
        )

    def test_live_resolution_is_cached_per_distinct_path(self):
        cache: dict[str, str] = {}
        rec = _rec("2026-08-01T00:00:00+00:00", "C:/nope/plain-repo")
        cr.resolve_repo_root(rec, resolve_live=True, cache=cache)
        self.assertIn("C:/nope/plain-repo", cache)
        # Second call is served from the cache — no second subprocess.
        self.assertEqual(
            cr.resolve_repo_root(rec, resolve_live=True, cache=cache),
            "C:/nope/plain-repo",
        )


class RepoNameTest(unittest.TestCase):
    def test_basename(self):
        self.assertEqual(cr.repo_name("C:/p/my-repo"), "my-repo")

    def test_no_basename_degrades_to_path(self):
        self.assertEqual(cr.repo_name("myrepo"), "myrepo")


# ── aggregation ────────────────────────────────────────────────────────────

class CollectActivityTest(unittest.TestCase):
    def test_several_worktrees_of_one_repo_collapse_to_one_bucket(self):
        with tempfile.TemporaryDirectory() as d:
            trail = Path(d) / "learning-trail"
            base = "C:/p/myrepo"
            _seed_trail(trail, "main", [
                _rec("2026-08-01T10:00:00+00:00", base, session="a"),
            ])
            _seed_trail(trail, "wt1", [
                _rec("2026-08-02T10:00:00+00:00", f"{base}/.claude/worktrees/one",
                     session="b"),
                _rec("2026-08-03T10:00:00+00:00", f"{base}/.claude/worktrees/one",
                     session="b"),
            ])
            _seed_trail(trail, "wt2", [
                _rec("2026-08-04T10:00:00+00:00", f"{base}/.claude/worktrees/two",
                     session="c"),
            ])
            buckets = cr.collect_activity(trail, resolve_live=False)
            self.assertEqual(list(buckets), ["myrepo"])
            self.assertEqual(buckets["myrepo"]["turns"], 4)
            self.assertEqual(len(buckets["myrepo"]["sessions"]), 3)

    def test_mixed_separators_produce_one_bucket(self):
        with tempfile.TemporaryDirectory() as d:
            trail = Path(d) / "learning-trail"
            _seed_trail(trail, "a", [
                _rec("2026-08-01T10:00:00+00:00", "C:/p/myrepo"),
                _rec("2026-08-02T10:00:00+00:00", "C:\\p\\myrepo"),
                _rec("2026-08-03T10:00:00+00:00",
                     "C:\\p\\myrepo\\.claude\\worktrees\\feat"),
            ])
            buckets = cr.collect_activity(trail, resolve_live=False)
            self.assertEqual(list(buckets), ["myrepo"])
            self.assertEqual(buckets["myrepo"]["roots"], {"C:/p/myrepo"})
            self.assertEqual(buckets["myrepo"]["turns"], 3)

    def test_malformed_lines_are_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            trail = Path(d) / "learning-trail"
            trail.mkdir(parents=True)
            (trail / "a.jsonl").write_text(
                json.dumps(_rec("2026-08-01T10:00:00+00:00", "C:/p/myrepo")) + "\n"
                "not json\n"
                "\n"
                "[1,2,3]\n",
                encoding="utf-8",
            )
            buckets = cr.collect_activity(trail, resolve_live=False)
            self.assertEqual(buckets["myrepo"]["turns"], 1)

    def test_missing_trail_dir_is_empty(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(cr.collect_activity(Path(d) / "absent"), {})


class UnharvestedTest(unittest.TestCase):
    def test_counts_only_records_newer_than_watermark(self):
        with tempfile.TemporaryDirectory() as d:
            trail = Path(d) / "learning-trail"
            wm = datetime(2026, 8, 2, tzinfo=timezone.utc)
            _seed_trail(trail, "a", [
                _rec("2026-08-01T10:00:00+00:00", "C:/p/myrepo"),  # older
                _rec("2026-08-02T00:00:00+00:00", "C:/p/myrepo"),  # equal, harvested
                _rec("2026-08-03T10:00:00+00:00", "C:/p/myrepo"),  # newer
                _rec("2026-08-04T10:00:00+00:00", "C:/p/myrepo"),  # newer
            ], watermark=wm)
            buckets = cr.collect_activity(trail, resolve_live=False)
            self.assertEqual(buckets["myrepo"]["turns"], 4)
            self.assertEqual(buckets["myrepo"]["unharvested"], 2)

    def test_no_watermark_means_everything_is_unharvested(self):
        with tempfile.TemporaryDirectory() as d:
            trail = Path(d) / "learning-trail"
            path = _seed_trail(trail, "a", [
                _rec("2026-08-01T10:00:00+00:00", "C:/p/myrepo"),
                _rec("2026-08-02T10:00:00+00:00", "C:/p/myrepo"),
                _rec("2026-08-03T10:00:00+00:00", "C:/p/myrepo"),
            ])
            self.assertFalse(rs.watermark_path(path).exists())
            buckets = cr.collect_activity(trail, resolve_live=False)
            self.assertEqual(buckets["myrepo"]["unharvested"], 3)

    def test_per_trail_watermarks_apply_after_collapsing_to_one_repo(self):
        # Two worktrees of one repo, harvested at different times: each record is
        # judged against *its own* trail's watermark, not a merged one.
        with tempfile.TemporaryDirectory() as d:
            trail = Path(d) / "learning-trail"
            base = "C:/p/myrepo"
            _seed_trail(trail, "wt1", [
                _rec("2026-08-05T10:00:00+00:00", f"{base}/.claude/worktrees/one"),
            ], watermark=datetime(2026, 8, 1, tzinfo=timezone.utc))  # -> unharvested
            _seed_trail(trail, "wt2", [
                _rec("2026-08-05T10:00:00+00:00", f"{base}/.claude/worktrees/two"),
            ], watermark=datetime(2026, 8, 9, tzinfo=timezone.utc))  # -> harvested
            buckets = cr.collect_activity(trail, resolve_live=False)
            self.assertEqual(buckets["myrepo"]["turns"], 2)
            self.assertEqual(buckets["myrepo"]["unharvested"], 1)


class SummariseTest(unittest.TestCase):
    def test_span_recency_sessions_and_promotions(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            trail = root / "learning-trail"
            memory = root / "memory"
            _seed_trail(trail, "a", [
                _rec("2026-08-10T10:00:00+00:00", "C:/p/myrepo", session="s1"),
                _rec("2026-08-12T10:00:00+00:00", "C:/p/myrepo", session="s2"),
                _rec("2026-08-18T10:00:00+00:00", "C:/p/myrepo", session="s2"),
                _rec("2026-08-11T10:00:00+00:00", "C:/p/myrepo", session=""),
            ])
            _ledger(memory, [
                "- 2026-08-11 | repo/myrepo/loop.md | aaaaaaaaaaaa | promoted: loop",
                "- 2026-08-12 | repo/myrepo/adr/0001-x.md | bbbbbbbbbbbb | promoted: x",
                "- 2026-08-13 | repo/other/thing.md | cccccccccccc | promoted: thing",
                "- 2026-08-14 | feedback/bar.md | dddddddddddd | promoted: bar",
            ])
            (stats,) = cr.summarise(trail, memory, resolve_live=False, today=TODAY)
            self.assertEqual(stats["repo"], "myrepo")
            self.assertEqual(stats["turns"], 4)
            # Empty session_id is not a distinct session.
            self.assertEqual(stats["sessions"], 2)
            self.assertEqual(stats["first_date"], "2026-08-10")
            self.assertEqual(stats["last_date"], "2026-08-18")
            self.assertEqual(stats["recency_days"], 2)
            self.assertEqual(stats["promotions"], 2)

    def test_promotions_match_only_the_repo_prefix(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            trail = root / "learning-trail"
            memory = root / "memory"
            _seed_trail(trail, "a", [_rec("2026-08-10T10:00:00+00:00", "C:/p/my")])
            _ledger(memory, [
                # `repo/my-other/` must not match the `my` bucket.
                "- 2026-08-11 | repo/my-other/x.md | aaaaaaaaaaaa | promoted: x",
                "- 2026-08-11 | repo/my/x.md | bbbbbbbbbbbb | promoted: x",
            ])
            (stats,) = cr.summarise(trail, memory, resolve_live=False, today=TODAY)
            self.assertEqual(stats["promotions"], 1)

    def test_results_sorted_by_repo_name(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            trail = root / "learning-trail"
            _seed_trail(trail, "a", [
                _rec("2026-08-10T10:00:00+00:00", "C:/p/zeta"),
                _rec("2026-08-10T10:00:00+00:00", "C:/p/alpha"),
            ])
            stats = cr.summarise(trail, root / "memory", resolve_live=False,
                                 today=TODAY)
            self.assertEqual([s["repo"] for s in stats], ["alpha", "zeta"])


# ── the invariant: only bytes between the markers change ───────────────────

HANDWRITTEN = """---
last_updated: 2026-01-01
custom_key: keep me
shipped: 12
---

# myrepo — readiness

## Outcome summary

Three of the last five sessions ended clean. The two that did not both stalled
on the same flaky integration test.

## Recurring flags

- Migrations get written without a rollback path.
- The e2e suite is skipped under time pressure.

## Notes

Deep hand-written prose that the generator must never touch. Ever.
"""


def _stats(repo="myrepo", **over):
    base = {
        "repo": repo,
        "roots": ["C:/p/myrepo"],
        "turns": 12,
        "sessions": 3,
        "first_date": "2026-08-10",
        "last_date": "2026-08-18",
        "recency_days": 2,
        "unharvested": 4,
        "promotions": 1,
    }
    base.update(over)
    return base


class ComposeTest(unittest.TestCase):
    def test_handwritten_prose_survives_a_run(self):
        """#25/#45 regression: whole-file overwrite discarded existing content."""
        out = cr.compose(HANDWRITTEN, _stats(), "2026-08-20")
        for fragment in (
            "Three of the last five sessions ended clean.",
            "on the same flaky integration test.",
            "- Migrations get written without a rollback path.",
            "- The e2e suite is skipped under time pressure.",
            "Deep hand-written prose that the generator must never touch. Ever.",
            "## Outcome summary",
            "## Recurring flags",
            "## Notes",
            "custom_key: keep me",
            "shipped: 12",
            "# myrepo — readiness",
        ):
            self.assertIn(fragment, out, fragment)
        # And the file grew: the block was added, nothing was replaced.
        self.assertIn(cr.GENERATED_BEGIN, out)
        self.assertIn(cr.GENERATED_END, out)
        self.assertGreater(len(out), len(HANDWRITTEN))

    def test_only_the_block_and_last_updated_change_on_a_second_pass(self):
        first = cr.compose(HANDWRITTEN, _stats(), "2026-08-20")
        second = cr.compose(first, _stats(turns=99, unharvested=0), "2026-08-21")
        # Everything outside the markers is byte-identical apart from the one
        # permitted frontmatter field.
        def outside(text):
            b = text.index(cr.GENERATED_BEGIN)
            e = text.index(cr.GENERATED_END) + len(cr.GENERATED_END)
            return text[:b] + text[e:]
        self.assertEqual(
            outside(first).replace("last_updated: 2026-08-20", "X"),
            outside(second).replace("last_updated: 2026-08-21", "X"),
        )
        self.assertIn("Turns recorded: 99", second)
        self.assertNotIn("Turns recorded: 12", second)

    def test_running_twice_is_byte_identical(self):
        first = cr.compose(HANDWRITTEN, _stats(), "2026-08-20")
        second = cr.compose(first, _stats(), "2026-08-20")
        self.assertEqual(first, second)

    def test_unchanged_input_on_a_later_day_does_not_bump_last_updated(self):
        # last_updated is bumped only when the block actually changed, so a
        # re-run on an unchanged trail leaves the file byte-identical.
        first = cr.compose(HANDWRITTEN, _stats(), "2026-08-20")
        again = cr.compose(first, _stats(), "2026-09-01")
        self.assertEqual(first, again)
        self.assertIn("last_updated: 2026-08-20", again)

    def test_file_without_markers_gains_them_at_the_end(self):
        out = cr.compose(HANDWRITTEN, _stats(), "2026-08-20")
        self.assertTrue(out.index(cr.GENERATED_BEGIN) > out.index("## Notes"))

    def test_markers_are_rewritten_wherever_the_human_moved_them(self):
        moved = HANDWRITTEN.replace(
            "## Recurring flags",
            f"{cr.GENERATED_BEGIN}\nstale content\n{cr.GENERATED_END}\n\n"
            "## Recurring flags",
        )
        out = cr.compose(moved, _stats(), "2026-08-20")
        self.assertNotIn("stale content", out)
        self.assertLess(out.index(cr.GENERATED_BEGIN), out.index("## Recurring flags"))
        self.assertIn("Deep hand-written prose", out)

    def test_missing_last_updated_key_is_inserted_not_rewritten(self):
        text = "---\nname: myrepo\nnote: keep\n---\n\n# myrepo\n\nprose\n"
        out = cr.compose(text, _stats(), "2026-08-20")
        self.assertIn("name: myrepo", out)
        self.assertIn("note: keep", out)
        self.assertIn("last_updated: 2026-08-20", out)

    def test_file_without_frontmatter_is_not_given_one(self):
        text = "# myrepo\n\nprose only, no frontmatter\n"
        out = cr.compose(text, _stats(), "2026-08-20")
        self.assertFalse(out.startswith("---"))
        self.assertIn("prose only, no frontmatter", out)
        self.assertIn(cr.GENERATED_BEGIN, out)

    def test_absent_file_is_seeded_from_the_template(self):
        out = cr.compose(None, _stats(), "2026-08-20")
        self.assertIn("last_updated: 2026-08-20", out)
        self.assertIn("# myrepo — readiness", out)
        self.assertIn(cr.GENERATED_BEGIN, out)

    def test_seed_template_keeps_the_example_files_sections(self):
        example = EXAMPLE_READINESS_FIXTURE.read_text(encoding="utf-8")
        expected = [ln for ln in example.splitlines() if ln.startswith("## ")]
        seeded = [ln for ln in cr.SEED_TEMPLATE.splitlines() if ln.startswith("## ")]
        self.assertEqual(expected, seeded)

    @unittest.skipUnless(
        EXAMPLE_READINESS_SHIPPED.exists(),
        "no memory/repo/EXAMPLE/ — expected on an instance, where memory/ is not synced",
    )
    def test_example_fixture_has_not_drifted_from_the_shipped_example(self):
        """Drift guard for the fixture copy of the shipped EXAMPLE readiness.

        `memory/repo/EXAMPLE/readiness.md` is a product artifact (README calls it
        out as the one seeded example note), so it stays where users expect it.
        But `memory/` is excluded from `FRAMEWORK_PATHS`, so a synced test cannot
        read it downstream — hence the copy under `tests/fixtures/`. This test
        runs only in the framework repo, where both files exist, and fails there
        the moment the two diverge.
        """
        self.assertEqual(
            EXAMPLE_READINESS_FIXTURE.read_text(encoding="utf-8"),
            EXAMPLE_READINESS_SHIPPED.read_text(encoding="utf-8"),
            "tests/fixtures/example_readiness.md has drifted from "
            "memory/repo/EXAMPLE/readiness.md — re-copy one onto the other",
        )


# ── the outcome summary must stay honest ───────────────────────────────────

class OutcomeSummaryTest(unittest.TestCase):
    def test_block_says_insufficient_data(self):
        block = cr.render_block(_stats())
        self.assertIn("Insufficient data", block)
        self.assertIn("no clean-vs-flagged verdict is available", block)
        self.assertIn("transcript_path", block)

    def test_outcome_section_contains_no_fabricated_count(self):
        block = cr.render_block(_stats(turns=12, promotions=1))
        start = block.index("### Outcome summary")
        section = block[start:]
        for word in ("clean:", "flagged:", "ended clean", "sessions clean"):
            self.assertNotIn(word, section)
        # The promotion count lives in the activity section and must not leak
        # into the outcome section as a stand-in verdict.
        self.assertNotIn("Promotions into", section)
        self.assertIn("are not a substitute", section)

    def test_block_is_deterministic_in_its_stats(self):
        self.assertEqual(cr.render_block(_stats()), cr.render_block(_stats()))
        self.assertNotEqual(cr.render_block(_stats()), cr.render_block(_stats(turns=13)))


# ── planning + applying ────────────────────────────────────────────────────

class PlanTest(unittest.TestCase):
    def test_repo_without_memory_dir_is_skipped_not_created(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            trail = root / "learning-trail"
            memory = root / "memory"
            memory.mkdir()
            _seed_trail(trail, "a", [_rec("2026-08-18T10:00:00+00:00", "C:/p/ghost")])
            entries = cr.plan(trail, memory, resolve_live=False, today=TODAY)
            self.assertEqual([e["status"] for e in entries], ["skipped-no-dir"])
            cr.apply_plan(entries)
            self.assertFalse((memory / "repo" / "ghost").exists())

    def test_existing_dir_without_readiness_is_seeded(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            trail = root / "learning-trail"
            memory = root / "memory"
            _make_repo_mem(memory, "myrepo")
            _seed_trail(trail, "a", [_rec("2026-08-18T10:00:00+00:00", "C:/p/myrepo")])
            entries = cr.plan(trail, memory, resolve_live=False, today=TODAY)
            self.assertEqual(entries[0]["status"], "seed")
            path = memory / "repo" / "myrepo" / "readiness.md"
            self.assertFalse(path.exists())  # dry run wrote nothing
            cr.apply_plan(entries)
            text = path.read_text(encoding="utf-8")
            self.assertIn("# myrepo — readiness", text)
            self.assertIn(cr.GENERATED_BEGIN, text)

    def test_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            trail = root / "learning-trail"
            memory = root / "memory"
            _make_repo_mem(memory, "myrepo", readiness=HANDWRITTEN)
            _seed_trail(trail, "a", [_rec("2026-08-18T10:00:00+00:00", "C:/p/myrepo")])
            path = memory / "repo" / "myrepo" / "readiness.md"
            before = path.read_bytes()
            cr.plan(trail, memory, resolve_live=False, today=TODAY)
            self.assertEqual(path.read_bytes(), before)

    def test_apply_twice_is_byte_identical(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            trail = root / "learning-trail"
            memory = root / "memory"
            _make_repo_mem(memory, "myrepo", readiness=HANDWRITTEN)
            _seed_trail(trail, "a", [
                _rec("2026-08-18T10:00:00+00:00", "C:/p/myrepo"),
                _rec("2026-08-17T10:00:00+00:00",
                     "C:/p/myrepo/.claude/worktrees/feat"),
            ])
            path = memory / "repo" / "myrepo" / "readiness.md"

            cr.apply_plan(cr.plan(trail, memory, resolve_live=False, today=TODAY))
            first = path.read_bytes()
            cr.apply_plan(cr.plan(trail, memory, resolve_live=False, today=TODAY))
            self.assertEqual(path.read_bytes(), first)

            # And the hand-written prose is still there after both passes.
            text = path.read_text(encoding="utf-8")
            self.assertIn("Deep hand-written prose", text)
            self.assertIn("- Migrations get written without a rollback path.", text)

    def test_second_plan_reports_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            trail = root / "learning-trail"
            memory = root / "memory"
            _make_repo_mem(memory, "myrepo", readiness=HANDWRITTEN)
            _seed_trail(trail, "a", [_rec("2026-08-18T10:00:00+00:00", "C:/p/myrepo")])
            cr.apply_plan(cr.plan(trail, memory, resolve_live=False, today=TODAY))
            again = cr.plan(trail, memory, resolve_live=False, today=TODAY)
            self.assertEqual(again[0]["status"], "unchanged")
            self.assertEqual(cr.apply_plan(again), [])

    def test_repo_filter_limits_to_one_repository(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            trail = root / "learning-trail"
            memory = root / "memory"
            _make_repo_mem(memory, "alpha")
            _make_repo_mem(memory, "beta")
            _seed_trail(trail, "a", [
                _rec("2026-08-18T10:00:00+00:00", "C:/p/alpha"),
                _rec("2026-08-18T10:00:00+00:00", "C:/p/beta"),
            ])
            entries = cr.plan(trail, memory, repo="beta", resolve_live=False,
                              today=TODAY)
            self.assertEqual([e["repo"] for e in entries], ["beta"])

    def test_only_readiness_md_is_ever_written(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            trail = root / "learning-trail"
            memory = root / "memory"
            repo_mem = _make_repo_mem(memory, "myrepo", readiness=HANDWRITTEN)
            (repo_mem / "overview.md").write_text("# overview\n", encoding="utf-8")
            _seed_trail(trail, "a", [_rec("2026-08-18T10:00:00+00:00", "C:/p/myrepo")])

            snapshot = {
                p: p.read_bytes()
                for p in memory.rglob("*") if p.is_file()
            }
            cr.apply_plan(cr.plan(trail, memory, resolve_live=False, today=TODAY))
            target = repo_mem / "readiness.md"
            after = {p: p.read_bytes() for p in memory.rglob("*") if p.is_file()}
            self.assertEqual(set(snapshot), set(after))  # no new files
            for path, data in snapshot.items():
                if path != target:
                    self.assertEqual(after[path], data, str(path))


# ── CLI ────────────────────────────────────────────────────────────────────

class MainTest(unittest.TestCase):
    def _run(self, argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = cr.main(argv)
        return rc, out.getvalue()

    def test_no_trail_data_is_an_honest_empty_state_exit_zero(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "learning-trail").mkdir()
            (root / "memory").mkdir()
            rc, out = self._run([
                "--trail-dir", str(root / "learning-trail"),
                "--memory-root", str(root / "memory"),
            ])
            self.assertEqual(rc, 0)
            self.assertIn("no learning-trail data found", out)
            self.assertIn("honest empty state", out)

    def test_dry_run_reports_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            trail = root / "learning-trail"
            memory = root / "memory"
            _make_repo_mem(memory, "myrepo", readiness=HANDWRITTEN)
            _seed_trail(trail, "a", [_rec("2026-08-18T10:00:00+00:00", "C:/p/myrepo")])
            path = memory / "repo" / "myrepo" / "readiness.md"
            before = path.read_bytes()
            rc, out = self._run([
                "--trail-dir", str(trail), "--memory-root", str(memory),
            ])
            self.assertEqual(rc, 0)
            self.assertIn("dry run", out)
            self.assertIn("myrepo", out)
            self.assertIn("INSUFFICIENT DATA", out)
            self.assertEqual(path.read_bytes(), before)

    def test_apply_writes_and_preserves_prose(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            trail = root / "learning-trail"
            memory = root / "memory"
            _make_repo_mem(memory, "myrepo", readiness=HANDWRITTEN)
            _seed_trail(trail, "a", [_rec("2026-08-18T10:00:00+00:00", "C:/p/myrepo")])
            rc, out = self._run([
                "--trail-dir", str(trail), "--memory-root", str(memory), "--apply",
            ])
            self.assertEqual(rc, 0)
            self.assertNotIn("dry run", out)
            text = (memory / "repo" / "myrepo" / "readiness.md").read_text(
                encoding="utf-8"
            )
            self.assertIn(cr.GENERATED_BEGIN, text)
            self.assertIn("Deep hand-written prose", text)

    def test_json_output_shape(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            trail = root / "learning-trail"
            memory = root / "memory"
            _make_repo_mem(memory, "myrepo")
            _seed_trail(trail, "a", [_rec("2026-08-18T10:00:00+00:00", "C:/p/myrepo")])
            rc, out = self._run([
                "--trail-dir", str(trail), "--memory-root", str(memory), "--json",
            ])
            self.assertEqual(rc, 0)
            payload = json.loads(out)
            self.assertFalse(payload["applied"])
            self.assertFalse(payload["outcome_summary"]["available"])
            self.assertEqual(len(payload["repos"]), 1)
            entry = payload["repos"][0]
            self.assertEqual(entry["repo"], "myrepo")
            self.assertEqual(entry["turns"], 1)
            # The rendered file text is never dumped into the JSON plan.
            self.assertNotIn("new_text", entry)

    def test_trail_dir_defaults_to_claude_config_dir(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            saved = os.environ.get("CLAUDE_CONFIG_DIR")
            os.environ["CLAUDE_CONFIG_DIR"] = str(root)
            try:
                _seed_trail(root / "learning-trail", "a", [
                    _rec("2026-08-18T10:00:00+00:00", "C:/p/myrepo"),
                ])
                memory = root / "memory"
                _make_repo_mem(memory, "myrepo")
                rc, out = self._run(["--memory-root", str(memory), "--json"])
                self.assertEqual(rc, 0)
                payload = json.loads(out)
                self.assertEqual(payload["repos"][0]["repo"], "myrepo")
            finally:
                if saved is None:
                    os.environ.pop("CLAUDE_CONFIG_DIR", None)
                else:
                    os.environ["CLAUDE_CONFIG_DIR"] = saved


if __name__ == "__main__":
    unittest.main()
