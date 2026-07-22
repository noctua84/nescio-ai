import io
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "hooks"))
import record_stop as rs  # noqa: E402


class ConfigDirTest(unittest.TestCase):
    def test_honors_claude_config_dir(self):
        with tempfile.TemporaryDirectory() as d:
            saved = os.environ.get("CLAUDE_CONFIG_DIR")
            os.environ["CLAUDE_CONFIG_DIR"] = d
            try:
                self.assertEqual(rs.config_dir(), Path(d))
                self.assertEqual(rs.trail_dir(), Path(d) / "learning-trail")
                self.assertTrue((Path(d) / "learning-trail").is_dir())
            finally:
                if saved is None:
                    del os.environ["CLAUDE_CONFIG_DIR"]
                else:
                    os.environ["CLAUDE_CONFIG_DIR"] = saved

    def test_defaults_to_home_when_unset(self):
        saved = os.environ.pop("CLAUDE_CONFIG_DIR", None)
        try:
            self.assertEqual(rs.config_dir(), Path.home() / ".claude")
        finally:
            if saved is not None:
                os.environ["CLAUDE_CONFIG_DIR"] = saved


class RepoKeyTest(unittest.TestCase):
    def test_slug_prefix_with_hash_suffix(self):
        key = rs.repo_key("C:\\Users\\me\\proj")
        self.assertTrue(key.startswith("C--Users-me-proj-"))
        # 8-char hex hash suffix keeps distinct paths on distinct files.
        self.assertRegex(key, r"-[0-9a-f]{8}$")

    def test_collision_resistant(self):
        # "foo/bar" and "foo-bar" both slugify to "foo-bar" and used to collide
        # onto the same trail file; the hash suffix must now separate them.
        a = rs.repo_key("foo/bar")
        b = rs.repo_key("foo-bar")
        self.assertTrue(a.startswith("foo-bar-"))
        self.assertTrue(b.startswith("foo-bar-"))
        self.assertNotEqual(a, b)


class PreviewTest(unittest.TestCase):
    def test_collapses_to_single_line(self):
        self.assertEqual(rs.message_preview("a\n b\t c"), "a b c")

    def test_truncates_to_500_chars(self):
        self.assertEqual(len(rs.message_preview("x" * 900)), 500)

    def test_redacts_openai_key(self):
        preview = rs.message_preview("here is sk-abcdef0123456789ABCDEF token")
        self.assertEqual(preview, "[redacted]")

    def test_redacts_github_token(self):
        preview = rs.message_preview("ghp_" + "a" * 36)
        self.assertEqual(preview, "[redacted]")

    def test_redacts_aws_and_jwt_and_slack(self):
        # split literals so the scrub baseline doesn't flag the fixtures as real
        # secrets — message_preview still sees the concatenated value (same style
        # as the ghp_/sk_live_ fixtures above).
        self.assertEqual(rs.message_preview("AKIA" + "ABCDEFGHIJKLMNOP"), "[redacted]")
        self.assertEqual(rs.message_preview("xoxb-" + "123456789012-abcXYZ"), "[redacted]")
        jwt = "eyJhbGciOi.eyJzdWIiOi.SflKxwRJSM"
        self.assertEqual(rs.message_preview(jwt), "[redacted]")

    def test_redacts_stripe_underscore_key(self):
        self.assertEqual(rs.message_preview("sk_live_" + "a" * 24), "[redacted]")
        self.assertEqual(rs.message_preview("rk_test_" + "b" * 24), "[redacted]")

    def test_redacts_github_oauth_token(self):
        self.assertEqual(rs.message_preview("gho_" + "a" * 36), "[redacted]")
        self.assertEqual(rs.message_preview("github_pat_" + "a" * 24), "[redacted]")

    def test_redacts_google_api_key(self):
        self.assertEqual(rs.message_preview("AIza" + "A1b2" * 9), "[redacted]")

    def test_redacts_pem_private_key(self):
        self.assertEqual(
            rs.message_preview("-----BEGIN RSA PRIVATE " + "KEY-----"), "[redacted]"
        )
        self.assertEqual(
            rs.message_preview("-----BEGIN PRIVATE " + "KEY-----"), "[redacted]"
        )

    def test_redacts_url_credentials(self):
        self.assertEqual(
            rs.message_preview("clone https://user:secret@example.com/x.git"),
            "[redacted]",
        )

    def test_redacts_before_truncating(self):
        # A secret whose identifying prefix straddles the 500-char boundary:
        # truncate-first would sever "sk_live_" mid-prefix and leak the rest.
        # Redact-first scans the full collapsed text and catches it.
        filler = "a" * 495
        secret = "sk_live_" + "c" * 30
        self.assertEqual(rs.message_preview(filler + secret), "[redacted]")

    def test_clean_text_passes_through(self):
        self.assertEqual(rs.message_preview("just a normal reply"), "just a normal reply")


