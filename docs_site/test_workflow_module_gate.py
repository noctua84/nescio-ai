# docs_site/test_workflow_module_gate.py
"""Tests for `.github/workflows/module-gate.yml`: its triggers and its excludes.

Lives in `docs_site/`, NOT `tests/`. `tests/` is on FRAMEWORK_PATHS and ships
into every derived instance, which never receives this repository's `.github/`,
so a test there reading the workflow raises FileNotFoundError and reds the
downstream build. The behaviour of the gate itself stays in
`tests/test_module_gate.py`; only the assertions about the YAML moved here. See
`test_ci_coverage.py` for the full argument.

That boundary has already been crossed once by accident. `#238` added the
exclude-pattern assertions below as `tests/test_module_gate_excludes.py`,
reading `.github/` from a module that ships downstream, and at the same time
retired the `memory/**/*.md` spelling that `test_prose_records_are_excluded`
pinned by name here. Both were invisible on that pull request, because
`docs-tests` deliberately does not run on `pull_request` (see
`test_ci_coverage.py`, "THE TRADEOFF, STATED PLAINLY"), so the first report was
a red `main`. The assertions now live here, in the one module that already
existed for exactly this job and already has a workflow step behind it --
merged in rather than added as a second module, so no new step is needed and
there is only one place that reads these patterns.

Needs PyYAML, so the `docs-tests` job installs it before running this module.

Run from the repo root:

    python -m unittest discover -s docs_site -p "test_workflow_module_gate.py"
"""

from __future__ import annotations

import re
import subprocess
import sys
import unittest

from site_under_test import _REPO_ROOT

# MUST stay a top-level insert against the repository ROOT, not `scripts/`: it
# needs no PYTHONPATH because `scripts/__init__.py` exists. Same mechanism and
# same justification as `docs_site/gen_theme.py`, whose docstring argues the
# reversal of the old "docs_site/ imports nothing from scripts/" stance. The
# dependency direction is the safe one -- `scripts/` is on FRAMEWORK_PATHS and
# is present on every checkout this module runs from -- and `module_scan` is
# stdlib-only with no further `scripts/` imports, so this buys no new runtime
# dependency.
sys.path.insert(0, str(_REPO_ROOT))
from scripts import module_scan  # noqa: E402

_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "module-gate.yml"

#: Directories the workflow's own comment calls long-form prose records rather
#: than modules. Every tracked `.md` under these must be excluded.
_PROSE_DIRS = ("docs/plans", "docs/specs", "docs/reports", ".sisyphus", "memory")


def _gate_run_step() -> str:
    """The `run:` body of the workflow's last module-gate step."""
    import yaml

    doc = yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))
    return doc["jobs"]["module-gate"]["steps"][-1]["run"]


def _workflow_excludes() -> tuple[str, ...]:
    """The `--exclude` patterns the workflow actually passes.

    Read out of the workflow rather than hardcoded here. A hardcoded copy
    drifts from the workflow the moment either changes, which is precisely the
    failure this module exists to catch -- and precisely what happened when
    `test_prose_records_are_excluded` named `memory/**/*.md` as a literal and
    the workflow moved on without it.
    """
    return tuple(re.findall(r"--exclude '([^']+)'", _gate_run_step()))


def _tracked_md(prefix: str) -> list[str]:
    proc = subprocess.run(
        ["git", "-C", str(_REPO_ROOT), "ls-files", "-z", "--", f"{prefix}/*.md"],
        capture_output=True,
        check=True,
    )
    raw = proc.stdout.decode("utf-8", errors="surrogateescape")
    return [name for name in raw.split("\0") if name]


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


