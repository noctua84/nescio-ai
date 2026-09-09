"""Tests for scripts/module_scan.py.

These build real throwaway git repositories and run real `git ls-files`, because
the scanner's whole contract is "what git tracks, minus what is not source" --
mocking git would test the mock. `user.email` / `user.name` / `commit.gpgsign`
are set inside each temp repo so this passes on a clean CI machine and on a
developer box with global commit signing enabled.
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import module_scan  # noqa: E402


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
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


def _write(repo: Path, rel: str, lines: int) -> Path:
    """Write `rel` with exactly `lines` physical lines, then track it."""
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x\n" * lines, encoding="utf-8")
    _git(repo, "add", "--", rel)
    return path


class ModuleScanTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = _init_repo(Path(self._tmp.name))

    def paths_over(self, **kw) -> list[str]:
        result = module_scan.scan(
            self.repo, kw.get("tripwire", 400), kw.get("excludes", ())
        )
        return [entry["path"] for entry in result["over"]]


class TestTripwireBoundary(ModuleScanTestCase):
    def test_only_files_strictly_over_the_tripwire_are_reported(self):
        """400 is not over 400. Off-by-one here would flag every file at the limit."""
        _write(self.repo, "under.py", 399)
        _write(self.repo, "exactly.py", 400)
        _write(self.repo, "over.py", 401)
        self.assertEqual(self.paths_over(), ["over.py"])

    def test_tripwire_override_is_honoured(self):
        _write(self.repo, "small.py", 60)
        _write(self.repo, "medium.py", 120)
        self.assertEqual(self.paths_over(tripwire=100), ["medium.py"])

    def test_over_list_is_sorted_by_size_descending(self):
        _write(self.repo, "big.py", 900)
        _write(self.repo, "bigger.py", 1200)
        _write(self.repo, "biggest.py", 1500)
        self.assertEqual(
            self.paths_over(), ["biggest.py", "bigger.py", "big.py"]
        )


class TestExclusions(ModuleScanTestCase):
    def test_generated_vendored_and_lockfiles_are_omitted(self):
        _write(self.repo, "real.py", 500)
        _write(self.repo, "api_pb2.py", 500)
        _write(self.repo, "bundle.min.js", 500)
        _write(self.repo, "node_modules/dep/index.js", 500)
        _write(self.repo, "migrations/0001_initial.py", 500)
        _write(self.repo, "uv.lock", 500)
        self.assertEqual(self.paths_over(), ["real.py"])

    def test_binary_files_are_skipped_not_counted(self):
        blob = self.repo / "image.bin"
        blob.write_bytes(b"\x00\x01" * 5000)
        _git(self.repo, "add", "--", "image.bin")
        self.assertEqual(self.paths_over(), [])

    def test_untracked_and_ignored_files_are_omitted(self):
        _write(self.repo, "tracked.py", 500)
        (self.repo / "untracked.py").write_text("x\n" * 500, encoding="utf-8")
        (self.repo / ".gitignore").write_text("ignored.py\n", encoding="utf-8")
        _git(self.repo, "add", "--", ".gitignore")
        (self.repo / "ignored.py").write_text("x\n" * 500, encoding="utf-8")
        self.assertEqual(self.paths_over(), ["tracked.py"])

    def test_extra_exclude_globs_are_applied(self):
        _write(self.repo, "keep.py", 500)
        _write(self.repo, "CHANGELOG.md", 500)
        self.assertEqual(
            self.paths_over(excludes=("CHANGELOG.md",)), ["keep.py"]
        )


class TestLineCounting(ModuleScanTestCase):
    def test_a_non_utf8_file_is_counted_not_crashed_on(self):
        """Latin-1 bytes are not valid UTF-8. Counting is done on bytes for this."""
        path = self.repo / "latin.py"
        path.write_bytes(("caf\xe9\n" * 500).encode("latin-1"))
        _git(self.repo, "add", "--", "latin.py")
        self.assertEqual(self.paths_over(), ["latin.py"])

    def test_a_final_line_without_a_newline_still_counts(self):
        path = self.repo / "noeol.py"
        path.write_text("x\n" * 400 + "last", encoding="utf-8")
        _git(self.repo, "add", "--", "noeol.py")
        self.assertEqual(module_scan.count_lines(path), 401)

    def test_an_empty_file_counts_zero(self):
        path = self.repo / "empty.py"
        path.write_text("", encoding="utf-8")
        self.assertEqual(module_scan.count_lines(path), 0)


class TestReportAndExit(ModuleScanTestCase):
    def test_an_empty_repo_reports_cleanly_and_exits_zero(self):
        self.assertEqual(module_scan.main(["--repo", str(self.repo)]), 0)

    def test_exit_is_zero_even_when_files_are_over(self):
        """It is a report, not a gate. A non-zero exit would make it a CI blocker."""
        _write(self.repo, "huge.py", 5000)
        self.assertEqual(module_scan.main(["--repo", str(self.repo)]), 0)

    def test_json_output_shape_is_stable(self):
        _write(self.repo, "huge.py", 1200)
        result = module_scan.scan(self.repo, 400, ())
        payload = json.loads(json.dumps(result))
        self.assertEqual(payload["tripwire"], 400)
        self.assertEqual(payload["scanned"], 1)
        self.assertEqual(payload["over"], [{"path": "huge.py", "lines": 1200}])

    def test_scanned_counts_every_eligible_file_not_just_the_over_ones(self):
        _write(self.repo, "small.py", 10)
        _write(self.repo, "huge.py", 1200)
        result = module_scan.scan(self.repo, 400, ())
        self.assertEqual(result["scanned"], 2)
        self.assertEqual(len(result["over"]), 1)


if __name__ == "__main__":
    unittest.main()
