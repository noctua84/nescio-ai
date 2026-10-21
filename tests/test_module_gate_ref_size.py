"""Regression tests for issue #194: the gate must measure size from `--head`,
not the working tree.

Kept out of `tests/test_module_gate.py` on purpose. That file sits at 389
lines against the 400-line tripwire and `tests/**` is not excluded from
`module_gate.py`'s own CI run -- growing it here would very likely cross the
tripwire and force a `Module-check:` acknowledgement onto a PR about
something else entirely.

Same house pattern as `test_module_gate.py`: real throwaway git repositories,
real `git`, `user.email` / `user.name` / `commit.gpgsign` set locally per repo
so this passes on a clean CI machine and on a developer box with global commit
signing enabled. Every call into `module_gate` goes through
`contextlib.redirect_stdout(io.StringIO())` so the gate's banner never reaches
the suite log.
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
import module_scan  # noqa: E402


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


def _write_text(repo: Path, rel: str, lines: int) -> None:
    """Overwrite `rel` with exactly `lines` physical lines and stage it."""
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x\n" * lines, encoding="utf-8")
    _git(repo, "add", "--", rel)


def _commit(repo: Path, message: str) -> str:
    _git(repo, "commit", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _run_gate(repo: Path, **kwargs) -> tuple[int, str]:
    """Run module_gate.main against `repo`, with stdout/stderr captured so
    the gate's own banner never reaches the real test-suite log."""
    args = ["--repo", str(repo)]
    for flag, value in kwargs.items():
        if flag == "exclude":
            for glob in value:
                args += ["--exclude", glob]
            continue
        if value is None:
            continue
        args += [f"--{flag.replace('_', '-')}", str(value)]
    out_buf, err_buf = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out_buf), contextlib.redirect_stderr(err_buf):
        rc = module_gate.main(args)
    return rc, out_buf.getvalue()


class ModuleGateRefSizeTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = _init_repo(Path(self._tmp.name))
        _write_text(self.repo, "README.md", 5)
        self.base_sha = _commit(self.repo, "chore: initial commit")


class TestWorkingTreeDisagreesWithHead(ModuleGateRefSizeTestCase):
    def test_gate_fails_for_an_over_tripwire_head_even_when_checkout_is_under(self):
        """The regression from #194: `--head` names a ref that is over the
        tripwire, but the *checked-out* working tree (left on a different
        branch) is under it. The gate must measure the ref, not the
        filesystem, or it fails open -- reporting PASS when the true answer
        for `head` is FAIL.
        """
        # feature: add big.py over the tripwire, on its own branch.
        _git(self.repo, "checkout", "-b", "feature")
        _write_text(self.repo, "big.py", 450)
        head_sha = _commit(self.repo, "feat: grow big.py")

        # Leave the working tree on `main`, where big.py does not exist at
        # all (so if the gate were still reading `repo / path`, it would see
        # "file does not exist" and skip it -- the same fail-open outcome as
        # the issue's own repro, where the working tree had an under-tripwire
        # version instead of a missing one. Either way, head disagrees with
        # the checkout.)
        _git(self.repo, "checkout", "main")
        self.assertFalse((self.repo / "big.py").exists())

        rc, out = _run_gate(self.repo, base=self.base_sha, head=head_sha)

        self.assertEqual(rc, 1, f"expected FAIL, got rc={rc}, output:\n{out}")
        self.assertIn("big.py", out)
        self.assertIn("450 lines", out)

    def test_gate_fails_when_checkout_has_an_under_tripwire_version_of_the_same_path(self):
        """Closer to the issue's own repro than the "file missing" case above:
        the working tree has a *different, under-tripwire* copy of the exact
        path that is over the tripwire at `head`."""
        _write_text(self.repo, "shared.py", 100)
        mid_sha = _commit(self.repo, "feat: add shared.py under the tripwire")

        _git(self.repo, "checkout", "-b", "feature")
        _write_text(self.repo, "shared.py", 450)
        head_sha = _commit(self.repo, "feat: grow shared.py past the tripwire")

        # Leave the checkout at mid_sha's content (under the tripwire) while
        # --head points past it.
        _git(self.repo, "checkout", "main")
        _git(self.repo, "reset", "--hard", mid_sha)
        self.assertEqual(
            (self.repo / "shared.py").read_text(encoding="utf-8").count("\n"), 100
        )

        rc, out = _run_gate(self.repo, base=self.base_sha, head=head_sha)

        self.assertEqual(rc, 1, f"expected FAIL, got rc={rc}, output:\n{out}")
        self.assertIn("shared.py", out)
        self.assertIn("450 lines", out)


class TestReadBlobAtRef(ModuleGateRefSizeTestCase):
    def test_a_binary_file_at_head_is_skipped_not_counted(self):
        blob_path = self.repo / "image.bin"
        blob_path.write_bytes(b"\x00\x01" * 5000)
        _git(self.repo, "add", "--", "image.bin")
        head_sha = _commit(self.repo, "feat: add a binary blob")

        data = module_gate.read_blob_at_ref(self.repo, head_sha, "image.bin")

        self.assertIsNotNone(data)
        self.assertIsNone(module_scan.count_lines_from_bytes(data))

    def test_a_path_deleted_at_head_returns_none_rather_than_raising(self):
        _write_text(self.repo, "gone.py", 10)
        mid_sha = _commit(self.repo, "feat: add gone.py")
        _git(self.repo, "rm", "gone.py")
        head_sha = _commit(self.repo, "chore: remove gone.py")

        data = module_gate.read_blob_at_ref(self.repo, head_sha, "gone.py")

        self.assertIsNone(data)
        # And the equivalent still exists at the prior ref.
        self.assertIsNotNone(module_gate.read_blob_at_ref(self.repo, mid_sha, "gone.py"))

    def test_find_hits_skips_a_path_deleted_at_head_without_crashing(self):
        """A path that `git diff --numstat` reports (because it changed
        somewhere in the range) may not exist at `head` at all if a later
        commit in the same range deleted it. `find_hits` must skip it, the
        same as the old `.exists()` guard did for the working tree."""
        _write_text(self.repo, "transient.py", 450)
        _commit(self.repo, "feat: add transient.py over the tripwire")
        _git(self.repo, "rm", "transient.py")
        head_sha = _commit(self.repo, "chore: remove transient.py")

        rc, out = _run_gate(self.repo, base=self.base_sha, head=head_sha)

        self.assertEqual(rc, 0, f"expected PASS (nothing to flag), got:\n{out}")
        self.assertNotIn("transient.py", out)

    def test_a_file_with_no_trailing_newline_at_head_counts_the_last_line(self):
        path = self.repo / "noeol.py"
        path.write_text("x\n" * 449 + "last", encoding="utf-8")
        _git(self.repo, "add", "--", "noeol.py")
        head_sha = _commit(self.repo, "feat: add noeol.py without a trailing newline")

        data = module_gate.read_blob_at_ref(self.repo, head_sha, "noeol.py")

        self.assertEqual(module_scan.count_lines_from_bytes(data), 450)


if __name__ == "__main__":
    unittest.main()
