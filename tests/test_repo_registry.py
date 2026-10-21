"""Tests for the repository registry: loading, validation, and the two aliases.

`tests/` is synced to instances by `scripts/sync_from_upstream.py`; `memory/` and
`repo-registry.toml` deliberately are **not**. So every behavioural test here runs
against a fixture written into a temp dir, never against this brain's own repos —
a downstream instance has different ones, and a test that knew ours would fail
there for no reason. The one test that reads the real registry is guarded by
`skipUnless(... .exists())` and asserts only that it validates clean, which is
true of any correctly-maintained registry regardless of what is in it.
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "hooks"))
sys.path.insert(0, str(ROOT / "scripts"))
import _repo_registry as rr  # noqa: E402
import _trail_scope as scope  # noqa: E402
import assess_repo_readiness as arr  # noqa: E402
import check_repo_registry as crr  # noqa: E402
import compute_readiness as cr  # noqa: E402

REAL_REGISTRY = ROOT / "repo-registry.toml"
REAL_MEMORY_ROOT = ROOT / "memory"
REAL_ADR_CONFIG = ROOT / "adr-publish.toml"

# A healthy two-repo registry, one of them carrying a historical trail key. Small
# enough to read at a glance; every validation test below mutates a copy of it.
HEALTHY = """
[dirs.widget-service]
github = "acme/widget-service"
trail_keys = ["widget-service", "old-widget-service"]

[dirs.web]
github = "acme/web"
"""


# ── helpers ────────────────────────────────────────────────────────────────

class _Tree:
    """A temp brain: a registry file plus `memory/repo/<dir>/` dirs."""

    def __init__(self, stack, toml_text: str, dirs: tuple[str, ...]):
        self.base = Path(stack.enter_context(tempfile.TemporaryDirectory()))
        self.registry = self.base / "repo-registry.toml"
        self.registry.write_text(toml_text, encoding="utf-8")
        self.memory_root = self.base / "memory"
        for name in dirs:
            (self.memory_root / "repo" / name).mkdir(parents=True, exist_ok=True)

    def load(self) -> rr.Registry:
        return rr.load_registry(self.registry)

    def problems(self, *, adr_config=None) -> list[str]:
        return rr.validate(
            self.load(), memory_root=self.memory_root, adr_config=adr_config
        )

    def write_adr_config(self, text: str) -> Path:
        path = self.base / "adr-publish.toml"
        path.write_text(text, encoding="utf-8")
        return path


class RegistryTestCase(unittest.TestCase):
    """Base class owning the temp-dir stack and the alias-cache reset.

    The alias cache is process-global by design (it is read once per trail record
    on a hot path). Clearing it around every test keeps one test's fixture from
    leaking into the next — and keeps this module from disturbing the rest of the
    suite, which runs in the same process.
    """

    def setUp(self):
        import contextlib

        self._stack = contextlib.ExitStack()
        self.addCleanup(self._stack.close)
        rr.clear_cache()
        self.addCleanup(rr.clear_cache)

    def tree(self, toml_text: str = HEALTHY,
             dirs: tuple[str, ...] = ("widget-service", "web")) -> _Tree:
        return _Tree(self._stack, toml_text, dirs)


# ── loading ────────────────────────────────────────────────────────────────

class LoadRegistry(RegistryTestCase):

    def test_loads_entries_and_defaults(self):
        reg = self.tree().load()
        by_dir = reg.by_dir()
        self.assertEqual(sorted(by_dir), ["web", "widget-service"])
        web = by_dir["web"]
        self.assertEqual(web.github, "acme/web")
        self.assertTrue(web.clone_expected, "clone_expected defaults to true")
        self.assertEqual(web.note, "")
        self.assertEqual(web.declared_trail_keys, ())

    def test_a_dir_implicitly_owns_the_trail_key_equal_to_its_own_name(self):
        """`web` declares no keys, yet must own `web` — otherwise the alias map
        would answer None for the overwhelmingly common case and every caller
        would need its own fallback."""
        reg = self.tree().load()
        self.assertEqual(reg.by_dir()["web"].trail_keys, ("web",))
        self.assertEqual(reg.dir_for_trail_key("web"), "web")

    def test_declared_keys_are_kept_separately_and_deduped(self):
        reg = self.tree("""
