import contextlib
import importlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent


def _pin_not_a_venv(case: unittest.TestCase) -> None:
    """Make the wiring tests venv-agnostic.

    The wiring tests assert ``command == sys.executable``. install.py now refuses
    to wire a virtualenv interpreter (it resolves the base one instead), so a
    developer running the suite from a venv would see every such assertion
    fail. Pinning ``sys.base_prefix == sys.prefix`` tells the resolver "not a
    venv" regardless of which interpreter is running the tests.
    """
    p = mock.patch.object(sys, "base_prefix", sys.prefix)
    p.start()
    case.addCleanup(p.stop)


class WireStopHookTest(unittest.TestCase):
    """install.wire_stop_hook injects the global Stop hook into a config dir's
    settings.json with install-time resolved absolute paths, idempotently,
    honoring --dry-run, and never clobbering unrelated keys."""

    def setUp(self):
        sys.path.insert(0, str(ROOT))
        self.install = importlib.import_module("install")
        _pin_not_a_venv(self)  # assertions below compare against sys.executable

    def _local(self, config_dir: Path) -> Path:
        return config_dir / "settings.json"

    def _script(self, config_dir: Path) -> str:
        return str(config_dir / "hooks" / "record_stop.py")

    def _seed_script(self, config_dir: Path) -> None:
        """Create hooks/record_stop.py so wire_stop_hook's existence guard passes.

        Wiring is a no-op (outside --dry-run) when the resolved script is absent,
        so any test that expects a real write must first materialize it.
        """
        hooks = config_dir / "hooks"
        hooks.mkdir(parents=True, exist_ok=True)
        (hooks / "record_stop.py").write_text("# stub\n", encoding="utf-8")

    def test_fresh_injection_creates_file_and_entry(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d)
            self._seed_script(cfg)
            self.install.wire_stop_hook(cfg, dry_run=False)

            local = self._local(cfg)
            self.assertTrue(local.is_file())
            data = json.loads(local.read_text(encoding="utf-8"))

            stop = data["hooks"]["Stop"]
            self.assertEqual(len(stop), 1)
            entry = stop[0]["hooks"][0]
            self.assertEqual(entry["type"], "command")
            self.assertEqual(entry["command"], sys.executable)
            self.assertEqual(entry["args"][0], self._script(cfg))
            self.assertIs(entry["async"], True)

    def test_trailing_newline_and_indent(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d)
            self._seed_script(cfg)
            self.install.wire_stop_hook(cfg, dry_run=False)
            text = self._local(cfg).read_text(encoding="utf-8")
            self.assertTrue(text.endswith("\n"))
            # indent=2 pretty-printed (not a single compact line)
            self.assertIn("\n  ", text)

    def test_idempotent_second_run_does_not_duplicate(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d)
            self._seed_script(cfg)
            self.install.wire_stop_hook(cfg, dry_run=False)
            first = self._local(cfg).read_text(encoding="utf-8")
            self.install.wire_stop_hook(cfg, dry_run=False)
            second = self._local(cfg).read_text(encoding="utf-8")

            self.assertEqual(first, second)
            data = json.loads(second)
            self.assertEqual(len(data["hooks"]["Stop"]), 1)

    def test_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d)
            # No script on disk: --dry-run must still preview (guard is bypassed)
            # yet write nothing.
            self.install.wire_stop_hook(cfg, dry_run=True)
            self.assertFalse(self._local(cfg).exists())

    def test_dry_run_leaves_existing_file_untouched(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d)
            local = self._local(cfg)
            original = json.dumps({"outputStyle": "Explanatory"}, indent=2) + "\n"
            local.write_text(original, encoding="utf-8")

            self.install.wire_stop_hook(cfg, dry_run=True)
            self.assertEqual(local.read_text(encoding="utf-8"), original)

    def test_preserves_existing_unrelated_keys(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d)
            self._seed_script(cfg)
            local = self._local(cfg)
            local.write_text(
                json.dumps({
                    "outputStyle": "Explanatory",
                    "permissions": {"allow": ["Bash(git status:*)"]},
                }, indent=2) + "\n",
                encoding="utf-8",
            )

            self.install.wire_stop_hook(cfg, dry_run=False)
            data = json.loads(local.read_text(encoding="utf-8"))

            self.assertEqual(data["outputStyle"], "Explanatory")
            self.assertEqual(data["permissions"]["allow"], ["Bash(git status:*)"])
            entry = data["hooks"]["Stop"][0]["hooks"][0]
            self.assertEqual(entry["command"], sys.executable)
            self.assertEqual(entry["args"][0], self._script(cfg))

    def test_merges_into_existing_hooks_block(self):
        # A pre-existing hooks section (e.g. a different event) must survive, and
        # a pre-existing unrelated Stop entry must not be dropped.
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d)
            self._seed_script(cfg)
            local = self._local(cfg)
            local.write_text(
                json.dumps({
                    "hooks": {
                        "Stop": [
                            {"hooks": [{"type": "command",
                                        "command": "echo",
                                        "args": ["other"]}]}
                        ],
                        "PreToolUse": [{"matcher": "Bash", "hooks": []}],
                    }
                }, indent=2) + "\n",
                encoding="utf-8",
            )

            self.install.wire_stop_hook(cfg, dry_run=False)
            data = json.loads(local.read_text(encoding="utf-8"))

            self.assertIn("PreToolUse", data["hooks"])
            stop = data["hooks"]["Stop"]
            self.assertEqual(len(stop), 2)  # existing echo entry + our record_stop
            scripts = [
                e["args"][0]
                for group in stop
                for e in group["hooks"]
                if e.get("args")
            ]
            self.assertIn(self._script(cfg), scripts)
            self.assertIn("other", scripts)

            # Re-running is still idempotent against this mixed list.
            self.install.wire_stop_hook(cfg, dry_run=False)
            data2 = json.loads(local.read_text(encoding="utf-8"))
            self.assertEqual(len(data2["hooks"]["Stop"]), 2)

    # --- QA-audit regression coverage ------------------------------------

    def test_skips_when_hooks_script_missing(self):
        # [MAJOR] With no hooks/record_stop.py on disk, wiring must be a no-op so
        # we never wire a hook to a script the hooks/ symlink failed to create
        # (and never leave a real settings.json blocking future installs).
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d)  # deliberately no hooks/record_stop.py
            self.install.wire_stop_hook(cfg, dry_run=False)
            self.assertFalse(self._local(cfg).exists())

    def test_missing_script_leaves_existing_settings_untouched(self):
        # A pre-existing settings.json must not be rewritten when the
        # script is absent (guard runs before any load/modify/write).
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d)
            local = self._local(cfg)
            original = json.dumps({"outputStyle": "Explanatory"}, indent=2) + "\n"
            local.write_text(original, encoding="utf-8")

            self.install.wire_stop_hook(cfg, dry_run=False)
            self.assertEqual(local.read_text(encoding="utf-8"), original)

    def test_preserves_comment_doc_keys(self):
        # [MINOR] _comment_* documentation keys (seeded in the template) must
        # survive the wiring write — wire_stop_hook reads raw JSON, not the
        # comment-stripping load_json.
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d)
            self._seed_script(cfg)
            local = self._local(cfg)
            local.write_text(
                json.dumps({
                    "_comment_hooks": "Stop hook is wired by install.py",
                    "example_note_example": "kept too",
                    "outputStyle": "Explanatory",
                }, indent=2) + "\n",
                encoding="utf-8",
            )

            self.install.wire_stop_hook(cfg, dry_run=False)
            data = json.loads(local.read_text(encoding="utf-8"))

            self.assertEqual(data["_comment_hooks"],
                             "Stop hook is wired by install.py")
            self.assertEqual(data["example_note_example"], "kept too")
            self.assertEqual(data["outputStyle"], "Explanatory")
            self.assertIn("Stop", data["hooks"])

    def test_path_normalized_idempotency(self):
        # [MINOR] A Stop entry whose stored script path differs only in spelling
        # (redundant './' segment, and case/separator on Windows) must be treated
        # as already wired — not duplicated.
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d)
            self._seed_script(cfg)
            local = self._local(cfg)

            # Same script, spelled with a redundant '.' segment (normpath folds it
            # on every platform). Built as a raw string because pathlib would
            # silently drop the '.' before it ever reaches the settings file.
            head, tail = os.path.split(self._script(cfg))
            variant = head + os.sep + "." + os.sep + tail
            self.assertNotEqual(variant, self._script(cfg))
            local.write_text(
                json.dumps({
                    "hooks": {
                        "Stop": [
                            {"hooks": [{"type": "command",
                                        "command": sys.executable,
                                        "args": [variant],
                                        "async": True}]}
                        ]
                    }
                }, indent=2) + "\n",
                encoding="utf-8",
            )

            self.install.wire_stop_hook(cfg, dry_run=False)
            data = json.loads(local.read_text(encoding="utf-8"))

            stop = data["hooks"]["Stop"]
            self.assertEqual(len(stop), 1)  # not double-wired
            self.assertEqual(len(stop[0]["hooks"]), 1)
            # Original (variant) entry left in place since interpreter matches.
            self.assertEqual(stop[0]["hooks"][0]["args"], [variant])

    @unittest.skipUnless(os.name == "nt", "case/separator folding is Windows-only")
    def test_path_normalized_idempotency_case_and_sep_windows(self):
        # On Windows, C:\ vs c:/ spellings of the same script must not double-wire.
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d)
            self._seed_script(cfg)
            local = self._local(cfg)

            variant = self._script(cfg).replace("\\", "/").lower()
            self.assertNotEqual(variant, self._script(cfg))
            local.write_text(
                json.dumps({
                    "hooks": {
                        "Stop": [
                            {"hooks": [{"type": "command",
                                        "command": sys.executable,
                                        "args": [variant],
                                        "async": True}]}
                        ]
                    }
                }, indent=2) + "\n",
                encoding="utf-8",
            )

            self.install.wire_stop_hook(cfg, dry_run=False)
            data = json.loads(local.read_text(encoding="utf-8"))
            self.assertEqual(len(data["hooks"]["Stop"]), 1)

    def test_interpreter_change_rewires_in_place(self):
        # [MINOR] When a matching Stop entry's `command` (interpreter) has drifted
        # from the current sys.executable (e.g. a Python upgrade), it is re-pointed
        # in place — not skipped, and not duplicated.
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d)
            self._seed_script(cfg)
            local = self._local(cfg)
            stale = str(Path(d) / "old" / "python.exe")
            local.write_text(
                json.dumps({
                    "hooks": {
                        "Stop": [
                            {"hooks": [{"type": "command",
                                        "command": stale,
                                        "args": [self._script(cfg)],
                                        "async": True}]}
                        ]
                    }
                }, indent=2) + "\n",
                encoding="utf-8",
            )

            self.install.wire_stop_hook(cfg, dry_run=False)
            data = json.loads(local.read_text(encoding="utf-8"))

            stop = data["hooks"]["Stop"]
            self.assertEqual(len(stop), 1)          # re-wired in place, no duplicate
            self.assertEqual(len(stop[0]["hooks"]), 1)
            entry = stop[0]["hooks"][0]
            self.assertEqual(entry["command"], sys.executable)  # updated
            self.assertEqual(entry["args"][0], self._script(cfg))

    def test_interpreter_change_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d)
            self._seed_script(cfg)
            local = self._local(cfg)
            original = json.dumps({
                "hooks": {
                    "Stop": [
                        {"hooks": [{"type": "command",
                                    "command": "/old/python",
                                    "args": [self._script(cfg)],
                                    "async": True}]}
                    ]
                }
            }, indent=2) + "\n"
            local.write_text(original, encoding="utf-8")

            self.install.wire_stop_hook(cfg, dry_run=True)
            self.assertEqual(local.read_text(encoding="utf-8"), original)


