import contextlib
import io
import json
import os
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
        """The trail path harvest_nudge/record_stop resolve for a working dir."""
        return rs.trail_dir() / f"{rs.repo_key(rs.git_root(work))}.jsonl"

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
        p = rs.trail_dir() / harvest_nudge.pending_name(rs.git_root(work))
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
                root = rs.git_root(work)
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


if __name__ == "__main__":
    unittest.main()
