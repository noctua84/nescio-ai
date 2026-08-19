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


class FixtureRepoMixin(unittest.TestCase):
    AGENTS = {
        "orchestrator": "Coordinates the crew.",
        "scout": "Triages a request before planning.",
        "reviewer": "Audits the built code.",
    }
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
        # The fixture repo holds only a handful of the real definitions, so the
        # "listed in a group but absent" warnings are expected here; nothing else is.
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
            self.assertEqual(counts, {"agents": 3, "skills": 3})
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
    def test_unmapped_name_still_renders(self) -> None:
        _make_repo(self.repo, {"brand-new-agent": "Does a thing."}, {})
        pages, warnings = gen_catalog.build_pages(self.repo)
        self.assertIn("### `brand-new-agent`", pages["agents.md"])
        self.assertIn(f"## {gen_catalog.UNGROUPED_TITLE}", pages["agents.md"])
        self.assertTrue(any("brand-new-agent" in w for w in warnings))

    def test_no_duplicate_names_across_group_tables(self) -> None:
        for label, groups in (("agents", gen_catalog.AGENT_GROUPS), ("skills", gen_catalog.SKILL_GROUPS)):
            names = [n for _, bucket in groups for n in bucket]
            self.assertEqual(len(names), len(set(names)), f"duplicate in {label} groups")


class TestCountGuard(FixtureRepoMixin):
    def test_passes_when_page_matches_listing(self) -> None:
        page = "### `a`\n### `b`\n"
        paths = [self.repo / "agents" / "orchestrator.md", self.repo / "agents" / "scout.md"]
        self.assertEqual(gen_catalog.check_count("agents", page, paths, self.repo), 2)

    def test_fires_when_a_definition_never_reaches_the_page(self) -> None:
        """The core guarantee: a file on disk that vanished during rendering."""
        original = gen_catalog._group

        def dropping_group(items, groups):
            grouped, warnings = original(items, groups)
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
