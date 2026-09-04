# docs_site/test_ci_coverage.py
"""Every test module in this repository must be executed by some CI step.

THE DEFECT THIS EXISTS FOR. A suite that is never invoked is indistinguishable
from a suite that passes: both are silent, and the green tick cannot tell them
apart. That has now bitten twice from the same blind spot.

  * `docs_site/` ran nowhere. `test_committed_pages_are_up_to_date` existed the
    whole time with no trigger behind it, so the committed catalog drifted out
    of step with `agents/` and nothing said so.
  * `brand/` ran nowhere. The design system's own suite sat in the repository,
    green on a laptop, never once executed by CI. It was found by grepping
    `.github/` by hand.

Both were fixed one at a time, and neither fix left anything behind that would
notice the third occurrence. A fourth discovery root added tomorrow would be
exactly as invisible as the first two were. This module is the thing that
notices: it enumerates the test modules on disk, enumerates what the workflows
actually run, and fails when the first set is not covered by the second.

WHY IT LIVES IN `docs_site/` AND NOT `tests/`. `tests/` is on FRAMEWORK_PATHS
(`scripts/sync_from_upstream.py`) and is copied into every derived downstream
instance. Those instances never receive `.github/`, `brand/` or `docs_site/` --
but they are real repositories that may well have workflows and test
directories of their own, so a detector shipped in `tests/` would not lie
dormant there. It would run, read *their* CI, and red their build over a policy
that belongs to this repository and concerns subsystems their install does not
contain. A `skipTest` when `.github/` is absent does not help, because the
problem case is the downstream repo that *has* one. No test in `tests/` reads
this repository's own `.github/` today -- the ones that mention workflows write
fixtures into a temporary directory instead -- and that is the boundary being
kept. `docs_site/` is off FRAMEWORK_PATHS, already holds the precedent for
reading these workflow files (`test_site_content.py::MaterialPinTest`, which
pins the two-workflow `mkdocs-material` agreement), and is itself a root with a
job behind it.

THE TRADEOFF, STATED PLAINLY: a detector in a non-required job is only as good
as the trigger behind it. `docs-tests` does not run on `pull_request` and is
deliberately not among main's required status checks -- protection requires
exactly ["tests"] -- so this detector reports on push-to-main, the weekly cron
and manual dispatch, and never on the pull request that introduced the gap. It
catches the third occurrence after the merge that caused it, not before. That
is the same trade the `docs-tests` job already accepts for catalog drift, made
for the same reason: the alternative is gating outside contributors on
`brand/`/`docs_site/`, which is what produced a check nobody could act on last
time. Post-merge and dated beats never, which is what we had.

The corollary is that this module is not self-supporting: it needs a step of
its own in `.github/workflows/tests.yml`, because the `docs_site` steps name
their modules with `-p` rather than discovering the directory. If that step is
ever dropped, `test_every_test_module_is_run_by_a_workflow_step` will report
*itself* as uncovered -- but only if something still runs it. There is no way
out of that regress; there is only making the first link short and loud.

HOW THE WORKFLOWS ARE READ: textually, with a small indentation-aware scan --
no YAML parser. This repository is stdlib-only on purpose and that invariant is
itself tested (`brand/test_rasterisers.py`), so PyYAML is not an option, and
stdlib ships no YAML reader. The two remaining choices are a hand-rolled YAML
parser or a scanner that understands only the shapes these files actually use.
The scanner is the more honest of the two: a partial YAML parser invites the
belief that it handles YAML, and would be far more code to be wrong in.

What the scan is, precisely: comment lines are dropped, then top-level keys,
the `on:` trigger names, job names, job-level `if:` expressions and `run:`
commands (single-line and block scalar) are recognised by indentation.
Dropping comments is load-bearing rather than tidy: `tests.yml` discusses
`discover -s tests`, `discover -s docs_site` and `-s brand` in its prose, so a
naive grep over the raw text would report full coverage no matter what the
steps say. `ScannerTest` pins that against a fixture.

What it therefore cannot guarantee: anything that decides at runtime. A step
that builds its command from a matrix variable, an `env` indirection, or a
shell script invoked by name is invisible here and reads as no coverage at all.
That direction is the safe one -- it over-reports gaps rather than certifying
absent ones -- but it means the fix for such a step is to name it in the
workflow, not to loosen this module.

DISCOVERY IS MODELLED, NOT EXECUTED. `_collected` reproduces what `unittest
discover -s DIR -p PAT` would collect by walking the tree: files matching the
pattern directly inside DIR, plus the same in any subdirectory that is an
importable package. Importing the modules to ask the real loader would mean
executing every test module's import side effects inside this one. A test file
somewhere the loader cannot reach -- a non-package subdirectory -- is reported
as uncovered, which is what it is.

WHETHER A ROOT RUNS ON `pull_request` IS CHECKED, BUT SEPARATELY, AND NOT AS A
DEMAND THAT IT SHOULD. A suite behind a push-to-main-only job is covered, and
later than a reader skimming the workflow would assume. Failing on that would
amount to demanding `brand/` and `docs_site/` run on pull requests, which
`tests.yml` refuses at length and for good reasons. So the classification is
pinned instead of policed: each root is labelled from the workflows as
pull-request-gated or post-merge-only, and compared against a table stating
what this repository has decided. Moving a root between those two states stays
possible; doing it silently does not. Adding a root forces an entry, which is
the same forcing function as the coverage check one level up.

No test counts are quoted here, deliberately: nothing in CI asserts them, and
`test_gen_catalog.py::test_no_hardcoded_counts_in_the_generator` holds the
generator to the same rule.

Run from the repo root:

    python -m unittest discover -s docs_site -p "test_ci_coverage.py"
"""

