import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from hooks import harvest_nudge, record_stop as rs  # noqa: E402


class HarvestNudgeTest(unittest.TestCase):
    def _with_config(self, d):
        saved = os.environ.get("CLAUDE_CONFIG_DIR")
        os.environ["CLAUDE_CONFIG_DIR"] = d
        return saved

    def _restore_config(self, saved):
        if saved is None:
            os.environ.pop("CLAUDE_CONFIG_DIR", None)
        else:
            os.environ["CLAUDE_CONFIG_DIR"] = saved

    def _trail_for(self, work: str) -> Path:
        """The trail path harvest_nudge resolves for a working dir.

        Mirrors `nudge()`'s identity: `git_roots(...)[1]`, the *repository* root.
        In a plain TemporaryDirectory that equals the worktree root, so every test
        using this helper is unaffected by the distinction — which is exactly why
        none of them caught the worktree-scoping bug. See WorktreeScopingTest.
        """
        return rs.trail_dir() / f"{rs.repo_key(rs.git_roots(work)[1])}.jsonl"

    def _seed_trail(self, work: str, *, n_unharvested: int, watermark: datetime):
        """Write a trail with a watermark and `n_unharvested` newer records."""
        trail = self._trail_for(work)
        rs.write_watermark(rs.watermark_path(trail), watermark)
        lines = []
        # A harvested (older-than-watermark) record that must NOT be counted.
        harvested = watermark - timedelta(days=1)
        lines.append(json.dumps({"ts": harvested.isoformat(), "m": "harvested"}))
        for i in range(n_unharvested):
            ts = watermark + timedelta(hours=i + 1)
            lines.append(json.dumps({"ts": ts.isoformat(), "m": f"new-{i}"}))
        trail.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return trail

    def test_message_when_count_meets_threshold(self):
        with tempfile.TemporaryDirectory() as cfg, tempfile.TemporaryDirectory() as work:
            saved = self._with_config(cfg)
            saved_thresh = harvest_nudge.NUDGE_THRESHOLD
            try:
                wm = datetime(2026, 7, 1, tzinfo=timezone.utc)
                self._seed_trail(work, n_unharvested=5, watermark=wm)
                harvest_nudge.NUDGE_THRESHOLD = 5
                msg = harvest_nudge.nudge({"source": "startup", "cwd": work})
                self.assertIn("un-harvested", msg)
                self.assertIn("/harvest-memory", msg)
                self.assertIn("5", msg)
            finally:
                harvest_nudge.NUDGE_THRESHOLD = saved_thresh
                self._restore_config(saved)

    def test_silent_below_threshold(self):
        with tempfile.TemporaryDirectory() as cfg, tempfile.TemporaryDirectory() as work:
            saved = self._with_config(cfg)
            saved_thresh = harvest_nudge.NUDGE_THRESHOLD
            try:
                wm = datetime(2026, 7, 1, tzinfo=timezone.utc)
                self._seed_trail(work, n_unharvested=3, watermark=wm)
                harvest_nudge.NUDGE_THRESHOLD = 10
                self.assertEqual(
                    harvest_nudge.nudge({"source": "startup", "cwd": work}), ""
                )
            finally:
                harvest_nudge.NUDGE_THRESHOLD = saved_thresh
                self._restore_config(saved)

    def test_resume_source_also_nudges(self):
        with tempfile.TemporaryDirectory() as cfg, tempfile.TemporaryDirectory() as work:
            saved = self._with_config(cfg)
            saved_thresh = harvest_nudge.NUDGE_THRESHOLD
            try:
                wm = datetime(2026, 7, 1, tzinfo=timezone.utc)
                self._seed_trail(work, n_unharvested=5, watermark=wm)
                harvest_nudge.NUDGE_THRESHOLD = 5
                self.assertNotEqual(
                    harvest_nudge.nudge({"source": "resume", "cwd": work}), ""
                )
            finally:
                harvest_nudge.NUDGE_THRESHOLD = saved_thresh
                self._restore_config(saved)

    def test_silent_on_compact_and_clear(self):
        with tempfile.TemporaryDirectory() as cfg, tempfile.TemporaryDirectory() as work:
            saved = self._with_config(cfg)
            saved_thresh = harvest_nudge.NUDGE_THRESHOLD
            try:
                wm = datetime(2026, 7, 1, tzinfo=timezone.utc)
                self._seed_trail(work, n_unharvested=50, watermark=wm)
                harvest_nudge.NUDGE_THRESHOLD = 1
                self.assertEqual(
                    harvest_nudge.nudge({"source": "compact", "cwd": work}), ""
                )
                self.assertEqual(
                    harvest_nudge.nudge({"source": "clear", "cwd": work}), ""
                )
            finally:
                harvest_nudge.NUDGE_THRESHOLD = saved_thresh
                self._restore_config(saved)

    def test_silent_when_trail_absent(self):
        with tempfile.TemporaryDirectory() as cfg, tempfile.TemporaryDirectory() as work:
            saved = self._with_config(cfg)
            saved_thresh = harvest_nudge.NUDGE_THRESHOLD
            try:
                harvest_nudge.NUDGE_THRESHOLD = 1
                self.assertEqual(
                    harvest_nudge.nudge({"source": "startup", "cwd": work}), ""
                )
            finally:
                harvest_nudge.NUDGE_THRESHOLD = saved_thresh
                self._restore_config(saved)

    def test_count_unharvested_ignores_malformed_and_harvested(self):
        with tempfile.TemporaryDirectory() as cfg, tempfile.TemporaryDirectory() as work:
            saved = self._with_config(cfg)
            try:
                wm = datetime(2026, 7, 1, tzinfo=timezone.utc)
                trail = self._trail_for(work)
                lines = [
                    "not json",
                    "",
                    json.dumps({"ts": (wm - timedelta(days=1)).isoformat()}),  # harvested
                    json.dumps({"ts": (wm + timedelta(hours=1)).isoformat()}),  # new
                    json.dumps({"ts": (wm + timedelta(hours=2)).isoformat()}),  # new
                ]
                trail.write_text("\n".join(lines) + "\n", encoding="utf-8")
                self.assertEqual(harvest_nudge.count_unharvested(trail, wm), 2)
            finally:
                self._restore_config(saved)

    def test_main_prints_message_on_startup_over_threshold(self):
        with tempfile.TemporaryDirectory() as cfg, tempfile.TemporaryDirectory() as work:
            saved = self._with_config(cfg)
            saved_thresh = harvest_nudge.NUDGE_THRESHOLD
            saved_stdin = sys.stdin
            try:
                wm = datetime(2026, 7, 1, tzinfo=timezone.utc)
                self._seed_trail(work, n_unharvested=5, watermark=wm)
                harvest_nudge.NUDGE_THRESHOLD = 5
                sys.stdin = io.StringIO(
                    json.dumps({"source": "startup", "cwd": work})
                )
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    rc = harvest_nudge.main()
                self.assertEqual(rc, 0)
                self.assertIn("un-harvested", out.getvalue())
            finally:
                harvest_nudge.NUDGE_THRESHOLD = saved_thresh
                sys.stdin = saved_stdin
                self._restore_config(saved)

    def test_main_silent_on_bad_stdin(self):
        saved_stdin = sys.stdin
        try:
            sys.stdin = io.StringIO("{not json")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = harvest_nudge.main()
            self.assertEqual(rc, 0)
            self.assertEqual(out.getvalue(), "")
        finally:
            sys.stdin = saved_stdin

    def test_count_unharvested_early_exits_at_limit(self):
        with tempfile.TemporaryDirectory() as cfg, tempfile.TemporaryDirectory() as work:
            saved = self._with_config(cfg)
            try:
                wm = datetime(2026, 7, 1, tzinfo=timezone.utc)
                # 20 un-harvested records, but ask to stop at 5.
                trail = self._seed_trail(work, n_unharvested=20, watermark=wm)
                capped = harvest_nudge.count_unharvested(trail, wm, limit=5)
                self.assertEqual(capped, 5)
                # And without the limit the true count is reported (20), proving
                # the cap — not the data — is what bounded the previous result.
                self.assertEqual(harvest_nudge.count_unharvested(trail, wm), 20)
            finally:
                self._restore_config(saved)

    def test_count_unharvested_below_limit_returns_true_count(self):
        with tempfile.TemporaryDirectory() as cfg, tempfile.TemporaryDirectory() as work:
            saved = self._with_config(cfg)
            try:
                wm = datetime(2026, 7, 1, tzinfo=timezone.utc)
                trail = self._seed_trail(work, n_unharvested=3, watermark=wm)
                # Fewer records than the limit → the real count, not the limit.
                self.assertEqual(
                    harvest_nudge.count_unharvested(trail, wm, limit=10), 3
                )
            finally:
                self._restore_config(saved)

    def test_counts_legacy_six_field_records(self):
        # Pre-#65 records have no repo_root/transcript_path. count_unharvested
        # keys on ts alone and must handle them without error.
        with tempfile.TemporaryDirectory() as d:
            trail = Path(d) / "legacy.jsonl"
            legacy = {
                "ts": "2026-07-05T00:00:00+00:00",
                "session_id": "old-1",
                "git_root": "/gone/worktree",
                "git_branch": "main",
                "prompt_id": "p-old",
                "message_preview": "legacy turn",
            }
            trail.write_text(json.dumps(legacy) + "\n", encoding="utf-8")
            wm = datetime(2026, 7, 1, tzinfo=timezone.utc)
            self.assertEqual(harvest_nudge.count_unharvested(trail, wm), 1)

    # ---- the unfinished-harvest marker ----------------------------------

    def _write_marker(self, payload, work):
        """Write the marker for the repo containing ``work``; return its path."""
        p = rs.trail_dir() / harvest_nudge.pending_name(rs.git_roots(work)[1])
        p.write_text(
            payload if isinstance(payload, str) else json.dumps(payload),
            encoding="utf-8",
        )
        return p

    def test_pending_marker_produces_a_message(self):
        with tempfile.TemporaryDirectory() as cfg, tempfile.TemporaryDirectory() as work:
            saved = self._with_config(cfg)
            try:
                self._write_marker(
                    {
                        "at": "2026-07-12T08:00:00+00:00",
                        "reason": "read manifest not readable",
                        "read": "eval/learnings/20260712T080000Z/read.json",
                        "cwd": work,
                    },
                    work,
                )
                msg = harvest_nudge.nudge({"source": "startup", "cwd": work})
                self.assertIn("WITHOUT stamping", msg)
                self.assertIn("read manifest not readable", msg)
                self.assertIn("eval/learnings/20260712T080000Z/read.json", msg)
            finally:
                self._restore_config(saved)

    def test_pending_marker_outranks_the_count_nudge(self):
        with tempfile.TemporaryDirectory() as cfg, tempfile.TemporaryDirectory() as work:
            saved = self._with_config(cfg)
            saved_thresh = harvest_nudge.NUDGE_THRESHOLD
            try:
                wm = datetime(2026, 7, 1, tzinfo=timezone.utc)
                self._seed_trail(work, n_unharvested=50, watermark=wm)
                harvest_nudge.NUDGE_THRESHOLD = 1
                self._write_marker(
                    {"reason": "no --read manifest given", "read": None}, work
                )
                msg = harvest_nudge.nudge({"source": "startup", "cwd": work})
                self.assertIn("WITHOUT stamping", msg)
                self.assertNotIn("un-harvested learning-trail records", msg)
                self.assertIn("No read manifest was given", msg)
            finally:
                harvest_nudge.NUDGE_THRESHOLD = saved_thresh
                self._restore_config(saved)

    def test_another_repos_marker_does_not_suppress_this_repos_count_nudge(self):
        # The second half of the machine-global marker bug: while ANY repo had an
        # unfinished harvest, every other repo on the machine got that repo's
        # message instead of its own count nudge — one broken harvest blinding
        # ~100 repos' reminders indefinitely.
        with tempfile.TemporaryDirectory() as cfg, \
                tempfile.TemporaryDirectory() as work, \
                tempfile.TemporaryDirectory() as other:
            saved = self._with_config(cfg)
            saved_thresh = harvest_nudge.NUDGE_THRESHOLD
            try:
                wm = datetime(2026, 7, 1, tzinfo=timezone.utc)
                self._seed_trail(work, n_unharvested=50, watermark=wm)
                harvest_nudge.NUDGE_THRESHOLD = 5
                marker = self._write_marker(
                    {"reason": "some other repo's problem", "read": "x/read.json"},
                    other,
                )
                self.assertTrue(marker.is_file())
                self.assertEqual(harvest_nudge.pending_message(rs.git_root(work)), "")
                msg = harvest_nudge.nudge({"source": "startup", "cwd": work})
                self.assertIn("un-harvested learning-trail records", msg)
                self.assertNotIn("WITHOUT stamping", msg)
                # ...and the other repo still gets its own reminder.
                self.assertIn(
                    "WITHOUT stamping",
                    harvest_nudge.nudge({"source": "startup", "cwd": other}),
                )
            finally:
                harvest_nudge.NUDGE_THRESHOLD = saved_thresh
                self._restore_config(saved)

    def test_pending_marker_still_respects_the_source_filter(self):
        with tempfile.TemporaryDirectory() as cfg, tempfile.TemporaryDirectory() as work:
            saved = self._with_config(cfg)
            try:
                self._write_marker({"reason": "whatever", "read": None}, work)
                for source in ("compact", "clear"):
                    self.assertEqual(
                        harvest_nudge.nudge({"source": source, "cwd": work}), ""
                    )
            finally:
                self._restore_config(saved)

    def test_absent_marker_leaves_existing_behaviour_unchanged(self):
        with tempfile.TemporaryDirectory() as cfg, tempfile.TemporaryDirectory() as work:
            saved = self._with_config(cfg)
            saved_thresh = harvest_nudge.NUDGE_THRESHOLD
            try:
                wm = datetime(2026, 7, 1, tzinfo=timezone.utc)
                self._seed_trail(work, n_unharvested=5, watermark=wm)
                harvest_nudge.NUDGE_THRESHOLD = 5
                self.assertEqual(harvest_nudge.pending_message(rs.git_root(work)), "")
                msg = harvest_nudge.nudge({"source": "startup", "cwd": work})
                self.assertIn("un-harvested learning-trail records", msg)
            finally:
                harvest_nudge.NUDGE_THRESHOLD = saved_thresh
                self._restore_config(saved)

    def test_malformed_marker_falls_back_to_normal_behaviour(self):
        with tempfile.TemporaryDirectory() as cfg, tempfile.TemporaryDirectory() as work:
            saved = self._with_config(cfg)
            saved_thresh = harvest_nudge.NUDGE_THRESHOLD
            saved_stdin = sys.stdin
            try:
                wm = datetime(2026, 7, 1, tzinfo=timezone.utc)
                self._seed_trail(work, n_unharvested=5, watermark=wm)
                harvest_nudge.NUDGE_THRESHOLD = 5
                self._write_marker("{not json", work)
                self.assertEqual(harvest_nudge.pending_message(rs.git_root(work)), "")
                msg = harvest_nudge.nudge({"source": "startup", "cwd": work})
                self.assertIn("un-harvested learning-trail records", msg)
                # And the hook itself still exits 0 with a marker it cannot read.
                sys.stdin = io.StringIO(
                    json.dumps({"source": "startup", "cwd": work})
                )
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    rc = harvest_nudge.main()
                self.assertEqual(rc, 0)
                self.assertIn("un-harvested", out.getvalue())
            finally:
                harvest_nudge.NUDGE_THRESHOLD = saved_thresh
                sys.stdin = saved_stdin
                self._restore_config(saved)

    def test_marker_that_is_not_an_object_is_ignored(self):
        with tempfile.TemporaryDirectory() as cfg, tempfile.TemporaryDirectory() as work:
            saved = self._with_config(cfg)
            try:
                self._write_marker("[1, 2, 3]", work)
                self.assertEqual(harvest_nudge.pending_message(rs.git_root(work)), "")
                self.assertEqual(
                    harvest_nudge.nudge({"source": "startup", "cwd": work}), ""
                )
            finally:
                self._restore_config(saved)

    def test_marker_without_a_reason_still_produces_a_message(self):
        with tempfile.TemporaryDirectory() as cfg, tempfile.TemporaryDirectory() as work:
            saved = self._with_config(cfg)
            try:
                self._write_marker({}, work)
                msg = harvest_nudge.nudge({"source": "startup", "cwd": work})
                self.assertIn("no reason recorded", msg)
            finally:
                self._restore_config(saved)

    def test_pending_marker_naming_matches_mark_harvested(self):
        # The hook deliberately does not import scripts/, so the marker name is
        # duplicated on both sides. Pin the prefix AND the derivation: a rename or
        # a re-keying on either side would otherwise orphan every marker — the
        # hook would look for a file mark_harvested never writes, and the
        # unfinished-harvest reminder would go permanently silent.
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
        import mark_harvested  # noqa: E402

        self.assertEqual(harvest_nudge.PENDING_PREFIX, mark_harvested.PENDING_PREFIX)
        with tempfile.TemporaryDirectory() as cfg, tempfile.TemporaryDirectory() as work:
            saved = self._with_config(cfg)
            try:
                root = rs.git_roots(work)[1]
                self.assertEqual(
                    harvest_nudge.pending_name(root),
                    mark_harvested.pending_name(root),
                )
                # And the path the writer picks is the one the reader reads.
                self.assertEqual(
                    mark_harvested.pending_path(work),
                    rs.trail_dir() / harvest_nudge.pending_name(root),
                )
            finally:
                self._restore_config(saved)

    def test_bad_threshold_env_falls_back(self):
        import importlib

        saved_env = os.environ.get("CLAUDE_HARVEST_NUDGE_THRESHOLD")
        os.environ["CLAUDE_HARVEST_NUDGE_THRESHOLD"] = "notanint"
        try:
            # Re-import the module so its import-time parse runs against the bad
            # env value; it must fall back to 20 rather than raise ValueError.
            reloaded = importlib.reload(harvest_nudge)
            self.assertEqual(reloaded.NUDGE_THRESHOLD, 20)
        finally:
            if saved_env is None:
                os.environ.pop("CLAUDE_HARVEST_NUDGE_THRESHOLD", None)
            else:
                os.environ["CLAUDE_HARVEST_NUDGE_THRESHOLD"] = saved_env
            importlib.reload(harvest_nudge)


