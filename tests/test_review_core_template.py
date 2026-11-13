"""Contract tests for the PR-review template's review-learning capture.

`github-action/claude-review-core.yml` is copied into target repos. Claude
must stay read-only with respect to git; it only stages learning notes to
/tmp/review-learnings/, and a deterministic shell step after it opens the
note PRs. These tests parse the YAML and check that contract.
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

    def test_still_has_write_and_read(self):
        entries = [t.strip() for t in self._allowed_tools().split(",")]
        self.assertIn("Write", entries)
        self.assertIn("Read", entries)


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


class MergeGateTest(_CoreBase):
    def test_needs_review_and_not_cancelled(self):
        gate = self.jobs["merge-gate"]
        needs = gate["needs"]
        needs = [needs] if isinstance(needs, str) else needs
        self.assertIn("review", needs)
        self.assertIn("!cancelled()", str(gate.get("if", "")))


class SnippetSkipConditionsTest(unittest.TestCase):
    def test_if_skips_all_six(self):
        doc = _load(SNIPPET)
        cond = doc["claude-review"]["if"]
        expected = (
            "github.event.pull_request.draft == false",
            "github.event.pull_request.user.login != 'dependabot[bot]'",
            "github.event.pull_request.user.login != 'github-actions[bot]'",
            "!startsWith(github.event.pull_request.head.ref, 'release-please--')",
            "!startsWith(github.event.pull_request.head.ref, 'claude/')",
            "!contains(github.event.pull_request.labels.*.name, 'skip-claude-review')",
        )
        for clause in expected:
            with self.subTest(clause=clause):
                self.assertIn(clause, cond)


if __name__ == "__main__":
    unittest.main()