from __future__ import annotations

import re
import tempfile
import unittest
from fnmatch import fnmatch
from pathlib import Path
from typing import NamedTuple

_DOCS_SITE = Path(__file__).resolve().parent
_REPO_ROOT = _DOCS_SITE.parent
_WORKFLOW_DIR = _REPO_ROOT / ".github" / "workflows"

#: unittest's own default for `discover -p`.
_DEFAULT_PATTERN = "test*.py"

#: Never walked when looking for test modules. Hidden directories (`.git`,
#: `.claude`, `.sisyphus`) are skipped by the leading-dot rule instead.
_IGNORED_DIRS = frozenset({"__pycache__", "node_modules", "site", "_site"})

#: What each discovery root is worth as a merge signal.
#: True  -- covered by a job that runs on `pull_request`; a gate on the change.
#: False -- covered only post-merge (push-to-main, cron, manual dispatch).
#: The False entries are deliberate. See the "CATALOG DRIFT IS DELIBERATELY NOT
#: A MERGE GATE" and "brand/ IS THE THIRD UNITTEST ROOT" comments in
#: .github/workflows/tests.yml before changing one; `docs-tests` additionally
#: *cannot* be made required while it has no `pull_request` trigger, because a
#: required check that never reports blocks every PR forever.
_GATES_PULL_REQUESTS = {
    "tests": True,
    "brand": False,
    "docs_site": False,
}


class Invocation(NamedTuple):
    """One `python -m unittest discover` call found in a workflow."""

    workflow: str
    job: str
    start_dir: str
    pattern: str


# --------------------------------------------------------------------------
# Reading the tree
# --------------------------------------------------------------------------


def _iter_test_modules(root: Path) -> set[Path]:
    """Every `test*.py` under `root`, hidden and cache directories aside.

    Deliberately not limited to what any loader can reach: a test file in a
    place no `discover` invocation collects is precisely the thing being
    hunted, so it must show up here to be reportable as uncovered.
    """
    found: set[Path] = set()
    stack = [root]
    while stack:
        current = stack.pop()
        for entry in sorted(current.iterdir()):
            if entry.name.startswith(".") or entry.name in _IGNORED_DIRS:
                continue
            if entry.is_dir():
                stack.append(entry)
            elif entry.is_file() and fnmatch(entry.name, _DEFAULT_PATTERN):
                found.add(entry)
    return found


