"""Behaviour tests for the review core's "Snapshot review state" step.

`github-action/scripts/claude-review/snapshot-state.sh` is run directly with
bash against the fake `gh` from _review_step_harness.py. The contract under
test: a non-numeric PR number fails before any API call; the four state files
land in /tmp/review-state/ (the path is fixed in the script, so the tests copy
the directory out and remove it again); the step only READS (no write calls)
and fails hard when a read fails.

Skipped unless `bash` and `jq` are on PATH.
"""
import json
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _review_step_harness import BASH, StepHarness, comment, posix  # noqa: E402

PR = "7"
REPO = "o/r"

ISSUE_COMMENTS = f"repos/{REPO}/issues/{PR}/comments"
REVIEW_COMMENTS = f"repos/{REPO}/pulls/{PR}/comments"
OPEN_PRS = f"repos/{REPO}/pulls?state=open&per_page=100"
GRAPHQL = "graphql"

STATE_FILES = {"issue-comments.jsonl", "review-comments.jsonl",
               "review-threads.json", "open-learning-prs.txt"}

THREADS = {"data": {"repository": {"pullRequest": {"reviewThreads": {"nodes": [
    {"id": "T1", "isResolved": True, "comments": {"nodes": []}}]}}}}}


def _bash(code, *args):
    return subprocess.run([BASH, "-c", code, "_", *args], capture_output=True, timeout=60)


class SnapshotStepTest(StepHarness):
    SCRIPT = "snapshot-state"

    def setUp(self):
        super().setUp()
        # The script rm -rf's and recreates a fixed /tmp path: never run over a
        # directory some other process owns.
        if _bash('test -e /tmp/review-state').returncode == 0:
            self.skipTest("/tmp/review-state already exists; refusing to clobber it")
        self.addCleanup(_bash, "rm -rf /tmp/review-state")
        self.respond(ISSUE_COMMENTS, [])
        self.respond(REVIEW_COMMENTS, [])
        self.respond(GRAPHQL, THREADS)
        self.respond(OPEN_PRS, [])

    def run_snapshot(self, pr=PR, repo=REPO):
        return self.run_step({"PR_NUMBER": pr, "REPO": repo})

    def collect(self):
        """Copy /tmp/review-state out of the bash filesystem; {name: text}."""
        dest = self.root / "collected"
        proc = _bash('mkdir -p "$1" && cp -r /tmp/review-state/. "$1"', posix(dest))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return {p.name: p.read_text(encoding="utf-8") for p in dest.iterdir()}

    def test_non_numeric_pr_number_fails_before_any_api_call(self):
        for bad in ("", "abc", "7x", "-1", "1 2", "7;id"):
            with self.subTest(pr=bad):
                self.clear_calls()
                proc = self.run_snapshot(pr=bad)
                self.assertExit(proc, 1)
                self.assertEqual(self.calls(), [])

    def test_writes_the_four_state_files(self):
        self.respond(ISSUE_COMMENTS, [comment(1, "octocat", "hello"),
                                      comment(2, "github-actions[bot]", "summary")])
        self.respond(REVIEW_COMMENTS, [
            {"id": 3, "user": {"login": "octocat"}, "body": "nit", "path": "a.py",
             "line": 4, "in_reply_to_id": None, "extra": "dropped"}])
        self.respond(OPEN_PRS, [
            {"number": 11, "head": {"ref": "claude/review-learning/7-foo"}},
            {"number": 12, "head": {"ref": "feature/x"}}])
        proc = self.run_snapshot()
        self.assertExit(proc, 0)
        files = self.collect()
        self.assertEqual(set(files), STATE_FILES)

        issue = [json.loads(line) for line in files["issue-comments.jsonl"].splitlines()]
        self.assertEqual([c["id"] for c in issue], [1, 2])
        self.assertEqual(issue[0], {"id": 1, "user": "octocat", "body": "hello"})
        review = [json.loads(line) for line in files["review-comments.jsonl"].splitlines()]
        self.assertEqual(review, [{"id": 3, "user": "octocat", "body": "nit",
                                   "path": "a.py", "line": 4, "in_reply_to_id": None}])
        self.assertEqual(json.loads(files["review-threads.json"]), THREADS)
        self.assertEqual(files["open-learning-prs.txt"].split(), ["11"])

    def test_empty_pr_lists_still_write_all_four_files(self):
        self.assertExit(self.run_snapshot(), 0)
        files = self.collect()
        self.assertEqual(set(files), STATE_FILES)
        self.assertEqual(files["issue-comments.jsonl"], "")
        self.assertEqual(files["open-learning-prs.txt"], "")

    def test_paginated_reads_keep_every_page(self):
        self.respond(ISSUE_COMMENTS, [comment(i, "octocat", f"c{i}") for i in (1, 2, 3)], pages=2)
        self.assertExit(self.run_snapshot(), 0)
        lines = self.collect()["issue-comments.jsonl"].splitlines()
        self.assertEqual([json.loads(x)["id"] for x in lines], [1, 2, 3])

    def test_a_stale_snapshot_is_replaced_not_merged(self):
        _bash("mkdir -p /tmp/review-state && echo old > /tmp/review-state/stale.txt")
        self.assertExit(self.run_snapshot(), 0)
        self.assertEqual(set(self.collect()), STATE_FILES)

    def test_only_reads_and_the_graphql_variables_are_typed(self):
        self.assertExit(self.run_snapshot(), 0)
        self.assertEqual(self.writes(), [])
        gql = [c for c in self.calls() if c["endpoint"] == GRAPHQL]
        self.assertEqual(len(gql), 1)
        self.assertEqual({k: gql[0]["fields"][k] for k in ("owner", "name", "number")},
                         {"owner": "o", "name": "r", "number": PR})

    def test_a_failed_read_fails_the_step(self):
        for endpoint in (ISSUE_COMMENTS, REVIEW_COMMENTS, GRAPHQL, OPEN_PRS):
            with self.subTest(endpoint=endpoint):
                self.refuse("GET", endpoint)
                proc = self.run_snapshot()
                self.assertNotEqual(proc.returncode, 0, self.output)
                (self.fake / "fail.txt").unlink()
                _bash("rm -rf /tmp/review-state")


if __name__ == "__main__":
    unittest.main()
