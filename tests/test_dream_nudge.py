import contextlib
import io
import json
import os
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from hooks import harvest_nudge  # noqa: E402  (puts hooks/ on sys.path)

# Bare names, never `hooks.`-qualified: see tests/test_harvest_nudge.py for why
# patching the qualified module would leave the code under test untouched.
import dream_nudge  # noqa: E402
import record_stop as rs  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import dream  # noqa: E402

NOW = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)
ENV_KEYS = (
    "CLAUDE_CONFIG_DIR",
    "CLAUDE_DREAM_NUDGE",
    "CLAUDE_DREAM_NUDGE_DAYS",
    "CLAUDE_DREAM_NUDGE_SESSIONS",
    "CLAUDE_DREAM_NUDGE_FIRST_SESSIONS",
)


class DreamNudgeTest(unittest.TestCase):
    """Synthetic config dir + fake repo root; transcripts are empty files whose
    mtimes are set explicitly, because the hook only ever stats them."""

    def setUp(self):
        self._saved_env = {k: os.environ.get(k) for k in ENV_KEYS}
        for k in ENV_KEYS:
            os.environ.pop(k, None)
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.config = base / "config"
        self.config.mkdir()
        os.environ["CLAUDE_CONFIG_DIR"] = str(self.config)
        self.repo = base / "work" / "my.repo"
        self.repo.mkdir(parents=True)
        self.root = dream_nudge.dream_root(str(self.repo))
        self.main_dir = self.config / "projects" / dream.slug(self.root)
        self.main_dir.mkdir(parents=True)

    def tearDown(self):
        for k, v in self._saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self._tmp.cleanup()

    # -- fixtures --------------------------------------------------------

    def sessions(self, n, *, at, directory=None, prefix="s"):
        d = directory or self.main_dir
        d.mkdir(parents=True, exist_ok=True)
        paths = []
        for i in range(n):
            p = d / f"{prefix}{i}.jsonl"
            p.write_text("{}\n", encoding="utf-8")
            os.utime(p, (at.timestamp(), at.timestamp()))
            paths.append(p)
        return paths

    def stamp(self, when):
        state = self.config / "dreams" / rs.repo_key(self.root) / dream_nudge.STATE_NAME
        state.parent.mkdir(parents=True)
        state.write_text(json.dumps({"since": when.strftime("%Y-%m-%dT%H:%M:%SZ")}), encoding="utf-8")
        return state

    def msg(self, **kw):
        return dream_nudge.dream_message(str(self.repo), now=NOW, **kw)

    # -- dreamt before ---------------------------------------------------

    def test_fires_when_old_and_enough_sessions(self):
        self.stamp(NOW - timedelta(days=8))
        self.sessions(10, at=NOW - timedelta(days=1))
        out = self.msg()
        self.assertIn("/dream", out)
        self.assertIn("10+ sessions", out)
        self.assertIn("8 days ago", out)
        self.assertNotIn("\n", out)

    def test_silent_when_dream_is_recent_even_with_many_sessions(self):
        self.stamp(NOW - timedelta(days=6))
        self.sessions(50, at=NOW - timedelta(hours=1))
        self.assertEqual(self.msg(), "")

    def test_silent_when_too_few_sessions_since_dream(self):
        self.stamp(NOW - timedelta(days=30))
        self.sessions(9, at=NOW - timedelta(days=1))
        self.sessions(20, at=NOW - timedelta(days=40), prefix="old")  # before the dream
        self.assertEqual(self.msg(), "")

    def test_worktree_transcript_dirs_count_and_foreign_dirs_do_not(self):
        self.stamp(NOW - timedelta(days=8))
        wt = self.config / "projects" / (dream.slug(self.root) + "--claude-worktrees-feat")
        other = self.config / "projects" / (dream.slug(self.root) + "-other")
        self.sessions(5, at=NOW - timedelta(days=1))
        self.sessions(4, at=NOW - timedelta(days=1), directory=other, prefix="o")
        self.assertEqual(self.msg(), "")
        self.sessions(5, at=NOW - timedelta(days=1), directory=wt, prefix="w")
        self.assertIn("10+ sessions", self.msg())

    def test_current_session_transcript_is_not_counted(self):
        self.stamp(NOW - timedelta(days=8))
        paths = self.sessions(10, at=NOW - timedelta(days=1))
        self.assertEqual(self.msg(current_transcript=str(paths[0])), "")

    def test_env_overrides_thresholds(self):
        self.stamp(NOW - timedelta(days=2))
        self.sessions(3, at=NOW - timedelta(days=1))
        os.environ["CLAUDE_DREAM_NUDGE_DAYS"] = "1"
        os.environ["CLAUDE_DREAM_NUDGE_SESSIONS"] = "3"
        self.assertIn("3+ sessions", self.msg())

    def test_bad_env_values_fall_back_to_defaults(self):
        self.stamp(NOW - timedelta(days=8))
        self.sessions(10, at=NOW - timedelta(days=1))
        os.environ["CLAUDE_DREAM_NUDGE_DAYS"] = "soon"
        os.environ["CLAUDE_DREAM_NUDGE_SESSIONS"] = "-4"
        self.assertIn("10+ sessions", self.msg())

    def test_zero_session_threshold_never_fires_on_an_empty_repo(self):
        self.stamp(NOW - timedelta(days=8))
        os.environ["CLAUDE_DREAM_NUDGE_SESSIONS"] = "0"
        self.assertEqual(self.msg(), "")

    def test_disabled_by_env(self):
        self.stamp(NOW - timedelta(days=8))
        self.sessions(10, at=NOW - timedelta(days=1))
        os.environ["CLAUDE_DREAM_NUDGE"] = "0"
        self.assertEqual(self.msg(), "")

    def test_count_short_circuits_at_limit(self):
        self.sessions(25, at=NOW - timedelta(days=1))
        n = dream_nudge.count_sessions_since([self.main_dir], NOW - timedelta(days=2), limit=4)
        self.assertEqual(n, 4)

    # -- never dreamt ----------------------------------------------------

    def test_never_dreamt_needs_the_higher_bar_inside_the_first_window(self):
        self.sessions(29, at=NOW - timedelta(days=3))
        self.sessions(40, at=NOW - timedelta(days=20), prefix="old")  # outside 14d
        self.assertEqual(self.msg(), "")
        self.sessions(1, at=NOW - timedelta(days=3), prefix="x")
        out = self.msg()
        self.assertIn("never run", out)
        self.assertIn("CLAUDE_DREAM_NUDGE=0", out)

    def test_unparseable_watermark_counts_as_never_dreamt(self):
        state = self.stamp(NOW)
        state.write_text("{not json", encoding="utf-8")
        self.sessions(10, at=NOW - timedelta(days=1))
        self.assertEqual(self.msg(), "")
        os.environ["CLAUDE_DREAM_NUDGE_FIRST_SESSIONS"] = "10"
        self.assertIn("never run", self.msg())

    def test_silent_with_no_transcript_dirs_or_config(self):
        os.environ["CLAUDE_CONFIG_DIR"] = str(Path(self._tmp.name) / "absent")
        self.assertEqual(self.msg(), "")

    # -- contract with scripts/dream.py ---------------------------------

    def test_constants_match_dream_py(self):
        self.assertEqual(dream_nudge.STATE_NAME, dream.STATE_NAME)
        self.assertEqual(dream_nudge.FIRST_WINDOW_DAYS, dream.DEFAULT_DAYS)
        self.assertEqual(dream_nudge._slug("D:\\w\\my.repo"), dream.slug("D:\\w\\my.repo"))

    def test_reads_the_watermark_dream_py_writes(self):
        """End to end: a real dream.py run stamps the file this hook reads.

        Run with a forward-slashed --repo (git's spelling, which is what
        git_roots hands the hook): the hook must still land on dream.py's key.
        """
        empty = Path(self._tmp.name) / "empty"
        empty.mkdir()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = dream.main(["--repo", self.repo.as_posix(), "--transcripts", str(empty)])
        self.assertEqual(rc, 0)
        state = self.config / "dreams" / rs.repo_key(dream_nudge.dream_root(self.repo.as_posix())) / dream_nudge.STATE_NAME
        self.assertTrue(state.is_file(), msg=str(list((self.config / "dreams").rglob("*"))))
        self.assertIsNotNone(dream_nudge.read_last_dream(state))
        # Freshly dreamt: silent however many sessions exist.
        self.sessions(50, at=datetime.now(timezone.utc))
        self.assertEqual(dream_nudge.dream_message(self.repo.as_posix()), "")

    def test_transcript_dirs_match_dream_py(self):
        (self.config / "projects" / (dream.slug(self.root) + "--claude-worktrees-a")).mkdir()
        (self.config / "projects" / (dream.slug(self.root) + "x")).mkdir()
        projects = self.config / "projects"
        self.assertEqual(
            sorted(dream_nudge._transcript_dirs(projects, self.root)),
            dream.transcript_dirs(projects, Path(self.root)),
        )

    # -- hook entry points ----------------------------------------------

    def _run_main(self, event):
        saved_stdin = sys.stdin
        sys.stdin = io.StringIO(json.dumps(event))
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                rc = harvest_nudge.main()
        finally:
            sys.stdin = saved_stdin
        return rc, out.getvalue()

    def _due(self):
        self.stamp(datetime.now(timezone.utc) - timedelta(days=8))
        self.sessions(10, at=datetime.now(timezone.utc) - timedelta(hours=1))

    def test_main_prints_dream_line_on_startup_and_resume(self):
        self._due()
        for source in ("startup", "resume"):
            rc, out = self._run_main({"source": source, "cwd": str(self.repo)})
            self.assertEqual(rc, 0)
            self.assertIn("A dream is due", out)

    def test_main_silent_on_clear_and_compact(self):
        self._due()
        for source in ("clear", "compact"):
            rc, out = self._run_main({"source": source, "cwd": str(self.repo)})
            self.assertEqual((rc, out), (0, ""))

    def test_dream_nudge_swallows_failures(self):
        saved = rs.git_roots

        def explode(cwd):
            raise RuntimeError("boom")

        rs.git_roots = explode
        try:
            self.assertEqual(dream_nudge.dream_nudge({"source": "startup", "cwd": "x"}), "")
        finally:
            rs.git_roots = saved

    def test_dream_nudge_disabled_skips_git(self):
        os.environ["CLAUDE_DREAM_NUDGE"] = "off"
        saved = rs.git_roots
        calls = []
        rs.git_roots = lambda cwd: calls.append(cwd) or (cwd, cwd)
        try:
            self.assertEqual(dream_nudge.dream_nudge({"source": "startup", "cwd": "x"}), "")
        finally:
            rs.git_roots = saved
        self.assertEqual(calls, [])

    def test_large_projects_dir_stays_fast(self):
        """Budget guard: 2,000 transcripts across 200 foreign dirs plus this repo's."""
        self.stamp(NOW - timedelta(days=8))
        projects = self.config / "projects"
        for i in range(200):
            d = projects / f"C--elsewhere-{i}"
            d.mkdir()
            for j in range(10):
                (d / f"{j}.jsonl").write_text("", encoding="utf-8")
        self.sessions(500, at=NOW - timedelta(days=1))
        start = time.perf_counter()
        self.assertIn("10+", self.msg())
        self.assertLess(time.perf_counter() - start, 0.5)


if __name__ == "__main__":
    unittest.main()
