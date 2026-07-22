import io, sys, tempfile, unittest
from contextlib import redirect_stdout
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import install_github_action as gha  # noqa: E402

class InstallFilesTest(unittest.TestCase):
    def _run(self, auth, expect_input, expect_secret):
        with tempfile.TemporaryDirectory() as d:
            target = Path(d); (target / ".git").mkdir()
            written = gha.install_files(target, auth=auth, ci_workflow_name="CI")
            core = target / ".github/workflows/claude-review-core.yml"
            wrapper = target / ".github/workflows/claude-code-review.yml"
            learn = target / ".claude/memory/review-learnings"
            self.assertTrue(core.is_file()); self.assertTrue(wrapper.is_file())
            self.assertTrue((learn / ".gitkeep").is_file())
            self.assertTrue((learn / "README.md").is_file())
            body = core.read_text()
            self.assertIn(expect_input, body)
            self.assertIn(expect_secret, body)
            # the other auth's tokens must be absent
            other = "anthropic_api_key" if auth == "oauth" else "claude_code_oauth_token"
            self.assertNotIn(other, body)
            self.assertFalse((target / ".git" / "objects").exists())

    def test_oauth(self):
        self._run("oauth", "claude_code_oauth_token", "CLAUDE_CODE_OAUTH_TOKEN")

    def test_apikey(self):
        self._run("apikey", "anthropic_api_key", "ANTHROPIC_API_KEY")

class MainNonGitTargetTest(unittest.TestCase):
    def test_main_returns_1_on_non_git_target(self):
        with tempfile.TemporaryDirectory() as d:
            target = Path(d)  # no .git here
            old_argv = sys.argv
            sys.argv = ["install_github_action.py", str(target), "--auth", "oauth", "--skip-secret"]
            try:
                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = gha.main()
            finally:
                sys.argv = old_argv
            self.assertEqual(rc, 1)
            self.assertIn("not a git working tree", buf.getvalue())

class ClobberGuardTest(unittest.TestCase):
    def test_force_false_preserves_hand_edit_force_true_overwrites(self):
        with tempfile.TemporaryDirectory() as d:
            target = Path(d); (target / ".git").mkdir()
            gha.install_files(target, auth="oauth", ci_workflow_name="CI")
            core = target / ".github/workflows/claude-review-core.yml"
            hand_edit = "# hand-edited by a human, do not clobber\n"
            core.write_text(hand_edit, encoding="utf-8")

            written = gha.install_files(target, auth="oauth", ci_workflow_name="CI", force=False)
            self.assertNotIn(core, written)
            self.assertEqual(core.read_text(encoding="utf-8"), hand_edit)

            written = gha.install_files(target, auth="oauth", ci_workflow_name="CI", force=True)
            self.assertIn(core, written)
            self.assertNotEqual(core.read_text(encoding="utf-8"), hand_edit)

    def test_identical_content_is_not_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            target = Path(d); (target / ".git").mkdir()
            gha.install_files(target, auth="oauth", ci_workflow_name="CI")
            core = target / ".github/workflows/claude-review-core.yml"
            # re-running with identical content should count as written, not skipped
            written = gha.install_files(target, auth="oauth", ci_workflow_name="CI", force=False)
            self.assertIn(core, written)

class SetSecretTest(unittest.TestCase):
    def _capture_argv(self, auth, repo="owner/name"):
        calls = []
        def fake_call(argv):
            calls.append(argv)
            return 0
        old_call = gha.subprocess.call
        gha.subprocess.call = fake_call
        try:
            rc = gha.set_secret(repo, auth)
        finally:
            gha.subprocess.call = old_call
        self.assertEqual(rc, 0)
        self.assertEqual(len(calls), 1)
        return calls[0]

    def test_oauth_secret_name(self):
        argv = self._capture_argv("oauth")
        self.assertEqual(argv, ["gh", "secret", "set", "CLAUDE_CODE_OAUTH_TOKEN", "--repo", "owner/name"])

    def test_apikey_secret_name(self):
        argv = self._capture_argv("apikey")
        self.assertEqual(argv, ["gh", "secret", "set", "ANTHROPIC_API_KEY", "--repo", "owner/name"])

if __name__ == "__main__":
    unittest.main()
