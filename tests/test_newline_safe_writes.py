"""Byte-level regression for issue 84: repo-tracked and other-people's-repo writes stay LF.

`Path.write_text(s)` expands "\\n" to `os.linesep`, so on Windows it emits CRLF
into files that `.gitattributes` pins to LF -- or into a user's own repository,
whose line-ending policy this project does not control. The fix is
`newline=""` on the write.

These tests compare BYTES and seed from CRLF fixtures. A test that seeds and
snapshots through the same newline-blind text APIs on both ends cannot see this
defect class (that is how the apply_theme bug survived), so every assertion
here reads `read_bytes()`. Off Windows the unguarded API already emits LF, so
the suite only has teeth on Windows -- the platform that matters.
"""

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import install  # noqa: E402
import install_github_action as gha  # noqa: E402
import mark_adopted  # noqa: E402
import promote_learnings as pl  # noqa: E402

TARGET = "feedback/sample-learning.md"
LEDGER_CRLF = b"# Learning log\r\n\r\nSeed intro.\r\n\r\n## Entries\r\n"


def _seed_crlf_ledger(repo: Path) -> Path:
    memory = repo / "memory"
    memory.mkdir(parents=True, exist_ok=True)
    ledger = memory / "learning-log.md"
    ledger.write_bytes(LEDGER_CRLF)
    return ledger


def _nom(**over) -> dict:
    base = {
        "scope": "feedback",
        "target": TARGET,
        "name": "feedback-sample-learning",
        "description": "A one-line description.",
        "type": "feedback",
        "source": "empirical",
        "date": "2026-07-12",
    }
    base.update(over)
    return base


class PromoteLearningsLfBytesTest(unittest.TestCase):
    def _assert_lf_only(self, path: Path):
        raw = path.read_bytes()
        self.assertIn(b"\n", raw)
        self.assertNotIn(b"\r", raw, f"{path.name} contains CR: {raw!r}")

    def test_body_path_note_and_ledger_are_lf(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            ledger = _seed_crlf_ledger(repo)
            rc, summary = pl.promote([_nom(body="Line one.\n\nLine two.")], repo_dir=repo)
            self.assertEqual(rc, 0, summary)
            self._assert_lf_only(repo / "memory" / TARGET)
            self._assert_lf_only(ledger)

    def test_units_path_note_and_ledger_are_lf(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            ledger = _seed_crlf_ledger(repo)
            units = [{"text": "A unit.\n\nWith two paragraphs.",
                      "source": "empirical", "date": "2026-07-12"}]
            rc, summary = pl.promote([_nom(units=units)], repo_dir=repo)
            self.assertEqual(rc, 0, summary)
            self._assert_lf_only(repo / "memory" / TARGET)
            self._assert_lf_only(ledger)


class MarkAdoptedLfBytesTest(unittest.TestCase):
    def test_adoption_ledger_is_lf_after_update(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            adopt, adopted = root / "adopt", root / "adopted"
            run = adopt / "20260101-000000"
            run.mkdir(parents=True)
            (run / "sources.json").write_text(
                json.dumps([{"source": "~/x", "sha8": "abcdef012345"}]), encoding="utf-8")
            ledger = root / "adoption-log.md"
            ledger.write_bytes(
                b"# Adoption log\r\n\r\n- 2026-01-01 | ~/x | abcdef012345 | pending\r\n")
            argv = ["mark_adopted.py", "20260101-000000", "--status", "integrated"]
            with mock.patch.object(mark_adopted, "ADOPT", adopt), \
                 mock.patch.object(mark_adopted, "ADOPTED", adopted), \
                 mock.patch.object(mark_adopted, "LEDGER", ledger), \
                 mock.patch.object(sys, "argv", argv), \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(mark_adopted.main(), 0)
            raw = ledger.read_bytes()
            self.assertIn(b"integrated", raw)
            self.assertNotIn(b"\r", raw)


class InstallGithubActionLfBytesTest(unittest.TestCase):
    def test_workflow_files_written_into_user_repo_are_lf(self):
        with tempfile.TemporaryDirectory() as d:
            target = Path(d)
            (target / ".git").mkdir()
            written = gha.install_files(target, auth="oauth", ci_workflow_name="CI")
            self.assertTrue(written)
            for path in written:
                self.assertNotIn(b"\r", path.read_bytes(), f"{path} contains CR")

    def test_force_overwrite_of_crlf_file_lands_lf(self):
        with tempfile.TemporaryDirectory() as d:
            target = Path(d)
            (target / ".git").mkdir()
            gha.install_files(target, auth="oauth", ci_workflow_name="CI")
            core = target / ".github/workflows/claude-review-core.yml"
            core.write_bytes(b"name: x\r\non: y\r\n")
            with contextlib.redirect_stdout(io.StringIO()):
                gha.install_files(target, auth="oauth", ci_workflow_name="CI", force=True)
            self.assertNotIn(b"\r", core.read_bytes())


class InstallPyLfBytesTest(unittest.TestCase):
    def setUp(self):
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))

    def test_merged_settings_json_in_users_config_dir_is_lf(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, claude = Path(tmp) / "repo", Path(tmp) / "claude"
            repo.mkdir()
            claude.mkdir()
            (repo / "settings.json").write_text(
                json.dumps({"agent": "orchestrator"}), encoding="utf-8")
            (claude / "settings.json").write_bytes(b'{\r\n  "mykey": 1\r\n}\r\n')
            with mock.patch.object(install, "REPO_DIR", repo), \
                 mock.patch.object(install, "CLAUDE_DIR", claude):
                install.install_settings(frozenset({"agent"}), dry_run=False)
            raw = (claude / "settings.json").read_bytes()
            self.assertIn(b"orchestrator", raw)
            self.assertNotIn(b"\r", raw)

    def test_global_claude_md_import_over_crlf_file_is_lf(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo, claude = Path(tmp) / "repo", Path(tmp) / "claude"
            repo.mkdir()
            claude.mkdir()
            (claude / "CLAUDE.md").write_bytes(b"# my rules\r\n\r\nBe terse.\r\n")
            with mock.patch.object(install, "REPO_DIR", repo), \
                 mock.patch.object(install, "CLAUDE_DIR", claude):
                install.install_claude_md("import", dry_run=False)
            raw = (claude / "CLAUDE.md").read_bytes()
            self.assertIn(b"Be terse.", raw)
            self.assertNotIn(b"\r", raw)


if __name__ == "__main__":
    unittest.main()
