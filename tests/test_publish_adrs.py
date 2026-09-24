import io
import os
import shutil
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

import publish_adrs as pa

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "publish_adrs"


def _copy_fixture_brain(dest: Path) -> Path:
    brain = dest / "brain"
    shutil.copytree(FIXTURES / "brain", brain)
    shutil.copy(FIXTURES / "config.toml", brain / "adr-publish.toml")
    return brain


class LoadConfigTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain = _copy_fixture_brain(Path(self._tmp.name))
        self.cfg = pa.load_config(self.brain / "adr-publish.toml")

    def tearDown(self):
        self._tmp.cleanup()

    def test_target(self):
        self.assertEqual(self.cfg.target.github, "acme/docs-repo")
        self.assertEqual(self.cfg.target.path_env, "ACME_DOCS_PATH")
        self.assertEqual(self.cfg.target.adr_root, "adr")
        self.assertEqual(self.cfg.target.reserved_from, 1000)
        self.assertEqual(self.cfg.target.template, "skills/create-adr/adr-template.md")

    def test_repos_keep_file_order(self):
        self.assertEqual([r.slug for r in self.cfg.repos], ["alpha", "beta"])
        self.assertEqual(self.cfg.repos[0].brain_dirs, ("alpha", "alpha-old"))
        self.assertEqual(self.cfg.repos[0].github, "acme/alpha")

    def test_publish_and_brain_root(self):
        self.assertEqual(self.cfg.publish["beta"], ("0001-b.md", "unnumbered-note.md"))
        self.assertEqual(self.cfg.brain_root, self.brain)

    def test_missing_required_key_raises(self):
        (self.brain / "adr-publish.toml").write_text(
            '[target]\ngithub = "acme/docs-repo"\n', encoding="utf-8")
        with self.assertRaises(pa.ConfigError):
            pa.load_config(self.brain / "adr-publish.toml")

    def _write(self, text):
        (self.brain / "adr-publish.toml").write_text(text, encoding="utf-8")

    def test_brain_dirs_string_is_rejected(self):
        self._write(
            '[target]\ngithub = "acme/docs-repo"\npath_env = "X"\ntemplate = "t.md"\n'
            '[repos.alpha]\ngithub = "acme/alpha"\nbrain_dirs = "alpha"\n')
        with self.assertRaisesRegex(pa.ConfigError, r"brain_dirs.*list of strings"):
            pa.load_config(self.brain / "adr-publish.toml")

    def test_reserved_from_non_int_is_config_error(self):
        self._write(
            '[target]\ngithub = "acme/docs-repo"\npath_env = "X"\ntemplate = "t.md"\n'
            'reserved_from = "soon"\n[repos.alpha]\ngithub = "acme/alpha"\nbrain_dirs = ["alpha"]\n')
        with self.assertRaisesRegex(pa.ConfigError, r"reserved_from.*integer"):
            pa.load_config(self.brain / "adr-publish.toml")

    def test_missing_target_table_names_top_level(self):
        self._write('[repos.alpha]\ngithub = "acme/alpha"\nbrain_dirs = ["alpha"]\n')
        with self.assertRaisesRegex(pa.ConfigError, r"missing `target` in the top level"):
            pa.load_config(self.brain / "adr-publish.toml")

    def test_publish_value_string_is_rejected(self):
        self._write(
            '[target]\ngithub = "acme/docs-repo"\npath_env = "X"\ntemplate = "t.md"\n'
            '[repos.alpha]\ngithub = "acme/alpha"\nbrain_dirs = ["alpha"]\n'
            '[publish]\n"alpha" = "0002-thing.md"\n')
        with self.assertRaisesRegex(pa.ConfigError, r"list of strings"):
            pa.load_config(self.brain / "adr-publish.toml")


class BuildEntriesTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain = _copy_fixture_brain(Path(self._tmp.name))
        self.cfg = pa.load_config(self.brain / "adr-publish.toml")

    def tearDown(self):
        self._tmp.cleanup()

    def test_entries_resolve_slug_and_paths(self):
        entries = pa.build_entries(self.cfg)
        by_target = {e.target_rel: e for e in entries}
        self.assertEqual(sorted(by_target), [
            "alpha/0002-thing.md", "alpha/0009-later.md",
            "beta/0001-b.md", "beta/unnumbered-note.md",
        ])
        e = by_target["alpha/0002-thing.md"]
        self.assertEqual(e.brain_dir, "alpha")
        self.assertEqual(e.slug, "alpha")
        self.assertEqual(e.github, "acme/alpha")
        self.assertEqual(e.source_rel, "memory/repo/alpha/adr/0002-thing.md")
        self.assertEqual(e.source, self.brain / "memory/repo/alpha/adr/0002-thing.md")

    def test_unmapped_brain_dir_raises(self):
        cfg = pa.Config(target=self.cfg.target, repos=self.cfg.repos,
                        publish={**self.cfg.publish, "gamma": ("0001-g.md",)},
                        brain_root=self.cfg.brain_root)
        with self.assertRaisesRegex(pa.ConfigError, "gamma"):
            pa.build_entries(cfg)

    def test_target_collision_raises(self):
        cfg = pa.Config(target=self.cfg.target, repos=self.cfg.repos,
                        publish={**self.cfg.publish, "alpha-old": ("0002-thing.md",)},
                        brain_root=self.cfg.brain_root)
        with self.assertRaisesRegex(pa.ConfigError, "alpha/0002-thing.md"):
            pa.build_entries(cfg)

    def test_missing_source_raises(self):
        cfg = pa.Config(target=self.cfg.target, repos=self.cfg.repos,
                        publish={**self.cfg.publish, "beta": ("0001-b.md", "0404-missing.md")},
                        brain_root=self.cfg.brain_root)
        with self.assertRaisesRegex(pa.ConfigError, "0404-missing.md"):
            pa.build_entries(cfg)


class PathValidationTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain = _copy_fixture_brain(Path(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()

    def _write(self, text):
        (self.brain / "adr-publish.toml").write_text(text, encoding="utf-8")

    def test_adr_root_dotdot_is_rejected(self):
        self._write('''[target]
github = "acme/docs-repo"
path_env = "X"
template = "t.md"
adr_root = ".."

[repos.alpha]
github = "acme/alpha"
brain_dirs = ["alpha"]
''')
        with self.assertRaisesRegex(pa.ConfigError, r"adr_root"):
            pa.load_config(self.brain / "adr-publish.toml")

    def test_adr_root_absolute_is_rejected(self):
        # Both forms are rejected on every platform: the drive-letter form
        # is not `Path.is_absolute()` on Windows, so the allowlist regex
        # (not an is_absolute() check) is what has to catch it.
        for abs_path in ("C:/abs", "/abs"):
            self._write(f'''[target]
github = "acme/docs-repo"
path_env = "X"
template = "t.md"
adr_root = "{abs_path}"

[repos.alpha]
github = "acme/alpha"
brain_dirs = ["alpha"]
''')
            with self.assertRaisesRegex(pa.ConfigError, r"adr_root"):
                pa.load_config(self.brain / "adr-publish.toml")

    def test_adr_root_empty_is_rejected(self):
        self._write('''[target]
github = "acme/docs-repo"
path_env = "X"
template = "t.md"
adr_root = ""

[repos.alpha]
github = "acme/alpha"
brain_dirs = ["alpha"]
''')
        with self.assertRaisesRegex(pa.ConfigError, r"adr_root"):
            pa.load_config(self.brain / "adr-publish.toml")

    def test_adr_root_nested_relative_is_allowed(self):
        self._write('''[target]
github = "acme/docs-repo"
path_env = "X"
template = "t.md"
adr_root = "docs/adr"

[repos.alpha]
github = "acme/alpha"
brain_dirs = ["alpha"]
''')
        cfg = pa.load_config(self.brain / "adr-publish.toml")
        self.assertEqual(cfg.target.adr_root, "docs/adr")

    def test_repo_slug_dotdot_is_rejected(self):
        self._write('''[target]
github = "acme/docs-repo"
path_env = "X"
template = "t.md"

[repos.".."]
github = "acme/alpha"
brain_dirs = ["alpha"]
''')
        with self.assertRaisesRegex(pa.ConfigError, r"slug"):
            pa.load_config(self.brain / "adr-publish.toml")

    def test_repo_slug_with_separator_is_rejected(self):
        self._write('''[target]
github = "acme/docs-repo"
path_env = "X"
template = "t.md"

[repos."a/b"]
github = "acme/alpha"
brain_dirs = ["alpha"]
''')
        with self.assertRaisesRegex(pa.ConfigError, r"slug"):
            pa.load_config(self.brain / "adr-publish.toml")

    def test_brain_dir_with_dotdot_is_rejected(self):
        self._write('''[target]
github = "acme/docs-repo"
path_env = "X"
template = "t.md"

[repos.alpha]
github = "acme/alpha"
brain_dirs = ["../x"]
''')
        with self.assertRaisesRegex(pa.ConfigError, r"brain_dirs"):
            pa.load_config(self.brain / "adr-publish.toml")

    def test_publish_filename_with_dotdot_is_rejected(self):
        self._write('''[target]
github = "acme/docs-repo"
path_env = "X"
template = "t.md"

[repos.alpha]
github = "acme/alpha"
brain_dirs = ["alpha"]

[publish]
"alpha" = ["../../../../x.md"]
''')
        with self.assertRaisesRegex(pa.ConfigError, r"publish"):
            pa.load_config(self.brain / "adr-publish.toml")

    def test_repo_slug_drive_letter_is_rejected(self):
        self._write('''[target]
github = "acme/docs-repo"
path_env = "X"
template = "t.md"

[repos."C:"]
github = "acme/alpha"
brain_dirs = ["alpha"]
''')
        with self.assertRaisesRegex(pa.ConfigError, r"slug"):
            pa.load_config(self.brain / "adr-publish.toml")

    def test_adr_root_drive_relative_is_rejected(self):
        self._write('''[target]
github = "acme/docs-repo"
path_env = "X"
template = "t.md"
adr_root = "C:adr"

[repos.alpha]
github = "acme/alpha"
brain_dirs = ["alpha"]
''')
        with self.assertRaisesRegex(pa.ConfigError, r"adr_root"):
            pa.load_config(self.brain / "adr-publish.toml")

    def test_slug_ntfs_stream_is_rejected(self):
        self._write('''[target]
github = "acme/docs-repo"
path_env = "X"
template = "t.md"

[repos."alpha:ads"]
github = "acme/alpha"
brain_dirs = ["alpha"]
''')
        with self.assertRaisesRegex(pa.ConfigError, r"slug"):
            pa.load_config(self.brain / "adr-publish.toml")

    def test_adr_root_backslash_is_rejected(self):
        self._write('''[target]
github = "acme/docs-repo"
path_env = "X"
template = "t.md"
adr_root = "docs\\\\adr"

[repos.alpha]
github = "acme/alpha"
brain_dirs = ["alpha"]
''')
        with self.assertRaisesRegex(pa.ConfigError, r"adr_root"):
            pa.load_config(self.brain / "adr-publish.toml")

    def test_adr_root_rooted_without_drive_is_rejected(self):
        self._write('''[target]
github = "acme/docs-repo"
path_env = "X"
template = "t.md"
adr_root = "/abs"

[repos.alpha]
github = "acme/alpha"
brain_dirs = ["alpha"]
''')
        with self.assertRaisesRegex(pa.ConfigError, r"adr_root"):
            pa.load_config(self.brain / "adr-publish.toml")

    def test_nested_adr_root_and_dotted_slug_load(self):
        self._write('''[target]
github = "acme/docs-repo"
path_env = "X"
template = "t.md"
adr_root = "docs/adr"

[repos."widget.service-v2"]
github = "acme/alpha"
brain_dirs = ["alpha"]
''')
        cfg = pa.load_config(self.brain / "adr-publish.toml")
        self.assertEqual(cfg.target.adr_root, "docs/adr")
        self.assertEqual(cfg.repos[0].slug, "widget.service-v2")


def _git(args, cwd):
    subprocess.run(["git", *args], cwd=cwd, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _make_docs_checkout(path: Path, origin="https://github.com/acme/docs-repo.git") -> Path:
    path.mkdir(parents=True)
    _git(["init", "-q", "-b", "main"], path)
    _git(["config", "user.email", "t@example.com"], path)
    _git(["config", "user.name", "t"], path)
    _git(["remote", "add", "origin", origin], path)
    (path / "README.md").write_text("# docs\n", encoding="utf-8")
    _git(["add", "README.md"], path)
    _git(["commit", "-q", "-m", "init"], path)
    return path


class PreconditionsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.brain = _copy_fixture_brain(base)
        _git(["init", "-q"], self.brain)
        _git(["config", "user.email", "t@example.com"], self.brain)
        _git(["config", "user.name", "t"], self.brain)
        _git(["add", "."], self.brain)
        _git(["commit", "-q", "-m", "brain"], self.brain)
        self.docs = _make_docs_checkout(base / "docs")
        self.cfg = pa.load_config(self.brain / "adr-publish.toml")
        self.entries = pa.build_entries(self.cfg)

    def tearDown(self):
        self._tmp.cleanup()

    def test_clean_checkout_passes(self):
        self.assertEqual(pa.check_preconditions(self.cfg, self.entries, self.docs), [])

    def test_not_a_git_checkout(self):
        plain = Path(self._tmp.name) / "plain"
        plain.mkdir()
        errs = pa.check_preconditions(self.cfg, self.entries, plain)
        self.assertTrue(any("not a git checkout" in e for e in errs), errs)

    def test_missing_docs_dir_is_an_error(self):
        missing = Path(self._tmp.name) / "does-not-exist"
        errs = pa.check_preconditions(self.cfg, self.entries, missing)
        self.assertEqual(len(errs), 1, errs)
        self.assertIn("does not exist", errs[0])

    def test_origin_check_is_case_insensitive(self):
        other = _make_docs_checkout(Path(self._tmp.name) / "cased",
                                    origin="https://github.com/ACME/Docs-Repo.git")
        self.assertEqual(pa.check_preconditions(self.cfg, self.entries, other), [])

    def test_wrong_origin(self):
        other = _make_docs_checkout(Path(self._tmp.name) / "other",
                                    origin="https://github.com/acme/elsewhere.git")
        errs = pa.check_preconditions(self.cfg, self.entries, other)
        self.assertTrue(any("acme/docs-repo" in e for e in errs), errs)

    def test_dirty_tree(self):
        (self.docs / "scratch.md").write_text("x\n", encoding="utf-8")
        errs = pa.check_preconditions(self.cfg, self.entries, self.docs)
        self.assertTrue(any("not clean" in e for e in errs), errs)

    def test_missing_template(self):
        (self.brain / "skills/create-adr/adr-template.md").unlink()
        errs = pa.check_preconditions(self.cfg, self.entries, self.docs)
        self.assertTrue(any("adr-template.md" in e for e in errs), errs)

    def test_brain_sha_is_short_hex(self):
        self.assertRegex(pa.brain_sha(self.cfg), r"^[0-9a-f]{7,}$")


class ResolveDocsPathTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain = _copy_fixture_brain(Path(self._tmp.name))
        self.cfg = pa.load_config(self.brain / "adr-publish.toml")

    def tearDown(self):
        self._tmp.cleanup()
        os.environ.pop("ACME_DOCS_PATH", None)

    def test_override_wins(self):
        os.environ["ACME_DOCS_PATH"] = "/from/env"
        self.assertEqual(pa.resolve_docs_path(self.cfg, Path("/override")), Path("/override").resolve())

    def test_env_used(self):
        os.environ["ACME_DOCS_PATH"] = self._tmp.name
        self.assertEqual(pa.resolve_docs_path(self.cfg, None), Path(self._tmp.name).resolve())

    def test_neither_raises(self):
        with self.assertRaisesRegex(pa.PublishError, "ACME_DOCS_PATH"):
            pa.resolve_docs_path(self.cfg, None)


class RenderIndexTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.brain = _copy_fixture_brain(Path(self._tmp.name))
        self.cfg = pa.load_config(self.brain / "adr-publish.toml")
        self.rows = [
            pa.IndexRow("alpha", "0002", "ADR 0002: Do the thing", "accepted", "Do the thing.", "alpha/0002-thing.md"),
            pa.IndexRow("alpha", "0009", "ADR-0009: Later", "as-built", "", "alpha/0009-later.md"),
            pa.IndexRow("beta", "0001", "ADR 0001: Beta one", "accepted", "Beta one.", "beta/0001-b.md"),
            pa.IndexRow("beta", "—", "", "unknown", "An unnumbered ADR.", "beta/unnumbered-note.md"),
        ]

    def tearDown(self):
        self._tmp.cleanup()

    def test_sections_tables_and_footer(self):
        out = pa.render_index(self.cfg, self.rows, "abc1234", "2026-09-10")
        self.assertIn("# Architecture Decision Records\n", out)
        self.assertIn("numbered below 1000 are generated", out)
        self.assertIn("`TEMPLATE.md`", out)
        self.assertIn("Any other Markdown file inside these folders is removed on the next "
                      "sync — number it, or keep it outside this tree.", out)
        alpha = out.index("## acme/alpha")
        beta = out.index("## acme/beta")
        self.assertLess(alpha, beta)
        self.assertIn("| 0002 | [ADR 0002: Do the thing](alpha/0002-thing.md) | accepted | Do the thing. |", out)
        self.assertIn("| — | [unnumbered-note.md](beta/unnumbered-note.md) | unknown | An unnumbered ADR. |", out)
        self.assertTrue(out.endswith("_Synced 2026-09-10 from brain commit abc1234._\n"))

    def test_pipes_in_cells_are_escaped(self):
        rows = [pa.IndexRow("alpha", "0002", "a | b", "accepted", "c | d", "alpha/x.md")]
        out = pa.render_index(self.cfg, rows, "abc1234", "2026-09-10")
        self.assertIn("| 0002 | [a \\| b](alpha/x.md) | accepted | c \\| d |", out)

    def test_strip_footer(self):
        out = pa.render_index(self.cfg, self.rows, "abc1234", "2026-09-10")
        stripped = pa.strip_index_footer(out)
        self.assertNotIn("_Synced", stripped)
        self.assertEqual(pa.strip_index_footer(pa.render_index(self.cfg, self.rows, "fff9999", "2027-01-01")),
                         stripped)

    def test_brackets_in_title_are_escaped(self):
        rows = [pa.IndexRow("alpha", "0002", "[Superseded] old way", "superseded", "", "alpha/x.md")]
        out = pa.render_index(self.cfg, rows, "abc1234", "2026-09-10")
        self.assertIn("| 0002 | [\\[Superseded\\] old way](alpha/x.md) | superseded |  |", out)

    def test_rows_within_slug_are_sorted_by_number_regardless_of_input_order(self):
        rows = [
            pa.IndexRow("alpha", "0009", "Later", "as-built", "", "alpha/0009-later.md"),
            pa.IndexRow("alpha", "0002", "Thing", "accepted", "", "alpha/0002-thing.md"),
            pa.IndexRow("alpha", "—", "Note", "unknown", "", "alpha/note.md"),
        ]
        out = pa.render_index(self.cfg, rows, "abc1234", "2026-09-10")
        i_0002 = out.index("| 0002 |")
        i_0009 = out.index("| 0009 |")
        i_dash = out.index("| — |")
        self.assertLess(i_0002, i_0009)
        self.assertLess(i_0009, i_dash)


class AdrNumberTest(unittest.TestCase):
    def test_leading_four_digits(self):
        self.assertEqual(pa.adr_number("0009-later.md"), 9)

    def test_unnumbered_is_none(self):
        self.assertIsNone(pa.adr_number("unnumbered-note.md"))

    def test_three_digits_is_none(self):
        self.assertIsNone(pa.adr_number("009-short.md"))

    def test_reserved_range(self):
        self.assertEqual(pa.adr_number("1001-contractor.md"), 1001)


class PlanApplyTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.brain = _copy_fixture_brain(base)
        self.docs = _make_docs_checkout(base / "docs")
        self.cfg = pa.load_config(self.brain / "adr-publish.toml")
        self.entries = pa.build_entries(self.cfg)

    def tearDown(self):
        self._tmp.cleanup()

    def plan(self, synced_at="2026-09-10", sha="abc1234"):
        return pa.compute_plan(self.cfg, self.entries, self.docs, synced_at=synced_at, brain_sha=sha)

    def test_fresh_target_adds_everything(self):
        p = self.plan()
        self.assertEqual(sorted(p.added), [
            "README.md", "TEMPLATE.md", "alpha/0002-thing.md", "alpha/0009-later.md",
            "beta/0001-b.md", "beta/unnumbered-note.md",
        ])
        self.assertEqual(p.updated, [])
        self.assertEqual(p.deleted, [])

    def test_transformed_content(self):
        p = self.plan()
        text = p.contents["alpha/0002-thing.md"]
        self.assertIn('source_repo: "acme/alpha"', text)
        self.assertIn("[ADR-0009](0009-later.md)", text)
        self.assertIn("ADR-0006 (not yet implemented — not published)", text)
        self.assertIn("readiness note (brain-internal note, not published)", text)
        self.assertIn("[beta 0001](../beta/0001-b.md#decision)", text)
        self.assertNotIn("[Source:", text)

    def test_apply_then_replan_is_noop(self):
        pa.apply_plan(self.plan(), self.docs, self.cfg.target.adr_root)
        self.assertTrue((self.docs / "adr/alpha/0002-thing.md").is_file())
        self.assertTrue((self.docs / "adr/README.md").is_file())
        self.assertTrue((self.docs / "adr/TEMPLATE.md").is_file())
        p2 = self.plan(synced_at="2027-01-01", sha="fff9999")
        self.assertEqual((p2.added, p2.updated, p2.deleted), ([], [], []))
        self.assertEqual(len(p2.unchanged), 6)
        # the old dates survive
        self.assertIn('synced_at: "2026-09-10"',
                      (self.docs / "adr/alpha/0002-thing.md").read_text(encoding="utf-8"))
        self.assertIn("_Synced 2026-09-10 from brain commit abc1234._",
                      (self.docs / "adr/README.md").read_text(encoding="utf-8"))

    def test_body_change_updates_file_and_index_footer(self):
        pa.apply_plan(self.plan(), self.docs, self.cfg.target.adr_root)
        src = self.brain / "memory/repo/alpha/adr/0009-later.md"
        src.write_text(src.read_text(encoding="utf-8") + "\nMore.\n", encoding="utf-8")
        p2 = self.plan(synced_at="2027-01-01", sha="fff9999")
        self.assertEqual(sorted(p2.updated), ["README.md", "alpha/0009-later.md"])
        self.assertIn('synced_at: "2027-01-01"', p2.contents["alpha/0009-later.md"])
        self.assertTrue(p2.contents["README.md"].endswith("from brain commit fff9999._\n"))

    def test_orphans_below_reserved_are_deleted_reserved_kept(self):
        pa.apply_plan(self.plan(), self.docs, self.cfg.target.adr_root)
        (self.docs / "adr/alpha/0007-stale.md").write_text("old\n", encoding="utf-8")
        (self.docs / "adr/alpha/1001-contractor.md").write_text("theirs\n", encoding="utf-8")
        (self.docs / "adr/beta/note-without-number.md").write_text("x\n", encoding="utf-8")
        p2 = self.plan()
        self.assertEqual(sorted(p2.deleted), ["alpha/0007-stale.md", "beta/note-without-number.md"])
        pa.apply_plan(p2, self.docs, self.cfg.target.adr_root)
        self.assertFalse((self.docs / "adr/alpha/0007-stale.md").exists())
        self.assertTrue((self.docs / "adr/alpha/1001-contractor.md").exists())

    def test_undecodable_existing_target_raises(self):
        pa.apply_plan(self.plan(), self.docs, self.cfg.target.adr_root)
        (self.docs / "adr/alpha/0002-thing.md").write_bytes(b"\xff\xfe")
        with self.assertRaisesRegex(pa.PublishError, "cannot decode"):
            self.plan(synced_at="2027-01-01", sha="fff9999")

    def test_apply_refuses_target_outside_root(self):
        plan = pa.Plan(added=["x"], contents={"../escape.md": "x\n"})
        with self.assertRaisesRegex(pa.PublishError, "outside"):
            pa.apply_plan(plan, self.docs, self.cfg.target.adr_root)
        self.assertFalse((self.docs / "escape.md").exists())

    def test_directory_named_md_is_not_orphaned(self):
        pa.apply_plan(self.plan(), self.docs, self.cfg.target.adr_root)
        (self.docs / "adr/beta/weird.md").mkdir()
        p2 = self.plan()
        self.assertNotIn("beta/weird.md", p2.deleted)

    def test_apply_only_touches_files_under_adr_root(self):
        """Regression guard for the fixture config: with the adr_root that
        this test class's config actually uses, apply_plan must never write
        or delete anything outside <docs>/adr/. This is not an escape-attempt
        test (see test_apply_refuses_target_outside_root for that) — it just
        pins the normal, well-behaved-config code path."""
        def snapshot():
            return {p.relative_to(self.docs): p.read_bytes()
                    for p in self.docs.rglob("*")
                    if p.is_file() and ".git" not in p.parts}

        before = snapshot()
        pa.apply_plan(self.plan(), self.docs, self.cfg.target.adr_root)
        after = snapshot()
        changed = (set(before) | set(after)) - {
            rel for rel in (set(before) & set(after)) if before[rel] == after[rel]
        }
        self.assertTrue(changed)
        for rel in changed:
            self.assertEqual(rel.parts[0], "adr", f"{rel} changed outside adr_root")

    def test_renamed_slug_folder_is_orphaned(self):
        pa.apply_plan(self.plan(), self.docs, self.cfg.target.adr_root)
        renamed_repos = tuple(
            pa.RepoMap(slug="beta-renamed", github=r.github, brain_dirs=r.brain_dirs)
            if r.slug == "beta" else r
            for r in self.cfg.repos
        )
        cfg2 = pa.Config(target=self.cfg.target, repos=renamed_repos,
                         publish=self.cfg.publish, brain_root=self.cfg.brain_root)
        entries2 = pa.build_entries(cfg2)
        p2 = pa.compute_plan(cfg2, entries2, self.docs, synced_at="2026-09-10", brain_sha="abc1234")
        self.assertEqual(sorted(p2.deleted), ["beta/0001-b.md", "beta/unnumbered-note.md"])
        self.assertIn("beta-renamed/0001-b.md", p2.added)

    def test_unknown_folder_reserved_files_survive(self):
        pa.apply_plan(self.plan(), self.docs, self.cfg.target.adr_root)
        extra = self.docs / "adr" / "extra"
        extra.mkdir()
        (extra / "1001-theirs.md").write_text("theirs\n", encoding="utf-8")
        (extra / "0001-stale.md").write_text("stale\n", encoding="utf-8")
        p2 = self.plan()
        self.assertEqual(p2.deleted, ["extra/0001-stale.md"])

    def test_written_files_use_lf(self):
        pa.apply_plan(self.plan(), self.docs, self.cfg.target.adr_root)
        raw = (self.docs / "adr/alpha/0002-thing.md").read_bytes()
        self.assertNotIn(b"\r", raw)

    def test_index_description_with_quotes_is_not_escaped(self):
        src = self.brain / "memory/repo/beta/adr/0001-b.md"
        src.write_text(src.read_text(encoding="utf-8").replace(
            "description: Beta one.", 'description: Always send "en" and a \\ backslash.'),
            encoding="utf-8")
        p = self.plan()
        self.assertIn('| 0001 | [ADR 0001: Beta one](beta/0001-b.md) | accepted | Always send "en" and a \\\\ backslash. |',
                      p.contents["README.md"])
        self.assertIn('description: "Always send \\"en\\" and a \\\\ backslash."', p.contents["beta/0001-b.md"])


class CliTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.brain = _copy_fixture_brain(base)
        _git(["init", "-q"], self.brain)
        _git(["config", "user.email", "t@example.com"], self.brain)
        _git(["config", "user.name", "t"], self.brain)
        _git(["add", "."], self.brain)
        _git(["commit", "-q", "-m", "brain"], self.brain)
        self.docs = _make_docs_checkout(base / "docs")
        self.config = self.brain / "adr-publish.toml"

    def tearDown(self):
        self._tmp.cleanup()

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = pa.main(["--config", str(self.config), "--docs-path", str(self.docs), *args])
        return code, out.getvalue(), err.getvalue()

    def test_dry_run_reports_and_writes_nothing(self):
        code, out, _ = self.run_cli()
        self.assertEqual(code, 0)
        self.assertIn("+ add     alpha/0002-thing.md", out)
        self.assertIn("+++ ADDED  alpha/0002-thing.md", out)
        self.assertIn("(dry run", out)
        self.assertFalse((self.docs / "adr").exists())

    def test_missing_docs_path_is_exit_2(self):
        missing = Path(self._tmp.name) / "nope"
        code, _, err = self.run_cli("--docs-path", str(missing))
        self.assertEqual(code, 2)
        self.assertIn("does not exist", err)

    def test_apply_writes_and_second_run_is_quiet(self):
        code, out, _ = self.run_cli("--apply")
        self.assertEqual(code, 0)
        self.assertIn("published:", out)
        self.assertTrue((self.docs / "adr/README.md").is_file())
        _git(["add", "."], self.docs)
        _git(["commit", "-q", "-m", "publish"], self.docs)
        code, out, _ = self.run_cli("--apply")
        self.assertEqual(code, 0)
        self.assertIn("nothing to do", out)

    def test_dirty_docs_is_exit_2(self):
        (self.docs / "junk.md").write_text("x\n", encoding="utf-8")
        code, _, err = self.run_cli()
        self.assertEqual(code, 2)
        self.assertIn("not clean", err)

    def test_bad_config_is_exit_2(self):
        self.config.write_text("[target]\n", encoding="utf-8")
        code, _, err = self.run_cli()
        self.assertEqual(code, 2)
        self.assertIn("missing", err)

    def test_diff_for_updated_file(self):
        self.run_cli("--apply")
        _git(["add", "."], self.docs)
        _git(["commit", "-q", "-m", "publish"], self.docs)
        src = self.brain / "memory/repo/beta/adr/0001-b.md"
        src.write_text(src.read_text(encoding="utf-8") + "\nChanged.\n", encoding="utf-8")
        code, out, _ = self.run_cli()
        self.assertEqual(code, 0)
        self.assertIn("~ update  beta/0001-b.md", out)
        self.assertIn("+Changed.", out)


if __name__ == "__main__":
    unittest.main()