class WireSessionStartHookTest(unittest.TestCase):
    """install.wire_sessionstart_hook injects a synchronous SessionStart hook
    (harvest_nudge.py, no `async` key) into settings.json, idempotently,
    honoring the existence guard and dry-run, without clobbering a Stop entry."""

    def setUp(self):
        sys.path.insert(0, str(ROOT))
        self.install = importlib.import_module("install")
        _pin_not_a_venv(self)  # assertions below compare against sys.executable

    def _local(self, config_dir: Path) -> Path:
        return config_dir / "settings.json"

    def _script(self, config_dir: Path) -> str:
        return str(config_dir / "hooks" / "harvest_nudge.py")

    def _seed_script(self, config_dir: Path) -> None:
        hooks = config_dir / "hooks"
        hooks.mkdir(parents=True, exist_ok=True)
        (hooks / "harvest_nudge.py").write_text("# stub\n", encoding="utf-8")

    def _seed_stop_script(self, config_dir: Path) -> None:
        hooks = config_dir / "hooks"
        hooks.mkdir(parents=True, exist_ok=True)
        (hooks / "record_stop.py").write_text("# stub\n", encoding="utf-8")

    def test_fresh_injection_creates_entry_without_async_key(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d)
            self._seed_script(cfg)
            self.install.wire_sessionstart_hook(cfg, dry_run=False)

            data = json.loads(self._local(cfg).read_text(encoding="utf-8"))
            ss = data["hooks"]["SessionStart"]
            self.assertEqual(len(ss), 1)
            entry = ss[0]["hooks"][0]
            self.assertEqual(entry["type"], "command")
            self.assertEqual(entry["command"], sys.executable)
            self.assertEqual(entry["args"][0], self._script(cfg))
            # Synchronous hook: the async key must be omitted entirely.
            self.assertNotIn("async", entry)

    def test_idempotent_second_run_does_not_duplicate(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d)
            self._seed_script(cfg)
            self.install.wire_sessionstart_hook(cfg, dry_run=False)
            first = self._local(cfg).read_text(encoding="utf-8")
            self.install.wire_sessionstart_hook(cfg, dry_run=False)
            second = self._local(cfg).read_text(encoding="utf-8")
            self.assertEqual(first, second)
            data = json.loads(second)
            self.assertEqual(len(data["hooks"]["SessionStart"]), 1)

    def test_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d)
            self.install.wire_sessionstart_hook(cfg, dry_run=True)
            self.assertFalse(self._local(cfg).exists())

    def test_skips_when_hooks_script_missing(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d)  # no hooks/harvest_nudge.py
            self.install.wire_sessionstart_hook(cfg, dry_run=False)
            self.assertFalse(self._local(cfg).exists())

    def test_wiring_sessionstart_preserves_existing_stop(self):
        # SessionStart wiring must not drop a pre-existing Stop entry.
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d)
            self._seed_stop_script(cfg)
            self._seed_script(cfg)
            self.install.wire_stop_hook(cfg, dry_run=False)
            self.install.wire_sessionstart_hook(cfg, dry_run=False)

            data = json.loads(self._local(cfg).read_text(encoding="utf-8"))
            self.assertIn("Stop", data["hooks"])
            self.assertIn("SessionStart", data["hooks"])
            stop_entry = data["hooks"]["Stop"][0]["hooks"][0]
            self.assertIs(stop_entry["async"], True)
            ss_entry = data["hooks"]["SessionStart"][0]["hooks"][0]
            self.assertNotIn("async", ss_entry)

    def test_wiring_stop_preserves_existing_sessionstart(self):
        # And the reverse: wiring Stop after SessionStart keeps SessionStart intact.
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d)
            self._seed_stop_script(cfg)
            self._seed_script(cfg)
            self.install.wire_sessionstart_hook(cfg, dry_run=False)
            self.install.wire_stop_hook(cfg, dry_run=False)

            data = json.loads(self._local(cfg).read_text(encoding="utf-8"))
            self.assertEqual(len(data["hooks"]["SessionStart"]), 1)
            self.assertEqual(len(data["hooks"]["Stop"]), 1)
            self.assertNotIn(
                "async", data["hooks"]["SessionStart"][0]["hooks"][0]
            )


