# tests/test_agent_definitions.py
"""Validate the crew's agent definitions.

Agent behaviour is prose and cannot be unit-tested. What *can* be pinned
mechanically is the frontmatter contract and the orchestrator's dispatch
wiring — which is precisely what drifts silently when these files are
edited by hand.
"""

import contextlib
import io
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import apply_theme  # noqa: E402
from _crew_common import (  # noqa: E402
    BOUNDARY_PHRASE,
    BOUNDED_WRITERS,
    CODE_WRITERS,
    TIERED_AGENTS,
    expected_roster,
    themed_name,
)

AGENTS_DIR = ROOT / "agents"

# Models the crew is allowed to name. Anything else is a typo or an
# unreviewed bump.
ALLOWED_MODELS = {
    "claude-opus-5",
    "claude-opus-4-8",
    "claude-sonnet-5",
    "claude-haiku-4-5",
}

FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)

# A dispatch declaration in the orchestrator charter. The value may name
# several agents separated by `|` (the builder cost tiers do), so it is parsed
# rather than substring-matched. Deliberately unanchored: the charter writes
# these both inline (`Agent(subagent_type: "explore", ...)`) and on their own
# line inside a multi-line block, and both forms are real dispatches.
DISPATCH_RE = re.compile(r'subagent_type: "([^"]*)"')


def _agent_files(agents_dir=AGENTS_DIR):
    return sorted(agents_dir.glob("*.md"))


def _current_theme(agents_dir=AGENTS_DIR):
    """The theme on disk, normalised to a name `_crew_common` accepts.

    `detect_theme` returns None for a tree it cannot classify; treating that as
    'functional' preserves the behaviour these helpers had before they were
    routed through `_crew_common`, which rejects an unknown theme outright.
    """
    return "philosophers" if apply_theme.detect_theme(agents_dir) == "philosophers" else "functional"


def _themed(functional_name, agents_dir=AGENTS_DIR):
    """The on-disk name of `functional_name` under the theme currently applied.

    These tests ship to instances (``tests`` is in ``FRAMEWORK_PATHS``), and an
    instance may have run ``apply_theme.py``. Asserting the functional name
    there asserts this repo's own state rather than a property of the framework.

    Delegates to `_crew_common.themed_name` rather than indexing `PAIRS`: the
    tier variants (`builder-simple`, `builder-standard`) are not PAIRS keys, so
    a `dict(PAIRS)[name]` lookup KeyErrors on exactly the names the write-policy
    tests below map through here.
    """
    return themed_name(functional_name, _current_theme(agents_dir))


def _off_theme(functional_name, agents_dir=AGENTS_DIR):
    """The counterpart name that must *not* survive under the current theme.

    A half-applied rename leaves both names in the tree; asserting the absence
    of this one gives the wiring tests teeth in either direction.
    """
    themed = _themed(functional_name, agents_dir)
    if themed != functional_name:
        return functional_name
    return themed_name(functional_name, "philosophers")


def _tool_tokens(value):
    """Split a `tools:`/`disallowedTools:` frontmatter value into exact tokens.

    Substring matching is not safe here: ``"Edit" in "NotebookEdit"`` is True,
    so a substring check would read `disallowedTools: NotebookEdit` as a ban on
    Edit — the exact drift these tests exist to catch.
    """
    return {t.strip() for t in value.split(",") if t.strip()}


def _dispatch_targets(text):
    """Every `subagent_type:` value declared in a charter, split on `|`.

    Returned as a list of sets because one declaration may offer a choice of
    agents — the builder cost tiers share a single dispatch block. Comparing
    parsed sets rather than raw substrings keeps `"builder"` from matching
    inside `"builder-simple"`, the same token-vs-substring hazard `_tool_tokens`
    exists for.
    """
    return [
        {alternative.strip() for alternative in match.group(1).split("|")}
        for match in DISPATCH_RE.finditer(text)
    ]


def _may_not_edit(fields):
    """Is this agent barred from editing production code by its frontmatter?

    Either it names Edit in `disallowedTools`, or it restricts itself with a
    read-only `tools` allowlist (as `vision` does).
    """
    disallowed = _tool_tokens(fields.get("disallowedTools", ""))
    tools = _tool_tokens(fields.get("tools", ""))
    read_only_allowlist = bool(tools) and not (tools & {"Edit", "Write"})
    return "Edit" in disallowed or read_only_allowlist


class TestFrontmatterMixin:
    def _frontmatter(self, path):
        text = path.read_text(encoding="utf-8")
        match = FRONTMATTER_RE.match(text)
        self.assertTrue(match, f"{path.name}: missing YAML frontmatter block")
        fields = {}
        for line in match.group(1).splitlines():
            if ":" in line and not line.startswith((" ", "\t", "#")):
                key, _, value = line.partition(":")
                fields[key.strip()] = value.strip()
        return fields