[dirs.svc]
github = "acme/svc"
trail_keys = ["svc", "old", "old"]
""", dirs=("svc",)).load()
        entry = reg.by_dir()["svc"]
        self.assertEqual(entry.trail_keys, ("svc", "old"))
        self.assertEqual(entry.declared_trail_keys, ("svc", "old", "old"))

    def test_github_may_be_omitted(self):
        reg = self.tree("""
[dirs.svc]
clone_expected = false
note = "client repo"
""", dirs=("svc",)).load()
        self.assertEqual(reg.by_dir()["svc"].github, "")

    def test_absent_file_raises(self):
        with self.assertRaises(rr.RegistryError) as ctx:
            rr.load_registry(Path(tempfile.gettempdir()) / "definitely-not-here.toml")
        self.assertIn("no repository registry", str(ctx.exception))

    def test_unparseable_toml_raises(self):
        with self.assertRaises(rr.RegistryError):
            self.tree("[dirs.svc\n", dirs=("svc",)).load()

    def test_missing_dirs_table_raises(self):
        with self.assertRaises(rr.RegistryError) as ctx:
            self.tree("[shared_slugs]\n", dirs=()).load()
        self.assertIn("[dirs.", str(ctx.exception))

    def test_unknown_entry_key_raises(self):
        """A typo'd `trail_key` reads as a declared alias and behaves as none at
        all — the exact failure the registry exists to prevent, so it is loud."""
        with self.assertRaises(rr.RegistryError) as ctx:
            self.tree("""
[dirs.svc]
github = "acme/svc"
trail_key = ["old"]
""", dirs=("svc",)).load()
        self.assertIn("trail_key", str(ctx.exception))

    def test_unknown_top_level_table_raises(self):
        with self.assertRaises(rr.RegistryError) as ctx:
            self.tree(HEALTHY + "\n[aliases]\nx = 1\n").load()
        self.assertIn("aliases", str(ctx.exception))

    def test_malformed_slug_raises(self):
        for bad in ('"acme"', '"acme/web/extra"', '"https://github.com/acme/web"', "5"):
            with self.subTest(bad=bad):
                with self.assertRaises(rr.RegistryError):
                    self.tree(f"[dirs.web]\ngithub = {bad}\n", dirs=("web",)).load()

    def test_non_boolean_clone_expected_raises(self):
        with self.assertRaises(rr.RegistryError):
            self.tree('[dirs.web]\ngithub = "acme/web"\nclone_expected = "no"\n',
                      dirs=("web",)).load()

    def test_trail_keys_must_be_a_list_of_path_segments(self):
        for bad in ('"old"', '["../escape"]', '[1]', '["has/slash"]'):
            with self.subTest(bad=bad):
                with self.assertRaises(rr.RegistryError):
                    self.tree(f'[dirs.web]\ngithub = "acme/web"\ntrail_keys = {bad}\n',
                              dirs=("web",)).load()

    def test_shared_slug_needs_at_least_two_dirs(self):
        with self.assertRaises(rr.RegistryError) as ctx:
            self.tree(HEALTHY + '\n[shared_slugs]\n"acme/web" = ["web"]\n').load()
        self.assertIn("not an exception", str(ctx.exception))

    def test_shared_slugs_must_be_a_table(self):
        with self.assertRaises(rr.RegistryError):
            self.tree(HEALTHY + "\nshared_slugs = 1\n").load()


# ── validation ─────────────────────────────────────────────────────────────

class Validate(RegistryTestCase):

    def test_healthy_registry_has_no_problems(self):
        self.assertEqual(self.tree().problems(), [])

    def test_unregistered_memory_dir_is_reported(self):
        problems = self.tree(dirs=("widget-service", "web", "stowaway")).problems()
        self.assertEqual(len(problems), 1)
        self.assertIn("stowaway", problems[0])
        self.assertIn("not registered", problems[0])

    def test_registered_dir_without_a_memory_dir_is_reported(self):
        problems = self.tree(dirs=("widget-service",)).problems()
        self.assertEqual(len(problems), 1)
        self.assertIn("[dirs.web]", problems[0])
        self.assertIn("does not exist", problems[0])

    def test_both_directions_are_reported_in_one_pass(self):
        """All findings, not the first: the file is hand-edited and a check that
        stops at one mistake costs an edit/run cycle per mistake."""
        problems = self.tree(dirs=("widget-service", "stowaway")).problems()
        self.assertEqual(len(problems), 2)
        self.assertTrue(any("stowaway" in p for p in problems))
        self.assertTrue(any("[dirs.web]" in p for p in problems))

    def test_two_dirs_sharing_a_slug_without_an_exception_is_reported(self):
        problems = self.tree("""