class WireCommandHookMatcherTest(unittest.TestCase):
    """install._wire_command_hook can scope a hook to a tool via the group's
    `matcher`, and treats that matcher as part of the hook's identity.

    A tool-event hook (PreToolUse/PostToolUse) wired without a matcher fires on
    every tool call in every session; on a synchronous hook that is a latency tax
    on the whole session. So the matcher must be expressible, and a matcher that
    has drifted must re-wire in place rather than silently no-op as "already
    wired" — which would leave the old, wrongly-scoped entry running.

    The two public wrappers pass no matcher, so these exercise the private
    _wire_command_hook directly against a stub script of our own name.
    """

    SCRIPT = "matcher_probe.py"
    EVENT = "PreToolUse"

    def setUp(self):
        sys.path.insert(0, str(ROOT))
        self.install = importlib.import_module("install")
        _pin_not_a_venv(self)  # assertions below compare against sys.executable

    def _local(self, config_dir: Path) -> Path:
        return config_dir / "settings.json"

    def _script(self, config_dir: Path) -> str:
        return str(config_dir / "hooks" / self.SCRIPT)

    def _seed_script(self, config_dir: Path) -> None:
        hooks = config_dir / "hooks"
        hooks.mkdir(parents=True, exist_ok=True)
        (hooks / self.SCRIPT).write_text("# stub\n", encoding="utf-8")

    def _wire(self, config_dir: Path, *, matcher=None, dry_run=False) -> None:
        self.install._wire_command_hook(
            config_dir,
            event_name=self.EVENT,
            script_name=self.SCRIPT,
            use_async=False,
            dry_run=dry_run,
            matcher=matcher,
        )

    def _seed_settings(self, config_dir: Path, groups: list) -> str:
        text = json.dumps({"hooks": {self.EVENT: groups}}, indent=2) + "\n"
        self._local(config_dir).write_text(text, encoding="utf-8")
        return text

    def _entry(self, config_dir: Path, *, command=None) -> dict:
        return {
            "type": "command",
            "command": command or sys.executable,
            "args": [self._script(config_dir)],
        }

    def _groups(self, config_dir: Path) -> list:
        data = json.loads(self._local(config_dir).read_text(encoding="utf-8"))
        return data["hooks"][self.EVENT]

    def _ours(self, config_dir: Path) -> list:
        """(group, entry) pairs whose entry references our stub script."""
        script = self._script(config_dir)
        return [
            (group, entry)
            for group in self._groups(config_dir)
            for entry in group.get("hooks", [])
            if script in (entry.get("args") or [])
        ]

    # --- defect 1: the matcher must be expressible at all -----------------

    def test_matcher_is_emitted_ahead_of_hooks(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d)
            self._seed_script(cfg)
            self._wire(cfg, matcher="Bash")

            groups = self._groups(cfg)
            self.assertEqual(len(groups), 1)
            # `matcher` first, matching the real Claude Code group shape.
            self.assertEqual(list(groups[0].keys()), ["matcher", "hooks"])
            self.assertEqual(groups[0]["matcher"], "Bash")
            entry = groups[0]["hooks"][0]
            self.assertEqual(entry["type"], "command")
            self.assertEqual(entry["command"], sys.executable)
            self.assertEqual(entry["args"][0], self._script(cfg))
            self.assertNotIn("async", entry)

    def test_without_matcher_group_shape_is_unchanged(self):
        # No matcher supplied: the emitted group must carry no `matcher` key at
        # all — the shape the Stop / SessionStart wiring has always produced.
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d)
            self._seed_script(cfg)
            self._wire(cfg)

            groups = self._groups(cfg)
            self.assertEqual(len(groups), 1)
            self.assertEqual(list(groups[0].keys()), ["hooks"])
            self.assertNotIn("matcher", groups[0])

    # --- defect 2: the matcher is part of the hook's identity -------------

    def test_adding_a_matcher_rewires_a_matcherless_entry(self):
        # The regression this class exists for: an already-wired, matcher-less
        # entry for the same script must NOT count as "already wired" once a
        # matcher is asked for. No-oping here leaves a hook firing on every tool.
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d)
            self._seed_script(cfg)
            self._seed_settings(cfg, [{"hooks": [self._entry(cfg)]}])

            self._wire(cfg, matcher="Bash")

            ours = self._ours(cfg)
            self.assertEqual(len(ours), 1)  # re-wired in place, not duplicated
            group, entry = ours[0]
            self.assertEqual(group.get("matcher"), "Bash")
            self.assertEqual(list(group.keys()), ["matcher", "hooks"])
            self.assertEqual(entry["command"], sys.executable)

    def test_same_matcher_rerun_is_a_noop(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d)
            self._seed_script(cfg)
            self._wire(cfg, matcher="Bash")
            first = self._local(cfg).read_text(encoding="utf-8")
            self._wire(cfg, matcher="Bash")
            second = self._local(cfg).read_text(encoding="utf-8")

            self.assertEqual(first, second)
            self.assertEqual(len(self._ours(cfg)), 1)

    def test_changed_matcher_rewires_in_place(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d)
            self._seed_script(cfg)
            self._seed_settings(
                cfg, [{"matcher": "Bash", "hooks": [self._entry(cfg)]}]
            )

            self._wire(cfg, matcher="Edit")

            self.assertEqual(len(self._groups(cfg)), 1)  # not duplicated
            ours = self._ours(cfg)
            self.assertEqual(len(ours), 1)
            self.assertEqual(ours[0][0].get("matcher"), "Edit")

    def test_removing_the_matcher_rewires(self):
        # matcher-bearing -> matcher-less is drift in the other direction and
        # must re-wire too, dropping the key rather than leaving it stale.
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d)
            self._seed_script(cfg)
            self._seed_settings(
                cfg, [{"matcher": "Bash", "hooks": [self._entry(cfg)]}]
            )

            self._wire(cfg, matcher=None)

            ours = self._ours(cfg)
            self.assertEqual(len(ours), 1)
            self.assertNotIn("matcher", ours[0][0])

    def test_explicit_null_matcher_counts_as_no_matcher(self):
        # An explicit `"matcher": null` and an absent key mean the same thing,
        # so wiring with matcher=None over it is a no-op, not a re-wire.
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d)
            self._seed_script(cfg)
            original = self._seed_settings(
                cfg, [{"matcher": None, "hooks": [self._entry(cfg)]}]
            )

            self._wire(cfg, matcher=None)
            self.assertEqual(self._local(cfg).read_text(encoding="utf-8"), original)

    def test_matcher_change_in_shared_group_leaves_other_hook_alone(self):
        # Our entry shares a group with somebody else's hook. Rewriting that
        # group's matcher would silently re-scope their hook, so ours is pulled
        # out into a correctly-matched group of its own instead.
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d)
            self._seed_script(cfg)
            other = {"type": "command", "command": "echo", "args": ["other"]}
            self._seed_settings(
                cfg, [{"matcher": "Bash", "hooks": [other, self._entry(cfg)]}]
            )

            self._wire(cfg, matcher="Edit")

            groups = self._groups(cfg)
            shared = [g for g in groups if other in g.get("hooks", [])]
            self.assertEqual(len(shared), 1)
            self.assertEqual(shared[0]["matcher"], "Bash")  # untouched
            self.assertEqual(shared[0]["hooks"], [other])   # ours moved out

            ours = self._ours(cfg)
            self.assertEqual(len(ours), 1)  # exactly one entry for our script
            self.assertEqual(ours[0][0].get("matcher"), "Edit")
            self.assertIsNot(ours[0][0], shared[0])

    def test_sole_occupant_rescope_preserves_other_group_keys(self):
        # The other branch: our entry is the group's sole occupant, so the group
        # is cleared and rebuilt in place to keep `matcher` ahead of `hooks`.
        # Anything else the user hung on that group has to survive that rebuild
        # — dropping it would be silent data loss in a real settings.json.
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d)
            self._seed_script(cfg)
            self._seed_settings(cfg, [{
                "matcher": "Bash",
                "hooks": [self._entry(cfg)],
                "_comment": "mine",
                "enabled": False,
            }])

            self._wire(cfg, matcher="Edit")

            groups = self._groups(cfg)
            self.assertEqual(len(groups), 1)  # re-scoped in place, not split
            group = groups[0]
            self.assertEqual(group["matcher"], "Edit")
            self.assertEqual(group["_comment"], "mine")
            self.assertIs(group["enabled"], False)
            # `matcher` still serialises ahead of `hooks`, extras trailing.
            self.assertEqual(
                list(group.keys()), ["matcher", "hooks", "_comment", "enabled"]
            )

            ours = self._ours(cfg)
            self.assertEqual(len(ours), 1)
            self.assertEqual(ours[0][1]["command"], sys.executable)

    def test_interpreter_and_matcher_drift_fixed_in_one_pass(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d)
            self._seed_script(cfg)
            stale = str(Path(d) / "old" / "python.exe")
            self._seed_settings(cfg, [{
                "matcher": "Bash",
                "hooks": [self._entry(cfg, command=stale)],
            }])

            self._wire(cfg, matcher="Edit")

            ours = self._ours(cfg)
            self.assertEqual(len(ours), 1)
            group, entry = ours[0]
            self.assertEqual(group.get("matcher"), "Edit")
            self.assertEqual(entry["command"], sys.executable)

    def test_prefers_the_group_whose_matcher_already_agrees(self):
        # Two groups reference our script (a pre-existing mess). The one whose
        # matcher already agrees wins, so a correct wiring stays a no-op.
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d)
            self._seed_script(cfg)
            original = self._seed_settings(cfg, [
                {"hooks": [self._entry(cfg)]},
                {"matcher": "Bash", "hooks": [self._entry(cfg)]},
            ])

            self._wire(cfg, matcher="Bash")
            self.assertEqual(self._local(cfg).read_text(encoding="utf-8"), original)

    def test_matcher_change_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d)
            self._seed_script(cfg)
            original = self._seed_settings(
                cfg, [{"matcher": "Bash", "hooks": [self._entry(cfg)]}]
            )

            self._wire(cfg, matcher="Edit", dry_run=True)
            self.assertEqual(self._local(cfg).read_text(encoding="utf-8"), original)

    def test_fresh_matcher_wiring_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d)
            self._wire(cfg, matcher="Bash", dry_run=True)
            self.assertFalse(self._local(cfg).exists())