def _collected(start: Path, pattern: str) -> set[Path]:
    """What `unittest discover -s start -p pattern` would collect.

    Files matching `pattern` directly inside `start`, plus the same in any
    subdirectory carrying `__init__.py`. Namespace-package discovery was
    removed from unittest in 3.11, so an unimportable subdirectory is a dead
    end for the real loader too.
    """
    found: set[Path] = set()
    if not start.is_dir():
        return found
    for entry in sorted(start.iterdir()):
        if entry.name.startswith(".") or entry.name in _IGNORED_DIRS:
            continue
        if entry.is_file() and fnmatch(entry.name, pattern):
            found.add(entry)
        elif entry.is_dir() and (entry / "__init__.py").is_file():
            found |= _collected(entry, pattern)
    return found


# --------------------------------------------------------------------------
# Reading the workflows
# --------------------------------------------------------------------------

_TOP_KEY_RE = re.compile(r"^([A-Za-z_][\w-]*):(.*)$")
_NESTED_KEY_RE = re.compile(r"^\s+([A-Za-z_][\w-]*):(.*)$")
_RUN_KEY_RE = re.compile(r"^\s*-?\s*run:(.*)$")
_BLOCK_SCALARS = frozenset({"|", ">", "|-", ">-", "|+", ">+"})

_DISCOVER_RE = re.compile(r"\bunittest\s+discover\b")
_START_DIR_RE = re.compile(r"(?:^|\s)(?:-s|--start-directory)[=\s]\s*(\S+)")
_PATTERN_RE = re.compile(r"(?:^|\s)(?:-p|--pattern)[=\s]\s*(\S+)")


def _unquote(token: str) -> str:
    return token.strip("'\"")


def scan_workflow(
    text: str, name: str = "<workflow>"
) -> tuple[set[str], dict[str, str], list[Invocation]]:
    """Return (trigger names, {job: job-level `if:` text}, discovery calls).

    Indentation-aware line scan, not a YAML parser -- see the module docstring
    for why that is the honest choice here rather than the lazy one. Comment
    lines are dropped first, which is what stops the extensive prose in
    `tests.yml` from being read as coverage.
    """
    triggers: set[str] = set()
    jobs: dict[str, str] = {}
    invocations: list[Invocation] = []

    section: str | None = None
    job: str | None = None
    block: list | None = None  # [kind, key_indent, owner, lines]

    def close_block() -> None:
        nonlocal block
        if block is None:
            return
        kind, _indent, owner, lines = block
        if kind == "if":
            jobs[owner] = " ".join(lines)
        else:
            invocations.extend(_invocations_in("\n".join(lines), name, owner))
        block = None

    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        expanded = raw.expandtabs(2)
        indent = len(expanded) - len(expanded.lstrip())

        if block is not None:
            if indent > block[1]:
                block[3].append(raw.strip())
                continue
            close_block()

        if indent == 0:
            match = _TOP_KEY_RE.match(raw)
            section = match.group(1) if match else None
            job = None
            if section == "on" and match:
                inline = match.group(2).strip()
                if inline.startswith("["):
                    triggers.update(
                        _unquote(t.strip()) for t in inline.strip("[]").split(",") if t.strip()
                    )
            continue

        if section == "on":
            match = _NESTED_KEY_RE.match(raw)
            if match and indent == 2:
                triggers.add(match.group(1))
            continue

        if section != "jobs":
            continue

        if indent == 2:
            match = _NESTED_KEY_RE.match(raw)
            if match:
                job = match.group(1)
                jobs.setdefault(job, "")
            continue

        if job is None:
            continue

        # Job-level keys sit at indent 4; steps and their keys sit deeper, so a
        # step's own `if:` is never mistaken for the job's.
        if indent == 4:
            match = _NESTED_KEY_RE.match(raw)
            if match and match.group(1) == "if":
                value = match.group(2).strip()
                if value in _BLOCK_SCALARS:
                    block = ["if", indent, job, []]
                else:
                    jobs[job] = value
            continue

        match = _RUN_KEY_RE.match(raw)
        if match:
            value = match.group(1).strip()
            if value in _BLOCK_SCALARS:
                block = ["run", indent, job, []]
            else:
                invocations.extend(_invocations_in(value, name, job))

    close_block()
    return triggers, jobs, invocations


