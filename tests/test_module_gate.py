"""Tests for scripts/module_gate.py.

Same house pattern as `test_module_scan.py`: real throwaway git repositories,
real `git`, `user.email` / `user.name` / `commit.gpgsign` set locally per repo
so this passes on a clean CI machine and on a developer box with global commit
signing enabled.

The gate prints a failure banner and a success confirmation -- by design, see
`module_gate.format_failure` / `format_success`. Every call into `module_gate`
below goes through `contextlib.redirect_stdout(io.StringIO())` so none of that
output reaches the *test suite's* stdout. A gate test that prints its banner
into the suite log would undo the point of the gate having a banner at all.
"""

import contextlib
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import module_gate  # noqa: E402


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, encoding="utf-8"
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"`git {' '.join(args)}` failed in {repo} (exit {proc.returncode}):\n"
            f"{proc.stderr.strip() or proc.stdout.strip()}"
        )
    return proc.stdout.strip()


def _init_repo(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "commit.gpgsign", "false")
    return repo


def _write(repo: Path, rel: str, lines: int) -> None:
    """Overwrite `rel` with exactly `lines` physical lines and stage it."""
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x\n" * lines, encoding="utf-8")
    _git(repo, "add", "--", rel)


def _commit(repo: Path, message: str) -> str:
    _git(repo, "commit", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _run_gate(repo: Path, **kwargs) -> tuple[int, str]:
    """Run module_gate.main against `repo`, with stdout captured (never
    allowed to reach the real test-suite stdout) and returned for assertions."""
    args = ["--repo", str(repo)]
    for flag, value in kwargs.items():
        if flag == "exclude":
            for glob in value:
                args += ["--exclude", glob]
            continue
        if value is None:
            continue
        args += [f"--{flag.replace('_', '-')}", str(value)]
    # module_gate prints its error banner (GateError path) to stderr, not
    # stdout -- redirect both, or an exit-2 scenario leaks git's own usage
    # text into the real suite log instead of the harmless `buf` below.
    out_buf, err_buf = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out_buf), contextlib.redirect_stderr(err_buf):
        rc = module_gate.main(args)
    return rc, out_buf.getvalue()


class ModuleGateTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = _init_repo(Path(self._tmp.name))
        # A trivial base commit every scenario can diverge from.
        _write(self.repo, "README.md", 5)
        self.base_sha = _commit(self.repo, "chore: initial commit")


class TestUnacknowledgedHit(ModuleGateTestCase):
    def test_growing_an_over_tripwire_file_with_no_ack_fails(self):
        _write(self.repo, "big.py", 450)
        head_sha = _commit(self.repo, "feat: grow big.py")

        rc, out = _run_gate(self.repo, base=self.base_sha, head=head_sha)

        self.assertEqual(rc, 1)
        self.assertIn("big.py", out)
        self.assertIn("450 lines", out)
        self.assertIn("Splitting is NOT required", out)

    def test_ack_in_commit_message_clears_the_hit(self):
        _write(self.repo, "big.py", 450)
        head_sha = _commit(
            self.repo,
            "feat: grow big.py\n\nModule-check: big.py — cohesive, one reason to change",
        )

        rc, out = _run_gate(self.repo, base=self.base_sha, head=head_sha)

        self.assertEqual(rc, 0)
        self.assertIn("big.py", out)

    def test_ack_in_ack_file_clears_the_hit(self):
        _write(self.repo, "big.py", 450)
        head_sha = _commit(self.repo, "feat: grow big.py")
        ack_file = Path(self._tmp.name) / "pr-body.txt"
        ack_file.write_text(
            "Module-check: big.py — cohesive, one reason to change\n",
            encoding="utf-8",
        )

        rc, out = _run_gate(
            self.repo, base=self.base_sha, head=head_sha, ack_file=ack_file
        )

        self.assertEqual(rc, 0)

    def test_ack_for_a_different_path_does_not_satisfy_the_hit(self):
        _write(self.repo, "big.py", 450)
        head_sha = _commit(
            self.repo,
            "feat: grow big.py\n\nModule-check: other.py — cohesive, one reason",
        )

        rc, out = _run_gate(self.repo, base=self.base_sha, head=head_sha)

        self.assertEqual(rc, 1)
        self.assertIn("big.py", out)

    def test_ack_with_empty_free_text_does_not_satisfy_the_hit(self):
        _write(self.repo, "big.py", 450)
        head_sha = _commit(
            self.repo,
            "feat: grow big.py\n\nModule-check: big.py —    \n",
        )

        rc, _out = _run_gate(self.repo, base=self.base_sha, head=head_sha)

        self.assertEqual(rc, 1)