def _has_git():
    return bool(rs._git(os.getcwd(), "--version"))


def _init_repo(path: str) -> None:
    """`git init` a temp repo with one commit, using repo-local identity only.

    Never touches global git config. Mirrors the helper of the same name in
    test_record_stop.py; duplicated rather than imported so this file stays
    self-contained.
    """
    rs._git(path, "init", "-q")
    rs._git(path, "config", "user.email", "test@example.invalid")
    rs._git(path, "config", "user.name", "Test")
    rs._git(path, "config", "commit.gpgsign", "false")
    Path(path, "seed.txt").write_text("seed\n", encoding="utf-8")
    rs._git(path, "add", "seed.txt")
    rs._git(path, "commit", "-q", "-m", "seed")


class WorktreeScopingTest(unittest.TestCase):
    """The nudge and the pending marker key on the *repository*, not the worktree.

    Every other test in this file runs in a plain TemporaryDirectory, where the
    worktree root and the repository root are the same path — so they cannot
    distinguish the two identities, and the whole suite passed while production
    was keyed on the wrong one. These use a real `git worktree add`.

    Both halves of the bug are covered: the count nudge read a fresh worktree's
    own near-empty trail (threshold unreachable in a worktree-driven workflow),
    and a pending marker written inside a worktree was orphaned when that worktree
    was deleted — unreadable from the main checkout, uncleanable by
    `clear_pending`, so an unfinished harvest went permanently silent.
    """

    def _with_config(self, d):
        saved = os.environ.get("CLAUDE_CONFIG_DIR")
        os.environ["CLAUDE_CONFIG_DIR"] = d
        return saved

    def _restore_config(self, saved):
        if saved is None:
            os.environ.pop("CLAUDE_CONFIG_DIR", None)
        else:
            os.environ["CLAUDE_CONFIG_DIR"] = saved

    @contextlib.contextmanager
    def _repo_and_worktree(self):
        """Yield ``(repo_path, worktree_path)`` for a real linked worktree."""
        if not _has_git():
            self.skipTest("git not available")
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d) / "repo"
            repo.mkdir()
            _init_repo(str(repo))
            wt = Path(d) / "wt"
            rs._git(str(repo), "worktree", "add", "-q", "-b", "side", str(wt))
            if not (wt / "seed.txt").exists():
                self.skipTest("git worktree add unavailable")
            yield repo, wt

    def _import_mark_harvested(self):
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
        import mark_harvested  # noqa: E402

        return mark_harvested

    def test_identities_actually_differ_inside_a_worktree(self):
        # Guards the premise of every test below: if git_roots collapsed the two,
        # these would pass vacuously and prove nothing.
        with self._repo_and_worktree() as (repo, wt):
            worktree_root, repo_root = rs.git_roots(str(wt))
            self.assertEqual(Path(worktree_root).resolve(), wt.resolve())
            self.assertEqual(Path(repo_root).resolve(), repo.resolve())
            self.assertNotEqual(
                rs.repo_key(worktree_root),
                rs.repo_key(repo_root),
                "the two identities must produce different trail/marker names",
            )

    def test_nudge_from_worktree_counts_the_repo_trail(self):
        with self._repo_and_worktree() as (repo, wt):
            with tempfile.TemporaryDirectory() as cfg:
                saved = self._with_config(cfg)
                saved_thresh = harvest_nudge.NUDGE_THRESHOLD
                try:
                    # Seed the repo's canonical trail, keyed on the repo root.
                    repo_key = rs.repo_key(rs.git_roots(str(repo))[1])
                    trail = rs.trail_dir() / f"{repo_key}.jsonl"
                    wm = datetime(2026, 7, 1, tzinfo=timezone.utc)
                    rs.write_watermark(rs.watermark_path(trail), wm)
                    lines = [
                        json.dumps({"ts": (wm + timedelta(hours=i + 1)).isoformat()})
                        for i in range(5)
                    ]
                    trail.write_text("\n".join(lines) + "\n", encoding="utf-8")
                    harvest_nudge.NUDGE_THRESHOLD = 5

                    # The worktree-keyed trail — what the buggy code looked for —
                    # must not exist, so a pass can only come from the repo trail.
                    wt_only = rs.trail_dir() / f"{rs.repo_key(rs.git_roots(str(wt))[0])}.jsonl"
                    self.assertFalse(wt_only.exists())

                    msg = harvest_nudge.nudge({"source": "startup", "cwd": str(wt)})
                    self.assertIn("un-harvested", msg)
                    self.assertIn("5", msg)
                finally:
                    harvest_nudge.NUDGE_THRESHOLD = saved_thresh
                    self._restore_config(saved)

    def test_marker_written_in_worktree_is_found_from_main_checkout(self):
        mark_harvested = self._import_mark_harvested()
        with self._repo_and_worktree() as (repo, wt):
            with tempfile.TemporaryDirectory() as cfg:
                saved = self._with_config(cfg)
                try:
                    mark_harvested.write_pending("test refusal", None, cwd=str(wt))

                    # One marker, whichever side of the boundary you ask from.
                    self.assertEqual(
                        mark_harvested.pending_path(str(wt)),
                        mark_harvested.pending_path(str(repo)),
                    )
                    # The hook duplicates the derivation rather than importing it,
                    # so it must resolve to the same file the writer used.
                    self.assertEqual(
                        mark_harvested.pending_path(str(wt)),
                        rs.trail_dir()
                        / harvest_nudge.pending_name(rs.git_roots(str(repo))[1]),
                    )
                    # And a session in the main checkout actually sees the warning.
                    msg = harvest_nudge.nudge({"source": "startup", "cwd": str(repo)})
                    self.assertIn("WITHOUT stamping", msg)
                    self.assertIn("test refusal", msg)
                finally:
                    self._restore_config(saved)

    def test_marker_survives_worktree_deletion_and_can_be_cleared(self):
        # The orphaning scenario end to end: refuse to stamp inside a worktree,
        # delete the worktree (as repo-hygiene does), then confirm the main
        # checkout still surfaces the warning and can clear it.
        mark_harvested = self._import_mark_harvested()
        with self._repo_and_worktree() as (repo, wt):
            with tempfile.TemporaryDirectory() as cfg:
                saved = self._with_config(cfg)
                try:
                    mark_harvested.write_pending("unfinished", None, cwd=str(wt))
                    marker = mark_harvested.pending_path(str(wt))
                    self.assertTrue(marker.exists())

                    rs._git(str(repo), "worktree", "remove", "--force", str(wt))
                    self.assertFalse(wt.exists())

                    self.assertTrue(
                        marker.exists(),
                        "the marker must outlive the worktree it was written from",
                    )
                    msg = harvest_nudge.nudge({"source": "startup", "cwd": str(repo)})
                    self.assertIn("WITHOUT stamping", msg)
                    self.assertIn("unfinished", msg)

                    mark_harvested.clear_pending(str(repo))
                    self.assertFalse(marker.exists())
                    self.assertEqual(
                        harvest_nudge.nudge({"source": "startup", "cwd": str(repo)}),
                        "",
                    )
                finally:
                    self._restore_config(saved)