class TestRoster(TestFrontmatterMixin, unittest.TestCase):
    def test_roster_matches_expected(self):
        theme = apply_theme.detect_theme(AGENTS_DIR)
        self.assertIsNotNone(theme, "could not detect the crew's theme in agents/")
        found = {path.stem for path in _agent_files()}
        self.assertEqual(found, expected_roster(theme))

    def test_roster_expectation_follows_the_philosophers_theme(self):
        """Applying the shipped theme must not break the roster assertion."""
        with tempfile.TemporaryDirectory() as d:
            themed_dir = Path(d) / "agents"
            shutil.copytree(AGENTS_DIR, themed_dir)
            with contextlib.redirect_stdout(io.StringIO()):
                rc = apply_theme.apply_theme(themed_dir, "philosophers")
            self.assertEqual(rc, 0)
            self.assertEqual(apply_theme.detect_theme(themed_dir), "philosophers")
            found = {path.stem for path in _agent_files(themed_dir)}
            self.assertEqual(found, expected_roster("philosophers"))


class TestAgentFrontmatter(TestFrontmatterMixin, unittest.TestCase):
    def test_name_matches_filename(self):
        for path in _agent_files():
            with self.subTest(agent=path.stem):
                self.assertEqual(self._frontmatter(path).get("name"), path.stem)

    def test_model_is_allowed(self):
        for path in _agent_files():
            with self.subTest(agent=path.stem):
                model = self._frontmatter(path).get("model")
                self.assertIn(model, ALLOWED_MODELS, f"{path.name}: unexpected model {model!r}")

    def test_description_is_substantive(self):
        for path in _agent_files():
            with self.subTest(agent=path.stem):
                description = self._frontmatter(path).get("description", "")
                self.assertGreaterEqual(
                    len(description), 40, f"{path.name}: description too thin to route on"
                )


class TestEditPermissions(TestFrontmatterMixin, unittest.TestCase):
    def test_only_declared_writers_can_edit(self):
        """The declared writers may Edit production code; nobody else may.

        Note this is about Edit, not Write. orchestrator, planner and reviewer
        deliberately retain Write so they can produce plans and audit reports —
        but none of them may Edit. vision restricts itself with a read-only
        ``tools`` allowlist instead of ``disallowedTools``.

        Both directions are asserted with the same predicate, so an agent
        cannot satisfy this test by being ambiguous: it is either in the
        declared set and demonstrably able to Edit, or outside it and
        demonstrably barred.

        The writers are renamed on a themed instance (``builder`` becomes
        ``archimedes``, and the tiers follow it), so every declared name is
        resolved through the theme actually on disk.
        """
        writers = {_themed(name) for name in CODE_WRITERS | BOUNDED_WRITERS}
        found = {path.stem for path in _agent_files()}
        self.assertEqual(
            writers - found, set(),
            "declared writers with no charter on disk — this test asserts "
            "nothing about them, so either the file or the declaration is wrong",
        )
        for path in _agent_files():
            with self.subTest(agent=path.stem):
                fields = self._frontmatter(path)
                if path.stem in writers:
                    self.assertFalse(
                        _may_not_edit(fields),
                        f"{path.stem}: declared a writer but its frontmatter bars Edit",
                    )
                    disallowed = _tool_tokens(fields.get("disallowedTools", ""))
                    self.assertNotIn(
                        "Write", disallowed, f"{path.stem} must retain Write access"
                    )
                else:
                    self.assertTrue(
                        _may_not_edit(fields),
                        f"{path.stem}: must not be able to Edit production code",
                    )

    def test_the_writer_set_is_pinned(self):
        """Growing the set of agents that may write code costs a deliberate edit.

        A red here does **not** mean "add the new name to the count". It means
        a seventh agent has been given write access to production code, and
        that is an architectural decision someone has to justify in the commit
        message — the whole point of this assertion is to force that
        conversation, which a self-updating registration set would silently
        skip.

        Six is not a magic number; it is the number of writers the crew was
        last deliberately agreed to have.
        """
        self.assertEqual(
            len(CODE_WRITERS | BOUNDED_WRITERS), 6,
            "adding a writer is an architectural decision — say why in the commit message",
        )

    def test_bounded_writers_declare_their_boundary(self):
        """Each bounded writer's charter body states its file boundary.

        This is a **doc-lint, not enforcement**. Agent frontmatter accepts tool
        *names* only — `tools`/`disallowedTools` have no path-scoped form, so
        `Edit(tests/**)` cannot be expressed here at all. Nothing stops a
        bounded writer from editing a production file; the only thing standing
        between it and one is the sentence this test pins.

        The body, not `description:`. `description:` is routing metadata the
        orchestrator reads to pick an agent; asserting there proves only that
        the blurb advertises a boundary, not that the agent is ever told about
        it. The spec puts enforcement in the prompt
        (docs/specs/2026-08-24-team-workflow-patterns.md:66).

        Deliberately out of scope: the `Write`-boundary agents. `planner`
        (read-only except `.sisyphus/`) and `reviewer` (writes only its report
        file) have real boundaries of the same kind, unchecked here because
        this invariant is Edit-centric. That gap is acknowledged, not hidden.
        """
        for name in BOUNDED_WRITERS:
            path = AGENTS_DIR / f"{_themed(name)}.md"
            with self.subTest(agent=path.stem):
                text = path.read_text(encoding="utf-8")
                body = FRONTMATTER_RE.sub("", text, count=1)
                self.assertIn(
                    BOUNDARY_PHRASE, body,
                    f"{path.stem}: boundary declared only in routing metadata",
                )

    def test_notebook_edit_alone_does_not_bar_editing(self):
        """Regression: `Edit` in `NotebookEdit` is True — tokens, not substrings."""
        self.assertFalse(_may_not_edit({"disallowedTools": "NotebookEdit"}))
        self.assertTrue(_may_not_edit({"disallowedTools": "Edit, NotebookEdit"}))
        self.assertTrue(_may_not_edit({"disallowedTools": "Write, Edit"}))

    def test_read_only_allowlist_containing_notebook_edit_is_accepted(self):
        """Regression: a read-only `tools` allowlist must not trip on `NotebookEdit`."""
        self.assertTrue(_may_not_edit({"tools": "Read, NotebookEdit"}))
        self.assertFalse(_may_not_edit({"tools": "Read, Edit"}))
        self.assertFalse(_may_not_edit({"tools": "Read, Write"}))