class VenvInterpreterGuardTest(unittest.TestCase):
    """install.py never wires a hook to a virtualenv interpreter (#144).

    A venv is disposable: when it is rebuilt, a hook wired to
    ``.venv/Scripts/python.exe`` dies silently (Claude Code does not surface a
    failed hook spawn). So, run from a venv, the installer must wire the *base*
    interpreter instead — and the drift repair must never "repair" a working
    system-interpreter wiring down to the venv path.

    Every test builds its own fake venv / base layout in a temp dir (real empty
    files, so ``os.path.isfile`` is honest) and patches ``sys`` to point at it;
    nothing here depends on the interpreter actually running the suite.
    """

    def setUp(self):
        sys.path.insert(0, str(ROOT))
        self.install = importlib.import_module("install")

    # --- fixtures ---------------------------------------------------------

    @staticmethod
    def _touch(path: Path) -> str:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
        return str(path)

    def _fake_venv(self, root: Path) -> tuple[Path, str]:
        """<root>/.venv with a pyvenv.cfg and a python in the platform's layout."""
        venv = root / ".venv"
        self._touch(venv / "pyvenv.cfg")
        if os.name == "nt":
            exe = self._touch(venv / "Scripts" / "python.exe")
        else:
            exe = self._touch(venv / "bin" / "python")
        return venv, exe

    def _fake_base(self, root: Path) -> tuple[Path, str]:
        """<root>/base holding the fallback candidate _resolve_hook_interpreter tries."""
        base = root / "base"
        if os.name == "nt":
            exe = self._touch(base / "python.exe")
        else:
            major, minor = sys.version_info[:2]
            exe = self._touch(base / "bin" / f"python{major}.{minor}")
        return base, exe

    def _patch_sys(self, **attrs) -> None:
        """Patch sys.<name> for the rest of the test (create=True covers
        sys._base_executable, which is private and not guaranteed present)."""
        for name, value in attrs.items():
            p = mock.patch.object(sys, name, value, create=True)
            p.start()
            self.addCleanup(p.stop)

    def _enter_venv(self, root: Path, *, base_executable) -> tuple[str, str]:
        """Patch sys as if running from <root>/.venv over <root>/base.
        Returns (venv python, base python)."""
        venv, venv_exe = self._fake_venv(root)
        base, base_exe = self._fake_base(root)
        self._patch_sys(
            prefix=str(venv),
            base_prefix=str(base),
            executable=venv_exe,
            _base_executable=base_executable,
        )
        return venv_exe, base_exe

    def _seed_stop_script(self, config_dir: Path) -> str:
        hooks = config_dir / "hooks"
        hooks.mkdir(parents=True, exist_ok=True)
        script = hooks / "record_stop.py"
        script.write_text("# stub\n", encoding="utf-8")
        return str(script)

    def _stop_entries(self, config_dir: Path) -> list:
        data = json.loads((config_dir / "settings.json").read_text(encoding="utf-8"))
        return [e for g in data["hooks"]["Stop"] for e in g["hooks"]]

    # --- _is_venv_interpreter -------------------------------------------

    def test_is_venv_interpreter_detects_both_layouts(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            venv = root / ".venv"
            self._touch(venv / "pyvenv.cfg")
            win = self._touch(venv / "Scripts" / "python.exe")
            posix = self._touch(venv / "bin" / "python")
            _, base_exe = self._fake_base(root)

            self.assertTrue(self.install._is_venv_interpreter(win))
            self.assertTrue(self.install._is_venv_interpreter(posix))
            self.assertFalse(self.install._is_venv_interpreter(base_exe))
            self.assertFalse(self.install._is_venv_interpreter(""))

    # --- _resolve_hook_interpreter --------------------------------------

    def test_not_a_venv_returns_sys_executable_and_no_note(self):
        self._patch_sys(base_prefix=sys.prefix)
        self.assertEqual(
            self.install._resolve_hook_interpreter(), (sys.executable, None)
        )

    def test_in_venv_resolves_base_executable(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            venv, venv_exe = self._fake_venv(root)
            base, base_exe = self._fake_base(root)
            # _base_executable is a *different* real file than the fallback, so
            # this proves it is consulted first.
            preferred = self._touch(root / "home" / "python.exe")
            self._patch_sys(prefix=str(venv), base_prefix=str(base),
                            executable=venv_exe, _base_executable=preferred)

            interpreter, note = self.install._resolve_hook_interpreter()
            self.assertEqual(interpreter, preferred)
            self.assertIsNotNone(note)
            self.assertIn(venv_exe, note)
            self.assertIn(preferred, note)

    def test_unverified_base_executable_falls_back_to_base_prefix(self):
        # POSIX getpath can leave _base_executable as an unverified guess
        # (<home>/python that does not exist). Then the Path(sys.base_prefix)
        # candidate matching this platform's layout must win.
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            guess = str(root / "home" / "python")  # never created
            venv_exe, base_exe = self._enter_venv(root, base_executable=guess)

            interpreter, note = self.install._resolve_hook_interpreter()
            self.assertEqual(interpreter, base_exe)
            self.assertIn(venv_exe, note)

    def test_base_executable_inside_venv_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            venv, venv_exe = self._fake_venv(root)
            base, base_exe = self._fake_base(root)
            # (a) the venv python itself: caught by the pyvenv.cfg check
            self._patch_sys(prefix=str(venv), base_prefix=str(base),
                            executable=venv_exe, _base_executable=venv_exe)
            self.assertEqual(self.install._resolve_hook_interpreter()[0], base_exe)

            # (b) a file deep under sys.prefix with no pyvenv.cfg in reach:
            # caught by the "not under sys.prefix" check
            deep = self._touch(venv / "a" / "b" / "python.exe")
            self._patch_sys(_base_executable=deep)
            self.assertEqual(self.install._resolve_hook_interpreter()[0], base_exe)

            # (c) a python inside a *different* venv, outside sys.prefix: only
            # the pyvenv.cfg check can catch this one — the sys.prefix filter
            # does not apply, since it is not under our sys.prefix at all.
            _, other_venv_exe = self._fake_venv(root / "other")
            self._patch_sys(_base_executable=other_venv_exe)
            self.assertEqual(self.install._resolve_hook_interpreter()[0], base_exe)

    def test_nothing_resolvable_returns_none_with_note(self):
        for missing in ("", None):
            with self.subTest(base_executable=missing), \
                    tempfile.TemporaryDirectory() as d:
                root = Path(d)
                venv, venv_exe = self._fake_venv(root)
                # base dir exists but holds no interpreter
                (root / "base").mkdir()
                self._patch_sys(prefix=str(venv), base_prefix=str(root / "base"),
                                executable=venv_exe, _base_executable=missing)

                interpreter, note = self.install._resolve_hook_interpreter()
                self.assertIsNone(interpreter)
                self.assertIn(venv_exe, note)
                self.assertIn("system Python", note)

    def test_relative_base_executable_candidate_is_rejected(self):
        # A relative sys._base_executable that happens to resolve against the
        # current working directory must not be wired verbatim — a candidate
        # only counts when it is absolute (_wire_command_hook promises an
        # install-time resolved *absolute* path).
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            venv, venv_exe = self._fake_venv(root)
            base, base_exe = self._fake_base(root)
            relative = Path("relative_base") / (
                "python.exe" if os.name == "nt" else "python"
            )
            self._touch(root / relative)

            original_cwd = os.getcwd()
            os.chdir(root)
            try:
                self._patch_sys(prefix=str(venv), base_prefix=str(base),
                                executable=venv_exe, _base_executable=str(relative))

                interpreter, note = self.install._resolve_hook_interpreter()
            finally:
                # Restore before the TemporaryDirectory cleanup below runs —
                # Windows refuses to rmdir a directory that is still the cwd.
                os.chdir(original_cwd)

            self.assertEqual(interpreter, base_exe)

    # --- wiring from a venv ---------------------------------------------

    def test_wire_stop_hook_from_venv_writes_base_interpreter(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            cfg = root / "claude"
            script = self._seed_stop_script(cfg)
            # _base_executable unset -> the Path(sys.base_prefix) fallback resolves
            venv_exe, base_exe = self._enter_venv(root, base_executable=None)

            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.install.wire_stop_hook(cfg, dry_run=False)

            entries = self._stop_entries(cfg)
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["command"], base_exe)
            self.assertNotEqual(entries[0]["command"], venv_exe)
            self.assertEqual(entries[0]["args"], [script])
            self.assertIn("running inside a virtualenv", out.getvalue())
            self.assertIn(venv_exe, out.getvalue())

    def test_unresolvable_venv_skips_and_writes_nothing(self):
        for dry_run in (False, True):
            with self.subTest(dry_run=dry_run), tempfile.TemporaryDirectory() as d:
                root = Path(d)
                cfg = root / "claude"
                self._seed_stop_script(cfg)
                venv, venv_exe = self._fake_venv(root)
                (root / "base").mkdir()
                self._patch_sys(prefix=str(venv), base_prefix=str(root / "base"),
                                executable=venv_exe, _base_executable="")

                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    self.install.wire_stop_hook(cfg, dry_run=dry_run)

                self.assertFalse((cfg / "settings.json").exists())
                self.assertIn("skipping Stop hook", out.getvalue())
                self.assertNotIn("would wire", out.getvalue())

    # --- drift repair must not downgrade --------------------------------

    def _seed_existing(self, cfg: Path, command: str, *, matcher=None) -> None:
        group: dict = {}
        if matcher is not None:
            group["matcher"] = matcher
        group["hooks"] = [{"type": "command", "command": command,
                           "args": [str(cfg / "hooks" / "record_stop.py")],
                           "async": True}]
        (cfg / "settings.json").write_text(
            json.dumps({"hooks": {"Stop": [group]}}, indent=2) + "\n",
            encoding="utf-8",
        )

    def _enter_pythonhome_route(self, root: Path) -> str:
        """sys.prefix == sys.base_prefix (so rule 1 sees "not a venv") but
        sys.executable is still a venv python — what PYTHONHOME does."""
        venv, venv_exe = self._fake_venv(root)
        self._patch_sys(prefix=str(venv), base_prefix=str(venv), executable=venv_exe)
        return venv_exe

    def test_no_downgrade_of_resolvable_command_to_venv_interpreter(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            cfg = root / "claude"
            self._seed_stop_script(cfg)
            system_exe = self._touch(root / "system" / "python.exe")
            self._seed_existing(cfg, system_exe)
            venv_exe = self._enter_pythonhome_route(root)
            self.assertEqual(self.install._resolve_hook_interpreter()[0], venv_exe)

            before = (cfg / "settings.json").read_text(encoding="utf-8")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.install.wire_stop_hook(cfg, dry_run=False)

            self.assertEqual((cfg / "settings.json").read_text(encoding="utf-8"), before)
            entries = self._stop_entries(cfg)
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["command"], system_exe)
            self.assertIn("not downgrading", out.getvalue())
            self.assertIn("already wired", out.getvalue())

    def test_unresolvable_existing_command_is_still_repointed(self):
        # Counter-test: the guard is specifically about *resolvable* existing
        # commands. A stale path that no longer exists has nothing to protect,
        # so the ordinary drift repair still re-points it (here, on the
        # PYTHONHOME-style route, to the venv path — rule 1 cannot see it).
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            cfg = root / "claude"
            self._seed_stop_script(cfg)
            stale = str(root / "gone" / "python.exe")  # never created
            self._seed_existing(cfg, stale)
            venv_exe = self._enter_pythonhome_route(root)

            with contextlib.redirect_stdout(io.StringIO()):
                self.install.wire_stop_hook(cfg, dry_run=False)

            entries = self._stop_entries(cfg)
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["command"], venv_exe)

    def test_matcher_drift_is_repaired_without_touching_kept_command(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            cfg = root / "claude"
            script = self._seed_stop_script(cfg)
            system_exe = self._touch(root / "system" / "python.exe")
            self._seed_existing(cfg, system_exe, matcher="Bash")
            self._enter_pythonhome_route(root)

            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.install._wire_command_hook(
                    cfg, event_name="Stop", script_name="record_stop.py",
                    use_async=True, dry_run=False, matcher=None,
                )

            data = json.loads((cfg / "settings.json").read_text(encoding="utf-8"))
            groups = data["hooks"]["Stop"]
            self.assertEqual(len(groups), 1)
            self.assertNotIn("matcher", groups[0])          # matcher repaired
            entry = groups[0]["hooks"][0]
            self.assertEqual(entry["command"], system_exe)   # command untouched
            self.assertEqual(entry["args"], [script])
            self.assertIn("not downgrading", out.getvalue())
            self.assertIn("matcher changed", out.getvalue())
            self.assertNotIn("interpreter changed", out.getvalue())


class CheckHooksTest(unittest.TestCase):
    """install.check_hooks / `install.py --check` report every wired hook whose
    command or args path no longer exists on disk — the symptom of #144 that
    Claude Code itself never surfaces. Read-only, exit 1 on any miss."""

    def setUp(self):
        sys.path.insert(0, str(ROOT))
        self.install = importlib.import_module("install")

    def _write(self, path: Path, groups_by_event: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"hooks": groups_by_event}, indent=2) + "\n",
                        encoding="utf-8")

    @staticmethod
    def _group(command: str, *args: str) -> dict:
        return {"hooks": [{"type": "command", "command": command,
                           "args": list(args)}]}

    def _run(self, settings_path: Path) -> tuple[int, str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = self.install.check_hooks(settings_path)
        return rc, out.getvalue()

    def test_absent_settings_file_is_ok(self):
        with tempfile.TemporaryDirectory() as d:
            rc, out = self._run(Path(d) / "settings.json")
            self.assertEqual(rc, 0)
            self.assertIn("no hooks wired", out)

    def test_all_paths_resolve(self):
        with tempfile.TemporaryDirectory() as d:
            script = Path(d) / "hooks" / "record_stop.py"
            script.parent.mkdir()
            script.write_text("# stub\n", encoding="utf-8")
            settings = Path(d) / "settings.json"
            self._write(settings, {"Stop": [self._group(sys.executable, str(script))]})

            rc, out = self._run(settings)
            self.assertEqual(rc, 0)
            self.assertIn(f"OK Stop: {sys.executable} {script}", out)
            self.assertIn("all hook paths resolve", out)

    def test_missing_command_is_reported(self):
        with tempfile.TemporaryDirectory() as d:
            gone = str(Path(d) / ".venv" / "Scripts" / "python.exe")
            settings = Path(d) / "settings.json"
            self._write(settings, {"Stop": [self._group(gone, "x.py")]})

            rc, out = self._run(settings)
            self.assertEqual(rc, 1)
            self.assertIn(f"MISSING Stop: {gone}", out)
            self.assertIn("1 missing hook path(s)", out)

    def test_missing_args_path_is_reported(self):
        with tempfile.TemporaryDirectory() as d:
            gone = str(Path(d) / "hooks" / "record_stop.py")
            settings = Path(d) / "settings.json"
            self._write(settings, {"SessionStart": [self._group(sys.executable, gone)]})

            rc, out = self._run(settings)
            self.assertEqual(rc, 1)
            self.assertIn(f"MISSING SessionStart: {gone} (args)", out)

    def test_relative_command_is_not_existence_checked(self):
        with tempfile.TemporaryDirectory() as d:
            settings = Path(d) / "settings.json"
            self._write(settings, {"Stop": [self._group("echo hi")]})

            rc, out = self._run(settings)
            self.assertEqual(rc, 0)
            self.assertIn("OK Stop: echo hi", out)

    def test_native_shape_command_with_existing_script_is_ok(self):
        # Claude Code's own hook shape: the whole command line in `command`,
        # no `args` key. This must not be existence-checked as one path.
        with tempfile.TemporaryDirectory() as d:
            script = Path(d) / "hooks" / "x.py"
            script.parent.mkdir()
            script.write_text("# stub\n", encoding="utf-8")
            command = f"{sys.executable} {script}"
            settings = Path(d) / "settings.json"
            self._write(settings, {
                "PreToolUse": [{"hooks": [{"type": "command", "command": command}]}],
            })

            rc, out = self._run(settings)
            self.assertEqual(rc, 0)
            self.assertIn(f"OK PreToolUse: {command}", out)

    def test_native_shape_command_with_missing_script_token_is_reported(self):
        with tempfile.TemporaryDirectory() as d:
            gone = str(Path(d) / "hooks" / "gone.py")
            command = f"{sys.executable} {gone}"
            settings = Path(d) / "settings.json"
            self._write(settings, {
                "PreToolUse": [{"hooks": [{"type": "command", "command": command}]}],
            })

            rc, out = self._run(settings)
            self.assertEqual(rc, 1)
            self.assertIn(f"MISSING PreToolUse: {gone} (in command)", out)
            self.assertIn("1 missing hook path(s)", out)

    def test_malformed_json_returns_1(self):
        with tempfile.TemporaryDirectory() as d:
            settings = Path(d) / "settings.json"
            settings.write_text("{not json", encoding="utf-8")

            rc, out = self._run(settings)
            self.assertEqual(rc, 1)
            self.assertIn("could not parse", out)

    def test_odd_shapes_are_skipped_not_crashed(self):
        with tempfile.TemporaryDirectory() as d:
            settings = Path(d) / "settings.json"
            settings.write_text(json.dumps({"hooks": {
                "Stop": "not a list",
                "SessionStart": [
                    None, {"hooks": "nope"}, {"hooks": [None, {"command": 3}]},
                    {"hooks": 5}, {"hooks": True},
                ],
            }}), encoding="utf-8")

            rc, out = self._run(settings)
            self.assertEqual(rc, 0)
            self.assertIn("all hook paths resolve", out)

    def test_main_check_exits_1_and_never_prompts(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = Path(d)
            gone = str(cfg / ".venv" / "Scripts" / "python.exe")
            self._write(cfg / "settings.json", {"Stop": [self._group(gone)]})

            out = io.StringIO()
            with mock.patch.object(self.install, "CLAUDE_DIR", cfg), \
                    mock.patch.object(self.install, "resolve_settings_choice",
                                      side_effect=AssertionError("prompted")) as rsc, \
                    mock.patch.object(self.install, "resolve_claudemd_choice",
                                      side_effect=AssertionError("prompted")) as rcc, \
                    contextlib.redirect_stdout(out):
                rc = self.install.main(["--check"])

            self.assertEqual(rc, 1)
            rsc.assert_not_called()
            rcc.assert_not_called()
            self.assertIn(f"MISSING Stop: {gone}", out.getvalue())


if __name__ == "__main__":
    unittest.main()