class BuildRecordTest(unittest.TestCase):
    def test_well_formed_event_yields_all_fields(self):
        with tempfile.TemporaryDirectory() as d:
            event = {
                "session_id": "sess-1",
                "cwd": d,
                "last_assistant_message": "did the thing",
                "turn_number": 3,
            }
            rec = rs.build_record(event)
            self.assertEqual(rec["session_id"], "sess-1")
            self.assertEqual(rec["message_preview"], "did the thing")
            self.assertTrue(rec["ts"])
            # ts must be parseable ISO8601
            datetime.fromisoformat(rec["ts"])
            self.assertIn("git_root", rec)
            self.assertIn("git_branch", rec)

    def test_captures_prompt_id_and_drops_turn_number(self):
        # turn_number is not a real Stop-payload field; prompt_id is.
        event = {"prompt_id": "p-123", "turn_number": 9}
        rec = rs.build_record(event)
        self.assertEqual(rec["prompt_id"], "p-123")
        self.assertNotIn("turn_number", rec)

    def test_missing_fields_tolerated(self):
        rec = rs.build_record({})
        self.assertEqual(rec["session_id"], "")
        self.assertIsNone(rec["prompt_id"])
        self.assertNotIn("turn_number", rec)
        self.assertEqual(rec["message_preview"], "")

    def test_git_root_falls_back_to_cwd_when_not_a_repo(self):
        with tempfile.TemporaryDirectory() as d:
            # A bare tempdir is not a git repo -> git_root falls back to cwd.
            root = rs.git_root(d)
            self.assertEqual(Path(root), Path(d))
            self.assertEqual(rs.git_branch(d), "")


class GitBranchTest(unittest.TestCase):
    @staticmethod
    def _has_git():
        return bool(rs._git(os.getcwd(), "--version"))

    def test_branch_reported_on_unborn_branch(self):
        # Regression for the reported bug: `rev-parse --abbrev-ref HEAD` fails on
        # a fresh repo with no commits, so git_branch used to return "". The
        # `branch --show-current` invocation reports the branch even then.
        if not self._has_git():
            self.skipTest("git not available")
        with tempfile.TemporaryDirectory() as d:
            rs._git(d, "init", "-q")
            rs._git(d, "checkout", "-q", "-b", "work")
            self.assertEqual(rs.git_branch(d), "work")

    def test_branch_non_empty_in_this_repo(self):
        if not self._has_git():
            self.skipTest("git not available")
        branch = rs.git_branch(str(ROOT))
        if not branch:
            # A detached-HEAD checkout (some CI setups) legitimately has no
            # branch; the assertion only applies to a normal branch checkout.
            self.skipTest("detached HEAD checkout")
        self.assertTrue(branch)


