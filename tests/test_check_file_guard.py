import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from hooks import check_file_guard as guard  # noqa: E402

import _crew_common  # noqa: E402  (tests run with PYTHONPATH=scripts)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "check_file_guard"


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _event(tool: str, tool_input: dict, *, agent: str | None = "qa-guard",
           cwd: str | None = "/work/proj") -> dict:
    ev: dict = {"hook_event_name": "PreToolUse", "tool_name": tool,
                "tool_input": tool_input}
    if agent is not None:
        ev["agent_type"] = agent
    if cwd is not None:
        ev["cwd"] = cwd
    return ev


def _bash(command: str, **kw) -> dict:
    return _event("Bash", {"command": command}, **kw)


def _ps(command: str, **kw) -> dict:
    return _event("PowerShell", {"command": command}, **kw)


class GuardedAgentsTest(unittest.TestCase):
    def test_guarded_agents_are_both_theme_names_of_qa_guard(self):
        # A PAIRS rename must fail here rather than silently disarm the guard.
        pair = next(p for p in _crew_common.PAIRS if p[0] == "qa-guard")
        self.assertEqual(guard.GUARDED_AGENTS, frozenset(pair))


class AgentScopeTest(unittest.TestCase):
    def test_other_agents_and_main_session_are_not_guarded(self):
        self.assertIsNone(guard.evaluate(_fixture("builder_write_ruff_toml.json")))
        self.assertIsNone(guard.evaluate(_fixture("main_session_write_ruff_toml.json")))

    def test_odd_agent_type_values_do_not_crash(self):
        for agent in (["qa-guard"], {"a": 1}, 7, None, ""):
            ev = _event("Write", {"file_path": "ruff.toml", "content": "x"})
            ev["agent_type"] = agent
            self.assertIsNone(guard.evaluate(ev))

    def test_unrelated_tools_are_ignored(self):
        self.assertIsNone(guard.evaluate(_event("Read", {"file_path": "ruff.toml"})))


class WholeFileTest(unittest.TestCase):
    def test_both_themes_denied_on_write_ruff_toml(self):
        for agent in ("qa-guard", "cato"):
            with self.subTest(agent=agent):
                reason = guard.evaluate(_event(
                    "Write", {"file_path": "/work/proj/ruff.toml", "content": "x"},
                    agent=agent))
                self.assertIn("ruff.toml", reason)
                self.assertIn("return BLOCKED", reason)
                self.assertIn("may not edit check definitions", reason)

    def test_new_conftest_denied(self):
        self.assertIsNotNone(guard.evaluate(_fixture("cato_write_new_conftest.json")))

    def test_windows_backslash_workflow_path_denied(self):
        reason = guard.evaluate(_fixture("qa_guard_write_workflow_windows.json"))
        self.assertIsNotNone(reason)
        self.assertIn("workflows", reason)

    def test_relative_and_case_variants_denied(self):
        for path in ("Ruff.TOML", ".github\\workflows\\a.yml", "sub/Makefile",
                     "GNUmakefile", ".pre-commit-config.yaml", "tox.ini"):
            with self.subTest(path=path):
                self.assertIsNotNone(guard.evaluate(
                    _event("Edit", {"file_path": path, "old_string": "a",
                                    "new_string": "b"})))

    def test_multiedit_and_notebookedit_on_protected_path_denied(self):
        self.assertIsNotNone(guard.evaluate(_event(
            "MultiEdit", {"file_path": "setup.cfg", "edits": []})))
        self.assertIsNotNone(guard.evaluate(_event(
            "NotebookEdit", {"notebook_path": "conftest.py"})))

    def test_ordinary_source_edit_allowed(self):
        self.assertIsNone(guard.evaluate(_fixture("qa_guard_edit_src.json")))

    def test_lookalike_names_allowed(self):
        for path in ("src/ruff_toml.py", "docs/github/workflows.md", "myconftest.py"):
            with self.subTest(path=path):
                self.assertIsNone(guard.evaluate(
                    _event("Write", {"file_path": path, "content": "x"})))