[dirs.web]
github = "acme/web"

[dirs.web-old]
github = "acme/web"
""", dirs=("web", "web-old")).problems()
        self.assertEqual(len(problems), 1)
        self.assertIn("acme/web", problems[0])
        self.assertIn("web-old", problems[0])

    def test_a_declared_shared_slug_is_accepted(self):
        self.assertEqual(self.tree("""
[dirs.web]
github = "acme/web"

[dirs.web-old]
github = "acme/web"

[shared_slugs]
"acme/web" = ["web", "web-old"]
""", dirs=("web", "web-old")).problems(), [])

    def test_a_shared_slug_declaring_the_wrong_dirs_is_reported(self):
        problems = self.tree("""
[dirs.web]
github = "acme/web"

[dirs.web-old]
github = "acme/web"

[shared_slugs]
"acme/web" = ["web", "web-ancient"]
""", dirs=("web", "web-old")).problems()
        self.assertTrue(any("declares" in p and "web-ancient" in p for p in problems))

    def test_a_stale_shared_slug_is_reported(self):
        """The exception must expire with the convergence it documents, or it
        rots into permanent permission to keep duplicating a repo."""
        problems = self.tree("""
[dirs.web]
github = "acme/web"

[dirs.widget-service]
github = "acme/widget-service"

[shared_slugs]
"acme/web" = ["web", "web-old"]
""").problems()
        self.assertTrue(any("stale exception" in p for p in problems))

    def test_undeclared_github_without_a_note_is_reported(self):
        problems = self.tree("[dirs.svc]\nclone_expected = false\n",
                             dirs=("svc",)).problems()
        self.assertEqual(len(problems), 1)
        self.assertIn("no `github`", problems[0])

    def test_clone_expected_false_without_a_note_is_reported(self):
        problems = self.tree("""
[dirs.svc]
github = "acme/svc"
clone_expected = false
""", dirs=("svc",)).problems()
        self.assertEqual(len(problems), 1)
        self.assertIn("clone_expected = false", problems[0])

    def test_a_deliberately_clone_less_repo_with_a_note_is_accepted(self):
        """Some repos are memory-only on purpose — an employer repo whose slug
        must not reach tracked config. Any "every dir needs a clone" rule would
        be wrong about them."""
        self.assertEqual(self.tree("""
[dirs.svc]
clone_expected = false
note = "Client repository: slug withheld, never cloned locally."
""", dirs=("svc",)).problems(), [])

    def test_a_trail_key_claimed_twice_is_reported(self):
        problems = self.tree("""
[dirs.web]
github = "acme/web"
trail_keys = ["legacy"]

[dirs.widget-service]
github = "acme/widget-service"
trail_keys = ["legacy"]
""").problems()
        self.assertEqual(len(problems), 1)
        self.assertIn("legacy", problems[0])
        self.assertIn("exactly one memory dir", problems[0])

    def test_claiming_another_dirs_own_name_as_a_trail_key_is_reported(self):
        problems = self.tree("""
[dirs.web]
github = "acme/web"

[dirs.widget-service]
github = "acme/widget-service"
trail_keys = ["web"]
""").problems()
        self.assertEqual(len(problems), 1)
        self.assertIn("implicitly", problems[0])


class ValidateAgainstAdrConfig(RegistryTestCase):
    """`adr-publish.toml` is instance-owned and optional, so the cross-check
    must skip when it is absent rather than fail."""

    def test_absent_adr_config_is_skipped_not_failed(self):
        tree = self.tree()
        self.assertEqual(
            rr.validate(tree.load(), memory_root=tree.memory_root,
                        adr_config=tree.base / "nope.toml"),
            [],
        )

    def test_none_disables_the_cross_check(self):
        tree = self.tree()
        tree.write_adr_config('[repos.x]\ngithub = "acme/x"\nbrain_dirs = ["ghost"]\n')
        self.assertEqual(
            rr.validate(tree.load(), memory_root=tree.memory_root, adr_config=None),
            [],
        )

    def test_agreeing_adr_config_produces_no_problems(self):
        tree = self.tree()
        adr = tree.write_adr_config("""
