"""Contract tests for the reusable PR-review core template.

`github-action/claude-review-core.yml` is copied into target repos. Claude
must stay read-only with respect to git AND GitHub: it holds no write tool.
A "Snapshot review state" step fetches the prior review state into
/tmp/review-state/ before Claude runs; Claude stages its comments under
/tmp/review-outbox/ and its learning notes under /tmp/review-learnings/;
deterministic shell steps after it publish the comments and open the note
PRs. These tests parse the YAML and check that contract.
"""
import re
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CORE = ROOT / "github-action" / "claude-review-core.yml"
SNIPPET = ROOT / "github-action" / "claude-review-automatic.snippet.yml"

CLAUDE_ACTION = "anthropics/claude-code-action"
LEARNING_STEP = "Open review-learning PRs"
RESOLVE_STEP = "Resolve PR context"
CHECKOUT_STEP = "Checkout PR head"
SNAPSHOT_STEP = "Snapshot review state"
PUBLISH_STEP = "Publish review comments"
GATE_STEP = "Submit formal review based on Claude's verdict"

# The full, exact allow-list Claude is meant to hold: read-only GitHub CLI
# calls, read-only git, `cat`, and the file tools it stages comments with.
EXPECTED_ALLOWED_TOOLS = {
    "Bash(gh pr view:*)",
    "Bash(gh pr diff:*)",
    "Bash(git diff:*)",
    "Bash(git log:*)",
    "Bash(cat:*)",
    "Write",
    "Read",
    "Grep",
    "Glob",
}

STATE_FILES = (
    "issue-comments.jsonl",
    "review-comments.jsonl",
    "review-threads.json",
    "open-learning-prs.txt",
)


