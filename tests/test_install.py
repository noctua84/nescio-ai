import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import _settings_split as ss  # noqa: E402


# A settings.json shaped like the real-world adopt case: one directory-sourced
# marketplace (machine-local) and one github-sourced (portable), plus statusLine,
# additionalDirectories, an allow list, and plugins from both marketplaces.
SAMPLE = {
    "permissions": {
        "allow": ["Bash(git commit:*)", "Bash(npx prisma migrate:*)"],
        "additionalDirectories": ["C:\\Users\\me\\Projects"],
        "defaultMode": "auto",
    },
    "statusLine": {"type": "command", "command": "bash ~/.claude/my-statusline.sh"},
    "model": "opus[1m]",
    "extraKnownMarketplaces": {
        "localmkt": {"source": {"source": "directory", "path": "C:\\Users\\me\\mkt"}},
        "acme": {"source": {"source": "github", "repo": "acme-org/claude-marketplace"}},
    },
    "enabledPlugins": {
        "figma@claude-plugins-official": True,     # builtin marketplace -> portable
        "localmkt-hooks@localmkt": True,         # local-path marketplace -> machine
        "acme-agent-skills@acme": True,          # github marketplace -> portable
    },
}


class DirectoryMarketplacesTest(unittest.TestCase):
    def test_only_directory_sourced_are_flagged(self):
        self.assertEqual(ss.directory_marketplaces(SAMPLE), {"localmkt"})

    def test_empty_when_no_marketplaces(self):
        self.assertEqual(ss.directory_marketplaces({}), set())


class ClassifyMachineLocalTest(unittest.TestCase):
    def setUp(self):
        self.machine = ss.classify_machine_local(SAMPLE)

    def test_statusline_moved(self):
        self.assertEqual(self.machine["statusLine"], SAMPLE["statusLine"])

    def test_additional_directories_moved_under_permissions(self):
        self.assertEqual(
            self.machine["permissions"]["additionalDirectories"],
            ["C:\\Users\\me\\Projects"],
        )

    def test_allow_list_not_moved(self):
        # allow-list portability is judgment, never a rule
        self.assertNotIn("allow", self.machine.get("permissions", {}))

    def test_only_directory_marketplace_moved(self):
        self.assertEqual(set(self.machine["extraKnownMarketplaces"]), {"localmkt"})

    def test_only_local_marketplace_plugin_moved(self):
        self.assertEqual(set(self.machine["enabledPlugins"]), {"localmkt-hooks@localmkt"})

    def test_portable_keys_absent(self):
        for key in ("model",):
            self.assertNotIn(key, self.machine)

    def test_does_not_mutate_input(self):
        before = json.dumps(SAMPLE, sort_keys=True)
        ss.classify_machine_local(SAMPLE)
        self.assertEqual(before, json.dumps(SAMPLE, sort_keys=True))

    def test_empty_settings_yield_empty(self):
        self.assertEqual(ss.classify_machine_local({}), {})


class DeepMergeTest(unittest.TestCase):
    def test_fills_missing_keys(self):
        self.assertEqual(ss.deep_merge({"a": 1}, {"b": 2}), {"a": 1, "b": 2})

    def test_base_scalar_wins(self):
        self.assertEqual(ss.deep_merge({"a": 1}, {"a": 2}), {"a": 1})

    def test_nested_dicts_merge(self):
        out = ss.deep_merge({"p": {"x": 1}}, {"p": {"y": 2}})
        self.assertEqual(out, {"p": {"x": 1, "y": 2}})

    def test_lists_union_dedup_order_preserving(self):
        out = ss.deep_merge({"l": ["a", "b"]}, {"l": ["b", "c"]})
        self.assertEqual(out["l"], ["a", "b", "c"])

    def test_existing_local_plugin_value_preserved(self):
        # user disabled a plugin locally; extracted machine keys must not flip it
        base = {"enabledPlugins": {"acme-agent-plugin@acme": False}}
        machine = ss.classify_machine_local(SAMPLE)
        out = ss.deep_merge(base, machine)
        self.assertFalse(out["enabledPlugins"]["acme-agent-plugin@acme"])
        self.assertTrue(out["enabledPlugins"]["localmkt-hooks@localmkt"])

    def test_does_not_mutate_args(self):
        base, overlay = {"a": {"x": 1}}, {"a": {"y": 2}}
        ss.deep_merge(base, overlay)
        self.assertEqual(base, {"a": {"x": 1}})
        self.assertEqual(overlay, {"a": {"y": 2}})


