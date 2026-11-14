# tests/test_tier_hook.py
"""The project hook that keeps the builder tier charters generated.

`scripts/tier_hook.py` blocks a direct edit to a generated charter (PreToolUse)
and regenerates the charters after a template edit (PostToolUse). Two things
matter beyond the happy paths: it must never break an unrelated edit, and the
`.claude/settings.json` that wires it must name a script that exists.

The sync script copies `scripts/` and `tests/` into instances but not `.claude/`,
so the settings test skips where the file is absent instead of failing there.
All behaviour tests run against a temp copy of `agents/`, never the real one.
"""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import render_tiers  # noqa: E402
import tier_hook  # noqa: E402

SCRIPT = ROOT / "scripts" / "tier_hook.py"
SETTINGS = ROOT / ".claude" / "settings.json"


def _payload(event, path, tool="Edit", **extra):
    return json.dumps({"hook_event_name": event, "tool_name": tool,
                       "tool_input": {"file_path": str(path)}, **extra})


class TierHookTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.agents = Path(tmp.name) / "agents"
        shutil.copytree(ROOT / "agents", self.agents)
        self.template = self.agents / "_src" / "tiers.md.tmpl"
        self.charters = list(render_tiers.rendered_charters(self.agents, self.template))

    def run_hook(self, raw):
        return tier_hook.process(raw, self.agents)

    def test_charter_edit_is_blocked_and_names_the_template(self):
        for tool in ("Edit", "Write", "MultiEdit"):
            for charter in self.charters:
                code, out, err = self.run_hook(_payload("PreToolUse", charter, tool))
                self.assertEqual(code, 2, f"{tool} {charter.name}")
                self.assertIn("tiers.md.tmpl", err)
                self.assertIn("generated", err)
                self.assertEqual(out, "")

    def test_charter_block_ignores_case_and_relative_paths(self):
        charter = self.charters[0]
        self.assertEqual(self.run_hook(_payload(
            "PreToolUse", Path("agents") / charter.name, cwd=str(self.agents.parent)))[0], 2)
        if sys.platform == "win32":
            self.assertEqual(self.run_hook(
                _payload("PreToolUse", str(charter).upper()))[0], 2)

    def test_charter_block_survives_a_broken_template(self):
        self.template.write_text("<!-- tier: nope -->\n", encoding="utf-8", newline="")
        code, _, err = self.run_hook(_payload("PreToolUse", self.charters[0]))
        self.assertEqual(code, 2)
        self.assertIn("tiers.md.tmpl", err)

    def test_template_edit_before_the_write_is_allowed(self):
        self.assertEqual(self.run_hook(_payload("PreToolUse", self.template)), (0, "", ""))

    def test_template_edit_regenerates_a_stale_charter(self):
        self.template.write_text(
            self.template.read_text(encoding="utf-8", newline="") + "\nhook marker line\n",
            encoding="utf-8", newline="")
        self.assertTrue(render_tiers.stale_charters(self.agents, self.template))
        code, out, err = self.run_hook(_payload("PostToolUse", self.template))
        self.assertEqual((code, err), (0, ""))
        for charter in self.charters:
            self.assertIn(charter.name, out)
            self.assertIn("hook marker line",
                          charter.read_text(encoding="utf-8", newline=""))
        self.assertEqual(render_tiers.stale_charters(self.agents, self.template), [])

    def test_template_edit_with_nothing_to_rewrite_is_quiet(self):
        self.assertEqual(self.run_hook(_payload("PostToolUse", self.template)), (0, "", ""))

    def test_malformed_template_exits_2_with_the_error(self):
        self.template.write_text(
            self.template.read_text(encoding="utf-8", newline="")
            + "\n<!-- tier: builder -->\nno closer\n", encoding="utf-8", newline="")
        before = {c: c.read_bytes() for c in self.charters}
        code, out, err = self.run_hook(_payload("PostToolUse", self.template))
        self.assertEqual(code, 2)
        self.assertIn("missing `<!-- end tier -->`", err)
        self.assertEqual(out, "")
        self.assertEqual({c: c.read_bytes() for c in self.charters}, before)

    def test_unrelated_inputs_exit_0_silently(self):
        other = self.agents / "README.md"
        cases = [
            _payload("PreToolUse", other),
            _payload("PostToolUse", other),
            _payload("PostToolUse", self.charters[0]),       # charters trigger nothing after
            _payload("PreToolUse", self.charters[0], tool="Read"),
            _payload("PostToolUse", self.template, tool="Bash"),
            _payload("SessionStart", self.template),
            json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Edit",
                        "tool_input": {}}),
            json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Edit",
                        "tool_input": {"file_path": 7}}),
            json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Edit",
                        "tool_input": "nope"}),
            json.dumps([1, 2]),
            json.dumps(None),
        ]
        for raw in cases:
            self.assertEqual(self.run_hook(raw), (0, "", ""), raw)

    def test_garbage_stdin_exits_0_silently(self):
        for raw in ("", "not json", "{", "\x00\xff", "{\"tool_input\": "):
            self.assertEqual(self.run_hook(raw), (0, "", ""), repr(raw))

    def test_script_end_to_end_through_stdin(self):
        def run(raw):
            return subprocess.run(
                [sys.executable, str(SCRIPT), "--agents-dir", str(self.agents)],
                input=raw.encode("utf-8"), capture_output=True, timeout=60)

        blocked = run(_payload("PreToolUse", self.charters[0]))
        self.assertEqual(blocked.returncode, 2)
        self.assertIn(b"tiers.md.tmpl", blocked.stderr)
        self.assertEqual(run("garbage").returncode, 0)
        self.template.write_text(
            self.template.read_text(encoding="utf-8", newline="") + "\nend to end\n",
            encoding="utf-8", newline="")
        regenerated = run(_payload("PostToolUse", self.template))
        self.assertEqual(regenerated.returncode, 0)
        self.assertIn(self.charters[0].name.encode(), regenerated.stdout)
        self.assertEqual(render_tiers.stale_charters(self.agents, self.template), [])


class TierHookSettingsTest(unittest.TestCase):
    @unittest.skipUnless(SETTINGS.is_file(),
                         ".claude/settings.json is repo-local; the sync does not copy it")
    def test_settings_register_both_events_for_the_script(self):
        hooks = json.loads(SETTINGS.read_text(encoding="utf-8"))["hooks"]
        self.assertEqual(set(hooks), {"PreToolUse", "PostToolUse"})
        for event, groups in hooks.items():
            self.assertEqual(len(groups), 1, event)
            self.assertEqual(groups[0]["matcher"], "Edit|Write|MultiEdit", event)
            [hook] = groups[0]["hooks"]
            self.assertEqual(hook["type"], "command")
            self.assertEqual(
                hook["command"], 'python "$CLAUDE_PROJECT_DIR/scripts/tier_hook.py"')
        self.assertTrue(SCRIPT.is_file())


if __name__ == "__main__":
    unittest.main()