# ---- the ADR 0002 memory-trigger reminder ------------------------------


@contextlib.contextmanager
def _patched(obj, name, value):
    """Temporarily set ``obj.name`` to ``value``, restoring it afterwards.

    Manual save/restore rather than ``unittest.mock``, matching this file's
    existing idiom (see the ``NUDGE_THRESHOLD`` save/restore above).
    """
    missing = object()
    saved = getattr(obj, name, missing)
    setattr(obj, name, value)
    try:
        yield
    finally:
        if saved is missing:
            delattr(obj, name)
        else:
            setattr(obj, name, saved)


class _FakeRun:
    """Stand-in for ``subprocess.run``: records calls, returns a canned result.

    This is the boundary the trigger reminder is tested across. The real
    ``check_memory_triggers.py`` is a 1500-line transcript-capable reporter; the
    failure paths below (timeout, undefined return code, malformed stdout)
    cannot be provoked through it, and the hook's whole contract is what it does
    with those answers.
    """

    def __init__(self, *, returncode=0, stdout="", raises=None):
        self.returncode = returncode
        self.stdout = stdout
        self.raises = raises
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        if self.raises is not None:
            raise self.raises
        return subprocess.CompletedProcess(argv, self.returncode, self.stdout, "")


def _trigger(name, verdict, *, headline="", can_fire=True):
    """One entry of the payload's ``triggers`` list, shaped like the script's."""
    return {
        "trigger": name,
        "verdict": verdict,
        "reason": None,
        "can_fire": can_fire,
        "headline": headline,
        "detail": [],
    }