def _invocations_in(command: str, workflow: str, job: str) -> list[Invocation]:
    """Every `unittest discover` call in one shell command."""
    found: list[Invocation] = []
    for line in command.splitlines():
        if not _DISCOVER_RE.search(line):
            continue
        start = _START_DIR_RE.search(line)
        pattern = _PATTERN_RE.search(line)
        found.append(
            Invocation(
                workflow=workflow,
                job=job,
                start_dir=_unquote(start.group(1)) if start else ".",
                pattern=_unquote(pattern.group(1)) if pattern else _DEFAULT_PATTERN,
            )
        )
    return found


def read_workflows(
    directory: Path,
) -> tuple[dict[str, set[str]], dict[str, str], list[Invocation]]:
    """Scan every workflow file.

    Returns per-workflow triggers, job-level `if:` texts keyed `workflow:job`,
    and every discovery call found across all of them.
    """
    triggers: dict[str, set[str]] = {}
    conditions: dict[str, str] = {}
    invocations: list[Invocation] = []
    for path in sorted(directory.glob("*.y*ml")):
        on, jobs, calls = scan_workflow(path.read_text(encoding="utf-8"), path.name)
        triggers[path.name] = on
        for job, condition in jobs.items():
            conditions[f"{path.name}:{job}"] = condition
        invocations.extend(calls)
    return triggers, conditions, invocations


# --------------------------------------------------------------------------
# The detector proper
# --------------------------------------------------------------------------


def uncovered(root: Path, invocations: list[Invocation]) -> set[Path]:
    """Test modules under `root` that no invocation would collect."""
    covered: set[Path] = set()
    for call in invocations:
        covered |= _collected((root / call.start_dir).resolve(), call.pattern)
    return _iter_test_modules(root) - covered


def _runs_on_pull_request(triggers: set[str], condition: str) -> bool | None:
    """Does a job with this `if:` fire on `pull_request`?

    None means "the expression is not one this scan classifies" -- reported as
    a failure asking for a human decision rather than guessed at. No job in
    this repository currently reaches that branch.
    """
    if "pull_request" not in triggers:
        return False
    if not condition.strip():
        return True
    if "pull_request" in condition or "always()" in condition:
        return None
    return False


class WorkflowCoverageTest(unittest.TestCase):
    """The headline guard: a root nothing runs is a root that fails here."""

    @classmethod
    def setUpClass(cls) -> None:
        if not _WORKFLOW_DIR.is_dir():
            raise AssertionError(
                f"{_WORKFLOW_DIR} is missing; there is nothing to check coverage against"
            )
        cls.triggers, cls.conditions, cls.invocations = read_workflows(_WORKFLOW_DIR)

    def test_workflows_were_actually_parsed(self) -> None:
        """A scan that silently read nothing would pass every check below."""
        self.assertTrue(self.triggers, "no workflow files were read")
        self.assertTrue(self.conditions, "no jobs were found in any workflow")
        self.assertTrue(
            self.invocations,
            "no `unittest discover` step was found in any workflow -- either CI "
            "runs no tests at all, or the scan in this module has stopped "
            "recognising the shape the steps are written in",
        )

    def test_every_test_module_is_run_by_a_workflow_step(self) -> None:
        """The recurrence guard behind PR #112 (docs_site) and PR #123 (brand).

        Both defects were a test directory that existed and executed nowhere.
        Nothing detected either one; both were found by hand, months apart.
        """
        missing = sorted(
            p.relative_to(_REPO_ROOT).as_posix() for p in uncovered(_REPO_ROOT, self.invocations)
        )
        self.assertEqual(
            [],
            missing,
            "these test modules exist but no step in .github/workflows/ runs them, so "
            "they can neither fail nor pass -- add a discovery step (or extend an "
            "existing `-p` pattern) in .github/workflows/tests.yml: " + ", ".join(missing),
        )

    def test_every_discovery_step_collects_something(self) -> None:
        """The mirror failure: a step aimed at a directory that moved.

        `unittest discover` over an empty or absent tree exits 0. A renamed
        root would leave the step green and the suite unrun -- the same
        silence, arrived at from the other side.
        """
        for call in self.invocations:
            with self.subTest(workflow=call.workflow, job=call.job, start=call.start_dir):
                start = (_REPO_ROOT / call.start_dir).resolve()
                self.assertTrue(
                    start.is_dir(),
                    f"{call.workflow} ({call.job}) discovers `{call.start_dir}`, "
                    "which is not a directory",
                )
                self.assertTrue(
                    _collected(start, call.pattern),
                    f"{call.workflow} ({call.job}) discovers `{call.start_dir}` with "
                    f"pattern `{call.pattern}` and collects nothing; the step exits 0 "
                    "and certifies nothing",
                )


