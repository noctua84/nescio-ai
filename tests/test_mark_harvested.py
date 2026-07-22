import contextlib
import io
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "hooks"))
sys.path.insert(0, str(ROOT / "scripts"))
import record_stop as rs  # noqa: E402
import mark_harvested  # noqa: E402


class MarkHarvestedTest(unittest.TestCase):
    def _with_config(self, d):
        saved = os.environ.get("CLAUDE_CONFIG_DIR")
        os.environ["CLAUDE_CONFIG_DIR"] = d
        return saved

    def _restore_config(self, saved):
        if saved is None:
            os.environ.pop("CLAUDE_CONFIG_DIR", None)
        else:
            os.environ["CLAUDE_CONFIG_DIR"] = saved

    def _seed_trails(self, names):
        """Create empty *.jsonl trail files; return their paths."""
        td = rs.trail_dir()
        paths = []
        for name in names:
            p = td / f"{name}.jsonl"
            p.write_text("{}\n", encoding="utf-8")
            paths.append(p)
        return paths

    def test_stamp_watermark_writes_paired_file(self):
        with tempfile.TemporaryDirectory() as cfg:
            saved = self._with_config(cfg)
            try:
                (trail,) = self._seed_trails(["repoA"])
                ts = datetime(2026, 7, 12, 8, 0, tzinfo=timezone.utc)
                wm = mark_harvested.stamp_watermark(trail, ts)
                self.assertEqual(wm, rs.watermark_path(trail))
                self.assertTrue(wm.is_file())
                self.assertEqual(rs.read_watermark(wm), ts)
            finally:
                self._restore_config(saved)

    def test_mark_all_harvested_stamps_every_trail(self):
        with tempfile.TemporaryDirectory() as cfg:
            saved = self._with_config(cfg)
            try:
                trails = self._seed_trails(["repoA", "repoB", "repoC"])
                ts = datetime(2026, 7, 12, 8, 0, tzinfo=timezone.utc)
                written = mark_harvested.mark_all_harvested(now=ts)
                self.assertEqual(len(written), 3)
                for trail in trails:
                    wm = rs.watermark_path(trail)
                    self.assertTrue(wm.is_file())
                    self.assertEqual(rs.read_watermark(wm), ts)
            finally:
                self._restore_config(saved)

    def test_mark_all_harvested_empty_dir_returns_empty(self):
        with tempfile.TemporaryDirectory() as cfg:
            saved = self._with_config(cfg)
            try:
                self.assertEqual(mark_harvested.mark_all_harvested(), [])
            finally:
                self._restore_config(saved)

    def test_main_with_at_stamps_all_and_returns_zero(self):
        with tempfile.TemporaryDirectory() as cfg:
            saved = self._with_config(cfg)
            try:
                trails = self._seed_trails(["repoA", "repoB"])
                iso = "2026-07-12T08:00:00+00:00"
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    rc = mark_harvested.main(["--at", iso])
                self.assertEqual(rc, 0)
                expected = datetime.fromisoformat(iso)
                for trail in trails:
                    self.assertEqual(
                        rs.read_watermark(rs.watermark_path(trail)), expected
                    )
            finally:
                self._restore_config(saved)

    def test_main_without_arg_stamps_with_now(self):
        with tempfile.TemporaryDirectory() as cfg:
            saved = self._with_config(cfg)
            try:
                (trail,) = self._seed_trails(["repoA"])
                before = datetime.now(timezone.utc)
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    rc = mark_harvested.main([])
                after = datetime.now(timezone.utc)
                self.assertEqual(rc, 0)
                stamped = rs.read_watermark(rs.watermark_path(trail))
                self.assertIsNotNone(stamped)
                self.assertGreaterEqual(stamped, before)
                self.assertLessEqual(stamped, after)
            finally:
                self._restore_config(saved)

    def test_main_bad_at_falls_back_to_now_and_returns_zero(self):
        with tempfile.TemporaryDirectory() as cfg:
            saved = self._with_config(cfg)
            try:
                (trail,) = self._seed_trails(["repoA"])
                before = datetime.now(timezone.utc)
                out, err = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    rc = mark_harvested.main(["--at", "not-a-timestamp"])
                after = datetime.now(timezone.utc)
                self.assertEqual(rc, 0)
                # Fell back to now() rather than crashing.
                stamped = rs.read_watermark(rs.watermark_path(trail))
                self.assertIsNotNone(stamped)
                self.assertGreaterEqual(stamped, before)
                self.assertLessEqual(stamped, after)
                self.assertIn("invalid --at", err.getvalue())
            finally:
                self._restore_config(saved)


if __name__ == "__main__":
    unittest.main()
