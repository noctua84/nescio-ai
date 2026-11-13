import contextlib
import io
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

from hooks import planner_spawn_guard as guard  # noqa: E402

import _crew_common  # noqa: E402  (tests run with PYTHONPATH=scripts)

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "planner_spawn_guard"
SCRIPT = ROOT / "hooks" / "planner_spawn_guard.py"


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _event(tool_input: object, *, tool: str = "Agent",
           agent: object = "planner") -> dict:
    ev: dict = {"hook_event_name": "PreToolUse", "tool_name": tool,
                "tool_input": tool_input, "cwd": "/work/proj"}
    if agent is not None:
        ev["agent_type"] = agent
    return ev


def _spawn(subagent_type: object, **kw) -> dict:
    return _event({"description": "d", "prompt": "p",
                   "subagent_type": subagent_type}, **kw)


class GuardedAgentsTest(unittest.TestCase):
    def test_guarded_agents_are_both_theme_names_of_planner(self):
        # A PAIRS rename must fail here rather than silently disarm the guard.
        pair = next(p for p in _crew_common.PAIRS if p[0] == "planner")
        self.assertEqual(guard.GUARDED_AGENTS, frozenset(pair))

    def test_allowed_subagents_are_real_agents(self):
        # An allowlist entry with no agent file behind it would be a typo that
        # denies every legitimate spawn of that agent.
        self.assertEqual(guard.ALLOWED_SUBAGENTS, frozenset({"explore", "librarian"}))
        for name in guard.ALLOWED_SUBAGENTS:
            with self.subTest(name=name):
                self.assertTrue((ROOT / "agents" / f"{name}.md").is_file(), name)

    def test_allowed_subagents_are_not_themed(self):
        # Both names must be identical under every theme, or the themed install
        # would spawn a name the guard does not recognise.
        themed = {name for pair in _crew_common.PAIRS for name in pair
                  if pair[0] != pair[1]}
        self.assertFalse(guard.ALLOWED_SUBAGENTS & themed)


class AgentScopeTest(unittest.TestCase):
    def test_other_agents_and_main_session_are_not_guarded(self):
        self.assertIsNone(guard.evaluate(_fixture("orchestrator_spawn_builder.json")))
        self.assertIsNone(guard.evaluate(_fixture("main_session_spawn_builder.json")))

    def test_odd_agent_type_values_do_not_crash(self):
        for agent in (["planner"], {"a": 1}, 7, None, "", "Planner", " planner"):
            with self.subTest(agent=agent):
                ev = _spawn("builder")
                ev["agent_type"] = agent
                self.assertIsNone(guard.evaluate(ev))

    def test_unrelated_tools_are_ignored(self):
        for tool in ("Read", "Bash", "Write", "agent"):
            with self.subTest(tool=tool):
                self.assertIsNone(guard.evaluate(_spawn("builder", tool=tool)))

    def test_missing_tool_name_is_ignored(self):
        ev = _spawn("builder")
        del ev["tool_name"]
        self.assertIsNone(guard.evaluate(ev))


class SpawnDecisionTest(unittest.TestCase):
    def test_both_themes_allowed_to_spawn_explore_and_librarian(self):
        for agent in ("planner", "plato"):
            for sub in ("explore", "librarian"):
                with self.subTest(agent=agent, sub=sub):
                    self.assertIsNone(guard.evaluate(_spawn(sub, agent=agent)))

    def test_plato_spawning_explore_fixture_allowed(self):
        self.assertIsNone(guard.evaluate(_fixture("plato_spawn_explore.json")))

    def test_surrounding_whitespace_is_stripped(self):
        for sub in (" explore", "librarian\n", "\texplore  "):
            with self.subTest(sub=sub):
                self.assertIsNone(guard.evaluate(_spawn(sub)))

    def test_both_themes_denied_spawning_other_agents(self):
        for agent in ("planner", "plato"):
            for sub in ("builder", "reviewer", "general-purpose", "orchestrator",
                        "planner", "Explore", "LIBRARIAN", "explore-v2"):
                with self.subTest(agent=agent, sub=sub):
                    reason = guard.evaluate(_spawn(sub, agent=agent))
                    self.assertIsNotNone(reason)
                    self.assertIn(repr(sub), reason)

    def test_builder_fixture_denied_and_reason_names_rejected_type(self):
        reason = guard.evaluate(_fixture("planner_spawn_builder.json"))
        self.assertIsNotNone(reason)
        self.assertIn("builder", reason)
        self.assertIn("explore", reason)
        self.assertIn("librarian", reason)

    def test_missing_subagent_type_fixture_denied(self):
        reason = guard.evaluate(_fixture("planner_spawn_no_subagent_type.json"))
        self.assertIsNotNone(reason)
        self.assertIn("general-purpose", reason)

    def test_empty_blank_and_non_string_subagent_type_denied(self):
        for sub in ("", "   ", "\n", None, 7, ["explore"], {"name": "explore"}, True):
            with self.subTest(sub=sub):
                reason = guard.evaluate(_spawn(sub))
                self.assertIsNotNone(reason)
                self.assertIn("general-purpose", reason)

    def test_non_dict_tool_input_denied(self):
        for tool_input in (None, "explore", ["explore"], 3):
            with self.subTest(tool_input=tool_input):
                self.assertIsNotNone(guard.evaluate(_event(tool_input)))

    def test_missing_tool_input_denied(self):
        ev = _spawn("explore")
        del ev["tool_input"]
        self.assertIsNotNone(guard.evaluate(ev))


