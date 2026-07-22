import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class WireStopHookTest(unittest.TestCase):
    """install.wire_stop_hook injects the global Stop hook into a config dir's
    settings.json with install-time resolved absolute paths, idempotently,
    honoring --dry-run, and never clobbering unrelated keys."""

    def setUp(self):
        sys.path.insert(0, str(ROOT))
        self.install = importlib.import_module("install")

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


if __name__ == "__main__":
    unittest.main()