class AppendAndPruneTest(unittest.TestCase):
    def test_append_writes_one_valid_jsonl_record(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "trail.jsonl"
            rs.append_record(path, {"ts": "x", "message_preview": "hi"})
            lines = path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 1)
            self.assertEqual(json.loads(lines[0])["message_preview"], "hi")

    def test_prune_drops_records_older_than_14_days(self):
        now = datetime(2026, 7, 12, tzinfo=timezone.utc)
        old = (now - timedelta(days=20)).isoformat()
        recent = (now - timedelta(days=2)).isoformat()
        lines = [
            json.dumps({"ts": old, "message_preview": "old"}),
            json.dumps({"ts": recent, "message_preview": "recent"}),
        ]
        # Watermark newer than the old record marks it harvested, so age-out
        # applies; without a watermark the old record would be protected.
        watermark = now - timedelta(days=10)
        kept = rs.prune_lines(lines, now=now, watermark=watermark)
        self.assertEqual(len(kept), 1)
        self.assertEqual(json.loads(kept[0])["message_preview"], "recent")

    def test_prune_skips_malformed_lines(self):
        kept = rs.prune_lines(["not json", "", "{bad"], now=datetime.now(timezone.utc))
        self.assertEqual(kept, [])

    def test_prune_drops_unparseable_ts(self):
        # Valid JSON but corrupted ts: aged out rather than kept forever, even
        # with no watermark (corrupt lines are never protected).
        now = datetime(2026, 7, 12, tzinfo=timezone.utc)
        lines = [json.dumps({"ts": "not-a-date", "message_preview": "corrupt"})]
        self.assertEqual(rs.prune_lines(lines, now=now), [])

    def test_prune_keeps_unharvested_old_records(self):
        # Watermark OLDER than a 20-day-old record → that record is un-harvested
        # (newer than the watermark) → kept despite exceeding the retention age.
        now = datetime(2026, 7, 12, tzinfo=timezone.utc)
        old = (now - timedelta(days=20)).isoformat()
        watermark = now - timedelta(days=25)
        lines = [json.dumps({"ts": old, "message_preview": "unharvested-old"})]
        kept = rs.prune_lines(lines, now=now, watermark=watermark)
        self.assertEqual(len(kept), 1)
        self.assertEqual(json.loads(kept[0])["message_preview"], "unharvested-old")

    def test_prune_no_watermark_keeps_all_parseable(self):
        # watermark=None → nothing has been harvested → every parseable record is
        # protected regardless of age.
        now = datetime(2026, 7, 12, tzinfo=timezone.utc)
        old = (now - timedelta(days=40)).isoformat()
        recent = (now - timedelta(days=1)).isoformat()
        lines = [
            json.dumps({"ts": old, "message_preview": "old"}),
            json.dumps({"ts": recent, "message_preview": "recent"}),
        ]
        kept = rs.prune_lines(lines, now=now, watermark=None)
        self.assertEqual(len(kept), 2)

    def test_prune_drops_harvested_old_keeps_unharvested_old(self):
        # Two old records straddling the watermark: the one at/below the watermark
        # (harvested) drops; the one above it (un-harvested) is kept.
        now = datetime(2026, 7, 12, tzinfo=timezone.utc)
        harvested_old = (now - timedelta(days=30)).isoformat()
        unharvested_old = (now - timedelta(days=18)).isoformat()
        watermark = now - timedelta(days=20)
        lines = [
            json.dumps({"ts": harvested_old, "message_preview": "harvested"}),
            json.dumps({"ts": unharvested_old, "message_preview": "unharvested"}),
        ]
        kept = rs.prune_lines(lines, now=now, watermark=watermark)
        self.assertEqual(len(kept), 1)
        self.assertEqual(json.loads(kept[0])["message_preview"], "unharvested")

    def test_append_does_not_lose_prior_line(self):
        # Below the prune threshold: append is a pure O_APPEND write, so an
        # existing line survives untouched alongside the new one.
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "trail.jsonl"
            path.write_text(
                json.dumps({"ts": "2026-07-11T00:00:00+00:00", "m": "first"}) + "\n",
                encoding="utf-8",
            )
            rs.append_record(path, {"ts": "2026-07-12T00:00:00+00:00", "m": "second"})
            lines = path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 2)
            self.assertEqual(json.loads(lines[0])["m"], "first")
            self.assertEqual(json.loads(lines[1])["m"], "second")

    def test_append_prunes_when_over_threshold(self):
        # Past PRUNE_SIZE_THRESHOLD the cold path fires: stale lines are dropped
        # via the atomic temp-file rewrite, bounding file growth.
        now = datetime(2026, 7, 12, tzinfo=timezone.utc)
        old = json.dumps({"ts": (now - timedelta(days=30)).isoformat(), "m": "old"})
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "trail.jsonl"
            path.write_text("\n".join([old] * 200) + "\n", encoding="utf-8")
            # Stamp a watermark newer than the 30-day-old records so they count
            # as harvested and are eligible to age out; the appended record (ts
            # now) is newer than the watermark, so it is protected.
            rs.write_watermark(
                rs.watermark_path(path), now - timedelta(days=1)
            )
            saved = rs.PRUNE_SIZE_THRESHOLD
            rs.PRUNE_SIZE_THRESHOLD = 10  # force the prune path
            try:
                rs.append_record(
                    path, {"ts": now.isoformat(), "m": "new"}, now=now
                )
            finally:
                rs.PRUNE_SIZE_THRESHOLD = saved
            lines = path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 1)
            self.assertEqual(json.loads(lines[0])["m"], "new")

    def test_prune_never_raises_on_missing_file(self):
        # The cold path must swallow any error so it can never fail the hook.
        with tempfile.TemporaryDirectory() as d:
            missing = Path(d) / "gone.jsonl"
            rs._maybe_prune(missing)  # no file -> stat() raises, swallowed

    def test_prune_ceiling_caps_unharvested(self):
        # Even with no watermark (every record un-harvested), the absolute
        # ceiling bounds the kept set to the most-recent ABSOLUTE_MAX_RECORDS.
        now = datetime(2026, 7, 12, tzinfo=timezone.utc)
        saved = rs.ABSOLUTE_MAX_RECORDS
        rs.ABSOLUTE_MAX_RECORDS = 5
        try:
            total = rs.ABSOLUTE_MAX_RECORDS + 3
            lines = [
                json.dumps(
                    {
                        "ts": (now - timedelta(minutes=total - i)).isoformat(),
                        "m": f"rec-{i}",
                    }
                )
                for i in range(total)
            ]
            kept = rs.prune_lines(lines, now=now, watermark=None)
            self.assertEqual(len(kept), rs.ABSOLUTE_MAX_RECORDS)
            # The tail (newest) is what survives: last 5 of rec-0..rec-7.
            kept_ms = [json.loads(k)["m"] for k in kept]
            self.assertEqual(
                kept_ms, [f"rec-{i}" for i in range(3, total)]
            )
        finally:
            rs.ABSOLUTE_MAX_RECORDS = saved

    def test_maybe_prune_skips_rewrite_when_nothing_dropped(self):
        # Over the size threshold but nothing to drop (all un-harvested, under
        # the ceiling): the file must be left byte-for-byte identical and no
        # temp file left behind. Then a case that DOES drop → file is rewritten.
        now = datetime(2026, 7, 12, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "trail.jsonl"
            keep_lines = [
                json.dumps(
                    {"ts": (now - timedelta(days=i)).isoformat(), "m": f"k-{i}"}
                )
                for i in range(5)
            ]
            original = "\n".join(keep_lines) + "\n"
            path.write_text(original, encoding="utf-8")
            before_mtime = path.stat().st_mtime_ns
            saved = rs.PRUNE_SIZE_THRESHOLD
            rs.PRUNE_SIZE_THRESHOLD = 10  # force the prune path
            try:
                # No watermark → everything un-harvested → nothing dropped.
                rs._maybe_prune(path, now=now)
                self.assertEqual(path.read_text(encoding="utf-8"), original)
                self.assertEqual(path.stat().st_mtime_ns, before_mtime)
                self.assertFalse((path.parent / (path.name + ".tmp")).exists())

                # Now stamp a watermark that makes the oldest records harvested
                # and aged out → the file must be rewritten (shorter).
                rs.write_watermark(
                    rs.watermark_path(path), now - timedelta(days=1)
                )
                # Rewrite the trail with old harvested records that should drop.
                old = json.dumps(
                    {"ts": (now - timedelta(days=30)).isoformat(), "m": "old"}
                )
                fresh = json.dumps({"ts": now.isoformat(), "m": "fresh"})
                path.write_text("\n".join([old, old, fresh]) + "\n", encoding="utf-8")
                rs._maybe_prune(path, now=now)
                remaining = path.read_text(encoding="utf-8").splitlines()
                self.assertEqual(len(remaining), 1)
                self.assertEqual(json.loads(remaining[0])["m"], "fresh")
                self.assertFalse((path.parent / (path.name + ".tmp")).exists())
            finally:
                rs.PRUNE_SIZE_THRESHOLD = saved


class WatermarkTest(unittest.TestCase):
    def test_watermark_path_pairs_trail(self):
        self.assertEqual(
            rs.watermark_path(Path("x/abc.jsonl")), Path("x/abc.watermark")
        )

    def test_watermark_write_then_read(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "trail.watermark"
            ts = datetime(2026, 7, 12, 9, 30, tzinfo=timezone.utc)
            rs.write_watermark(path, ts)
            self.assertEqual(rs.read_watermark(path), ts)

    def test_read_watermark_missing_returns_none(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(rs.read_watermark(Path(d) / "absent.watermark"))

    def test_read_watermark_corrupt_returns_none(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "trail.watermark"
            path.write_text("not-a-timestamp", encoding="utf-8")
            self.assertIsNone(rs.read_watermark(path))

    def test_read_watermark_naive_assumes_utc(self):
        # A watermark written without tz info is read back as UTC-aware so it can
        # be compared against tz-aware record timestamps.
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "trail.watermark"
            path.write_text("2026-07-12T09:30:00", encoding="utf-8")
            parsed = rs.read_watermark(path)
            self.assertIsNotNone(parsed)
            self.assertEqual(parsed.tzinfo, timezone.utc)


class RecordEventTest(unittest.TestCase):
    def _with_config(self, d):
        saved = os.environ.get("CLAUDE_CONFIG_DIR")
        os.environ["CLAUDE_CONFIG_DIR"] = d
        return saved

    def _restore_config(self, saved):
        if saved is None:
            os.environ.pop("CLAUDE_CONFIG_DIR", None)
        else:
            os.environ["CLAUDE_CONFIG_DIR"] = saved

    def test_record_event_appends_to_repo_trail(self):
        with tempfile.TemporaryDirectory() as cfg, tempfile.TemporaryDirectory() as work:
            saved = self._with_config(cfg)
            try:
                event = {
                    "session_id": "s9",
                    "cwd": work,
                    "last_assistant_message": "hello world",
                    "turn_number": 1,
                }
                path = rs.record_event(event)
                self.assertTrue(path.is_file())
                self.assertEqual(path.parent, Path(cfg) / "learning-trail")
                rec = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
                self.assertEqual(rec["session_id"], "s9")
                self.assertEqual(rec["message_preview"], "hello world")
                self.assertEqual(Path(rec["git_root"]), Path(work))
            finally:
                self._restore_config(saved)


class MainTest(unittest.TestCase):
    def _run_main(self, raw_stdin):
        saved_stdin = sys.stdin
        sys.stdin = io.StringIO(raw_stdin)
        try:
            return rs.main()
        finally:
            sys.stdin = saved_stdin

    def test_empty_stdin_returns_zero(self):
        self.assertEqual(self._run_main(""), 0)

    def test_invalid_json_returns_zero(self):
        self.assertEqual(self._run_main("{not json"), 0)

    def test_non_object_json_returns_zero(self):
        self.assertEqual(self._run_main("[1, 2, 3]"), 0)

    def test_well_formed_stdin_records_and_returns_zero(self):
        with tempfile.TemporaryDirectory() as cfg, tempfile.TemporaryDirectory() as work:
            saved = os.environ.get("CLAUDE_CONFIG_DIR")
            os.environ["CLAUDE_CONFIG_DIR"] = cfg
            try:
                event = {"session_id": "m1", "cwd": work,
                         "last_assistant_message": "done", "turn_number": 2}
                rc = self._run_main(json.dumps(event))
                self.assertEqual(rc, 0)
                trail = Path(cfg) / "learning-trail"
                files = list(trail.glob("*.jsonl"))
                self.assertEqual(len(files), 1)
                rec = json.loads(files[0].read_text(encoding="utf-8").splitlines()[0])
                self.assertEqual(rec["session_id"], "m1")
            finally:
                if saved is None:
                    os.environ.pop("CLAUDE_CONFIG_DIR", None)
                else:
                    os.environ["CLAUDE_CONFIG_DIR"] = saved


if __name__ == "__main__":
    unittest.main()