[repos.web]
github = "acme/web"
brain_dirs = ["web"]
""")
        self.assertEqual(tree.problems(adr_config=adr), [])

    def test_adr_brain_dir_the_registry_does_not_register_is_reported(self):
        tree = self.tree()
        adr = tree.write_adr_config("""
[repos.web]
github = "acme/web"
brain_dirs = ["web", "web-ancient"]
""")
        problems = tree.problems(adr_config=adr)
        self.assertTrue(any("web-ancient" in p and "does not register" in p
                            for p in problems))

    def test_disagreeing_github_slug_is_reported(self):
        tree = self.tree()
        adr = tree.write_adr_config("""
[repos.web]
github = "other-org/web"
brain_dirs = ["web"]
""")
        problems = tree.problems(adr_config=adr)
        self.assertEqual(len(problems), 1)
        self.assertIn("other-org/web", problems[0])
        self.assertIn("acme/web", problems[0])

    def test_one_adr_slug_fed_by_dirs_of_different_repos_is_reported(self):
        """adr-publish already treats those dirs as one repository; the registry
        saying they are two is a contradiction between the two files."""
        tree = self.tree()
        adr = tree.write_adr_config("""
[repos.web]
brain_dirs = ["web", "widget-service"]
""")
        problems = tree.problems(adr_config=adr)
        self.assertTrue(any("different repositories" in p for p in problems))

    def test_malformed_adr_config_is_tolerated(self):
        """A mid-edit adr-publish.toml is an ADR-publishing problem; reporting it
        here would blame the registry for someone else's syntax error."""
        tree = self.tree()
        adr = tree.write_adr_config("[repos.web\n")
        self.assertEqual(tree.problems(adr_config=adr), [])


# ── the lenient accessors ──────────────────────────────────────────────────

class AliasAccessors(RegistryTestCase):

    def test_resolves_aliases_and_own_names(self):
        path = self.tree().registry
        self.assertEqual(
            rr.dir_for_trail_key("old-widget-service", path=path), "widget-service"
        )
        self.assertEqual(rr.dir_for_trail_key("widget-service", path=path),
                         "widget-service")

    def test_unregistered_key_is_none_not_the_key(self):
        """`None` — not the key — because the callers must distinguish "resolves
        here" from "unknown", and `_trail_scope` may only merge two roots when
        the registry declares both."""
        self.assertIsNone(rr.dir_for_trail_key("stranger", path=self.tree().registry))

    def test_empty_key_is_none(self):
        path = self.tree().registry
        self.assertIsNone(rr.dir_for_trail_key("", path=path))
        self.assertIsNone(rr.dir_for_trail_key(None, path=path))

    def test_absent_registry_yields_no_aliases_instead_of_raising(self):
        missing = Path(tempfile.gettempdir()) / "definitely-not-here.toml"
        self.assertEqual(rr.alias_map(missing), {})
        self.assertIsNone(rr.dir_for_trail_key("anything", path=missing))

    def test_malformed_registry_yields_no_aliases_instead_of_raising(self):
        """The hot path degrades to pre-registry behaviour rather than derailing
        a harvest over a config typo; `check_repo_registry.py` and the real-tree
        test below are what make a bad registry loud."""
        tree = self.tree("[dirs.svc\n", dirs=("svc",))
        self.assertEqual(rr.alias_map(tree.registry), {})

    def test_the_map_is_cached_until_cleared(self):
        tree = self.tree()
        self.assertEqual(rr.dir_for_trail_key("old-widget-service",
                                              path=tree.registry), "widget-service")
        tree.registry.write_text('[dirs.other]\ngithub = "acme/other"\n',
                                 encoding="utf-8")
        self.assertEqual(
            rr.dir_for_trail_key("old-widget-service", path=tree.registry),
            "widget-service",
            "a re-read on every lookup would dominate a run that resolves one "
            "alias per trail record",
        )
        rr.clear_cache()
        self.assertIsNone(
            rr.dir_for_trail_key("old-widget-service", path=tree.registry)
        )

    def test_a_duplicate_claim_does_not_raise_in_the_lenient_path(self):
        """`validate` reports it; `alias_map` must stay total so a hot path
        cannot be derailed by a registry defect."""
        tree = self.tree("""
[dirs.web]
github = "acme/web"
trail_keys = ["legacy"]

[dirs.widget-service]
github = "acme/widget-service"
trail_keys = ["legacy"]
""")
        self.assertEqual(rr.alias_map(tree.registry)["legacy"], "web")


