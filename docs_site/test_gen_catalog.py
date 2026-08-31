"""Tests for the catalog generator.

Lives in `docs_site/`, NOT `tests/`. `tests/` is on FRAMEWORK_PATHS and syncs
into derived instances, which never receive `docs_site/` -- a test there
importing this module would break `python -m unittest` for every downstream
user.

Run from the repo root:

    python -m unittest discover -s docs_site
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import gen_catalog
from gen_catalog import CatalogError

AGENT_FM = """---
name: {name}
description: {description}
model: claude-opus-4-8
disallowedTools: Write, Edit
---

Body text for {name}.
"""

SKILL_FM = """---
name: {name}
description: {description}
user-invocable: true
---

Body text for {name}.
"""


def _make_repo(root: Path, agents: dict[str, str], skills: dict[str, str]) -> Path:
    (root / "agents").mkdir(parents=True, exist_ok=True)
    (root / "skills").mkdir(parents=True, exist_ok=True)
    for name, description in agents.items():
        (root / "agents" / f"{name}.md").write_text(
            AGENT_FM.format(name=name, description=description), encoding="utf-8"
        )
    for name, description in skills.items():
        directory = root / "skills" / name
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "SKILL.md").write_text(
            SKILL_FM.format(name=name, description=description), encoding="utf-8"
        )
    return root


#: Agent grouping is strict in both directions, so a fixture repo carrying a
#: three-agent subset would (correctly) fail every `build_pages` call. The
#: fixture roster is therefore derived from the routing table rather than
#: retyped: what these tests need is "a repo whose agents/ matches
#: AGENT_GROUPS", and adding a real agent must not require an edit here.
#: Whether AGENT_GROUPS matches the *real* tree is covered by
#: TestAgainstTheRealRepo, which is the right place for that assertion.
FIXTURE_AGENTS = {
    name: f"Fixture description for {name}."
    for _, bucket in gen_catalog.AGENT_GROUPS
    for name in bucket
}


class FixtureRepoMixin(unittest.TestCase):
    AGENTS = FIXTURE_AGENTS
    SKILLS = {
        "threat-model": "Enumerates attack surfaces.",
        "risk-register": "Logs risks with named owners.",
        "code-navigation": "Finds where a symbol is defined.",
    }

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = _make_repo(Path(self._tmp.name), self.AGENTS, self.SKILLS)


class TestFrontmatterParsing(unittest.TestCase):
    def test_flat_scalars(self) -> None:
        fm, body = gen_catalog.split_frontmatter(
            "---\nname: x\ndescription: a, b: c\n---\nbody\n"
        )
        self.assertEqual(fm["name"], "x")
        self.assertEqual(fm["description"], "a, b: c")
        self.assertEqual(body, "body\n")

    def test_simple_list(self) -> None:
        fm, _ = gen_catalog.split_frontmatter("---\ntags:\n  - a\n  - b\n---\n")
        self.assertEqual(fm["tags"], ["a", "b"])

    def test_no_frontmatter_returns_empty(self) -> None:
        fm, body = gen_catalog.split_frontmatter("# heading\n")
        self.assertEqual(fm, {})
        self.assertEqual(body, "# heading\n")

    def test_unterminated_fence_returns_empty(self) -> None:
        fm, _ = gen_catalog.split_frontmatter("---\nname: x\nno closing fence\n")
        self.assertEqual(fm, {})

    def test_quoted_scalar_is_unquoted(self) -> None:
        fm, _ = gen_catalog.split_frontmatter('---\nname: "x"\n---\n')
        self.assertEqual(gen_catalog._scalar(fm, "name"), "x")


class TestRendering(FixtureRepoMixin):
    def test_every_row_has_name_and_description(self) -> None:
        pages, warnings = gen_catalog.build_pages(self.repo)
        # The fixture repo holds only a handful of the real *skills*, so the
        # "listed in a group but absent" warnings SKILL_GROUPS produces are
        # expected here; nothing else is. (The agent side cannot warn this way
        # at all -- strict grouping makes it fatal.)
        self.assertEqual(
            [w for w in warnings if not w.startswith("grouping table lists")], []
        )
        for kind, source in (("agents.md", self.AGENTS), ("skills.md", self.SKILLS)):
            page = pages[kind]
            for name, description in source.items():
                self.assertIn(f"### `{name}`", page, kind)
                self.assertIn(description, page, kind)

    def test_names_render_in_mono(self) -> None:
        pages, _ = gen_catalog.build_pages(self.repo)
        for name in self.AGENTS:
            # In the at-a-glance table and in the section heading.
            self.assertIn(f"`{name}`", pages["agents.md"])
        self.assertNotIn("### orchestrator", pages["agents.md"])

    def test_at_a_glance_precedes_detail(self) -> None:
        pages, _ = gen_catalog.build_pages(self.repo)
        page = pages["agents.md"]
        self.assertLess(page.index("## At a glance"), page.index("### `orchestrator`"))

    def test_agent_meta_line(self) -> None:
        pages, _ = gen_catalog.build_pages(self.repo)
        self.assertIn("**Model** `claude-opus-4-8`", pages["agents.md"])
        self.assertIn("**Denied tools** `Write`, `Edit`", pages["agents.md"])

    def test_generated_banner_present(self) -> None:
        pages, _ = gen_catalog.build_pages(self.repo)
        for page in pages.values():
            self.assertIn("Do not edit by hand", page)

    def test_writes_both_pages(self) -> None:
        with TemporaryDirectory() as out:
            counts = gen_catalog.generate(self.repo, Path(out))
            self.assertEqual(
                counts, {"agents": len(self.AGENTS), "skills": len(self.SKILLS)}
            )
            self.assertTrue((Path(out) / "agents.md").is_file())
            self.assertTrue((Path(out) / "skills.md").is_file())

    def test_check_mode_detects_drift(self) -> None:
        with TemporaryDirectory() as out:
            gen_catalog.generate(self.repo, Path(out))
            (Path(out) / "skills.md").write_text("hand edited\n", encoding="utf-8")
            with self.assertRaises(CatalogError) as ctx:
                gen_catalog.generate(self.repo, Path(out), check_only=True)
            self.assertIn("skills.md", str(ctx.exception))


class TestGrouping(FixtureRepoMixin):
    def test_unmapped_skill_still_renders_under_other(self) -> None:
        """Skills stay lenient: unlisted ones render under 'Other' and warn.

        Was `test_unmapped_name_still_renders`, which exercised the same
        leftover branch through the *agent* path. Agents are strict now (see
        below), so the lenient behaviour -- which SKILL_GROUPS still relies on
        -- is asserted here, where it survives.
        """
        _make_repo(self.repo, {}, {"brand-new-skill": "Does a thing."})
        pages, warnings = gen_catalog.build_pages(self.repo)
        self.assertIn("### `brand-new-skill`", pages["skills.md"])
        self.assertIn(f"## {gen_catalog.UNGROUPED_TITLE}", pages["skills.md"])
        self.assertTrue(any("brand-new-skill" in w for w in warnings))

    def test_unrouted_agent_is_fatal(self) -> None:
        """An agent no group routes fails the build, naming itself."""
        _make_repo(self.repo, {"brand-new-agent": "Does a thing."}, {})
        with self.assertRaises(CatalogError) as ctx:
            gen_catalog.build_pages(self.repo)
        message = str(ctx.exception)
        self.assertIn("brand-new-agent", message)
        self.assertIn("AGENT_GROUPS", message)

    def test_routed_name_with_no_definition_is_fatal(self) -> None:
        """The other direction: a table entry nothing on disk answers to.

        Pinning only filesystem -> table would leave the themed-roster refusal
        (below) emergent instead of enforced.
        """
        (self.repo / "agents" / "reviewer.md").unlink()
        with self.assertRaises(CatalogError) as ctx:
            gen_catalog.build_pages(self.repo)
        message = str(ctx.exception)
        self.assertIn("reviewer", message)
        self.assertIn("AGENT_GROUPS", message)

    def test_no_duplicate_names_across_group_tables(self) -> None:
        for label, groups in (("agents", gen_catalog.AGENT_GROUPS), ("skills", gen_catalog.SKILL_GROUPS)):
            names = [n for _, bucket in groups for n in bucket]
            self.assertEqual(len(names), len(set(names)), f"duplicate in {label} groups")


class TestThemedRosterIsRefused(unittest.TestCase):
    """A philosopher-themed checkout must never publish philosopher names.

    `scripts/apply_theme.py philosopher` renames every file in `agents/`
    (`planner.md` -> `plato.md`, and so on). The published catalog ships the
    *functional* roster, and strict grouping is the only thing enforcing that:
    the aliases are not in AGENT_GROUPS, so a themed tree fails loudly instead
    of quietly renaming the whole crew on the public site.

    Without this test that refusal is emergent -- it holds only because nobody
    has routed the aliases yet -- and a future author could delete it by adding
    them to the table, with no test going red. The build's own error message is
    asserted here too, including the `apply_theme.py functional` hint, because
    an unexplained "17 unrouted agents" is the one failure mode whose cause
    does not resemble its symptom.
    """

    THEMED_AGENTS = {
        "plato": "Plans the work.",
        "aristotle": "Advises on architecture.",
        "sisyphus": "Implements one scoped task.",
        "pyrrho": "Audits the built code.",
    }

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = _make_repo(
            Path(self._tmp.name),
            self.THEMED_AGENTS,
            {"threat-model": "Enumerates attack surfaces."},
        )

    def test_themed_roster_is_refused(self) -> None:
        with self.assertRaises(CatalogError) as ctx:
            gen_catalog.build_pages(self.repo)
        message = str(ctx.exception)
        for alias in self.THEMED_AGENTS:
            self.assertIn(alias, message)
        self.assertIn("AGENT_GROUPS", message)
        self.assertIn("apply_theme.py functional", message)

    def test_no_philosopher_alias_is_routed(self) -> None:
        routed = {n for _, bucket in gen_catalog.AGENT_GROUPS for n in bucket}
        self.assertEqual(routed & set(self.THEMED_AGENTS), set())


class TestCountGuard(FixtureRepoMixin):
    def test_passes_when_page_matches_listing(self) -> None:
        page = "### `a`\n### `b`\n"
        paths = [self.repo / "agents" / "orchestrator.md", self.repo / "agents" / "scout.md"]
        self.assertEqual(gen_catalog.check_count("agents", page, paths, self.repo), 2)

    def test_fires_when_a_definition_never_reaches_the_page(self) -> None:
        """The core guarantee: a file on disk that vanished during rendering."""
        original = gen_catalog._group

        # Signature tracks `_group`'s: the `strict=` keyword is passed by
        # `render_agents`, so a stub without it raises TypeError and the test
        # would pass for the wrong reason.
        def dropping_group(items, groups, *, strict=False):
            grouped, warnings = original(items, groups, strict=strict)
            # Silently lose the first item, as a buggy filter would.
            title, bucket = grouped[0]
            grouped[0] = (title, bucket[1:])
            return grouped, warnings

        gen_catalog._group = dropping_group
        self.addCleanup(setattr, gen_catalog, "_group", original)

        with self.assertRaises(CatalogError) as ctx:
            gen_catalog.build_pages(self.repo)
        self.assertIn("count-guard", str(ctx.exception))

    def test_addition_does_not_fire_the_guard(self) -> None:
        """A legitimate new agent/skill flows through both sides of the check."""
        before = gen_catalog.generate(self.repo, self.repo / "out")
        _make_repo(self.repo, {"newcomer": "A new agent."}, {"new-skill": "A new skill."})
        # Adding an agent now means routing it too -- that is the obligation
        # strict grouping creates, and CONTRIBUTING.md documents. Do here what
        # a real addition does in the source file, so what is under test stays
        # the count-guard rather than the routing table.
        original = gen_catalog.AGENT_GROUPS
        gen_catalog.AGENT_GROUPS = original + [("Newly added", ["newcomer"])]
        self.addCleanup(setattr, gen_catalog, "AGENT_GROUPS", original)
        after = gen_catalog.generate(self.repo, self.repo / "out")
        self.assertEqual(after["agents"], before["agents"] + 1)
        self.assertEqual(after["skills"], before["skills"] + 1)

    def test_no_hardcoded_counts_in_the_generator(self) -> None:
        source = Path(gen_catalog.__file__).read_text(encoding="utf-8")
        # The plan's "no magic 10/33" rule. Docstring prose may mention them.
        code = "\n".join(
            line for line in source.splitlines() if not line.lstrip().startswith("#")
        )
        for magic in ("== 10", "== 33", "!= 10", "!= 33"):
            self.assertNotIn(magic, code)


class TestMalformedInput(FixtureRepoMixin):
    def test_missing_skill_md_is_fatal(self) -> None:
        (self.repo / "skills" / "threat-model" / "SKILL.md").unlink()
        with self.assertRaises(CatalogError) as ctx:
            gen_catalog.build_pages(self.repo)
        self.assertIn("threat-model", str(ctx.exception))
        self.assertIn("SKILL.md", str(ctx.exception))

    def test_missing_description_is_fatal_not_skipped(self) -> None:
        (self.repo / "agents" / "scout.md").write_text(
            "---\nname: scout\nmodel: claude-opus-4-8\n---\n", encoding="utf-8"
        )
        with self.assertRaises(CatalogError) as ctx:
            gen_catalog.build_pages(self.repo)
        self.assertIn("agents/scout.md", str(ctx.exception))
        self.assertIn("description", str(ctx.exception))

    def test_absent_frontmatter_is_fatal(self) -> None:
        (self.repo / "agents" / "scout.md").write_text("just a body\n", encoding="utf-8")
        with self.assertRaises(CatalogError):
            gen_catalog.build_pages(self.repo)

    def test_name_location_mismatch_warns_but_renders(self) -> None:
        (self.repo / "agents" / "scout.md").write_text(
            AGENT_FM.format(name="scoutt", description="Typo'd name."), encoding="utf-8"
        )
        # Grouping keys off the frontmatter `name`, so under strict agent
        # grouping the typo is unrouted AND `scout` is now missing -- two fatal
        # errors that would mask the warning this test is about. Route the typo
        # so the page renders and the warning is what is left to observe.
        original = gen_catalog.AGENT_GROUPS
        gen_catalog.AGENT_GROUPS = [
            (title, ["scoutt" if n == "scout" else n for n in bucket])
            for title, bucket in original
        ]
        self.addCleanup(setattr, gen_catalog, "AGENT_GROUPS", original)
        pages, warnings = gen_catalog.build_pages(self.repo)
        self.assertIn("### `scoutt`", pages["agents.md"])
        self.assertTrue(any("does not match its location" in w for w in warnings))


class TestAgainstTheRealRepo(unittest.TestCase):
    """Regression cover for the actual agents/ and skills/ trees."""

    def setUp(self) -> None:
        self.repo = gen_catalog.REPO_DIR
        if not (self.repo / "agents").is_dir():
            self.skipTest("not running inside the nescio-ai repo")

    def test_every_real_definition_parses_and_renders(self) -> None:
        pages, _ = gen_catalog.build_pages(self.repo)
        for path in gen_catalog.agent_paths(self.repo):
            self.assertIn(f"### `{path.stem}`", pages["agents.md"])
        for path in gen_catalog.skill_paths(self.repo):
            self.assertIn(f"### `{path.parent.name}`", pages["skills.md"])

    def test_rendered_counts_equal_the_live_listing(self) -> None:
        pages, _ = gen_catalog.build_pages(self.repo)
        self.assertEqual(
            len(gen_catalog.ITEM_HEADING_RE.findall(pages["agents.md"])),
            len(gen_catalog.agent_paths(self.repo)),
        )
        self.assertEqual(
            len(gen_catalog.ITEM_HEADING_RE.findall(pages["skills.md"])),
            len(gen_catalog.skill_paths(self.repo)),
        )

    def test_committed_pages_are_up_to_date(self) -> None:
        gen_catalog.generate(self.repo, check_only=True)


if __name__ == "__main__":
    unittest.main()
