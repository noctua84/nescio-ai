"""Contract tests for how the PR-review core receives its inputs.

`github-action/claude-review-core.yml` is a reusable workflow. Any `${{ }}`
expression inside a `run:` script is pasted into the shell source before
bash parses it, so a caller-controlled value (such as `inputs.pr_number`)
could inject commands. Values must reach scripts through `env:` instead,
and the PR number must be validated before it is used.
"""
import re
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CORE = ROOT / "github-action" / "claude-review-core.yml"
TEMPLATE = ROOT / "github-action" / "claude-review-core.template.yml"
SCRIPTS = ROOT / "github-action" / "scripts" / "claude-review"

PR_STEP_ID = "pr"
PR_STEP_NAME = "Resolve PR context"
PR_NUMBER_RE = "^[1-9][0-9]*$"
OUTPUT_KEYS = ("number", "title", "user", "base_ref", "base_sha",
               "head_ref", "head_sha", "today")


def _load(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


class _CoreBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = _load(CORE)
        cls.jobs = cls.doc["jobs"]
        cls.steps = cls.jobs["review"]["steps"]

    def _pr_step(self):
        found = [s for s in self.steps if s.get("id") == PR_STEP_ID]
        self.assertEqual(len(found), 1, f"expected exactly one step with id {PR_STEP_ID!r}")
        step = found[0]
        self.assertEqual(step.get("name"), PR_STEP_NAME)
        return step


class NoInterpolationInAnyRunTest(_CoreBase):
    def test_no_expression_interpolation_in_any_run(self):
        seen = 0
        offenders = []
        for job_id, job in self.jobs.items():
            for i, step in enumerate(job.get("steps", [])):
                if "run" not in step:
                    continue
                seen += 1
                if "${{" in str(step["run"]):
                    offenders.append(f"{job_id}: {step.get('name', f'step {i}')}")
        self.assertGreater(seen, 0, "no run: steps found; the check would pass vacuously")
        self.assertEqual(
            offenders, [],
            "run: scripts must not interpolate ${{ }} expressions; pass values "
            f"through env: instead. Offending steps: {offenders}")

    def test_no_expression_interpolation_in_template_runs(self):
        # The template is the wiring source of the shipped core: its run:
        # blocks hold only `# @inline` markers, never an expression.
        doc = _load(TEMPLATE)
        runs = [str(s["run"]) for j in doc["jobs"].values()
                for s in j.get("steps", []) if "run" in s]
        self.assertGreater(len(runs), 0)
        self.assertEqual([r for r in runs if "${{" in r], [])

    def test_no_expression_interpolation_in_scripts(self):
        # A script is inlined verbatim into a run: block, so an expression in
        # it would be evaluated by Actions before bash ever parses it.
        scripts = sorted(SCRIPTS.glob("*.sh"))
        self.assertGreater(len(scripts), 0, "no scripts found; the check would pass vacuously")
        self.assertEqual(
            [s.name for s in scripts if "${{" in s.read_text(encoding="utf-8")], [])


class ResolvePrContextTest(_CoreBase):
    def test_pr_number_arrives_through_env(self):
        env = self._pr_step().get("env", {})
        self.assertIn("PR_NUMBER", env)
        self.assertIn("inputs.pr_number", str(env["PR_NUMBER"]))

    def test_validates_pr_number_and_fails(self):
        run = self._pr_step()["run"]
        self.assertIn(PR_NUMBER_RE, run)
        self.assertRegex(run, r"\bexit 1\b")

    def test_validates_before_first_use(self):
        run = self._pr_step()["run"]
        check = run.find(PR_NUMBER_RE)
        api = run.find("gh api")
        self.assertNotEqual(check, -1, "PR number validation not found")
        self.assertNotEqual(api, -1, "gh api call not found")
        self.assertLess(check, api, "PR number must be validated before the gh api call")

    def test_uses_env_values_in_script(self):
        run = self._pr_step()["run"]
        self.assertIn('"$PR_NUMBER"', run)
        self.assertRegex(run, r"\$\{?GITHUB_REPOSITORY\b")

    def test_outputs_preserved(self):
        run = self._pr_step()["run"]
        self.assertIn('"$GITHUB_OUTPUT"', run)
        for key in OUTPUT_KEYS:
            with self.subTest(key=key):
                self.assertRegex(run, rf'(?m)^\s*echo\s+"?{key}=')


class PrNumberRegexTest(_CoreBase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        step = next(s for s in cls.steps if s.get("id") == PR_STEP_ID)
        m = re.search(r'\[\[\s*"\$PR_NUMBER"\s*=~\s*(\S+)\s*\]\]', step["run"])
        assert m, 'no [[ "$PR_NUMBER" =~ ... ]] test found in the Resolve PR context step'
        cls.pattern = m.group(1)

    def _bash_matches(self, value):
        # bash [[ =~ ]] uses POSIX ERE without REG_NEWLINE: `^`/`$` anchor
        # only at the very start/end of the string. Python's `$` also
        # matches before a trailing newline, so drop the anchors and use
        # fullmatch, which anchors at the true string ends.
        self.assertTrue(self.pattern.startswith("^") and self.pattern.endswith("$"),
                        f"pattern {self.pattern!r} is not fully anchored")
        return re.fullmatch(self.pattern[1:-1], value) is not None

    def test_pattern_value(self):
        self.assertEqual(self.pattern, PR_NUMBER_RE)

    def test_accepts(self):
        for value in ("1", "42", "259"):
            with self.subTest(value=value):
                self.assertTrue(self._bash_matches(value))

    def test_rejects(self):
        for value in ("0", "01", "-1", "1a", "", "1; rm -rf /", "$(id)",
                      "1\n2", "1\n", " 1"):
            with self.subTest(value=value):
                self.assertFalse(self._bash_matches(value))


if __name__ == "__main__":
    unittest.main()
