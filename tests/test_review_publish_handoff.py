"""Behaviour tests for the publish step's handoff hardening.

The staged files reach the publish job through an artifact, so their content is
untrusted: `publish-comments.sh` rejects credential-shaped text itself, rejects
anything that is not a regular file, and reports `review_published=true` through
GITHUB_OUTPUT only after `review.md` was posted (the merge gate fails closed
without it).

Credential-shaped fixtures are built at runtime so that no token-shaped literal
sits in a tracked file. Skipped unless `bash` and `jq` are on PATH.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _review_step_harness import (  # noqa: E402
    StepHarness, comment as _comment, posix as _posix, step_script as _step_script)

PR = "7"
REPO = "o/r"
HEAD_SHA = "0123456789abcdef0123456789abcdef01234567"

ISSUE_COMMENTS = f"repos/{REPO}/issues/{PR}/comments"
REVIEW_COMMENTS = f"repos/{REPO}/pulls/{PR}/comments"
PR_FILES = f"repos/{REPO}/pulls/{PR}/files"

SUMMARY_MARKER = "<!-- claude-pr-summary -->"
REVIEW_MARKER = "<!-- claude-comprehensive-review -->"
VERDICT = "<!-- claude-verdict: APPROVE -->"

# One fixture per credential family the filter recognises.
FAMILIES = {
    "ghp_": "gh" + "p_" + "A" * 36,
    "gho_": "gh" + "o_" + "A" * 36,
    "ghu_": "gh" + "u_" + "A" * 36,
    "ghs_": "gh" + "s_" + "A" * 36,
    "ghr_": "gh" + "r_" + "A" * 36,
    "github_pat_": "github" + "_pat_" + "A1_" * 12,
    "sk-ant-": "sk-" + "ant-" + "api03-" + "A" * 24,
}
SAMPLE = FAMILIES["ghs_"]

REVIEW = f"{REVIEW_MARKER}\n{VERDICT}\n## Comprehensive Review\n"


def _finding(path, line, marker, extra=""):
    return (f"---\npath: {path}\nline: {line}\nside: RIGHT\n---\n"
            f"<!-- claude-finding: {marker} -->\n"
            f"**[MAJOR] Bug — {marker}**\nexplanation{extra}\n")


class _HandoffHarness(StepHarness):
    SCRIPT = "publish-comments"

    def setUp(self):
        super().setUp()
        self.outbox = self.root / "outbox"
        self.outbox.mkdir()
        self.gh_output = self.root / "github-output.txt"

    def stage(self, rel, text):
        path = self.outbox / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
        return path

    def run_publish(self, github_output=True):
        env = {
            "REVIEW_OUTBOX": _posix(self.outbox),
            "PR_NUMBER": PR,
            "REPO": REPO,
            "HEAD_SHA": HEAD_SHA,
        }
        if github_output:
            env["GITHUB_OUTPUT"] = _posix(self.gh_output)
        return self.run_step(env)

    def output_lines(self):
        if not self.gh_output.exists():
            return []
        return self.gh_output.read_text(encoding="utf-8").splitlines()

    def assertSampleNotLogged(self):
        for value in FAMILIES.values():
            self.assertNotIn(value, self.output)


class CredentialFilterTest(_HandoffHarness):
    def test_summary_with_credential_is_not_published(self):
        self.stage("summary.md", f"{SUMMARY_MARKER}\nleaked {SAMPLE} here\n")
        proc = self.run_publish()
        self.assertExit(proc, 0)
        self.assertEqual(self.write_keys(), [])
        self.assertSampleNotLogged()
        self.assertIn("credential-shaped", self.output)

    def test_review_with_credential_fails_and_is_not_published(self):
        self.stage("review.md", f"{REVIEW_MARKER}\n{VERDICT}\n## Review\n{SAMPLE}\n")
        proc = self.run_publish()
        self.assertNotEqual(proc.returncode, 0, self.output)
        self.assertEqual(self.write_keys(), [])
        self.assertSampleNotLogged()
        self.assertEqual(self.output_lines(), [])

    def test_credential_in_frontmatter_is_rejected(self):
        self.respond(PR_FILES, [{"filename": "src/a.py"}])
        self.stage("findings/fm.md", _finding("src/a.py", 4, "bug:fm").replace(
            "side: RIGHT\n", f"side: RIGHT\nnote: {SAMPLE}\n"))
        proc = self.run_publish()
        self.assertExit(proc, 0)
        self.assertEqual(self.write_keys(), [])
        self.assertSampleNotLogged()

    def test_secret_finding_skipped_clean_finding_posted(self):
        self.respond(PR_FILES, [{"filename": "src/a.py"}, {"filename": "docs/b.md"}])
        self.stage("findings/a-bad.md", _finding("src/a.py", 3, "bug:bad", f" {SAMPLE}"))
        self.stage("findings/b-good.md", _finding("docs/b.md", 5, "bug:good"))
        proc = self.run_publish()
        self.assertExit(proc, 0)
        posted = [c for c in self.writes() if c["endpoint"] == REVIEW_COMMENTS]
        self.assertEqual(len(posted), 1, self.output)
        self.assertEqual(posted[0]["fields"].get("path"), "docs/b.md")
        self.assertSampleNotLogged()

    def test_secret_reply_skipped_clean_reply_posted(self):
        self.respond(REVIEW_COMMENTS, [
            _comment(301, "github-actions[bot]", "<!-- claude-finding: bug:a -->\nf"),
        ])
        self.stage("replies/a-bad.md", f"---\nin_reply_to: 301\n---\nThanks {SAMPLE}\n")
        self.stage("replies/b-good.md", "---\nin_reply_to: 301\n---\nAddressed.\n")
        proc = self.run_publish()
        self.assertExit(proc, 0)
        self.assertEqual(self.write_keys(), [("POST", f"{REVIEW_COMMENTS}/301/replies")])
        self.assertEqual(self.writes()[0]["body"], "Addressed.\n")
        self.assertSampleNotLogged()

    def test_every_family_is_rejected(self):
        for family, value in FAMILIES.items():
            with self.subTest(family=family):
                self.clear_calls()
                self.stage("summary.md", f"{SUMMARY_MARKER}\ntext {value} text\n")
                proc = self.run_publish()
                self.assertExit(proc, 0)
                self.assertEqual(self.write_keys(), [], self.output)
                self.assertNotIn(value, self.output)

    def test_near_misses_are_accepted(self):
        near = {
            "short ghp_": "gh" + "p_" + "A" * 10,
            "bare sk-ant": "the sk-ant prefix",
            "bare github_pat_": "the github_pat_ prefix",
            "short sk-ant-": "sk-" + "ant-" + "A" * 5,
        }
        for name, text in near.items():
            with self.subTest(case=name):
                self.clear_calls()
                self.stage("summary.md", f"{SUMMARY_MARKER}\n{text}\n")
                proc = self.run_publish()
                self.assertExit(proc, 0)
                self.assertEqual(self.write_keys(), [("POST", ISSUE_COMMENTS)], self.output)


class NotRegularFileTest(_HandoffHarness):
    def test_directory_named_like_a_finding_is_rejected(self):
        self.respond(PR_FILES, [{"filename": "src/a.py"}])
        (self.outbox / "findings" / "x.md").mkdir(parents=True)
        proc = self.run_publish()
        self.assertExit(proc, 0)
        self.assertEqual(self.write_keys(), [])
        self.assertIn("not a regular file", self.output)


class ReviewPublishedOutputTest(_HandoffHarness):
    def test_published_review_writes_exactly_one_line(self):
        self.stage("review.md", REVIEW)
        proc = self.run_publish()
        self.assertExit(proc, 0)
        self.assertEqual(self.write_keys(), [("POST", ISSUE_COMMENTS)])
        self.assertEqual(self.output_lines(), ["review_published=true"])

    def test_no_review_staged_writes_nothing(self):
        self.stage("summary.md", f"{SUMMARY_MARKER}\nsummary\n")
        proc = self.run_publish()
        self.assertExit(proc, 0)
        self.assertEqual(self.output_lines(), [])

    def test_unpublishable_review_writes_nothing(self):
        self.stage("review.md", f"{REVIEW_MARKER}\nnot a verdict line\n")
        proc = self.run_publish()
        self.assertNotEqual(proc.returncode, 0, self.output)
        self.assertEqual(self.output_lines(), [])

    def test_refused_post_writes_nothing(self):
        self.refuse("POST", ISSUE_COMMENTS)
        self.stage("review.md", REVIEW)
        proc = self.run_publish()
        self.assertNotEqual(proc.returncode, 0, self.output)
        self.assertEqual(self.output_lines(), [])

    def test_unset_github_output_does_not_fail(self):
        self.stage("review.md", REVIEW)
        proc = self.run_publish(github_output=False)
        self.assertExit(proc, 0)
        self.assertEqual(self.write_keys(), [("POST", ISSUE_COMMENTS)])
        self.assertFalse(self.gh_output.exists())


class ScriptShapeTest(unittest.TestCase):
    def test_script_has_no_expression_interpolation(self):
        self.assertNotIn("${{", _step_script("publish-comments"))


if __name__ == "__main__":
    unittest.main()