# ── wiring: compute_readiness ──────────────────────────────────────────────

ALIASES = {"widget-service": "widget-service",
           "old-widget-service": "widget-service"}


def _rec(ts, repo_root, *, session="s1"):
    return {
        "ts": ts,
        "session_id": session,
        "git_root": repo_root,
        "repo_root": repo_root,
        "git_branch": "main",
        "prompt_id": "p1",
        "message_preview": "hello",
    }


class ComputeReadinessAlias(RegistryTestCase):

    def test_repo_name_resolves_an_alias(self):
        with mock.patch.object(rr, "alias_map", lambda path=None: ALIASES):
            self.assertEqual(
                cr.repo_name("C:/clones/old-widget-service"), "widget-service"
            )

    def test_repo_name_falls_back_to_the_basename_when_unregistered(self):
        with mock.patch.object(rr, "alias_map", lambda path=None: ALIASES):
            self.assertEqual(cr.repo_name("C:/clones/other-repo"), "other-repo")

    def test_repo_name_without_a_registry_is_the_bare_basename(self):
        with mock.patch.object(rr, "alias_map", lambda path=None: {}):
            self.assertEqual(cr.repo_name("C:/clones/some-repo"), "some-repo")

    def test_repo_name_degrades_to_the_full_path_without_a_basename(self):
        with mock.patch.object(rr, "alias_map", lambda path=None: ALIASES):
            self.assertEqual(cr.repo_name("/"), "/")

    def test_an_aliased_root_merges_into_one_bucket(self):
        """The merge is the point and it is visible: turns and un-harvested sum,
        the span widens, and both roots are listed."""
        base = Path(self._stack.enter_context(tempfile.TemporaryDirectory()))
        trail_dir = base / "learning-trail"
        trail_dir.mkdir()
        import json
        (trail_dir / "a.jsonl").write_text(
            json.dumps(_rec("2026-07-29T10:00:00+00:00",
                            "C:/clones/old-widget-service", session="old")) + "\n",
            encoding="utf-8")
        (trail_dir / "b.jsonl").write_text(
            json.dumps(_rec("2026-09-30T10:00:00+00:00",
                            "C:/clones/widget-service", session="new")) + "\n",
            encoding="utf-8")

        with mock.patch.object(rr, "alias_map", lambda path=None: ALIASES):
            merged = cr.summarise(trail_dir, base / "memory", resolve_live=False)
        self.assertEqual([s["repo"] for s in merged], ["widget-service"])
        self.assertEqual(merged[0]["turns"], 2)
        self.assertEqual(merged[0]["sessions"], 2)
        self.assertEqual(merged[0]["first_date"], "2026-07-29")
        self.assertEqual(merged[0]["last_date"], "2026-09-30")
        self.assertEqual(merged[0]["roots"],
                         ["C:/clones/old-widget-service", "C:/clones/widget-service"])

        with mock.patch.object(rr, "alias_map", lambda path=None: {}):
            split = cr.summarise(trail_dir, base / "memory", resolve_live=False)
        self.assertEqual([s["repo"] for s in split],
                         ["old-widget-service", "widget-service"])


# ── wiring: _trail_scope (the half that makes watermarks land) ─────────────