def _payload(*triggers, corpus_notes=12, directory_notes=None, limits=None):
    """A ``--skip-transcripts --json`` payload, shaped like the real script's.

    Only the keys the hook reads are modelled; the real payload carries more
    (``scan``, ``exit``, ``memory_root``...) and the hook must not need them.
    Every name here is invented — no fixture mirrors a real corpus.
    """
    return {
        "memory_root": "/fixture/memory",
        "corpus_notes": corpus_notes,
        "directory_notes": (
            {"alpha": 7, "beta": 5} if directory_notes is None else directory_notes
        ),
        "limits": ({"directory": 100, "corpus": 500} if limits is None else limits),
        "triggers": list(triggers),
    }


def _clear_payload(**kwargs):
    """Nothing to say: both size triggers clear, T3/T4 unknown (the real shape)."""
    return _payload(
        _trigger("t1-directory-size", "clear"),
        _trigger("t2-corpus-size", "clear"),
        _trigger("t3-unrouted-harvest", "unknown"),
        _trigger("t4-index-bypass", "unknown", can_fire=False),
        **kwargs,
    )


class TriggerLineRenderingTest(unittest.TestCase):
    """What the hook says about a payload — the pure rendering layer."""

    def test_fired_t2_names_the_trigger_its_count_and_its_threshold(self):
        lines = harvest_nudge._fired_lines(
            _payload(_trigger("t2-corpus-size", "FIRED"), corpus_notes=512)
        )
        self.assertEqual(len(lines), 1)
        self.assertIn("FIRED", lines[0])
        self.assertIn("T2", lines[0])
        self.assertIn("ADR 0002", lines[0])
        self.assertIn("512", lines[0])  # the measured count
        self.assertIn("500", lines[0])  # the threshold it is measured against

    def test_fired_t1_names_the_largest_directory_count_and_the_threshold(self):
        lines = harvest_nudge._fired_lines(
            _payload(
                _trigger("t1-directory-size", "FIRED"),
                directory_notes={"alpha": 118, "beta": 4},
            )
        )
        self.assertEqual(len(lines), 1)
        self.assertIn("FIRED", lines[0])
        self.assertIn("T1", lines[0])
        self.assertIn("118", lines[0])
        self.assertIn("100", lines[0])

    def test_fired_t3_reports_the_scripts_own_headline(self):
        # T3 has no numeric pair in the payload's structured fields, so the
        # headline is the only thing that can carry the finding.
        lines = harvest_nudge._fired_lines(
            _payload(
                _trigger(
                    "t3-unrouted-harvest",
                    "FIRED",
                    headline="3 harvest nomination(s) could not be routed",
                )
            )
        )
        self.assertEqual(len(lines), 1)
        self.assertIn("T3", lines[0])
        self.assertIn("3 harvest nomination(s) could not be routed", lines[0])

    def test_clear_payload_produces_no_lines(self):
        self.assertEqual(harvest_nudge._fired_lines(_clear_payload()), [])
        self.assertEqual(harvest_nudge._near_threshold_lines(_clear_payload()), [])

    def test_t4_is_never_named_even_when_the_payload_claims_it_fired(self):
        # With --skip-transcripts T4 is always `unknown` with can_fire=False, so
        # this payload is impossible in production. It is forced anyway: ADR 0004's
        # guarantee is that `unknown` must never read as a finding *or* as
        # `clear`, and pinning it against the data rather than against the
        # producer means a future T4 that could fire cannot leak a bypass rate
        # into session context without someone deciding that it should.
        forced = _payload(
            _trigger("t4-index-bypass", "FIRED", headline="bypass rate 99%"),
            _trigger("t1-directory-size", "clear"),
            _trigger("t2-corpus-size", "clear"),
        )
        self.assertEqual(harvest_nudge._fired_lines(forced), [])
        rendered = "\n".join(
            harvest_nudge._fired_lines(forced)
            + harvest_nudge._near_threshold_lines(forced)
        )
        for needle in ("t4", "T4", "bypass", "99"):
            self.assertNotIn(needle, rendered)

    def test_unknown_verdicts_are_never_rendered(self):
        # T3 `unknown` means "no tally was ever recorded", which is precisely not
        # the same as zero unrouted learnings. Rendering it either way would be a
        # claim the payload does not support.
        unknown = _payload(
            _trigger("t3-unrouted-harvest", "unknown", headline="no unrouted tally"),
            _trigger("t4-index-bypass", "unknown", can_fire=False),
        )
        self.assertEqual(harvest_nudge._fired_lines(unknown), [])
        self.assertEqual(harvest_nudge._near_threshold_lines(unknown), [])

    def test_two_line_budget_holds_when_more_triggers_fire_than_fit(self):
        everything = _payload(
            _trigger("t1-directory-size", "FIRED"),
            _trigger("t2-corpus-size", "FIRED"),
            _trigger("t3-unrouted-harvest", "FIRED", headline="2 unrouted"),
            corpus_notes=512,
            directory_notes={"alpha": 118, "beta": 101},
        )
        lines = harvest_nudge._fired_lines(everything)
        self.assertEqual(len(lines), 2)
        # The two findings that carry numbers are kept; the third is dropped,
        # not merged into one of them.
        self.assertIn("T1", lines[0])
        self.assertIn("T2", lines[1])
        self.assertNotIn("2 unrouted", "\n".join(lines))

    def test_missing_triggers_key_renders_nothing(self):
        payload = {
            "corpus_notes": 12,
            "directory_notes": {"alpha": 7},
            "limits": {"directory": 100, "corpus": 500},
        }
        self.assertEqual(harvest_nudge._fired_lines(payload), [])

    def test_triggers_that_is_not_a_list_renders_nothing(self):
        payload = _clear_payload()
        payload["triggers"] = {"t2-corpus-size": "FIRED"}
        self.assertEqual(harvest_nudge._fired_lines(payload), [])

    def test_non_dict_trigger_entries_are_skipped_not_fatal(self):
        payload = _payload(corpus_notes=512)
        payload["triggers"] = [
            "t2-corpus-size",
            None,
            7,
            ["t2-corpus-size", "FIRED"],
            _trigger("t2-corpus-size", "FIRED"),
        ]
        lines = harvest_nudge._fired_lines(payload)
        self.assertEqual(len(lines), 1)
        self.assertIn("512", lines[0])
        # ...and a list of nothing but junk says nothing at all.
        payload["triggers"] = ["t2-corpus-size", None, 7]
        self.assertEqual(harvest_nudge._fired_lines(payload), [])

    def test_missing_limits_suppress_the_line_rather_than_guessing(self):
        # A line naming a count without the threshold it was measured against
        # would be noise, so the whole line is dropped.
        payload = _payload(_trigger("t2-corpus-size", "FIRED"), corpus_notes=512)
        del payload["limits"]
        self.assertEqual(harvest_nudge._fired_lines(payload), [])
        self.assertEqual(harvest_nudge._near_threshold_lines(payload), [])

    def test_near_threshold_reports_proximity_with_its_percentage(self):
        lines = harvest_nudge._near_threshold_lines(
            _clear_payload(directory_notes={"alpha": 95, "beta": 3})
        )
        self.assertEqual(len(lines), 1)
        self.assertIn("nearing threshold", lines[0])
        self.assertIn("T1", lines[0])
        self.assertIn("95", lines[0])
        self.assertIn("100", lines[0])

    def test_near_threshold_boundary_is_the_declared_fraction(self):
        limit = 100
        at = int(limit * harvest_nudge.NEAR_THRESHOLD_FRACTION)
        self.assertEqual(at, 90, "this test's arithmetic assumes a 0.9 fraction")
        self.assertEqual(
            len(
                harvest_nudge._near_threshold_lines(
                    _clear_payload(directory_notes={"alpha": at})
                )
            ),
            1,
        )
        self.assertEqual(
            harvest_nudge._near_threshold_lines(
                _clear_payload(directory_notes={"alpha": at - 1})
            ),
            [],
        )
        # The same boundary for the corpus, against its own (different) limit.
        self.assertEqual(
            len(harvest_nudge._near_threshold_lines(_clear_payload(corpus_notes=450))),
            1,
        )
        self.assertEqual(
            harvest_nudge._near_threshold_lines(_clear_payload(corpus_notes=449)), []
        )

    def test_near_threshold_tolerates_a_zero_limit(self):
        # The percentage divides by the limit; a zero limit must not raise
        # inside a SessionStart hook.
        self.assertEqual(
            harvest_nudge._near_threshold_lines(
                _clear_payload(
                    corpus_notes=10,
                    directory_notes={"alpha": 10},
                    limits={"directory": 0, "corpus": 0},
                )
            ),
            [],
        )