def _load(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


class _CoreBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = _load(CORE)
        cls.jobs = cls.doc["jobs"]
        cls.steps = cls.jobs["review"]["steps"]

    def _claude_index(self):
        idx = [i for i, s in enumerate(self.steps)
               if str(s.get("uses", "")).startswith(CLAUDE_ACTION + "@")]
        self.assertEqual(len(idx), 1, "expected exactly one claude-code-action step")
        return idx[0]

    def _claude_step(self):
        return self.steps[self._claude_index()]

    def _learning_index(self):
        idx = [i for i, s in enumerate(self.steps) if s.get("name") == LEARNING_STEP]
        self.assertEqual(len(idx), 1, f"expected exactly one {LEARNING_STEP!r} step")
        return idx[0]

    def _learning_step(self):
        return self.steps[self._learning_index()]

    def _named_index(self, name):
        idx = [i for i, s in enumerate(self.steps) if s.get("name") == name]
        self.assertEqual(len(idx), 1, f"expected exactly one {name!r} step")
        return idx[0]

    def _named_step(self, name):
        return self.steps[self._named_index(name)]


class CoreParsesTest(_CoreBase):
    def test_is_reusable_workflow(self):
        # PyYAML parses the bare `on:` key as boolean True.
        self.assertIn("workflow_call", self.doc[True])
        self.assertIn("review", self.jobs)
        self.assertIn("merge-gate", self.jobs)


class AllowedToolsTest(_CoreBase):
    def _allowed_tools(self):
        args = self._claude_step()["with"]["claude_args"]
        m = re.search(r'--allowed-tools\s+"([^"]*)"', args)
        self.assertIsNotNone(m, "claude_args has no --allowed-tools \"...\" value")
        return m.group(1)

    def test_no_git_write_tools(self):
        tools = self._allowed_tools()
        for forbidden in ("git push", "git commit", "git add",
                          "git checkout", "git fetch", "gh pr create"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, tools)

    def _entries(self):
        return [t.strip() for t in self._allowed_tools().split(",")]

    def test_still_has_write_and_read(self):
        entries = self._entries()
        self.assertIn("Write", entries)
        self.assertIn("Read", entries)

    def test_exact_allow_list(self):
        entries = self._entries()
        self.assertEqual(set(entries), EXPECTED_ALLOWED_TOOLS)
        self.assertEqual(len(entries), len(set(entries)), "duplicate allow-list entries")

    def test_no_gh_api(self):
        # A prefix rule cannot constrain the method or a GraphQL mutation,
        # so no form of `gh api` may appear.
        for entry in self._entries():
            with self.subTest(entry=entry):
                self.assertNotIn("gh api", entry)
                self.assertNotRegex(entry, r"\bapi\b")

    def test_no_gh_pr_comment_or_review(self):
        for entry in self._entries():
            with self.subTest(entry=entry):
                self.assertNotIn("gh pr comment", entry)
                self.assertNotIn("gh pr review", entry)
                self.assertNotIn("gh pr edit", entry)

    def test_no_unrestricted_bash(self):
        for entry in self._entries():
            with self.subTest(entry=entry):
                self.assertNotIn(entry, ("Bash", "Bash(*)", "Bash(:*)", "Bash()"))
                if entry.startswith("Bash"):
                    # Every Bash rule names a concrete command prefix.
                    self.assertRegex(entry, r"^Bash\([a-z][a-z ]*[a-z]:\*\)$")

    def test_no_network_tools(self):
        for entry in self._entries():
            with self.subTest(entry=entry):
                for tool in ("curl", "wget", "WebFetch", "nc ", "python", "node"):
                    self.assertNotIn(tool, entry)


class LearningStepTest(_CoreBase):
    def test_runs_after_claude_step(self):
        self.assertGreater(self._learning_index(), self._claude_index())

    def test_survives_failure_and_never_fails_job(self):
        step = self._learning_step()
        self.assertIs(step.get("continue-on-error"), True)
        self.assertIn("!cancelled()", str(step.get("if", "")))

    def test_branch_pattern_and_stage_dir(self):
        run = self._learning_step()["run"]
        self.assertIn("claude/review-learning/$PR_NUMBER-$SLUG", run)
        self.assertIn("/tmp/review-learnings", run)

    def test_no_expression_interpolation_in_run(self):
        step = self._learning_step()
        self.assertNotIn("${{", step["run"])
        # The inputs the script uses arrive through env: instead.
        for var in ("PR_NUMBER", "BASE_REF", "REPO", "GH_TOKEN"):
            with self.subTest(var=var):
                self.assertIn(var, step.get("env", {}))

    def test_kind_allow_list(self):
        run = self._learning_step()["run"]
        self.assertIn("regression|security|architecture)", run)


class SlugRegexTest(_CoreBase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        step = next(s for s in cls.steps if s.get("name") == LEARNING_STEP)
        m = re.search(r"^\s*SLUG_RE='([^']*)'\s*$", step["run"], re.M)
        assert m, "SLUG_RE assignment not found in the learning step"
        cls.slug_re = re.compile(m.group(1))

    def test_pattern_value(self):
        self.assertEqual(self.slug_re.pattern, r"^[a-z0-9]([a-z0-9-]{0,48}[a-z0-9])?$")

    def test_accepts(self):
        for slug in ("config-key-renamed", "a", "a" * 50, "a" + "-" * 48 + "b"):
            with self.subTest(slug=slug):
                self.assertIsNotNone(self.slug_re.search(slug))

    def test_rejects(self):
        for slug in ("Bad_Slug", "-lead", "trail-", "a" * 51, "../x", "a/b", ""):
            with self.subTest(slug=slug):
                self.assertIsNone(self.slug_re.search(slug))


class PromptTest(_CoreBase):
    def _prompt(self):
        return self._claude_step()["with"]["prompt"]

    def test_step_4b_before_step_5(self):
        prompt = self._prompt()
        i4b = prompt.find("## Step 4b")
        i5 = prompt.find("## Step 5")
        self.assertNotEqual(i4b, -1, "prompt has no Step 4b heading")
        self.assertNotEqual(i5, -1, "prompt has no Step 5 heading")
        self.assertLess(i4b, i5)

    def test_mentions_stage_dir(self):
        self.assertIn("/tmp/review-learnings/", self._prompt())

    def test_no_step_7(self):
        self.assertNotIn("Step 7", self._prompt())

    def test_no_github_write_instructions(self):
        prompt = self._prompt()
        self.assertNotIn("gh api", prompt)
        self.assertNotIn("gh pr comment", prompt)

    def test_names_snapshot_dir_and_files(self):
        prompt = self._prompt()
        self.assertIn("/tmp/review-state/", prompt)
        for name in STATE_FILES:
            with self.subTest(file=name):
                self.assertIn(f"/tmp/review-state/{name}", prompt)

    def test_names_outbox_layout(self):
        prompt = self._prompt()
        for path in ("/tmp/review-outbox/",
                     "/tmp/review-outbox/summary.md",
                     "/tmp/review-outbox/review.md",
                     "/tmp/review-outbox/findings/",
                     "/tmp/review-outbox/replies/"):
            with self.subTest(path=path):
                self.assertIn(path, prompt)


class StepOrderTest(_CoreBase):
    def test_review_pipeline_order(self):
        order = [
            self._named_index(RESOLVE_STEP),
            self._named_index(CHECKOUT_STEP),
            self._named_index(SNAPSHOT_STEP),
            self._claude_index(),
            self._named_index(PUBLISH_STEP),
            self._learning_index(),
        ]
        self.assertEqual(order, sorted(order), f"step indices out of order: {order}")
        self.assertEqual(len(set(order)), len(order))


class SnapshotStepTest(_CoreBase):
    def _step(self):
        return self._named_step(SNAPSHOT_STEP)

    def test_has_id_state(self):
        self.assertEqual(self._step().get("id"), "state")

    def test_no_expression_interpolation_in_run(self):
        self.assertNotIn("${{", self._step()["run"])

    def test_env_inputs(self):
        env = self._step().get("env", {})
        for var in ("GH_TOKEN", "PR_NUMBER", "REPO"):
            with self.subTest(var=var):
                self.assertIn(var, env)

    def test_writes_all_state_files(self):
        run = self._step()["run"]
        self.assertIn("/tmp/review-state", run)
        for name in STATE_FILES:
            with self.subTest(file=name):
                self.assertIn(f"$STATE/{name}", run)

    def test_fails_hard(self):
        step = self._step()
        self.assertFalse(step.get("continue-on-error", False))
        self.assertIn("set -euo pipefail", step["run"])

    def test_reads_only(self):
        run = self._step()["run"]
        self.assertNotRegex(run, r"(?:-X|--method)\s*(?:PATCH|POST|PUT|DELETE)")
        self.assertNotIn("mutation", run)
        self.assertNotIn("--input", run)


class PublishStepTest(_CoreBase):
    def _step(self):
        return self._named_step(PUBLISH_STEP)

    def test_runs_unless_cancelled(self):
        self.assertIn("!cancelled()", str(self._step().get("if", "")))

    def test_not_continue_on_error(self):
        # A staged review that cannot be published must fail the job so the
        # fail-closed merge-gate does not act on a stale review.
        self.assertFalse(self._step().get("continue-on-error", False))

    def test_no_expression_interpolation_in_run(self):
        self.assertNotIn("${{", self._step()["run"])

    def test_env_inputs(self):
        env = self._step().get("env", {})
        for var in ("GH_TOKEN", "PR_NUMBER", "REPO", "HEAD_SHA"):
            with self.subTest(var=var):
                self.assertIn(var, env)

    def test_does_not_trust_claude_writable_snapshot(self):
        # /tmp/review-state is writable by Claude; the publisher must do its
        # own fresh reads. Comment lines may mention the path.
        code = "\n".join(line for line in self._step()["run"].splitlines()
                         if not line.lstrip().startswith("#"))
        self.assertNotIn("/tmp/review-state", code)


class PermissionsTest(_CoreBase):
    def test_review_job_keeps_write_scopes(self):
        perms = self.jobs["review"]["permissions"]
        for scope in ("contents", "pull-requests", "issues", "id-token"):
            with self.subTest(scope=scope):
                self.assertEqual(perms.get(scope), "write")

    def test_merge_gate_permissions(self):
        perms = self.jobs["merge-gate"]["permissions"]
        self.assertEqual(perms.get("contents"), "read")
        self.assertEqual(perms.get("pull-requests"), "write")


class MergeGateTest(_CoreBase):
    def test_needs_review_and_not_cancelled(self):
        gate = self.jobs["merge-gate"]
        needs = gate["needs"]
        needs = [needs] if isinstance(needs, str) else needs
        self.assertIn("review", needs)
        self.assertIn("!cancelled()", str(gate.get("if", "")))

    def _gate_step(self):
        steps = [s for s in self.jobs["merge-gate"]["steps"] if s.get("name") == GATE_STEP]
        self.assertEqual(len(steps), 1, f"expected exactly one {GATE_STEP!r} step")
        return steps[0]

    def _assignment(self, run, var):
        """The single-quoted value of the one `VAR='...'` line in `run`."""
        values = re.findall(rf"^\s*{var}='([^']*)'\s*$", run, re.M)
        self.assertEqual(len(values), 1, f"expected exactly one {var}='...' assignment")
        return values[0]

    def test_trusted_jq_matches_publish_step(self):
        # The gate may only trust the logins the publish step posts as.
        gate = self._assignment(self._gate_step()["run"], "TRUSTED_JQ")
        publish = self._assignment(self._named_step(PUBLISH_STEP)["run"], "TRUSTED_JQ")
        self.assertEqual(gate, publish)
        for login in ("github-actions[bot]", "claude[bot]"):
            with self.subTest(login=login):
                self.assertIn(f'.user.login == "{login}"', gate)

    def test_verdict_re_matches_publish_step(self):
        # The publish step guarantees line 2 matches the pattern the gate reads.
        gate = self._assignment(self._gate_step()["run"], "VERDICT_RE")
        publish = self._assignment(self._named_step(PUBLISH_STEP)["run"], "VERDICT_RE")
        self.assertEqual(gate, publish)

    def test_gate_uses_trusted_filter(self):
        self.assertIn("select($TRUSTED_JQ", self._gate_step()["run"])

    def test_no_expression_interpolation_in_gate_run(self):
        self.assertNotIn("${{", self._gate_step()["run"])


class SnippetSkipConditionsTest(unittest.TestCase):
    def test_if_skips_drafts_bots_release_please_and_label(self):
        doc = _load(SNIPPET)
        cond = doc["claude-review"]["if"]
        expected = (
            "github.event.pull_request.draft == false",
            "github.event.pull_request.user.login != 'dependabot[bot]'",
            "github.event.pull_request.user.login != 'github-actions[bot]'",
            "!startsWith(github.event.pull_request.head.ref, 'release-please--')",
            "!contains(github.event.pull_request.labels.*.name, 'skip-claude-review')",
        )
        for clause in expected:
            with self.subTest(clause=clause):
                self.assertIn(clause, cond)

    def test_if_does_not_skip_claude_branches(self):
        # Claude Code session PRs must be reviewed; review-learning PRs are
        # already excluded (GITHUB_TOKEN-opened, github-actions[bot] author).
        doc = _load(SNIPPET)
        cond = doc["claude-review"]["if"]
        self.assertNotIn("'claude/'", cond)


if __name__ == "__main__":
    unittest.main()