class WorkflowExcludeParsingTest(unittest.TestCase):
    def test_patterns_are_found(self):
        """A parse that silently returns nothing would make every test vacuous."""
        pats = _workflow_excludes()
        self.assertGreaterEqual(len(pats), 6, pats)

    def test_prose_dirs_are_each_named_by_some_pattern(self):
        """Every prose directory must appear in some pattern.

        This is the assertion `test_prose_records_are_excluded` used to make by
        naming one literal spelling. Checking that the directory is *mentioned*
        survives a change of glob spelling; the tests below check that the
        spelling chosen actually matches real files.
        """
        joined = " ".join(_workflow_excludes())
        for d in _PROSE_DIRS:
            self.assertIn(d, joined, f"{d} has no exclude pattern at all")


class ProseIsExcludedTest(unittest.TestCase):
    """The gate must not demand a module verdict for a prose document.

    ADR 0005 crossed the tripwire at 448 lines on #181 and the gate asked for
    one. The three tests its banner points at do not apply to prose, so the only
    available answer was a true-sounding sentence written to clear a gate -- the
    failure ADR 0006 exists to prevent.

    `module_scan.is_excluded` matches with `fnmatch`, where `*` ALREADY crosses
    `/`. So `memory/*.md` matches both `memory/CONVENTIONS.md` and
    `memory/repo/nescio/adr/0005-x.md`, while `memory/**/*.md` translates to a
    pattern needing a literal `/` after the wildcard and silently misses every
    `.md` sitting directly in the directory. A non-matching exclude pattern
    raises nothing -- it just does not exclude -- so these assert against the
    real tree through the real matcher.
    """

    def test_every_tracked_prose_md_is_excluded(self):
        pats = _workflow_excludes()
        missed: list[str] = []
        checked = 0
        for d in _PROSE_DIRS:
            for rel in _tracked_md(d):
                checked += 1
                if not module_scan.is_excluded(rel, pats):
                    missed.append(rel)
        self.assertGreater(checked, 0, "found no tracked prose at all to check")
        self.assertEqual(missed, [], f"not excluded by {pats}: {missed}")

    def test_memory_md_directly_in_the_directory_is_excluded(self):
        """The `memory/**/*.md` bug, pinned by name.

        `memory/CONVENTIONS.md` is the file that spelling missed, for as long as
        it stood. Latent only because the file is far short of the tripwire.
        """
        self.assertTrue(
            module_scan.is_excluded("memory/CONVENTIONS.md", _workflow_excludes())
        )

    def test_report_md_directly_in_the_directory_is_excluded(self):
        """The `docs/reports/**/*.md` bug, pinned by name.

        The first attempt at the `docs/reports` exclusion was spelled with `**`
        and excluded none of the four reports it was added for.
        """
        self.assertTrue(
            module_scan.is_excluded(
                "docs/reports/2026-08-29-wiki-index-marker-preservation.md",
                _workflow_excludes(),
            )
        )


class CodeIsStillGatedTest(unittest.TestCase):
    """The prose excludes must not become a hole for code.

    `*.md` scoping is the point: a script that lands in a prose directory is
    still a module and still gets a verdict.
    """

    def test_python_in_a_prose_dir_is_not_excluded(self):
        pats = _workflow_excludes()
        for rel in (
            "memory/scripts/thing.py",
            "memory/thing.py",
            "docs/reports/helper.py",
        ):
            self.assertFalse(
                module_scan.is_excluded(rel, pats), f"{rel} should still be gated"
            )

    def test_whole_prose_dirs_are_not_excluded_wholesale(self):
        """A bare `memory/**` would swallow code along with the prose."""
        run = _gate_run_step()
        self.assertNotIn("--exclude 'memory/**'", run)
        self.assertNotIn("--exclude 'docs/reports/**'", run)

    def test_source_trees_are_not_excluded(self):
        pats = _workflow_excludes()
        for rel in ("scripts/wiki_index.py", "tests/test_wiki_index.py"):
            self.assertFalse(
                module_scan.is_excluded(rel, pats), f"{rel} should still be gated"
            )


if __name__ == "__main__":
    unittest.main()