class SectionFileTest(unittest.TestCase):
    PYPROJECT = (
        '[project]\nname = "demo"\nversion = "1"\n\n'
        '[tool.ruff.lint]\nselect = ["E"]\n'
    )
    PACKAGE = json.dumps({
        "name": "demo", "scripts": {"lint": "eslint ."},
        "dependencies": {"left-pad": "1"},
    }, indent=2) + "\n"

    def _tmp(self, name: str, text: str) -> tuple[str, str]:
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        (Path(d.name) / name).write_text(text, encoding="utf-8")
        return d.name, str(Path(d.name) / name)

    def test_pyproject_edit_outside_tool_table_allowed(self):
        cwd, path = self._tmp("pyproject.toml", self.PYPROJECT)
        self.assertIsNone(guard.evaluate(_event(
            "Edit", {"file_path": path, "old_string": 'version = "1"',
                     "new_string": 'version = "2"'}, cwd=cwd)))

    def test_pyproject_edit_inside_tool_table_denied(self):
        cwd, path = self._tmp("pyproject.toml", self.PYPROJECT)
        reason = guard.evaluate(_event(
            "Edit", {"file_path": path, "old_string": 'select = ["E"]',
                     "new_string": 'select = []'}, cwd=cwd))
        self.assertIn("`tool` section", reason)

    def test_pyproject_multiedit_touching_tool_table_denied(self):
        cwd, path = self._tmp("pyproject.toml", self.PYPROJECT)
        self.assertIsNotNone(guard.evaluate(_event(
            "MultiEdit", {"file_path": path, "edits": [
                {"old_string": 'name = "demo"', "new_string": 'name = "x"'},
                {"old_string": '"E"', "new_string": '"F"'}]}, cwd=cwd)))

    def test_pyproject_write_changing_tool_table_denied(self):
        cwd, path = self._tmp("pyproject.toml", self.PYPROJECT)
        self.assertIsNotNone(guard.evaluate(_event(
            "Write", {"file_path": path, "content": '[project]\nname = "demo"\n'},
            cwd=cwd)))

    def test_pyproject_write_keeping_tool_table_allowed(self):
        cwd, path = self._tmp("pyproject.toml", self.PYPROJECT)
        self.assertIsNone(guard.evaluate(_event(
            "Write", {"file_path": path,
                      "content": self.PYPROJECT.replace('"demo"', '"other"')},
            cwd=cwd)))

    def test_pyproject_write_producing_invalid_toml_denied(self):
        cwd, path = self._tmp("pyproject.toml", self.PYPROJECT)
        reason = guard.evaluate(_event(
            "Write", {"file_path": path, "content": "[project\nname ="}, cwd=cwd))
        self.assertIn("would not parse", reason)

    def test_new_pyproject_with_tool_table_denied_without_one_allowed(self):
        with tempfile.TemporaryDirectory() as d:
            p = str(Path(d) / "pyproject.toml")
            self.assertIsNotNone(guard.evaluate(_event(
                "Write", {"file_path": p, "content": "[tool.ruff]\nx = 1\n"}, cwd=d)))
            self.assertIsNone(guard.evaluate(_event(
                "Write", {"file_path": p, "content": "[project]\nname = 'a'\n"}, cwd=d)))

    def test_edit_that_will_not_apply_is_left_to_claude_code(self):
        cwd, path = self._tmp("pyproject.toml", self.PYPROJECT)
        self.assertIsNone(guard.evaluate(_event(
            "Edit", {"file_path": path, "old_string": "no such text",
                     "new_string": "[tool.x]"}, cwd=cwd)))

    def test_replace_all_is_simulated(self):
        cwd, path = self._tmp("pyproject.toml", 'a = 1\n[tool.x]\nv = "z"\nw = "z"\n')
        self.assertIsNotNone(guard.evaluate(_event(
            "Edit", {"file_path": path, "old_string": '"z"', "new_string": '"y"',
                     "replace_all": True}, cwd=cwd)))
        # Without replace_all only the first occurrence changes; it is in [tool.x].
        self.assertIsNotNone(guard.evaluate(_event(
            "Edit", {"file_path": path, "old_string": '"z"', "new_string": '"y"'},
            cwd=cwd)))

    def test_unparsable_current_file_counts_as_absent_section(self):
        cwd, path = self._tmp("pyproject.toml", "[broken")
        self.assertIsNone(guard.evaluate(_event(
            "Write", {"file_path": path, "content": "[project]\nname = 'a'\n"},
            cwd=cwd)))

    def test_package_json_scripts_change_denied(self):
        cwd, path = self._tmp("package.json", self.PACKAGE)
        self.assertIsNotNone(guard.evaluate(_event(
            "Edit", {"file_path": path, "old_string": '"eslint ."',
                     "new_string": '"true"'}, cwd=cwd)))

    def test_package_json_dependencies_change_allowed(self):
        cwd, path = self._tmp("package.json", self.PACKAGE)
        self.assertIsNone(guard.evaluate(_event(
            "Edit", {"file_path": path, "old_string": '"left-pad": "1"',
                     "new_string": '"left-pad": "2"'}, cwd=cwd)))

    def test_package_json_invalid_result_denied(self):
        cwd, path = self._tmp("package.json", self.PACKAGE)
        self.assertIsNotNone(guard.evaluate(_event(
            "Write", {"file_path": path, "content": "{nope"}, cwd=cwd)))