class LeftoverKeysTest(unittest.TestCase):
    def test_reports_permissions_and_portable_keys(self):
        machine = ss.classify_machine_local(SAMPLE)
        leftover = ss.leftover_top_level_keys(SAMPLE, machine)
        # allow list still lives under permissions -> flagged for manual review
        self.assertIn("permissions", leftover)
        self.assertIn("model", leftover)
        # fully-moved keys are not reported
        self.assertNotIn("statusLine", leftover)

    def test_permissions_not_reported_when_only_additionaldirs(self):
        settings = {"permissions": {"additionalDirectories": ["/x"]}}
        machine = ss.classify_machine_local(settings)
        self.assertEqual(ss.leftover_top_level_keys(settings, machine), [])


class InstallModuleTest(unittest.TestCase):
    """install.py imports cleanly and its file helpers behave."""

    def setUp(self):
        sys.path.insert(0, str(ROOT))
        import importlib
        self.install = importlib.import_module("install")

    def test_load_json_strips_template_annotations(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "settings.local.json.example"
            p.write_text(json.dumps({
                "_comment": "docs",
                "outputStyle": "Explanatory",
                "permissions_additionalDirectories_example": {"x": 1},
            }), encoding="utf-8")
            out = self.install.load_json(p)
            self.assertEqual(out, {"outputStyle": "Explanatory"})

    def test_load_json_missing_returns_empty(self):
        self.assertEqual(self.install.load_json(Path("/no/such/file.json")), {})

    def test_backup_moves_file_and_never_deletes(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "settings.json"
            f.write_text("real", encoding="utf-8")
            dest = self.install.backup(f, "20260101-000000", dry_run=False)
            self.assertFalse(f.exists())
            self.assertTrue(dest.exists())
            self.assertEqual(dest.read_text(encoding="utf-8"), "real")
            self.assertEqual(dest.name, "settings.json.pre-adopt-20260101-000000.bak")

    def test_backup_dry_run_leaves_file(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "settings.json"
            f.write_text("real", encoding="utf-8")
            self.install.backup(f, "20260101-000000", dry_run=True)
            self.assertTrue(f.exists())

    def test_is_conflict_false_for_missing(self):
        self.assertFalse(self.install.is_conflict(Path("/no/such/path")))


class CanSymlinkTest(unittest.TestCase):
    def setUp(self):
        sys.path.insert(0, str(ROOT))
        import importlib
        self.install = importlib.import_module("install")

    def test_false_when_creation_raises(self):
        # Simulate a Windows shell without the symlink privilege: symlink_to raises.
        orig = Path.symlink_to

        def boom(self, *a, **k):
            raise OSError("[WinError 1314] no privilege")

        Path.symlink_to = boom
        try:
            with tempfile.TemporaryDirectory() as d:
                self.assertFalse(self.install.can_symlink(Path(d)))
                # the probe must not linger
                self.assertFalse((Path(d) / ".install-symlink-probe").exists())
        finally:
            Path.symlink_to = orig


class RelinkIntegrationTest(unittest.TestCase):
    """Exercise do_relink for real against isolated temp dirs. Symlink creation is
    stubbed so the outcome is deterministic. settings.json is no longer symlinked
    or rescued-to-settings.local.json — it's merged into a real ~/.claude/
    settings.json by install_settings — so these prove the new behavior."""

    def setUp(self):
        sys.path.insert(0, str(ROOT))
        import importlib
        self.install = importlib.import_module("install")

    def _repo(self, repo: Path):
        (repo / "settings.json").write_text(
            '{"agent":"orchestrator","permissions":{"allow":["Bash(ls:*)"]}}',
            encoding="utf-8")
        (repo / "CLAUDE.md").write_text("# claude\n", encoding="utf-8")

    def _run(self, repo: Path, home: Path, *, can_symlink, symlink,
             choice="minimal", claudemd_choice="skip"):
        """Run do_relink with can_symlink/symlink stubbed, dirs redirected.

        claudemd_choice defaults to 'skip' so the settings-focused cases don't also
        exercise CLAUDE.md; the CLAUDE.md path has its own tests below.
        """
        i = self.install
        saved = (i.REPO_DIR, i.CLAUDE_DIR, i.can_symlink, i.symlink)
        i.REPO_DIR, i.CLAUDE_DIR, i.can_symlink, i.symlink = repo, home, can_symlink, symlink
        try:
            return i.do_relink("20260101-000000", dry_run=False, ledger={},
                               choice=choice, claudemd_choice=claudemd_choice)
        finally:
            i.REPO_DIR, i.CLAUDE_DIR, i.can_symlink, i.symlink = saved

    def test_relink_merges_settings_into_real_file(self):
        # An existing real ~/.claude/settings.json is merged (adopted keys win,
        # user keys kept) into a real file — never symlinked, backed up, or
        # rescued to repo/settings.local.json.
        with tempfile.TemporaryDirectory() as repo_d, tempfile.TemporaryDirectory() as home_d:
            repo, home = Path(repo_d), Path(home_d)
            self._repo(repo)
            (home / "settings.json").write_text(
                json.dumps({"model": "opus[1m]", "agent": "general-purpose"}),
                encoding="utf-8")

            rc = self._run(repo, home,
                           can_symlink=lambda _d: True,
                           symlink=lambda src, dst, dry_run: True, choice="minimal")
            self.assertEqual(rc, 0)

            s = home / "settings.json"
            self.assertTrue(s.is_file() and not s.is_symlink())
            data = json.loads(s.read_text(encoding="utf-8"))
            self.assertEqual(data["agent"], "orchestrator")   # adopted key wins
            self.assertEqual(data["model"], "opus[1m]")        # user key preserved
            self.assertFalse((repo / "settings.local.json").exists())  # no rescue path

    def test_relink_removes_dead_local_symlink(self):
        # A leftover ~/.claude/settings.local.json SYMLINK from an older installer
        # is cleaned up (Claude Code never read it).
        with tempfile.TemporaryDirectory() as repo_d, tempfile.TemporaryDirectory() as home_d:
            repo, home = Path(repo_d), Path(home_d)
            self._repo(repo)
            (repo / "settings.local.json").write_text("{}", encoding="utf-8")
            (home / "settings.local.json").symlink_to(repo / "settings.local.json")

            self._run(repo, home,
                      can_symlink=lambda _d: True,
                      symlink=lambda src, dst, dry_run: True, choice="minimal")
            self.assertFalse((home / "settings.local.json").exists())

    def test_relink_restores_live_file_when_symlink_fails(self):
        # A LINK conflict (real ~/.claude/memory) is backed up, and restored if the
        # symlink fails — never left missing. (CLAUDE.md is no longer a LINK target;
        # it's handled by install_claude_md, so `memory` stands in as the conflict.)
        with tempfile.TemporaryDirectory() as repo_d, tempfile.TemporaryDirectory() as home_d:
            repo, home = Path(repo_d), Path(home_d)
            self._repo(repo)
            (repo / "memory").mkdir()
            (home / "memory").mkdir()
            (home / "memory" / "note.md").write_text("mine\n", encoding="utf-8")

            rc = self._run(repo, home,
                           can_symlink=lambda _d: True,             # past the pre-flight
                           symlink=lambda src, dst, dry_run: False)  # ...but each link fails

            self.assertTrue((home / "memory").is_dir())
            self.assertEqual((home / "memory" / "note.md").read_text(encoding="utf-8"), "mine\n")
            self.assertFalse((home / "memory.pre-adopt-20260101-000000.bak").exists())
            self.assertEqual(rc, 1)

    def test_relink_imports_claude_md(self):
        # do_relink threads claudemd_choice through to install_claude_md: 'import'
        # makes ~/.claude/CLAUDE.md a real file that @-imports the repo's, keeping
        # any lines the user already had.
        with tempfile.TemporaryDirectory() as repo_d, tempfile.TemporaryDirectory() as home_d:
            repo, home = Path(repo_d), Path(home_d)
            self._repo(repo)
            (home / "CLAUDE.md").write_text("# my own rules\n", encoding="utf-8")

            self._run(repo, home,
                      can_symlink=lambda _d: True,
                      symlink=lambda src, dst, dry_run: True,
                      choice="skip", claudemd_choice="import")

            t = home / "CLAUDE.md"
            self.assertTrue(t.is_file() and not t.is_symlink())
            text = t.read_text(encoding="utf-8")
            self.assertTrue(text.startswith(f"@{repo / 'CLAUDE.md'}"))
            self.assertIn("# my own rules", text)

    def test_relink_aborts_when_symlinks_unavailable(self):
        # Pre-flight refusal: live files untouched.
        with tempfile.TemporaryDirectory() as repo_d, tempfile.TemporaryDirectory() as home_d:
            repo, home = Path(repo_d), Path(home_d)
            self._repo(repo)
            (home / "settings.json").write_text('{"model":"x"}', encoding="utf-8")
            original = (home / "settings.json").read_text(encoding="utf-8")

            def must_not_call(*a, **k):
                self.fail("symlink() must not run when can_symlink() is False")

            rc = self._run(repo, home,
                           can_symlink=lambda _d: False, symlink=must_not_call)

            self.assertEqual(rc, 1)
            self.assertEqual((home / "settings.json").read_text(encoding="utf-8"), original)


class ClaudeMdInstallTest(unittest.TestCase):
    """Unit-test install_claude_md across import/replace/skip. Only one user-scope
    CLAUDE.md is read, so 'import' composes via Claude Code's `@path` import rather
    than overwriting the user's file."""

    def setUp(self):
        sys.path.insert(0, str(ROOT))
        import importlib
        self.install = importlib.import_module("install")

    def _run(self, repo: Path, home: Path, choice: str, *, dry_run=False) -> str:
        """Point install at temp dirs, seed the repo CLAUDE.md, run. Returns the
        expected import line."""
        i = self.install
        saved = (i.REPO_DIR, i.CLAUDE_DIR)
        i.REPO_DIR, i.CLAUDE_DIR = repo, home
        try:
            (repo / "CLAUDE.md").write_text("# framework\n", encoding="utf-8")
            i.install_claude_md(choice, dry_run)
            return f"@{repo / 'CLAUDE.md'}"
        finally:
            i.REPO_DIR, i.CLAUDE_DIR = saved

    def test_import_fresh_creates_real_importing_file(self):
        with tempfile.TemporaryDirectory() as r, tempfile.TemporaryDirectory() as h:
            repo, home = Path(r), Path(h)
            imp = self._run(repo, home, "import")
            t = home / "CLAUDE.md"
            self.assertTrue(t.is_file() and not t.is_symlink())
            self.assertTrue(t.read_text(encoding="utf-8").startswith(imp + "\n"))

    def test_import_preserves_existing_user_content(self):
        with tempfile.TemporaryDirectory() as r, tempfile.TemporaryDirectory() as h:
            repo, home = Path(r), Path(h)
            (home / "CLAUDE.md").write_text("# mine\n- rule\n", encoding="utf-8")
            imp = self._run(repo, home, "import")
            text = (home / "CLAUDE.md").read_text(encoding="utf-8")
            self.assertTrue(text.startswith(imp))
            self.assertIn("- rule", text)

    def test_import_is_idempotent(self):
        with tempfile.TemporaryDirectory() as r, tempfile.TemporaryDirectory() as h:
            repo, home = Path(r), Path(h)
            self._run(repo, home, "import")
            first = (home / "CLAUDE.md").read_text(encoding="utf-8")
            self._run(repo, home, "import")
            self.assertEqual((home / "CLAUDE.md").read_text(encoding="utf-8"), first)

    def test_import_migrates_repo_symlink_to_real_file(self):
        with tempfile.TemporaryDirectory() as r, tempfile.TemporaryDirectory() as h:
            repo, home = Path(r), Path(h)
            (repo / "CLAUDE.md").write_text("# framework\n", encoding="utf-8")
            (home / "CLAUDE.md").symlink_to(repo / "CLAUDE.md")
            imp = self._run(repo, home, "import")
            t = home / "CLAUDE.md"
            self.assertTrue(t.is_file() and not t.is_symlink())
            self.assertTrue(t.read_text(encoding="utf-8").startswith(imp))

    def test_replace_symlinks_and_backs_up_existing(self):
        with tempfile.TemporaryDirectory() as r, tempfile.TemporaryDirectory() as h:
            repo, home = Path(r), Path(h)
            (home / "CLAUDE.md").write_text("# mine\n", encoding="utf-8")
            self._run(repo, home, "replace")
            t = home / "CLAUDE.md"
            self.assertTrue(t.is_symlink())
            self.assertEqual(t.resolve(), (repo / "CLAUDE.md").resolve())
            baks = list(home.glob("CLAUDE.md.pre-adopt-*.bak"))
            self.assertEqual(len(baks), 1)
            self.assertEqual(baks[0].read_text(encoding="utf-8"), "# mine\n")

    def test_skip_leaves_file_untouched(self):
        with tempfile.TemporaryDirectory() as r, tempfile.TemporaryDirectory() as h:
            repo, home = Path(r), Path(h)
            self._run(repo, home, "skip")
            self.assertFalse((home / "CLAUDE.md").exists())

    def test_dry_run_import_writes_nothing(self):
        with tempfile.TemporaryDirectory() as r, tempfile.TemporaryDirectory() as h:
            repo, home = Path(r), Path(h)
            self._run(repo, home, "import", dry_run=True)
            self.assertFalse((home / "CLAUDE.md").exists())


if __name__ == "__main__":
    unittest.main()