class TriggerPayloadBoundaryTest(unittest.TestCase):
    """``_trigger_payload`` across the subprocess boundary — every failure is None.

    ``subprocess.run`` is faked rather than invoking the real script: these are
    the answers the real script cannot be made to give on demand, and they are
    exactly the ones that must degrade to silence.
    """

    SCRIPT = Path("nowhere") / "check_memory_triggers.py"

    def _payload_via(self, run):
        with _patched(harvest_nudge.subprocess, "run", run):
            return harvest_nudge._trigger_payload(
                Path("fixture") / "memory", self.SCRIPT
            )

    def test_return_code_1_is_success_not_failure(self):
        # THE regression this feature lives or dies on. check_memory_triggers.py
        # defines EXIT_FIRED = 1, so "a trigger fired" IS the non-zero-rc case.
        # Reading non-zero as failure — the obvious reading — turns the whole
        # reminder into a permanent no-op that nothing else would ever report.
        body = json.dumps(
            _payload(_trigger("t2-corpus-size", "FIRED"), corpus_notes=512)
        )
        payload = self._payload_via(_FakeRun(returncode=1, stdout=body))
        self.assertIsNotNone(payload)
        self.assertEqual(payload["corpus_notes"], 512)

    def test_return_code_0_is_also_accepted(self):
        payload = self._payload_via(
            _FakeRun(returncode=0, stdout=json.dumps(_clear_payload()))
        )
        self.assertIsNotNone(payload)

    def test_accepted_return_codes_match_the_scripts_own_exit_constants(self):
        # The hook does not import scripts/ (see the PENDING_PREFIX pin above),
        # so the accepted return codes are duplicated knowledge. Pin them against
        # the definitions so renumbering the script's exits cannot silently make a
        # fired trigger look like an error — or an error look like a finding.
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
        import check_memory_triggers  # noqa: E402

        self.assertEqual(check_memory_triggers.EXIT_PASS, 0)
        self.assertEqual(check_memory_triggers.EXIT_FIRED, 1)
        self.assertEqual(check_memory_triggers.EXIT_ERROR, 2)
        body = json.dumps(_clear_payload())
        for rc in (check_memory_triggers.EXIT_PASS, check_memory_triggers.EXIT_FIRED):
            self.assertIsNotNone(
                self._payload_via(_FakeRun(returncode=rc, stdout=body)),
                f"rc {rc} is a defined verdict and must be parsed",
            )
        self.assertIsNone(
            self._payload_via(
                _FakeRun(returncode=check_memory_triggers.EXIT_ERROR, stdout=body)
            ),
            "EXIT_ERROR must not be read as a verdict",
        )

    def test_undefined_return_code_is_silent(self):
        self.assertIsNone(
            self._payload_via(
                _FakeRun(returncode=3, stdout=json.dumps(_clear_payload()))
            )
        )

    def test_timeout_is_silent(self):
        self.assertIsNone(
            self._payload_via(
                _FakeRun(
                    raises=subprocess.TimeoutExpired(
                        cmd=["python"], timeout=harvest_nudge.TRIGGER_TIMEOUT
                    )
                )
            )
        )

    def test_oserror_launching_the_interpreter_is_silent(self):
        self.assertIsNone(
            self._payload_via(_FakeRun(raises=OSError("no such executable")))
        )

    def test_malformed_json_is_silent(self):
        self.assertIsNone(self._payload_via(_FakeRun(stdout="{not json")))
        self.assertIsNone(self._payload_via(_FakeRun(stdout="")))

    def test_json_that_is_not_an_object_is_silent(self):
        self.assertIsNone(self._payload_via(_FakeRun(stdout="[1, 2, 3]")))
        self.assertIsNone(self._payload_via(_FakeRun(stdout="null")))

    def test_the_subprocess_call_skips_transcripts_and_targets_the_given_memory(self):
        run = _FakeRun(stdout=json.dumps(_clear_payload()))
        with _patched(harvest_nudge.subprocess, "run", run):
            harvest_nudge._trigger_payload(Path("fixture") / "memory", self.SCRIPT)
        self.assertEqual(len(run.calls), 1)
        argv, kwargs = run.calls[0]
        self.assertEqual(argv[0], sys.executable)
        self.assertEqual(argv[1], str(self.SCRIPT))
        # --skip-transcripts is not optional: the full T4 scan takes minutes and
        # must never run inside a SessionStart hook.
        self.assertIn("--skip-transcripts", argv)
        self.assertIn("--json", argv)
        self.assertEqual(
            argv[argv.index("--memory-root") + 1], str(Path("fixture") / "memory")
        )
        # A pathological tree must not hang session start.
        self.assertEqual(kwargs["timeout"], harvest_nudge.TRIGGER_TIMEOUT)
        self.assertGreater(harvest_nudge.TRIGGER_TIMEOUT, 0)


