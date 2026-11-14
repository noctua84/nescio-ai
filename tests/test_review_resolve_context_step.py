"""Behaviour tests for the review core's "Resolve PR context" step.

`github-action/scripts/claude-review/resolve-pr-context.sh` is run directly with
bash against the fake `gh` from _review_step_harness.py. The contract under
test: a non-numeric PR number fails before any API call, and every value lands
in $GITHUB_OUTPUT as exactly one `key=value` line, so a line break inside a
free-text value (title, author, head ref) cannot add or alter an output.

Skipped unless `bash` and `jq` are on PATH.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _review_step_harness import StepHarness, posix  # noqa: E402

PR = "7"
REPO = "o/r"
ENDPOINT = f"repos/{REPO}/pulls/{PR}"

KEYS = ["number", "title", "user", "base_ref", "base_sha", "head_ref", "head_sha", "today"]


def pull(title="A title", user="octocat", head_ref="feature"):
    return {"title": title, "user": {"login": user},
            "base": {"ref": "main", "sha": "b" * 40},
            "head": {"ref": head_ref, "sha": "a" * 40}}


class ResolveContextStepTest(StepHarness):
    SCRIPT = "resolve-pr-context"

    def run_resolve(self, pr=PR):
        self.out_file = self.root / "github-output"
        self.out_file.write_bytes(b"")
        return self.run_step({"PR_NUMBER": pr, "GITHUB_REPOSITORY": REPO,
                              "GITHUB_OUTPUT": posix(self.out_file)})

    def output_lines(self):
        return self.out_file.read_bytes().decode("utf-8").split("\n")[:-1]

    def test_plain_values_become_one_line_each(self):
        self.respond(ENDPOINT, pull())
        self.assertExit(self.run_resolve(), 0)
        lines = self.output_lines()
        self.assertEqual([ln.split("=", 1)[0] for ln in lines], KEYS)
        self.assertIn("title=A title", lines)
        self.assertIn("user=octocat", lines)
        self.assertIn("head_ref=feature", lines)

    def test_line_breaks_in_free_text_do_not_add_output_lines(self):
        self.respond(ENDPOINT, pull(title="first\r\nsecond\nthird=x\rfourth",
                                    user="a\nb", head_ref="c\r\nd"))
        self.assertExit(self.run_resolve(), 0)
        lines = self.output_lines()
        self.assertEqual([ln.split("=", 1)[0] for ln in lines], KEYS, lines)
        self.assertEqual(len([ln for ln in lines if ln.startswith("title=")]), 1)
        self.assertEqual(lines[1], "title=first  second third=x fourth")
        self.assertEqual(lines[2], "user=a b")
        self.assertEqual(lines[5], "head_ref=c  d")

    def test_non_numeric_pr_number_fails_before_any_api_call(self):
        self.respond(ENDPOINT, pull())
        self.assertExit(self.run_resolve(pr="7; echo"), 1)
        self.assertEqual(self.calls(), [])
        self.assertEqual(self.out_file.read_bytes(), b"")


if __name__ == "__main__":
    unittest.main()
