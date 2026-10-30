# docs_site/test_workflow_module_gate.py
"""Tests for `.github/workflows/module-gate.yml`: its triggers and its excludes.

Lives in `docs_site/`, NOT `tests/`. `tests/` is on FRAMEWORK_PATHS and ships
into every derived instance, which never receives this repository's `.github/`,
so a test there reading the workflow raises FileNotFoundError and reds the
downstream build. The behaviour of the gate itself stays in
`tests/test_module_gate.py`; only the assertions about the YAML moved here. See
`test_ci_coverage.py` for the full argument.

Needs PyYAML, so the `docs-tests` job installs it before running this module.

Run from the repo root:

    python -m unittest discover -s docs_site -p "test_workflow_module_gate.py"
"""

from __future__ import annotations

import unittest

from site_under_test import _REPO_ROOT

_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "module-gate.yml"


class WorkflowTriggerTest(unittest.TestCase):
    """The workflow must re-run when the PR body is edited.

    This gate's prescribed remedy is "add a `Module-check:` line to the PR
    body". GitHub's default `pull_request` type set is
    opened/synchronize/reopened and does NOT include `edited`, so without this
    the gate asks for a body edit and then ignores the edit it asked for: the
    check stays red while the acknowledgement is already there. `gh run rerun`
    is not an escape either, because `github.event.pull_request.body` is an
    event-payload snapshot and a re-run replays the stale body -- the only ways
    out are a push or a close/reopen, neither of which a reader would guess.

    Asserted against the YAML rather than trusted to a comment because the
    failure is silent: drop `types` and everything still parses, still runs, and
    only misbehaves on the one path the gate's own instructions send people
    down.
    """

    #: `yaml.safe_load` resolves the bare key `on` to the BOOLEAN True under
    #: YAML 1.1, so a GitHub workflow's trigger block is `doc[True]`, never
    #: `doc["on"]`. Looking it up by the string silently finds nothing and the
    #: assertions below would pass on an empty dict.
    ON_KEY = True

    def test_pull_request_types_include_edited(self):
        import yaml

        doc = yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))

        self.assertIn(
            self.ON_KEY, doc, "no `on:` block -- did the key spelling change?"
        )
        pull_request = doc[self.ON_KEY]["pull_request"]

        # The realistic regression is someone deleting the `types` line, which
        # leaves a bare `pull_request:` parsing to None -- so that case is
        # handled explicitly. Subscripting None here would raise a TypeError
        # that says nothing about what broke or why it matters.
        self.assertIsNotNone(
            pull_request,
            "`pull_request:` has no `types`, so GitHub applies the default set "
            "and the gate no longer re-runs when the PR body is edited -- which "
            "is the one action its own failure banner tells you to take.",
        )
        types = pull_request.get("types")
        self.assertIsNotNone(types, "`pull_request:` is present but names no `types`")

        self.assertIn(
            "edited",
            types,
            "without `edited` the gate ignores the body edit it asked for",
        )
        # Naming `types` REPLACES the defaults, so the three that were implicit
        # have to stay named or the gate silently stops running on new pushes --
        # a far worse failure than the one this test exists to prevent.
        for required in ("opened", "synchronize", "reopened"):
            self.assertIn(
                required,
                types,
                f"`types` replaces the defaults; {required} must stay listed",
            )

    def test_prose_records_are_excluded(self):
        """The gate must not demand a module verdict for a prose document.

        ADR 0005 crossed the tripwire at 448 lines on #181 and the gate asked
        for one. The three tests its banner points at do not apply to prose, so
        the only available answer was a true-sounding sentence written to clear
        a gate -- the failure ADR 0006 exists to prevent. Asserted here because
        the exclude lives in YAML, where nothing else would notice its removal.
        """
        import yaml

        doc = yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))
        run = doc["jobs"]["module-gate"]["steps"][-1]["run"]

        self.assertIn("memory/**/*.md", run)
        # Scoped to markdown on purpose: a `.py` under memory/ is still a module.
        self.assertNotIn("--exclude 'memory/**'", run)


if __name__ == "__main__":
    unittest.main()