class MainTest(unittest.TestCase):
    def _run(self, stdin_text: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(sys, "stdin", io.StringIO(stdin_text)), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = guard.main()
        return rc, out.getvalue(), err.getvalue()

    def test_deny_prints_exact_hook_json_and_exits_zero(self):
        raw = (FIXTURES / "planner_spawn_builder.json").read_text(encoding="utf-8")
        rc, out, _ = self._run(raw)
        self.assertEqual(rc, 0)
        data = json.loads(out)
        self.assertEqual(list(data), ["hookSpecificOutput"])
        hso = data["hookSpecificOutput"]
        self.assertEqual(set(hso), {"hookEventName", "permissionDecision",
                                    "permissionDecisionReason"})
        self.assertEqual(hso["hookEventName"], "PreToolUse")
        self.assertEqual(hso["permissionDecision"], "deny")
        self.assertIn("builder", hso["permissionDecisionReason"])
        self.assertEqual(out.count("\n"), 1)  # exactly one JSON object

    def test_missing_subagent_type_denies_through_main(self):
        raw = (FIXTURES / "planner_spawn_no_subagent_type.json").read_text(encoding="utf-8")
        rc, out, _ = self._run(raw)
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out)["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_allow_prints_nothing(self):
        for name in ("plato_spawn_explore.json", "orchestrator_spawn_builder.json",
                     "main_session_spawn_builder.json"):
            with self.subTest(name=name):
                raw = (FIXTURES / name).read_text(encoding="utf-8")
                self.assertEqual(self._run(raw), (0, "", ""))

    def test_malformed_stdin_fails_closed(self):
        for text in ("{not json", "", "[1, 2]", "null", '"planner"', "42"):
            with self.subTest(text=text):
                rc, out, err = self._run(text)
                self.assertEqual(rc, 2)
                self.assertEqual(out, "")
                self.assertIn("failing closed", err)

    def test_internal_error_in_evaluate_fails_closed(self):
        raw = (FIXTURES / "orchestrator_spawn_builder.json").read_text(encoding="utf-8")
        with mock.patch.object(guard, "evaluate", side_effect=RuntimeError("boom")):
            rc, out, err = self._run(raw)
        self.assertEqual((rc, out), (2, ""))
        self.assertIn("boom", err)


class ScriptTest(unittest.TestCase):
    """Run the hook as Claude Code does: a separate process fed JSON on stdin."""

    def _run(self, stdin_text: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(SCRIPT)], input=stdin_text.encode("utf-8"),
            capture_output=True, timeout=30, check=False)

    def test_deny_through_subprocess(self):
        raw = (FIXTURES / "planner_spawn_builder.json").read_text(encoding="utf-8")
        proc = self._run(raw)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        hso = json.loads(proc.stdout.decode("utf-8"))["hookSpecificOutput"]
        self.assertEqual(hso["permissionDecision"], "deny")
        self.assertIn("builder", hso["permissionDecisionReason"])

    def test_allow_through_subprocess(self):
        raw = (FIXTURES / "plato_spawn_explore.json").read_text(encoding="utf-8")
        proc = self._run(raw)
        self.assertEqual((proc.returncode, proc.stdout), (0, b""), proc.stderr)

    def test_malformed_stdin_through_subprocess_exits_2(self):
        proc = self._run("{not json")
        self.assertEqual((proc.returncode, proc.stdout), (2, b""))


if __name__ == "__main__":
    unittest.main()
