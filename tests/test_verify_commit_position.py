"""Tests for scripts/verify_commit_position.py.

These build real throwaway git repositories in a temp dir and run real `git`
against them — the whole point of the script is its reading of genuine git state
(reachability, detached HEAD), so mocking git would test the mock. The orphan
case in particular is created honestly: `git checkout --detach`, commit, switch
back, and the commit really is unreachable from the branch.

`user.email` / `user.name` are set with `git config` *inside* each temp repo so
commits work on a clean CI machine; global config is never touched. `commit.gpgsign`
is disabled locally for the same reason — a developer with global signing on
must not have these tests fail (or hang) on a missing key.
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import verify_commit_position as vcp  # noqa: E402


def _git(repo: Path, *args: str) -> str:
    """Run git in `repo`, raising with full stderr on failure."""
    proc = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"`git {' '.join(args)}` failed in {repo} (exit {proc.returncode}):\n"
            f"{proc.stderr.strip() or proc.stdout.strip()}"
        )
    return proc.stdout.strip()


def _commit(repo: Path, name: str, text: str) -> str:
    """Write a file, commit it, and return the resulting full sha."""
    (repo / name).write_text(text, encoding="utf-8")
    _git(repo, "add", name)
    _git(repo, "commit", "-m", f"add {name}")
    return _git(repo, "rev-parse", "HEAD")


def _init_repo(root: Path) -> Path:
    """A repo on branch `main` with one commit, configured for headless commits."""
    repo = root / "repo"
    repo.mkdir()
    _git(repo, "init", "--initial-branch=main")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "commit.gpgsign", "false")
    _commit(repo, "README.md", "initial\n")
    return repo


class VerifyCommitPositionTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base_dir = Path(self._tmp.name)
        self.repo = _init_repo(self.base_dir)

    def tearDown(self):
        self._tmp.cleanup()

    # ── happy path ─────────────────────────────────────────────────────────

    def test_commit_on_branch_passes(self):
        sha = _commit(self.repo, "a.txt", "a\n")
        rc, lines = vcp.verify(sha, "main", repo=self.repo)
        out = "\n".join(lines)
        self.assertEqual(rc, 0, out)
        self.assertIn("is reachable from main", out)
        self.assertIn("HEAD is attached to main", out)

    def test_short_sha_is_accepted(self):
        sha = _commit(self.repo, "a.txt", "a\n")
        rc, lines = vcp.verify(sha[:8], "main", repo=self.repo)
        self.assertEqual(rc, 0, "\n".join(lines))

    # ── orphan detection ───────────────────────────────────────────────────

    def test_commit_made_on_detached_head_is_reported_as_orphan(self):
        """The real failure mode: commit from a detached HEAD, then switch back."""
        _git(self.repo, "checkout", "--detach")
        orphan = _commit(self.repo, "orphan.txt", "lost work\n")
        _git(self.repo, "switch", "main")

        # Sanity: the commit genuinely is not on main.
        self.assertNotEqual(orphan, _git(self.repo, "rev-parse", "main"))

        rc, lines = vcp.verify(orphan, "main", repo=self.repo)
        out = "\n".join(lines)
        self.assertEqual(rc, 1, out)
        self.assertIn("is NOT reachable from main", out)
        self.assertIn("orphaned", out)
        # The recovery instructions must name both the branch and the sha.
        self.assertIn("git switch main", out)
        self.assertIn("git cherry-pick", out)
        self.assertIn(orphan[:12], out)

    def test_commit_on_other_branch_is_not_on_target_branch(self):
        _git(self.repo, "switch", "-c", "feature")
        sha = _commit(self.repo, "f.txt", "feature\n")
        _git(self.repo, "switch", "main")

        rc, lines = vcp.verify(sha, "main", repo=self.repo)
        self.assertEqual(rc, 1, "\n".join(lines))
        self.assertIn("is NOT reachable from main", "\n".join(lines))

    # ── detached HEAD at check time ────────────────────────────────────────

    def test_detached_head_at_check_time_fails_even_when_sha_is_fine(self):
        sha = _commit(self.repo, "a.txt", "a\n")
        _git(self.repo, "checkout", "--detach")

        rc, lines = vcp.verify(sha, "main", repo=self.repo)
        out = "\n".join(lines)
        self.assertEqual(rc, 1, out)
        # The reachability check still passed — only the detached check failed.
        self.assertIn("is reachable from main", out)
        self.assertIn("HEAD is detached", out)
        self.assertIn("git switch main", out)

    # ── base freshness: WARNING ONLY ───────────────────────────────────────

    def test_stale_base_warns_but_does_not_change_exit_code(self):
        """The important one: a stale base must never fail the command."""
        _git(self.repo, "switch", "-c", "feature")
        sha = _commit(self.repo, "f.txt", "feature\n")
        # main moves ahead after the branch was cut -> feature has a stale base.
        _git(self.repo, "switch", "main")
        _commit(self.repo, "m.txt", "moved on\n")
        _git(self.repo, "switch", "feature")

        rc, lines = vcp.verify(sha, "feature", base="main", repo=self.repo)
        out = "\n".join(lines)
        self.assertEqual(rc, 0, f"stale base must not fail the command:\n{out}")
        self.assertIn("WARN", out)
        self.assertIn("stale base", out)

    def test_stale_base_does_not_mask_a_real_orphan_failure(self):
        """A warning must not downgrade a hard failure either."""
        _git(self.repo, "switch", "-c", "feature")
        _commit(self.repo, "f.txt", "feature\n")
        _git(self.repo, "checkout", "--detach")
        orphan = _commit(self.repo, "orphan.txt", "lost\n")
        _git(self.repo, "switch", "main")
        _commit(self.repo, "m.txt", "moved on\n")
        _git(self.repo, "switch", "feature")

        rc, lines = vcp.verify(orphan, "feature", base="main", repo=self.repo)
        out = "\n".join(lines)
        self.assertEqual(rc, 1, out)
        self.assertIn("WARN", out)
        self.assertIn("is NOT reachable from feature", out)

    def test_fresh_base_reports_ok_and_no_warning(self):
        _git(self.repo, "switch", "-c", "feature")
        sha = _commit(self.repo, "f.txt", "feature\n")

        rc, lines = vcp.verify(sha, "feature", base="main", repo=self.repo)
        out = "\n".join(lines)
        self.assertEqual(rc, 0, out)
        self.assertIn("contains main", out)
        self.assertNotIn("WARN", out)

    def test_unresolvable_base_warns_rather_than_erroring(self):
        """An unfetched base ref must degrade to a warning, not exit 2."""
        sha = _commit(self.repo, "a.txt", "a\n")

        rc, lines = vcp.verify(sha, "main", base="origin/nope", repo=self.repo)
        out = "\n".join(lines)
        self.assertEqual(rc, 0, out)
        self.assertIn("WARN", out)
        self.assertIn("git fetch", out)

    # ── environment / usage errors → exit 2 ────────────────────────────────

    def test_not_a_git_repo_exits_2(self):
        with tempfile.TemporaryDirectory() as d:
            rc, lines = vcp.verify("HEAD", "main", repo=d)
            self.assertEqual(rc, 2, "\n".join(lines))
            self.assertIn("not a git repository", "\n".join(lines))

    def test_missing_repo_path_exits_2(self):
        rc, lines = vcp.verify("HEAD", "main", repo=self.base_dir / "nope")
        self.assertEqual(rc, 2, "\n".join(lines))
        self.assertIn("not a directory", "\n".join(lines))

    def test_unknown_sha_exits_2(self):
        rc, lines = vcp.verify("deadbeefdeadbeef", "main", repo=self.repo)
        self.assertEqual(rc, 2, "\n".join(lines))
        self.assertIn("unknown commit", "\n".join(lines))

    def test_unknown_branch_exits_2(self):
        sha = _commit(self.repo, "a.txt", "a\n")
        rc, lines = vcp.verify(sha, "no-such-branch", repo=self.repo)
        self.assertEqual(rc, 2, "\n".join(lines))
        self.assertIn("unknown branch", "\n".join(lines))


class MainCliTest(unittest.TestCase):
    """`main()` is a thin shell: it must return verify()'s code, not swallow it."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = _init_repo(Path(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()

    def _main(self, argv: list[str]) -> tuple[int, str]:
        import contextlib
        import io

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = vcp.main(argv)
        return rc, buf.getvalue()

    def test_main_returns_zero_on_pass(self):
        sha = _commit(self.repo, "a.txt", "a\n")
        rc, out = self._main([sha, "main", "--repo", str(self.repo)])
        self.assertEqual(rc, 0, out)
        self.assertIn("PASS", out)

    def test_main_returns_one_on_orphan(self):
        _git(self.repo, "checkout", "--detach")
        orphan = _commit(self.repo, "orphan.txt", "lost\n")
        _git(self.repo, "switch", "main")
        rc, out = self._main([orphan, "main", "--repo", str(self.repo)])
        self.assertEqual(rc, 1, out)
        self.assertIn("FAIL", out)

    def test_main_returns_two_on_bad_branch(self):
        sha = _commit(self.repo, "a.txt", "a\n")
        rc, out = self._main([sha, "nope", "--repo", str(self.repo)])
        self.assertEqual(rc, 2, out)


if __name__ == "__main__":
    unittest.main()