class TriggerMessageTest(unittest.TestCase):
    """``trigger_message``/``trigger_nudge``: resolution, gating, degradation."""

    def _with_config(self, d):
        saved = os.environ.get("CLAUDE_CONFIG_DIR")
        os.environ["CLAUDE_CONFIG_DIR"] = d
        return saved

    def _restore_config(self, saved):
        if saved is None:
            os.environ.pop("CLAUDE_CONFIG_DIR", None)
        else:
            os.environ["CLAUDE_CONFIG_DIR"] = saved

    @contextlib.contextmanager
    def _repo_with_memory(self):
        """Yield a fixture repo root that owns an (empty) ``memory/`` directory."""
        with tempfile.TemporaryDirectory() as work:
            (Path(work) / "memory").mkdir()
            yield work

    def test_framework_root_owns_the_trigger_script(self):
        # scripts/ is never symlinked into ~/.claude/; the hook reaches the
        # script through the hooks/ symlink's resolved parent instead. If this
        # stops holding, every trigger reminder goes silent and nothing says so.
        root = harvest_nudge._framework_root()
        self.assertEqual(root, Path(harvest_nudge.__file__).resolve().parent.parent)
        self.assertTrue((root / "scripts" / "check_memory_triggers.py").is_file())

    def test_fired_trigger_is_surfaced_for_this_repos_memory(self):
        run = _FakeRun(
            returncode=1,
            stdout=json.dumps(
                _payload(_trigger("t2-corpus-size", "FIRED"), corpus_notes=512)
            ),
        )
        with self._repo_with_memory() as work:
            with _patched(harvest_nudge.subprocess, "run", run):
                msg = harvest_nudge.trigger_message(work)
        self.assertIn("FIRED", msg)
        self.assertIn("512", msg)
        # The memory root handed to the script is this repo's, not the
        # framework's — the framework's own memory/ would report the same handful
        # of notes in every repo on the machine.
        argv = run.calls[0][0]
        self.assertEqual(
            argv[argv.index("--memory-root") + 1], str(Path(work) / "memory")
        )
        self.assertNotIn(str(harvest_nudge._framework_root() / "memory"), argv)

    def test_clear_corpus_says_nothing(self):
        run = _FakeRun(stdout=json.dumps(_clear_payload()))
        with self._repo_with_memory() as work:
            with _patched(harvest_nudge.subprocess, "run", run):
                self.assertEqual(harvest_nudge.trigger_message(work), "")

    def test_output_is_at_most_two_lines(self):
        run = _FakeRun(
            returncode=1,
            stdout=json.dumps(
                _payload(
                    _trigger("t1-directory-size", "FIRED"),
                    _trigger("t2-corpus-size", "FIRED"),
                    _trigger("t3-unrouted-harvest", "FIRED", headline="2 unrouted"),
                    corpus_notes=512,
                    directory_notes={"alpha": 118, "beta": 101},
                )
            ),
        )
        with self._repo_with_memory() as work:
            with _patched(harvest_nudge.subprocess, "run", run):
                msg = harvest_nudge.trigger_message(work)
        self.assertEqual(len(msg.splitlines()), 2)

    def test_a_fired_trigger_suppresses_the_near_threshold_note(self):
        # A FIRED trigger already implies "near the threshold"; printing both
        # would spend the whole two-line budget saying one thing twice.
        run = _FakeRun(
            returncode=1,
            stdout=json.dumps(
                _payload(
                    _trigger("t2-corpus-size", "FIRED"),
                    corpus_notes=512,
                    directory_notes={"alpha": 95},
                )
            ),
        )
        with self._repo_with_memory() as work:
            with _patched(harvest_nudge.subprocess, "run", run):
                msg = harvest_nudge.trigger_message(work)
        self.assertIn("FIRED", msg)
        self.assertNotIn("nearing threshold", msg)

    def test_near_threshold_is_surfaced_when_nothing_fired(self):
        run = _FakeRun(stdout=json.dumps(_clear_payload(directory_notes={"alpha": 95})))
        with self._repo_with_memory() as work:
            with _patched(harvest_nudge.subprocess, "run", run):
                msg = harvest_nudge.trigger_message(work)
        self.assertIn("nearing threshold", msg)
        self.assertIn("95", msg)

    def test_silent_when_memory_dir_is_absent(self):
        run = _FakeRun(
            stdout=json.dumps(_payload(_trigger("t2-corpus-size", "FIRED")))
        )
        with tempfile.TemporaryDirectory() as work:
            with _patched(harvest_nudge.subprocess, "run", run):
                self.assertEqual(harvest_nudge.trigger_message(work), "")
        # A repo with no brain has no triggers — and the script is never even run.
        self.assertEqual(run.calls, [])

    def test_silent_when_the_trigger_script_is_missing(self):
        # A copy-install, or a relocated framework, must produce silence rather
        # than an error line in every session's context.
        run = _FakeRun(
            stdout=json.dumps(_payload(_trigger("t2-corpus-size", "FIRED")))
        )
        with self._repo_with_memory() as work, tempfile.TemporaryDirectory() as fake:
            with _patched(harvest_nudge, "_framework_root", lambda: Path(fake)):
                with _patched(harvest_nudge.subprocess, "run", run):
                    self.assertEqual(harvest_nudge.trigger_message(work), "")
        self.assertEqual(run.calls, [])

    def test_silent_on_every_subprocess_failure(self):
        failures = [
            _FakeRun(raises=subprocess.TimeoutExpired(cmd=["python"], timeout=5)),
            _FakeRun(raises=OSError("boom")),
            _FakeRun(returncode=2, stdout=json.dumps(_clear_payload())),
            _FakeRun(stdout="{not json"),
            _FakeRun(stdout="[1, 2, 3]"),
        ]
        with self._repo_with_memory() as work:
            for run in failures:
                with self.subTest(case=str(run.raises or run.returncode)):
                    with _patched(harvest_nudge.subprocess, "run", run):
                        self.assertEqual(harvest_nudge.trigger_message(work), "")

    def test_source_gating_matches_the_rest_of_the_hook(self):
        calls = []

        def fake_payload(memory_root, script):
            calls.append((memory_root, script))
            return _payload(_trigger("t2-corpus-size", "FIRED"), corpus_notes=512)

        with tempfile.TemporaryDirectory() as cfg, self._repo_with_memory() as work:
            saved = self._with_config(cfg)
            try:
                with _patched(harvest_nudge, "_trigger_payload", fake_payload):
                    for source in ("clear", "compact", "", None, "unknown-source"):
                        self.assertEqual(
                            harvest_nudge.trigger_nudge({"source": source, "cwd": work}),
                            "",
                        )
                    # Not even consulted on a gated source: no subprocess cost.
                    self.assertEqual(calls, [])
                    for source in ("startup", "resume"):
                        self.assertIn(
                            "FIRED",
                            harvest_nudge.trigger_nudge(
                                {"source": source, "cwd": work}
                            ),
                        )
                    self.assertEqual(len(calls), 2)
            finally:
                self._restore_config(saved)