class TestOrchestratorWiring(unittest.TestCase):
    def _text(self):
        return (AGENTS_DIR / "orchestrator.md").read_text(encoding="utf-8")

    def test_orchestrator_dispatches_a_builder_tier_not_general_purpose(self):
        """Implementation work is dispatched to a builder tier, never elsewhere.

        The template used to name a single `builder`; it now offers the three
        cost tiers on one alternation line, so a literal grep for
        ``subagent_type: "builder"`` no longer sees it. Parsing the declared
        values instead of substring-matching keeps the original point — no
        implementation work goes to `general-purpose` — and additionally pins
        that a tier cannot silently vanish from the menu, which would make the
        planner's `simple`/`standard` classification undispatchable.
        """
        targets = _dispatch_targets(self._text())
        tiers = {_themed(name) for name in ("builder",) + TIERED_AGENTS}
        self.assertIn(
            tiers, targets,
            f"no dispatch block offers exactly the builder tiers {sorted(tiers)}",
        )
        off_theme = _off_theme("builder")
        for value in targets:
            self.assertNotIn(
                "general-purpose", value, "implementation work must not go to general-purpose"
            )
            self.assertNotIn(
                off_theme, value, f"{off_theme}: a half-applied theme left both names in the tree"
            )

    def test_orchestrator_names_builder_as_the_code_writer(self):
        text = self._text()
        self.assertIn(f"delegate to `{_themed('builder')}`", text)
        self.assertNotIn(f"delegate to `{_off_theme('builder')}`", text)

    def test_orchestrator_has_delivery_boundary_check(self):
        text = self._text()
        self.assertIn("### Delivery Boundary Check", text)
        self.assertIn("does the result need to re-enter this conversation?", text)

    def test_orchestrator_parallelism_is_bounded(self):
        text = self._text()
        self.assertIn("Maximize parallelism within a boundary", text)
        self.assertNotIn("2. **Maximize parallelism** — dispatch", text)

    def test_orchestrator_defers_verification_to_the_agent_contract(self):
        """The dispatch template must not license skipping verification.

        builder.md makes verification mandatory ("you may not report COMPLETE on
        work you have not executed"), so a Constraints line saying "run tests if
        they exist" would compete with the agent's own system prompt.
        """
        text = self._text()
        # The bulleted Constraints line; the orchestrator's own numbered
        # "run relevant tests" step is a different instruction and stays.
        self.assertNotIn("- Run relevant tests if they exist", text)
        self.assertIn("Verify per your contract", text)

    def test_orchestrator_receives_builder_findings(self):
        """The findings channel needs a receiver, not just a sender."""
        text = self._text()
        self.assertIn("<out-of-scope>", text)
        self.assertIn("<deviations>", text)

    def test_orchestrator_routes_blocked_to_the_user(self):
        """BLOCKED means a decision is needed — not another implementer."""
        text = self._text()
        self.assertIn("`BLOCKED`", text)
        self.assertIn("### Blocked", text)


if __name__ == "__main__":
    unittest.main()