class BashTest(unittest.TestCase):
    def assertDenied(self, command, *, tool=_bash):
        self.assertIsNotNone(guard.evaluate(tool(command)), command)

    def assertAllowed(self, command, *, tool=_bash):
        self.assertIsNone(guard.evaluate(tool(command)), command)

    def test_commands_that_do_not_touch_protected_files_allowed(self):
        for c in ("ruff check .", "python -m pytest -q", "git status --porcelain",
                  "echo hello > out.txt", "cat a.txt | tee b.txt"):
            with self.subTest(c=c):
                self.assertAllowed(c)

    def test_reads_of_protected_files_allowed(self):
        for c in ("cat pyproject.toml", "git diff -- ruff.toml",
                  "grep select pyproject.toml && echo ok", "head -20 .flake8",
                  "ls .github/workflows", "find . -name tox.ini",
                  "cat ruff.toml 2>&1 | grep line"):
            with self.subTest(c=c):
                self.assertAllowed(c)

    def test_write_forms_denied(self):
        for c in ("sed -i 's/a/b/' ruff.toml", "sed -i.bak 's/a/b/' ruff.toml",
                  "perl -pi -e 's/a/b/' .flake8", "echo x >> .flake8",
                  "printf x > mypy.ini", "printf x >mypy.ini", "echo x &> tox.ini",
                  "cat a 2>/dev/null > setup.cfg", "echo x | tee -a .coveragerc",
                  "cp /tmp/x .pre-commit-config.yaml", "mv a.ini ruff.toml",
                  "rm conftest.py", "touch pytest.ini", "truncate -s 0 .pylintrc",
                  "chmod +x .github/workflows/ci.yml",
                  "dd if=/dev/zero of=Makefile", "ls; rm -rf .github/workflows",
                  "cat x > .github\\workflows\\ci.yml"):
            with self.subTest(c=c):
                self.assertDenied(c)

    def test_cat_with_redirect_to_protected_file_denied(self):
        self.assertDenied("cat template > ruff.toml")

    def test_command_substitution_hides_no_write_in_a_read(self):
        self.assertDenied('echo "$(rm ruff.toml)"')
        self.assertDenied("cat `rm ruff.toml`")

    def test_inline_interpreters_mentioning_protected_file_denied(self):
        for c in ("python -c \"open('ruff.toml','w')\"",
                  "node -e \"fs.writeFileSync('package.json','')\"",
                  "bash -c 'echo x > ruff.toml'", "perl -e 'unlink q(tox.ini)'"):
            with self.subTest(c=c):
                self.assertDenied(c)

    def test_mention_fallback_reason_names_file_and_remedy(self):
        reason = guard.evaluate(_bash("make -f Makefile lint"))
        self.assertIn("cannot verify this command does not modify", reason)
        self.assertIn("makefile", reason)
        self.assertIn("Read tool", reason)
        self.assertIn("return BLOCKED", reason)

    def test_unbalanced_quotes_mentioning_protected_file_denied(self):
        self.assertDenied("echo 'oops ruff.toml")
        self.assertAllowed("echo 'oops")

    def test_git_read_only_allowlist_is_narrow(self):
        self.assertDenied("git checkout -- ruff.toml")
        self.assertDenied("git diff --output=ruff.toml")
        self.assertDenied("find . -name tox.ini -delete")

    def test_known_bypass_variable_indirection_is_not_caught(self):
        # Pinned limit: this is a tripwire, not a sandbox. The orchestrator's
        # `git status --porcelain` audit is the backstop. If this test starts
        # failing because the guard got smarter, flip it to assertDenied and
        # update the "Known bypasses" list in the module docstring.
        self.assertAllowed("f=ruff.toml; echo x > $f")

    def test_known_bypass_glob_is_not_caught(self):
        self.assertAllowed("echo x > ruff.t*ml")