class TriggerNudgeMainTest(unittest.TestCase):
    """``main()``: the trigger line prints *in addition*, and nothing ever raises."""

    def _with_config(self, d):
        saved = os.environ.get("CLAUDE_CONFIG_DIR")
        os.environ["CLAUDE_CONFIG_DIR"] = d
        return saved

    def _restore_config(self, saved):
        if saved is None:
            os.environ.pop("CLAUDE_CONFIG_DIR", None)
        else:
            os.environ["CLAUDE_CONFIG_DIR"] = saved

    def _run_main(self, work, source="startup"):
        saved_stdin = sys.stdin
        try:
            sys.stdin = io.StringIO(json.dumps({"source": source, "cwd": work}))
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = harvest_nudge.main()
            return rc, out.getvalue()
        finally:
            sys.stdin = saved_stdin

    @staticmethod
    def _fired_payload(memory_root=None, script=None):
        return _payload(_trigger("t2-corpus-size", "FIRED"), corpus_notes=512)

    def _seed_trail(self, work, *, n_unharvested, watermark):
        trail = rs.trail_dir() / f"{rs.repo_key(rs.git_roots(work)[1])}.jsonl"
        rs.write_watermark(rs.watermark_path(trail), watermark)
        lines = [
            json.dumps({"ts": (watermark + timedelta(hours=i + 1)).isoformat()})
            for i in range(n_unharvested)
        ]
        trail.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return trail

    @contextlib.contextmanager
    def _session(self):
        """Yield a fixture repo root with ``memory/``, under an isolated config dir."""
        with tempfile.TemporaryDirectory() as cfg, tempfile.TemporaryDirectory() as work:
            saved = self._with_config(cfg)
            saved_thresh = harvest_nudge.NUDGE_THRESHOLD
            try:
                (Path(work) / "memory").mkdir()
                yield work
            finally:
                harvest_nudge.NUDGE_THRESHOLD = saved_thresh
                self._restore_config(saved)

    def test_trigger_line_prints_alongside_the_count_nudge(self):
        # The two harvest reminders are priority-exclusive with each other
        # because they concern one subject. A fired memory trigger is a different
        # subject, so it is additive — neither reminder may swallow the other.
        wm = datetime(2026, 7, 1, tzinfo=timezone.utc)
        with self._session() as work:
            harvest_nudge.NUDGE_THRESHOLD = 5
            self._seed_trail(work, n_unharvested=5, watermark=wm)
            with _patched(harvest_nudge, "_trigger_payload", self._fired_payload):
                rc, out = self._run_main(work)
        self.assertEqual(rc, 0)
        self.assertIn("un-harvested", out)
        self.assertIn("Memory trigger FIRED", out)
        self.assertIn("512", out)

    def test_trigger_line_prints_alongside_the_unfinished_harvest_warning(self):
        with self._session() as work:
            marker = rs.trail_dir() / harvest_nudge.pending_name(rs.git_roots(work)[1])
            marker.write_text(
                json.dumps({"reason": "fixture refusal", "read": None}),
                encoding="utf-8",
            )
            with _patched(harvest_nudge, "_trigger_payload", self._fired_payload):
                rc, out = self._run_main(work)
        self.assertEqual(rc, 0)
        self.assertIn("WITHOUT stamping", out)
        self.assertIn("Memory trigger FIRED", out)

    def test_trigger_line_alone_does_not_invent_a_harvest_reminder(self):
        with self._session() as work:
            with _patched(harvest_nudge, "_trigger_payload", self._fired_payload):
                rc, out = self._run_main(work)
        self.assertEqual(rc, 0)
        self.assertIn("Memory trigger FIRED", out)
        self.assertNotIn("un-harvested", out)
        self.assertNotIn("WITHOUT stamping", out)

    def test_harvest_reminder_survives_a_silent_trigger_check(self):
        wm = datetime(2026, 7, 1, tzinfo=timezone.utc)
        with self._session() as work:
            harvest_nudge.NUDGE_THRESHOLD = 5
            self._seed_trail(work, n_unharvested=5, watermark=wm)
            with _patched(
                harvest_nudge, "_trigger_payload", lambda memory_root, script: None
            ):
                rc, out = self._run_main(work)
        self.assertEqual(rc, 0)
        self.assertIn("un-harvested", out)
        self.assertNotIn("Memory trigger", out)

    def test_main_is_silent_and_rc0_on_gated_sources(self):
        with self._session() as work:
            with _patched(harvest_nudge, "_trigger_payload", self._fired_payload):
                for source in ("clear", "compact"):
                    rc, out = self._run_main(work, source=source)
                    self.assertEqual(rc, 0)
                    self.assertEqual(out, "")

    def test_main_is_silent_and_rc0_when_the_repo_root_cannot_be_resolved(self):
        # git_roots() falls back to cwd rather than raising, so this is the
        # pathological case. Whatever the reason, a hook that raises breaks
        # session start for every repo on the machine.
        def explode(cwd):
            raise OSError("cannot resolve repo root")

        with self._session() as work:
            with _patched(rs, "git_roots", explode):
                rc, out = self._run_main(work)
        self.assertEqual(rc, 0)
        self.assertEqual(out, "")

    def test_main_is_silent_and_rc0_when_the_trigger_check_raises(self):
        def explode(memory_root, script):
            raise RuntimeError("unexpected")

        wm = datetime(2026, 7, 1, tzinfo=timezone.utc)
        with self._session() as work:
            harvest_nudge.NUDGE_THRESHOLD = 5
            self._seed_trail(work, n_unharvested=5, watermark=wm)
            with _patched(harvest_nudge, "_trigger_payload", explode):
                rc, out = self._run_main(work)
        self.assertEqual(rc, 0)
        self.assertNotIn("Memory trigger", out)
        # The other reminder had already been printed and must not be lost.
        self.assertIn("un-harvested", out)