class TriggerVisibilityTest(unittest.TestCase):
    """Covered is not the same as covered *before the merge*.

    This does not demand that every root gate pull requests -- `tests.yml`
    argues at length against exactly that for `brand/` and `docs_site/`, and
    those arguments stand. It pins which side of the line each root is on, so
    the answer to "when does this actually run" is a recorded decision instead
    of something a reader has to reconstruct from job-level `if:` expressions.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.triggers, cls.conditions, cls.invocations = read_workflows(_WORKFLOW_DIR)
        cls.gating = cls._classify()

    @classmethod
    def _classify(cls) -> dict[str, bool | None]:
        """Map each root to whether *any* job covering it fires on a PR."""
        result: dict[str, bool | None] = {}
        for call in cls.invocations:
            condition = cls.conditions.get(f"{call.workflow}:{call.job}", "")
            verdict = _runs_on_pull_request(cls.triggers.get(call.workflow, set()), condition)
            for module in _collected((_REPO_ROOT / call.start_dir).resolve(), call.pattern):
                root = module.relative_to(_REPO_ROOT).parts[0]
                if verdict is None:
                    result[root] = None
                elif result.get(root, False) is False:
                    result[root] = verdict
        return result

    def test_every_root_has_a_recorded_expectation(self) -> None:
        """A new discovery root must be classified, not merely wired up."""
        roots = {p.relative_to(_REPO_ROOT).parts[0] for p in _iter_test_modules(_REPO_ROOT)}
        self.assertEqual(
            sorted(roots),
            sorted(_GATES_PULL_REQUESTS),
            "the set of test roots on disk no longer matches the table in this module; "
            "a new root needs an entry saying whether it gates pull requests, and a "
            "removed one needs its entry deleted",
        )

    def test_each_root_runs_where_it_is_documented_to(self) -> None:
        for root, expected in sorted(_GATES_PULL_REQUESTS.items()):
            with self.subTest(root=root):
                self.assertIn(
                    root,
                    self.gating,
                    f"no workflow step covers `{root}` at all, so there is no trigger "
                    "to classify; test_every_test_module_is_run_by_a_workflow_step "
                    "names the modules that are going unrun",
                )
                actual = self.gating[root]
                self.assertIsNotNone(
                    actual,
                    f"the job covering `{root}` carries an `if:` this module does not "
                    "classify; decide by hand whether it fires on pull_request and "
                    "teach `_runs_on_pull_request` the shape",
                )
                if expected:
                    self.assertTrue(
                        actual,
                        f"`{root}` no longer runs on pull_request. It is the required "
                        'check; main\'s protection requires exactly ["tests"], and a '
                        "required check that never reports blocks every PR forever.",
                    )
                else:
                    self.assertFalse(
                        actual,
                        f"`{root}` now runs on pull_request. That is a deliberate "
                        "reversal, not a tidy-up: read the `docs-tests` comment in "
                        f".github/workflows/tests.yml, which refuses it because `{root}` "
                        "is presentation, is off FRAMEWORK_PATHS, and would gate "
                        "contributors on a subsystem their install does not contain -- "
                        "and which lists what else becomes mandatory in the same change.",
                    )


class ScannerTest(unittest.TestCase):
    """The scan's own failure modes, pinned against fixtures.

    `test_every_test_module_is_run_by_a_workflow_step` is only a guard if it
    can go red. These are the ways it could quietly stop being able to.
    """

    _FIXTURE = """\