class PowerShellTest(unittest.TestCase):
    def test_reads_allowed(self):
        for c in ("Get-Content ruff.toml", "gc pyproject.toml | Select-String tool",
                  "git diff -- ruff.toml", "Get-ChildItem .github\\workflows"):
            with self.subTest(c=c):
                self.assertIsNone(guard.evaluate(_ps(c)), c)

    def test_writes_denied(self):
        for c in ("Set-Content ruff.toml x", "Get-Content a | Set-Content ruff.toml",
                  "Get-Content a > ruff.toml", "Remove-Item .github\\workflows\\ci.yml",
                  "'x' | Out-File mypy.ini", "ni conftest.py; ls",
                  "Get-Content $(Set-Content ruff.toml x)"):
            with self.subTest(c=c):
                self.assertIsNotNone(guard.evaluate(_ps(c)), c)

    def test_unrelated_commands_allowed(self):
        self.assertIsNone(guard.evaluate(_ps("Set-Content notes.txt x")))


class MainTest(unittest.TestCase):
    def _run(self, stdin_text: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(sys, "stdin", io.StringIO(stdin_text)), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = guard.main()
        return rc, out.getvalue(), err.getvalue()

    def test_deny_prints_exact_hook_json_and_exits_zero(self):
        raw = (FIXTURES / "qa_guard_bash_sed_in_place.json").read_text(encoding="utf-8")
        rc, out, _ = self._run(raw)
        self.assertEqual(rc, 0)
        data = json.loads(out)
        self.assertEqual(list(data), ["hookSpecificOutput"])
        hso = data["hookSpecificOutput"]
        self.assertEqual(hso["hookEventName"], "PreToolUse")
        self.assertEqual(hso["permissionDecision"], "deny")
        self.assertIn(".flake8", hso["permissionDecisionReason"])
        self.assertEqual(out.count("\n"), 1)  # exactly one JSON object

    def test_windows_fixture_denies_through_main(self):
        raw = (FIXTURES / "qa_guard_write_workflow_windows.json").read_text(encoding="utf-8")
        rc, out, _ = self._run(raw)
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out)["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_allow_prints_nothing(self):
        raw = (FIXTURES / "builder_write_ruff_toml.json").read_text(encoding="utf-8")
        self.assertEqual(self._run(raw), (0, "", ""))

    def test_malformed_stdin_fails_closed(self):
        for text in ("{not json", "", "[1, 2]", "null"):
            with self.subTest(text=text):
                rc, out, err = self._run(text)
                self.assertEqual(rc, 2)
                self.assertEqual(out, "")
                self.assertIn("failing closed", err)

    def test_internal_error_in_evaluate_fails_closed(self):
        raw = (FIXTURES / "builder_write_ruff_toml.json").read_text(encoding="utf-8")
        with mock.patch.object(guard, "evaluate", side_effect=RuntimeError("boom")):
            rc, out, err = self._run(raw)
        self.assertEqual((rc, out), (2, ""))
        self.assertIn("boom", err)


if __name__ == "__main__":
    unittest.main()