class TriggerEndToEndTest(unittest.TestCase):
    """One run against the real ``check_memory_triggers.py``, on an invented tree.

    Everything else fakes the subprocess boundary. This exists so the two sides
    cannot drift apart unnoticed: it pins the real script's JSON key names, its
    ``limits`` shape, and — the part that matters most — that a genuinely fired
    trigger exits **1** and the hook still prints it.
    """

    @contextlib.contextmanager
    def _fixture_tree(self, notes):
        """Yield a repo root whose ``memory/fixture-topic/`` holds ``notes`` notes."""
        with tempfile.TemporaryDirectory() as cfg, tempfile.TemporaryDirectory() as work:
            saved = os.environ.get("CLAUDE_CONFIG_DIR")
            os.environ["CLAUDE_CONFIG_DIR"] = cfg
            try:
                topic = Path(work) / "memory" / "fixture-topic"
                topic.mkdir(parents=True)
                for i in range(notes):
                    (topic / f"note-{i:03d}.md").write_text(
                        f"# fixture note {i}\n", encoding="utf-8"
                    )
                yield work
            finally:
                if saved is None:
                    os.environ.pop("CLAUDE_CONFIG_DIR", None)
                else:
                    os.environ["CLAUDE_CONFIG_DIR"] = saved

    def test_fired_t1_is_reported_from_a_real_run(self):
        limit = 100  # DIR_NOTE_LIMIT; one directory at the limit fires T1 (rc 1)
        with self._fixture_tree(limit) as work:
            msg = harvest_nudge.trigger_message(work)
        self.assertIn("FIRED", msg)
        self.assertIn("T1", msg)
        self.assertIn(str(limit), msg)
        self.assertLessEqual(len(msg.splitlines()), 2)
        # T3 is `unknown` on a fresh tree (no tally was ever recorded) and T4 is
        # `unknown` by construction; neither may appear as a finding.
        self.assertNotIn("T3", msg)
        self.assertNotIn("T4", msg)

    def test_a_small_real_tree_says_nothing(self):
        with self._fixture_tree(3) as work:
            self.assertEqual(harvest_nudge.trigger_message(work), "")

if __name__ == "__main__":
    unittest.main()
