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

AGENTS_DIR = ROOT / "agents"

# Models the crew is allowed to name. Anything else is a typo or an
# unreviewed bump.
ALLOWED_MODELS = {
    "claude-opus-5",
    "claude-opus-4-8",
    "claude-sonnet-5",
    "claude-haiku-4-5",
}

# Agents whose names are the same under every theme. The remaining five are
# renamed by `scripts/apply_theme.py` (planner->plato, advisor->aristotle,
# reviewer->pyrrho, critic->socrates, builder->archimedes), so the roster is
# derived from the theme actually on disk rather than hardcoded.
THEME_INVARIANT_ROSTER = {
    "explore",
    "librarian",
    "orchestrator",
    "scout",
    "validator",
    "vision",
}

FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _agent_files(agents_dir=AGENTS_DIR):
    return sorted(agents_dir.glob("*.md"))


def _expected_roster(theme):
    """The agent filenames expected under `theme` ('functional'/'philosophers')."""
    themed = {p if theme == "philosophers" else f for f, p in apply_theme.PAIRS}
    return THEME_INVARIANT_ROSTER | themed


def _tool_tokens(value):
    """Split a `tools:`/`disallowedTools:` frontmatter value into exact tokens.

    Substring matching is not safe here: ``"Edit" in "NotebookEdit"`` is True,
    so a substring check would read `disallowedTools: NotebookEdit` as a ban on
    Edit — the exact drift these tests exist to catch.
    """
    return {t.strip() for t in value.split(",") if t.strip()}


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
        self.assertEqual(found, _expected_roster(theme))

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
            self.assertEqual(found, _expected_roster("philosophers"))


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
    def test_builder_is_the_only_editor(self):
        """builder is the only agent permitted to edit production code.

        Note this is about Edit, not Write. orchestrator, planner and reviewer
        deliberately retain Write so they can produce plans and audit reports —
        but none of them may Edit. vision restricts itself with a read-only
        ``tools`` allowlist instead of ``disallowedTools``.
        """
        for path in _agent_files():
            with self.subTest(agent=path.stem):
                fields = self._frontmatter(path)
                if path.stem == "builder":
                    disallowed = _tool_tokens(fields.get("disallowedTools", ""))
                    self.assertNotIn("Edit", disallowed, "builder must retain Edit access")
                    self.assertNotIn("Write", disallowed, "builder must retain Write access")
                else:
                    self.assertTrue(
                        _may_not_edit(fields),
                        f"{path.stem}: must not be able to Edit production code",
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

    def test_orchestrator_dispatches_builder_not_general_purpose(self):
        text = self._text()
        self.assertIn('subagent_type: "builder"', text)
        self.assertNotIn('subagent_type: "general-purpose"', text)

    def test_orchestrator_names_builder_as_the_code_writer(self):
        self.assertIn("delegate to `builder`", self._text())

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
