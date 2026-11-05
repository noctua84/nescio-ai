"""Tests for the learning-loop brain guard (`_learning_common.check_brain` /
`guard_brain`) and its wiring into `promote_learnings.py`, `begin_harvest.py`
and `compute_readiness.py`.

Every fixture repo here is a throwaway `git init` under a temp dir — never this
checkout's own `.git` — except where a test is explicitly about this real
checkout's own identity (the "no leak" and "end-to-end" cases), and even those
never assert on *what* that identity is, only that it never appears verbatim in
a guard message.
"""

import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import _learning_common as lc  # noqa: E402
import begin_harvest  # noqa: E402
import compute_readiness as cr  # noqa: E402
import promote_learnings as pl  # noqa: E402


def _git_available():
    try:
        subprocess.run(
            ["git", "--version"], capture_output=True, check=True, timeout=10
        )
        return True
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False


GIT_AVAILABLE = _git_available()


def _git(args, cwd):
    subprocess.run(
        ["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True
    )


def _init_repo(path: Path) -> Path:
    """`git init` a throwaway repo at ``path`` with one commit.

    The commit is what lets ``git worktree add`` succeed below — an unborn
    branch has no tree to check out.
    """
    path.mkdir(parents=True, exist_ok=True)
    _git(["init", "-q"], cwd=path)
    _git(["config", "user.email", "brain-guard-test@example.invalid"], cwd=path)
    _git(["config", "user.name", "brain-guard-test"], cwd=path)
    _git(["commit", "--allow-empty", "-q", "-m", "init"], cwd=path)
    return path


def _can_symlink(base: Path) -> bool:
    """Probe symlink support the same way `install.py`'s own tests do."""
    probe = base / ".brain-guard-symlink-probe"
    target = base / ".brain-guard-symlink-probe-target"
    try:
        target.mkdir(exist_ok=True)
        probe.symlink_to(target, target_is_directory=True)
        return True
    except OSError:
        return False
    finally:
        for p in (probe, target):
            try:
                if p.is_symlink() or p.is_dir():
                    (p.unlink() if p.is_symlink() else p.rmdir())
            except OSError:
                pass


@unittest.skipUnless(GIT_AVAILABLE, "git is not available on this runner")
class BrainGuardTestCase(unittest.TestCase):
    """Shared CLAUDE_CONFIG_DIR save/restore, mirroring test_begin_harvest.py."""

    def setUp(self):
        self._saved_cfg = os.environ.get("CLAUDE_CONFIG_DIR")
        self._saved_override = os.environ.get(lc.BRAIN_OVERRIDE_VAR)
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.cfg = self.base / "cfg"
        self.cfg.mkdir()
        os.environ["CLAUDE_CONFIG_DIR"] = str(self.cfg)
        os.environ.pop(lc.BRAIN_OVERRIDE_VAR, None)
        # Deliberately NOT a blanket `self.skipTest(...)` here: setUp runs
        # before *every* test in this class and its subclasses, and several
        # need no symlink at all (an absent <config>/memory, a real dir
        # outside git, a mocked git failure). A class-wide skip here would
        # silently stop covering those cases on a runner without symlink
        # support (e.g. Windows without Developer Mode) -- precisely the
        # environment where the dangling-symlink `broken` verdict matters
        # most. Tests that actually need one call `self._require_symlink()`
        # themselves, or go through `self._link_memory()`, which calls it.

    def tearDown(self):
        if self._saved_cfg is None:
            os.environ.pop("CLAUDE_CONFIG_DIR", None)
        else:
            os.environ["CLAUDE_CONFIG_DIR"] = self._saved_cfg
        if self._saved_override is None:
            os.environ.pop(lc.BRAIN_OVERRIDE_VAR, None)
        else:
            os.environ[lc.BRAIN_OVERRIDE_VAR] = self._saved_override
        self._tmp.cleanup()

    def _require_symlink(self):
        if not _can_symlink(self.base):
            self.skipTest("cannot create symlinks on this runner")

    def _link_memory(self, target: Path):
        self._require_symlink()
        (self.cfg / "memory").symlink_to(target, target_is_directory=True)


# ── git_common_dir ───────────────────────────────────────────────────────────

@unittest.skipUnless(GIT_AVAILABLE, "git is not available on this runner")
class GitCommonDirTest(unittest.TestCase):
    def test_returns_a_normalised_key_for_a_real_repo(self):
        with tempfile.TemporaryDirectory() as d:
            repo = _init_repo(Path(d) / "repo")
            key = lc.git_common_dir(repo)
            self.assertIsNotNone(key)
            self.assertEqual(key, key.casefold())
            self.assertNotIn("\\", key)

    def test_none_outside_any_git_repo(self):
        with tempfile.TemporaryDirectory() as d:
            plain = Path(d) / "plain"
            plain.mkdir()
            self.assertIsNone(lc.git_common_dir(plain))

    def test_none_when_git_is_not_on_path(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(
            lc.subprocess, "run", side_effect=FileNotFoundError("no git")
        ):
            self.assertIsNone(lc.git_common_dir(Path(d)))

    def test_none_on_timeout(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(
            lc.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(cmd="git", timeout=10),
        ):
            self.assertIsNone(lc.git_common_dir(Path(d)))

    def test_identical_between_a_repo_and_its_worktree(self):
        with tempfile.TemporaryDirectory() as d:
            repo = _init_repo(Path(d) / "repo")
            wt = Path(d) / "wt"
            _git(["worktree", "add", "-q", str(wt), "-b", "feature"], cwd=repo)
            self.assertEqual(lc.git_common_dir(repo), lc.git_common_dir(wt))

    def test_inherited_git_env_does_not_force_a_false_match(self):
        # Regression guard for the env-stripping in git_common_dir itself: if
        # GIT_DIR leaked through, querying repo_b's path would still answer
        # with repo_a's identity — exactly the silent false MATCH the guard
        # must never produce.
        with tempfile.TemporaryDirectory() as d:
            repo_a = _init_repo(Path(d) / "a")
            repo_b = _init_repo(Path(d) / "b")
            saved = os.environ.get("GIT_DIR")
            os.environ["GIT_DIR"] = str(repo_a / ".git")
            try:
                key_b = lc.git_common_dir(repo_b)
            finally:
                if saved is None:
                    os.environ.pop("GIT_DIR", None)
                else:
                    os.environ["GIT_DIR"] = saved
            self.assertEqual(key_b, lc.git_common_dir(repo_b))
            self.assertNotEqual(key_b, lc.git_common_dir(repo_a))

    def test_unicode_repo_name_does_not_raise(self):
        # Fix 1 regression -- a direct reproduction, not a mock. Before the
        # fix, subprocess.run(text=True) with no encoding= decoded git's
        # UTF-8 stdout using the process locale; on a non-UTF-8 console a
        # path whose UTF-8 bytes are undefined there (U+7A81 encodes to
        # b"\xe7\xa2\x81", and byte 0x81 is undefined in cp1252) crashed the
        # subprocess reader thread, leaving result.stdout as None and
        # result.returncode as 0 -- which `git_common_dir` then dereferenced
        # with .strip(), raising AttributeError. This must now return a real
        # string (or None), never raise, regardless of the console locale,
        # because the call is pinned to encoding="utf-8", errors="replace".
        with tempfile.TemporaryDirectory() as d:
            repo = _init_repo(Path(d) / "repo-突")
            key = lc.git_common_dir(repo)
            self.assertTrue(key is None or isinstance(key, str))
            self.assertIsNotNone(key)

    def test_git_toplevel_of_a_repo_equals_itself(self):
        with tempfile.TemporaryDirectory() as d:
            repo = _init_repo(Path(d) / "repo")
            key = lc.git_toplevel(repo)
            self.assertIsNotNone(key)
            self.assertEqual(key, str(repo).replace("\\", "/").casefold())

    def test_git_toplevel_none_outside_any_git_repo(self):
        with tempfile.TemporaryDirectory() as d:
            plain = Path(d) / "plain"
            plain.mkdir()
            self.assertIsNone(lc.git_toplevel(plain))

    def test_git_toplevel_of_nested_subdir_is_the_parent_repo_root(self):
        # The property check_brain's "brain" branch relies on: a nested
        # non-git subdirectory's toplevel is its *parent* repo's root, never
        # the subdirectory itself.
        with tempfile.TemporaryDirectory() as d:
            repo = _init_repo(Path(d) / "repo")
            nested = repo / "vendor" / "framework"
            nested.mkdir(parents=True)
            self.assertEqual(lc.git_toplevel(nested), lc.git_toplevel(repo))
            self.assertNotEqual(
                lc.git_toplevel(nested), str(nested).replace("\\", "/").casefold()
            )


# ── config_dir ───────────────────────────────────────────────────────────────

class ConfigDirTest(unittest.TestCase):
    def test_honours_claude_config_dir_over_home(self):
        saved = os.environ.get("CLAUDE_CONFIG_DIR")
        os.environ["CLAUDE_CONFIG_DIR"] = "/somewhere/explicit"
        try:
            self.assertEqual(lc.config_dir(), Path("/somewhere/explicit"))
        finally:
            if saved is None:
                os.environ.pop("CLAUDE_CONFIG_DIR", None)
            else:
                os.environ["CLAUDE_CONFIG_DIR"] = saved

    def test_falls_back_to_home_claude_when_unset(self):
        saved = os.environ.pop("CLAUDE_CONFIG_DIR", None)
        try:
            self.assertEqual(lc.config_dir(), Path.home() / ".claude")
        finally:
            if saved is not None:
                os.environ["CLAUDE_CONFIG_DIR"] = saved

    def test_empty_claude_config_dir_also_falls_back(self):
        saved = os.environ.get("CLAUDE_CONFIG_DIR")
        os.environ["CLAUDE_CONFIG_DIR"] = ""
        try:
            self.assertEqual(lc.config_dir(), Path.home() / ".claude")
        finally:
            if saved is None:
                os.environ.pop("CLAUDE_CONFIG_DIR", None)
            else:
                os.environ["CLAUDE_CONFIG_DIR"] = saved


# ── check_brain / guard_brain ────────────────────────────────────────────────

class CheckBrainTest(BrainGuardTestCase):
    def test_match_when_memory_resolves_into_repo_dir(self):
        brain = _init_repo(self.base / "brain")
        self._link_memory(brain)
        verdict, lines = lc.check_brain(repo_dir=brain)
        self.assertEqual(verdict, "brain")
        self.assertEqual(lines, [])

    def test_match_when_repo_dir_is_a_worktree_of_the_brain(self):
        brain = _init_repo(self.base / "brain")
        wt = self.base / "wt"
        _git(["worktree", "add", "-q", str(wt), "-b", "feature"], cwd=brain)
        self._link_memory(brain)
        verdict, lines = lc.check_brain(repo_dir=wt)
        self.assertEqual(verdict, "brain")
        self.assertEqual(lines, [])

    def test_confirmed_mismatch_refuses(self):
        brain = _init_repo(self.base / "brain")
        other = _init_repo(self.base / "other")
        self._link_memory(brain)
        verdict, lines = lc.check_brain(repo_dir=other)
        self.assertEqual(verdict, "mismatch")
        self.assertTrue(any(ln.startswith("error:") for ln in lines))
        self.assertEqual(lc.guard_brain(repo_dir=other, stream=io.StringIO()), 2)

    def test_git_ceiling_directories_does_not_downgrade_a_confirmed_mismatch(self):
        # Fix 2 regression. <config>/memory resolves (via symlink) to a
        # subdirectory of the brain (`brain/memory`, not the brain's root),
        # so querying it needs an *upward* git discovery from that
        # subdirectory. GIT_CEILING_DIRECTORIES set to the brain's own root
        # blocks exactly that upward step (measured: with this value,
        # unstripped, `git_common_dir(mem.resolve())` returns None) -- which
        # would downgrade this confirmed mismatch to "unknown" (warn, rc 0)
        # if the var were not stripped from the subprocess environment.
        brain = _init_repo(self.base / "brain")
        (brain / "memory").mkdir()
        other = _init_repo(self.base / "other")
        self._link_memory(brain / "memory")
        saved = os.environ.get("GIT_CEILING_DIRECTORIES")
        os.environ["GIT_CEILING_DIRECTORIES"] = str(brain)
        try:
            verdict, lines = lc.check_brain(repo_dir=other)
        finally:
            if saved is None:
                os.environ.pop("GIT_CEILING_DIRECTORIES", None)
            else:
                os.environ["GIT_CEILING_DIRECTORIES"] = saved
        self.assertEqual(verdict, "mismatch")
        self.assertTrue(any(ln.startswith("error:") for ln in lines))

    def test_dangling_symlink_is_broken_and_refuses(self):
        self._require_symlink()
        other = _init_repo(self.base / "other")
        (self.cfg / "memory").symlink_to(
            self.base / "never-created", target_is_directory=True
        )
        verdict, lines = lc.check_brain(repo_dir=other)
        self.assertEqual(verdict, "broken")
        self.assertTrue(any(ln.startswith("error:") for ln in lines))
        self.assertEqual(lc.guard_brain(repo_dir=other, stream=io.StringIO()), 2)

    def test_memory_as_a_regular_file_is_broken(self):
        # Fix 4 regression. No symlink involved -- a plain file (or a
        # symlink to one, not exercised separately here) at <config>/memory
        # is "configured but broken", the same class as the dangling-symlink
        # case above, not merely "unverifiable".
        other = _init_repo(self.base / "other")
        (self.cfg / "memory").write_text("not a directory\n", encoding="utf-8")
        verdict, lines = lc.check_brain(repo_dir=other)
        self.assertEqual(verdict, "broken")
        self.assertTrue(any(ln.startswith("error:") for ln in lines))
        self.assertEqual(lc.guard_brain(repo_dir=other, stream=io.StringIO()), 2)

    def test_nested_non_git_subdirectory_does_not_verdict_brain(self):
        # Fix 3 regression. A non-git copy of the tree nested inside the
        # brain's own working copy (no .git of its own) resolves `--git-
        # common-dir` up to the brain's, so common-dir equality alone would
        # falsely verdict "brain". Requiring repo_dir to be its own git
        # toplevel catches this. The positive case -- a real `git worktree`
        # still verdicts "brain" -- is already covered by
        # test_match_when_repo_dir_is_a_worktree_of_the_brain above.
        brain = _init_repo(self.base / "brain")
        self._link_memory(brain)
        nested = brain / "vendor" / "framework"
        nested.mkdir(parents=True)
        verdict, lines = lc.check_brain(repo_dir=nested)
        self.assertEqual(verdict, "mismatch")
        self.assertTrue(any(ln.startswith("error:") for ln in lines))

    def test_no_memory_entry_warns_and_proceeds(self):
        other = _init_repo(self.base / "other")
        verdict, lines = lc.check_brain(repo_dir=other)
        self.assertEqual(verdict, "unknown")
        self.assertTrue(any(ln.startswith("warning:") for ln in lines))
        self.assertEqual(lc.guard_brain(repo_dir=other, stream=io.StringIO()), 0)

    def test_memory_as_a_real_dir_outside_git_warns(self):
        other = _init_repo(self.base / "other")
        (self.cfg / "memory").mkdir()  # a real dir, not a symlink, not a repo
        verdict, lines = lc.check_brain(repo_dir=other)
        self.assertEqual(verdict, "unknown")
        self.assertTrue(any(ln.startswith("warning:") for ln in lines))

    def test_git_failure_warns_rather_than_refusing(self):
        brain = _init_repo(self.base / "brain")
        self._link_memory(brain)
        with mock.patch.object(lc, "git_common_dir", return_value=None):
            verdict, lines = lc.check_brain(repo_dir=brain)
        self.assertEqual(verdict, "unknown")
        self.assertTrue(any(ln.startswith("warning:") for ln in lines))

    def test_bare_value_of_1_does_not_override(self):
        brain = _init_repo(self.base / "brain")
        other = _init_repo(self.base / "other")
        self.assertNotEqual(other.name, "1")
        self._link_memory(brain)
        os.environ[lc.BRAIN_OVERRIDE_VAR] = "1"
        verdict, _ = lc.check_brain(repo_dir=other)
        self.assertEqual(verdict, "mismatch")

    def test_correct_basename_override_downgrades_and_logs(self):
        brain = _init_repo(self.base / "brain")
        other = _init_repo(self.base / "other")
        self._link_memory(brain)
        # Case-insensitive per the design.
        os.environ[lc.BRAIN_OVERRIDE_VAR] = other.name.upper()
        verdict, lines = lc.check_brain(repo_dir=other)
        self.assertEqual(verdict, "override")
        self.assertTrue(any(ln.startswith("warning:") for ln in lines))
        self.assertTrue(any(lc.BRAIN_OVERRIDE_VAR in ln for ln in lines))
        self.assertEqual(lc.guard_brain(repo_dir=other, stream=io.StringIO()), 0)

    def test_override_wrong_basename_still_refuses(self):
        brain = _init_repo(self.base / "brain")
        other = _init_repo(self.base / "other")
        self._link_memory(brain)
        os.environ[lc.BRAIN_OVERRIDE_VAR] = "not-" + other.name
        verdict, _ = lc.check_brain(repo_dir=other)
        self.assertEqual(verdict, "mismatch")

    def test_override_is_not_considered_for_unknown(self):
        # Override only applies to mismatch/broken; an unresolvable brain must
        # stay "unknown" (a warning, not an "override" verdict) even if the
        # var happens to be set to this repo's name.
        other = _init_repo(self.base / "other")
        os.environ[lc.BRAIN_OVERRIDE_VAR] = other.name
        verdict, _ = lc.check_brain(repo_dir=other)
        self.assertEqual(verdict, "unknown")

    def test_guard_brain_writes_to_stderr_and_never_stdout(self):
        # The default stream is load-bearing, not cosmetic: several entry
        # points' tests assert on the exact shape of stdout (begin_harvest's
        # `read_at` being line one) while legitimately running with no
        # <config>/memory entry, so the "unknown" warning must not land there.
        # Checked for a warning verdict and a refusing one, since both print.
        #
        # The "unknown" sub-case (first setup) needs no symlink at all and
        # must run even on a runner without symlink support; only the
        # "mismatch" sub-case (second setup) is added when one is available,
        # via a direct check rather than `self._link_memory` -- that method
        # calls `self._require_symlink()`, which would skip this whole test
        # (losing the first sub-case) rather than just omitting the second.
        other = _init_repo(self.base / "other")
        setups = [lambda: None]
        if _can_symlink(self.base):
            setups.append(lambda: (self.cfg / "memory").symlink_to(
                _init_repo(self.base / "brain"), target_is_directory=True))
        for setup in setups:
            setup()
            out, err = io.StringIO(), io.StringIO()
            with mock.patch.object(sys, "stdout", out), \
                    mock.patch.object(sys, "stderr", err):
                rc = lc.guard_brain(repo_dir=other)
            self.assertEqual(out.getvalue(), "")
            self.assertTrue(err.getvalue().strip(), "nothing was printed at all")
            self.assertIn(rc, (0, 2))

    def test_no_message_contains_an_absolute_path_or_a_repo_name(self):
        # Named to avoid colliding with words the messages legitimately use
        # ("brain", "memory") — this test is about *identifying* strings, like
        # a repo's own basename, never appearing, not about avoiding English.
        brain = _init_repo(self.base / "zz-root-one")
        other = _init_repo(self.base / "zz-root-two")
        self._link_memory(brain)

        forbidden = [brain.name, other.name, str(self.base), str(self.cfg)]

        _, mismatch_lines = lc.check_brain(repo_dir=other)
        (self.cfg / "memory").unlink()
        (self.cfg / "memory").symlink_to(
            self.base / "never-created", target_is_directory=True
        )
        _, broken_lines = lc.check_brain(repo_dir=other)
        (self.cfg / "memory").unlink()
        _, unknown_lines = lc.check_brain(repo_dir=other)
        self._link_memory(brain)
        os.environ[lc.BRAIN_OVERRIDE_VAR] = other.name
        _, override_lines = lc.check_brain(repo_dir=other)

        groups = {
            "mismatch": mismatch_lines,
            "broken": broken_lines,
            "unknown": unknown_lines,
            "override": override_lines,
        }
        # Non-vacuity. This is the only mechanical defence of the PUBLIC-repo
        # constraint, and every assertion below is a *negative* one: an empty
        # `lines` satisfies all of them while checking nothing. So pin that each
        # verdict still speaks, and that the scan really ran a line at a time --
        # otherwise a future refactor that stopped emitting messages would turn
        # this test green by saying less, not by leaking less.
        for verdict, lines in groups.items():
            self.assertTrue(lines, f"{verdict} emitted no lines to scan")
        scanned = 0
        for lines in groups.values():
            for line in lines:
                scanned += 1
                for token in forbidden:
                    self.assertNotIn(token, line)
                # No drive-letter absolute path (Windows) and no POSIX
                # absolute path either; "~/.claude/memory" is deliberately
                # the one exception and starts with "~", not "/".
                self.assertNotRegex(line, r"[A-Za-z]:[\\/]")
                self.assertFalse(line.startswith("/"))
        self.assertGreaterEqual(scanned, len(groups))


# ── wiring: the three entry points ──────────────────────────────────────────

@unittest.skipUnless(GIT_AVAILABLE, "git is not available on this runner")
class EntryPointGuardTest(BrainGuardTestCase):
    """End-to-end: CLAUDE_CONFIG_DIR/memory resolves into a throwaway repo that
    is never this real checkout, so REPO_DIR (the actual worktree these tests
    run from) is a confirmed mismatch — exactly the scenario the real incident
    hit. Each entry point must refuse before doing any of its own work.
    """

    def setUp(self):
        super().setUp()
        elsewhere = _init_repo(self.base / "elsewhere")
        self._link_memory(elsewhere)

    def _no_leak(self, text):
        self.assertNotIn(str(lc.REPO_DIR), text)
        self.assertNotIn(lc.REPO_DIR.name, text)

    def _staging_entries(self):
        """Names directly under the default staging root, if it exists at all.

        `begin_harvest`'s default `--out` is `REPO_DIR/eval/learnings/<stamp>/`,
        so a guard that refused too *late* would leave a `read.json` inside this
        very checkout -- the side effect the refusal is supposed to precede.
        Compared before/after rather than asserted absent, because `eval/` is
        gitignored and may legitimately hold real runs on a developer machine.
        """
        root = lc.REPO_DIR / "eval" / "learnings"
        return {p.name for p in root.iterdir()} if root.is_dir() else set()

    def test_promote_learnings_refuses_before_touching_the_manifest(self):
        argv = ["promote_learnings.py", str(self.base / "nonexistent-manifest.json")]
        err = io.StringIO()
        with mock.patch.object(sys, "argv", argv), \
                mock.patch.object(sys, "stderr", err):
            rc = pl.main()
        self.assertEqual(rc, 2)
        self.assertIn("refusing to write", err.getvalue())
        self.assertNotIn("no such manifest", err.getvalue())
        self._no_leak(err.getvalue())

    def test_begin_harvest_refuses_before_writing_read_json(self):
        before = self._staging_entries()
        err = io.StringIO()
        with mock.patch.object(sys, "stderr", err):
            rc = begin_harvest.main([])
        self.assertEqual(rc, 2)
        self.assertIn("refusing to write", err.getvalue())
        self._no_leak(err.getvalue())
        # The refusal landed *before* the write, not merely instead of a
        # success report: no new staging dir (and so no read.json) appeared.
        self.assertEqual(self._staging_entries(), before)

    def test_begin_harvest_help_exits_0_and_prints_help(self):
        # Fix 6 regression. This fixture is a confirmed mismatch (see the
        # class docstring) -- the hardest case -- so this also proves --help
        # bypasses the guard entirely rather than merely running fast enough
        # to race it. argparse's --help prints and calls sys.exit(0), which
        # raises SystemExit; it never returns from main().
        out = io.StringIO()
        with mock.patch.object(sys, "stdout", out), \
                self.assertRaises(SystemExit) as cm:
            begin_harvest.main(["--help"])
        self.assertEqual(cm.exception.code, 0)
        self.assertIn("usage:", out.getvalue())

    def test_compute_readiness_refuses_when_memory_root_is_default(self):
        err = io.StringIO()
        out = io.StringIO()
        with mock.patch.object(sys, "stderr", err), \
                mock.patch.object(sys, "stdout", out):
            rc = cr.main([])
        self.assertEqual(rc, 2)
        self.assertIn("refusing to write", err.getvalue())
        self._no_leak(err.getvalue())
        # main() ends by printing the plan's report; an empty stdout is the
        # observable proof that plan() -- which reads the trail and the
        # destination memory/ tree -- was never reached.
        self.assertEqual(out.getvalue(), "")

    def test_compute_readiness_explicit_memory_root_skips_the_guard(self):
        with mock.patch.object(cr, "guard_brain") as spy:
            with tempfile.TemporaryDirectory() as d:
                trail = Path(d) / "trail"
                trail.mkdir()
                memory = Path(d) / "memory"
                memory.mkdir()
                rc = cr.main([
                    "--trail-dir", str(trail),
                    "--memory-root", str(memory),
                ])
        self.assertEqual(rc, 0)
        spy.assert_not_called()

    def test_compute_readiness_default_memory_root_calls_the_guard(self):
        with mock.patch.object(cr, "guard_brain", return_value=0) as spy:
            with tempfile.TemporaryDirectory() as d:
                trail = Path(d) / "trail"
                trail.mkdir()
                rc = cr.main(["--trail-dir", str(trail)])
        self.assertEqual(rc, 0)
        spy.assert_called_once_with(cr.REPO_DIR)

    def test_compute_readiness_default_spelling_variants_all_fire_the_guard(self):
        # Fix 5 regression, inverted on correction (one-flag bypass). The
        # audit first measured that the *original* raw string compare
        # (`args.memory_root == str(DEFAULT_MEMORY_ROOT)`) let a trailing
        # separator, forward slashes, or a dot-segment -- all spellings of
        # the exact same default tree -- slip past unequal and silently skip
        # the guard. The `default=None` sentinel fix that followed went too
        # far the other way: it made *any* explicit --memory-root value skip
        # the guard, uniformly, which reopened the same hole from a different
        # angle -- `--memory-root memory`, run from a non-brain checkout,
        # resolves relative to cwd to that checkout's own memory/ tree (the
        # exact wrong-destination incident this guard exists to prevent) and
        # the guard stayed silent because *a* flag was supplied, even though
        # it did not name a different destination at all.
        #
        # DELIBERATE BEHAVIOUR CHANGE, not a weakened test: this is the
        # replacement assertion, and it inverts the old one on purpose. Every
        # spelling of the default tree below -- however written -- now
        # resolves (via Path.resolve() + os.path.normcase()) to the same
        # path as DEFAULT_MEMORY_ROOT and so must *fire* the guard, exactly
        # as if no --memory-root had been given at all. Only a genuinely
        # different, explicitly named tree (covered by
        # test_compute_readiness_explicit_memory_root_skips_the_guard above)
        # may still skip it.
        default = str(cr.DEFAULT_MEMORY_ROOT)
        variants = {
            "exact default string": default,
            "trailing separator": default + os.sep,
            "forward slashes": default.replace("\\", "/"),
            "dot segment": os.path.join(
                os.path.dirname(default), ".", os.path.basename(default)
            ),
            "absolute default path written out": str(
                cr.DEFAULT_MEMORY_ROOT.resolve()
            ),
        }
        for label, variant in variants.items():
            with mock.patch.object(cr, "guard_brain", return_value=0) as spy:
                with tempfile.TemporaryDirectory() as d:
                    trail = Path(d) / "trail"
                    trail.mkdir()
                    rc = cr.main([
                        "--trail-dir", str(trail),
                        "--memory-root", variant,
                    ])
            self.assertEqual(rc, 0, label)
            spy.assert_called_once_with(cr.REPO_DIR)

    def test_compute_readiness_genuinely_different_root_skips_the_guard(self):
        # Companion to the fire-the-guard test above: a resolved root that is
        # *not* the default -- including one spelled with a dot-segment or a
        # trailing separator of its own -- still skips the guard, same as
        # test_compute_readiness_explicit_memory_root_skips_the_guard, just
        # exercised through the odder spellings rather than a plain path.
        with mock.patch.object(cr, "guard_brain") as spy:
            with tempfile.TemporaryDirectory() as d:
                trail = Path(d) / "trail"
                trail.mkdir()
                memory = Path(d) / "elsewhere" / "memory"
                memory.mkdir(parents=True)
                variant = str(memory) + os.sep
                rc = cr.main([
                    "--trail-dir", str(trail),
                    "--memory-root", variant,
                ])
        self.assertEqual(rc, 0)
        spy.assert_not_called()


if __name__ == "__main__":
    unittest.main()