class TestNotAHit(ModuleGateTestCase):
    def test_shrinking_an_over_tripwire_file_is_not_a_hit(self):
        _write(self.repo, "big.py", 450)
        _commit(self.repo, "feat: add big.py")
        mid_sha = _git(self.repo, "rev-parse", "HEAD")

        _write(self.repo, "big.py", 420)  # still over tripwire, but shrank
        head_sha = _commit(self.repo, "refactor: trim big.py")

        rc, out = _run_gate(self.repo, base=mid_sha, head=head_sha)

        self.assertEqual(rc, 0)
        self.assertNotIn("FAIL", out)

    def test_a_new_file_created_over_the_tripwire_is_a_hit(self):
        _write(self.repo, "brand_new.py", 500)
        head_sha = _commit(self.repo, "feat: add brand_new.py")

        rc, out = _run_gate(self.repo, base=self.base_sha, head=head_sha)

        self.assertEqual(rc, 1)
        self.assertIn("brand_new.py", out)

    def test_a_changed_file_under_the_tripwire_is_not_a_hit(self):
        _write(self.repo, "small.py", 50)
        _commit(self.repo, "feat: add small.py")
        mid_sha = _git(self.repo, "rev-parse", "HEAD")

        _write(self.repo, "small.py", 80)
        head_sha = _commit(self.repo, "feat: grow small.py a bit")

        rc, out = _run_gate(self.repo, base=mid_sha, head=head_sha)

        self.assertEqual(rc, 0)
        self.assertNotIn("FAIL", out)

    def test_an_excluded_path_over_the_tripwire_and_grown_is_not_a_hit(self):
        _write(self.repo, "excluded.py", 450)
        head_sha = _commit(self.repo, "feat: grow excluded.py")

        rc, out = _run_gate(
            self.repo,
            base=self.base_sha,
            head=head_sha,
            exclude=["excluded.py"],
        )

        self.assertEqual(rc, 0)
        self.assertNotIn("FAIL", out)


class TestTripwireOverride(ModuleGateTestCase):
    def test_cli_tripwire_override_is_honoured(self):
        _write(self.repo, "medium.py", 120)
        head_sha = _commit(self.repo, "feat: add medium.py")

        rc_default, _ = _run_gate(self.repo, base=self.base_sha, head=head_sha)
        rc_override, _ = _run_gate(
            self.repo, base=self.base_sha, head=head_sha, tripwire=100
        )

        self.assertEqual(rc_default, 0)  # under the 400 default
        self.assertEqual(rc_override, 1)  # over the 100 override

    def test_tripwire_parsed_from_claude_md_architecture_section(self):
        claude_md = (
            "# Project\n\n"
            "## Architecture\n\n"
            "Module tripwire: 500 lines.\n\n"
            "## Git / PRs\n\nbranch for changes\n"
        )
        (self.repo / "CLAUDE.md").write_text(claude_md, encoding="utf-8")
        _git(self.repo, "add", "--", "CLAUDE.md")
        _commit(self.repo, "docs: declare tripwire")
        base_sha = _git(self.repo, "rev-parse", "HEAD")

        _write(self.repo, "file.py", 450)  # over 400, under the declared 500
        head_sha = _commit(self.repo, "feat: add file.py")

        rc, _out = _run_gate(self.repo, base=base_sha, head=head_sha)

        self.assertEqual(rc, 0)

    def test_literal_placeholder_tripwire_falls_back_to_400_without_raising(self):
        """This repo's real CLAUDE.md contains `Module tripwire: <N> lines.` as
        documentation of the syntax, not a real override. Parsing it must not
        raise and must fall back to the 400 default."""
        claude_md = (
            "# Project\n\n"
            "## Architecture\n\n"
            "- **Tripwire** -- a line such as `Module tripwire: <N> lines.` "
            "overrides the 400-line default.\n\n"
            "## Git / PRs\n\nbranch for changes\n"
        )
        (self.repo / "CLAUDE.md").write_text(claude_md, encoding="utf-8")
        _git(self.repo, "add", "--", "CLAUDE.md")
        _commit(self.repo, "docs: placeholder only")
        base_sha = _git(self.repo, "rev-parse", "HEAD")

        _write(self.repo, "file.py", 450)
        head_sha = _commit(self.repo, "feat: add file.py")

        rc, _out = _run_gate(self.repo, base=base_sha, head=head_sha)

        self.assertEqual(rc, 1)  # 450 > fallback 400 -- parsed fine, didn't raise

    def test_resolve_tripwire_directly_on_this_repos_own_claude_md(self):
        """Belt and suspenders: parse the real, tracked CLAUDE.md in this repo
        and confirm it resolves to the 400 default rather than raising or
        picking up a nonsense value from `<N>`."""
        self.assertEqual(module_gate.resolve_tripwire(ROOT / "CLAUDE.md"), 400)


class TestAckSeparatorsAndCase(ModuleGateTestCase):
    def _assert_ack_clears(self, ack_line: str) -> None:
        _write(self.repo, "big.py", 450)
        head_sha = _commit(self.repo, f"feat: grow big.py\n\n{ack_line}")
        rc, _out = _run_gate(self.repo, base=self.base_sha, head=head_sha)
        self.assertEqual(rc, 0, f"expected ack line to clear the hit: {ack_line!r}")

    def test_em_dash_separator(self):
        self._assert_ack_clears("Module-check: big.py — cohesive, one reason")

    def test_hyphen_separator(self):
        self._assert_ack_clears("Module-check: big.py - cohesive, one reason")

    def test_colon_separator(self):
        self._assert_ack_clears("Module-check: big.py: cohesive, one reason")

    def test_lowercase_directive_is_accepted(self):
        self._assert_ack_clears("module-check: big.py — cohesive, one reason")

    def test_mixed_case_directive_is_accepted(self):
        self._assert_ack_clears("MoDuLe-ChEcK: big.py — cohesive, one reason")


class TestGateErrors(ModuleGateTestCase):
    def test_bad_base_ref_exits_2_not_0(self):
        rc, _out = _run_gate(
            self.repo, base="refs/heads/does-not-exist", head=self.base_sha
        )

        self.assertEqual(rc, 2)

    def test_not_a_git_repo_exits_2(self):
        not_a_repo = Path(self._tmp.name) / "not-a-repo"
        not_a_repo.mkdir()

        rc, _out = _run_gate(not_a_repo, base="main", head="HEAD")

        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