class TrailScopeAlias(RegistryTestCase):

    def _trail(self, repo_root: str) -> tuple[Path, Path]:
        import json
        base = Path(self._stack.enter_context(tempfile.TemporaryDirectory()))
        trail = base / "t.jsonl"
        trail.write_text(
            json.dumps(_rec("2026-07-29T10:00:00+00:00", repo_root)) + "\n",
            encoding="utf-8")
        return base, trail

    def test_an_aliased_trail_belongs_to_the_renamed_repo(self):
        """Without this, the renamed checkout selects none of the old trails, so
        they are never stamped and their turns report un-harvested forever —
        aliasing only `repo_name` would relabel that number, not clear it."""
        _, trail = self._trail("C:/clones/old-widget-service")
        with mock.patch.object(rr, "alias_map", lambda path=None: ALIASES):
            self.assertTrue(
                scope.belongs_to_repo(trail, Path("C:/clones/widget-service"))
            )

    def test_without_the_alias_the_same_trail_does_not_belong(self):
        _, trail = self._trail("C:/clones/old-widget-service")
        with mock.patch.object(rr, "alias_map", lambda path=None: {}):
            self.assertFalse(
                scope.belongs_to_repo(trail, Path("C:/clones/widget-service"))
            )

    def test_unregistered_repos_sharing_a_basename_are_not_merged(self):
        """The safety property: two roots may be treated as one repository only
        because the registry declares both their basenames, never because two
        unrelated clones happen to be called the same thing."""
        _, trail = self._trail("C:/elsewhere/ui")
        with mock.patch.object(rr, "alias_map", lambda path=None: ALIASES):
            self.assertFalse(scope.belongs_to_repo(trail, Path("C:/clones/ui")))

    def test_exact_root_equality_still_matches(self):
        _, trail = self._trail("C:/clones/widget-service")
        with mock.patch.object(rr, "alias_map", lambda path=None: {}):
            self.assertTrue(
                scope.belongs_to_repo(trail, Path("C:/clones/widget-service"))
            )

    def test_a_worktree_record_still_resolves_to_the_repo(self):
        _, trail = self._trail(
            "C:/clones/widget-service/.claude/worktrees/feature"
        )
        with mock.patch.object(rr, "alias_map", lambda path=None: {}):
            self.assertTrue(
                scope.belongs_to_repo(trail, Path("C:/clones/widget-service"))
            )

    def test_trails_for_repo_selects_the_aliased_trail(self):
        import json
        base = Path(self._stack.enter_context(tempfile.TemporaryDirectory()))
        trail_dir = base / "learning-trail"
        trail_dir.mkdir()
        (trail_dir / "old.jsonl").write_text(
            json.dumps(_rec("2026-07-29T10:00:00+00:00",
                            "C:/clones/old-widget-service")) + "\n",
            encoding="utf-8")
        (trail_dir / "unrelated.jsonl").write_text(
            json.dumps(_rec("2026-07-29T10:00:00+00:00", "C:/clones/stranger")) + "\n",
            encoding="utf-8")
        with mock.patch.object(rr, "alias_map", lambda path=None: ALIASES), \
                mock.patch.object(scope.rs, "trail_dir", lambda: trail_dir):
            found = scope.trails_for_repo(Path("C:/clones/widget-service"))
        self.assertEqual([p.name for p in found], ["old.jsonl"])

    def test_registered_dir_is_none_without_a_registry(self):
        with mock.patch.object(rr, "alias_map", lambda path=None: {}):
            self.assertIsNone(scope.registered_dir("C:/clones/anything"))


# ── wiring: assess_repo_readiness ──────────────────────────────────────────

class AssessRepoReadinessAlias(RegistryTestCase):
    """`repo_name()`'s docstring cites `assess_repo_readiness.py` as the thing it
    matches, and the two must keep naming one repository identically. Without the
    alias a renamed clone reports memory depth `none` and `missing_items` claims
    the brain knows nothing about it — the strongest argument for a *lower*
    autonomy cap, derived from a naming accident.
    """

    def test_assess_reads_the_aliased_memory_dir(self):
        base = Path(self._stack.enter_context(tempfile.TemporaryDirectory()))
        memory_root = base / "memory"
        notes = memory_root / "repo" / "widget-service"
        notes.mkdir(parents=True)
        (notes / "MEMORY.md").write_text("index\n", encoding="utf-8")
        for i in range(3):
            (notes / f"note-{i}.md").write_text("body\n", encoding="utf-8")
        clone = base / "old-widget-service"
        clone.mkdir()

        with mock.patch.object(rr, "alias_map", lambda path=None: ALIASES):
            aliased = arr.assess(clone, memory_root=memory_root)
        self.assertEqual(aliased["repo"], "widget-service")
        self.assertEqual(aliased["memory_depth"]["notes"], 3)

        with mock.patch.object(rr, "alias_map", lambda path=None: {}):
            bare = arr.assess(clone, memory_root=memory_root)
        self.assertEqual(bare["repo"], "old-widget-service")
        self.assertEqual(bare["memory_depth"]["notes"], 0)