name: fixture
on:
  push:
  pull_request:
jobs:
  gated:
    steps:
      - run: python -m unittest discover -s alpha -v
  post-merge:
    if: >-
      github.event_name == 'schedule' ||
      (github.event_name == 'push' && github.ref == 'refs/heads/main')
    steps:
      # This mentions `discover -s ghost` in prose, the way tests.yml does.
      # - run: python -m unittest discover -s ghost
      - run: python -m unittest discover -s beta -p "test_one.py"
      - if: always()
        run: |
          echo "not a test step"
          python -m unittest discover -s gamma
"""

    def test_prose_and_commented_out_steps_are_not_coverage(self) -> None:
        """The failure that would make this module certify a lie.

        `tests.yml` discusses `discover -s tests`, `discover -s docs_site` and
        `-s brand` in its comments. A scan that counted those would report
        every root covered whatever the steps did -- and would have reported
        `brand/` covered throughout the entire period it ran nowhere.
        """
        _, _, calls = scan_workflow(self._FIXTURE, "fixture.yml")
        self.assertEqual(
            {"alpha", "beta", "gamma"},
            {c.start_dir for c in calls},
            "a commented-out invocation was read as a real step",
        )

    def test_patterns_jobs_and_block_scalars_are_read(self) -> None:
        triggers, conditions, calls = scan_workflow(self._FIXTURE, "fixture.yml")
        self.assertEqual({"push", "pull_request"}, triggers)
        by_dir = {c.start_dir: c for c in calls}
        self.assertEqual("test_one.py", by_dir["beta"].pattern)
        self.assertEqual(_DEFAULT_PATTERN, by_dir["alpha"].pattern)
        self.assertEqual("post-merge", by_dir["gamma"].job, "a block-scalar `run:` was missed")
        self.assertEqual("", conditions["gated"])
        self.assertIn("refs/heads/main", conditions["post-merge"])

    def test_a_step_level_if_is_not_read_as_the_jobs_if(self) -> None:
        """`- if: always()` on a step must not become the job's condition.

        Job-level and step-level `if:` differ only by indentation. Confusing
        them would reclassify a whole job's trigger from one step's guard.
        """
        _, conditions, _ = scan_workflow(self._FIXTURE, "fixture.yml")
        self.assertNotIn("always()", conditions["post-merge"])

    def test_the_detector_reports_an_uncovered_root(self) -> None:
        """Proof the guard can fail, without editing the real workflow.

        The same shape as `brand/`: a directory full of tests, and no step.
        """
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            for name in ("alpha", "orphan"):
                (root / name).mkdir()
                (root / name / "test_thing.py").write_text("", encoding="utf-8")
            calls = [Invocation("fixture.yml", "gated", "alpha", _DEFAULT_PATTERN)]

            self.assertEqual(
                {root / "orphan" / "test_thing.py"},
                uncovered(root, calls),
                "a test directory with no step behind it was not reported",
            )
            calls.append(Invocation("fixture.yml", "gated", "orphan", _DEFAULT_PATTERN))
            self.assertEqual(set(), uncovered(root, calls))

    def test_a_pattern_that_misses_a_sibling_module_is_reported(self) -> None:
        """The `-p` trap `tests.yml` warns about, in miniature.

        The `docs_site` steps name modules with `-p` instead of discovering the
        directory, so those patterns must cover the directory between them:
        "Add a further test module to docs_site/ without adding a step and it
        runs in neither."
        """
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            (root / "pages").mkdir()
            (root / "pages" / "test_named.py").write_text("", encoding="utf-8")
            (root / "pages" / "test_forgotten.py").write_text("", encoding="utf-8")
            calls = [Invocation("fixture.yml", "docs", "pages", "test_named.py")]
            self.assertEqual({root / "pages" / "test_forgotten.py"}, uncovered(root, calls))


if __name__ == "__main__":
    unittest.main()