# ── the CLI ────────────────────────────────────────────────────────────────

class CheckCli(RegistryTestCase):

    def _run(self, argv) -> tuple[int, str]:
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            code = crr.main(argv)
        return code, buf.getvalue()

    def test_healthy_registry_exits_zero(self):
        tree = self.tree()
        code, out = self._run(["--registry", str(tree.registry),
                               "--memory-root", str(tree.memory_root),
                               "--no-adr-check"])
        self.assertEqual(code, 0, out)
        self.assertIn("no problems found", out)
        self.assertIn("old-widget-service", out,
                      "the report names the aliases it resolved")

    def test_problems_exit_one_and_are_listed(self):
        tree = self.tree(dirs=("widget-service",))
        code, out = self._run(["--registry", str(tree.registry),
                               "--memory-root", str(tree.memory_root),
                               "--no-adr-check"])
        self.assertEqual(code, 1)
        self.assertIn("[dirs.web]", out)

    def test_an_absent_registry_exits_two_not_zero(self):
        """Exit 0 would read as "healthy" for an instance that simply has no
        registry — the one answer that keeps the reader from noticing."""
        code, out = self._run([
            "--registry", str(Path(tempfile.gettempdir()) / "definitely-not-here.toml"),
            "--no-adr-check",
        ])
        self.assertEqual(code, 2)
        self.assertIn("no repository registry", out)


# ── the real tree, only where there is one ─────────────────────────────────

class RealRegistry(unittest.TestCase):
    """The one test that reads this brain's own files.

    Skipped wherever `repo-registry.toml` is absent — which is every downstream
    instance that has not written one, since the file is tracked but not synced.
    It asserts only that whatever registry exists validates clean, which holds for
    any correctly-maintained registry regardless of which repos are in it, so this
    does not smuggle our repo list into a synced test.

    This is the gate the lenient alias accessors depend on: `alias_map()` silently
    yields `{}` on a malformed registry, so without a test that loads it strictly
    a typo would quietly disable the aliasing it was meant to declare.
    """

    @unittest.skipUnless(
        REAL_REGISTRY.exists(),
        "no repo-registry.toml — expected on an instance, where it is not synced",
    )
    def test_the_real_registry_loads_and_validates_clean(self):
        rr.clear_cache()
        self.addCleanup(rr.clear_cache)
        registry = rr.load_registry(REAL_REGISTRY)
        problems = rr.validate(
            registry,
            memory_root=REAL_MEMORY_ROOT,
            adr_config=REAL_ADR_CONFIG if REAL_ADR_CONFIG.is_file() else None,
        )
        self.assertEqual(
            problems, [],
            "repo-registry.toml disagrees with memory/repo/ or with itself; run "
            "`python scripts/check_repo_registry.py`",
        )

    @unittest.skipUnless(
        (ROOT / "repo-registry.toml.example").exists(),
        "no repo-registry.toml.example",
    )
    def test_the_shipped_example_loads(self):
        """The template is synced to every instance as the thing they copy, so a
        broken one breaks their first run rather than ours."""
        rr.clear_cache()
        self.addCleanup(rr.clear_cache)
        registry = rr.load_registry(ROOT / "repo-registry.toml.example")
        self.assertTrue(registry.entries)


class SyncedTemplate(unittest.TestCase):

    def test_the_example_is_in_framework_paths_but_the_real_file_is_not(self):
        """Same ownership split as `adr-publish.toml`: the template is framework
        and travels; the real file is a statement about *this* brain's repos and
        must never be copied over an instance's own."""
        import sync_from_upstream as sync
        self.assertIn("repo-registry.toml.example", sync.FRAMEWORK_PATHS)
        self.assertNotIn("repo-registry.toml", sync.FRAMEWORK_PATHS)


if __name__ == "__main__":
    unittest.main()
