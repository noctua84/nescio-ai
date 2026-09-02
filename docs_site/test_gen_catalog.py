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


#: The theme guidance carried by the roster assertions below. A themed checkout
#: is the one way to fail them without having actually added or removed an
#: agent, and the symptom (eleven unrouted philosopher names) does not look like
#: its cause.
#:
#: Deliberately a static string: `scripts/apply_theme.py` is NOT imported to
#: detect the condition. `docs_site/` must build and test with nothing from
#: `scripts/` on PYTHONPATH, and a hint costs nothing to keep true.
#:
#: This used to live in `gen_catalog.THEME_HINT`, appended to a `CatalogError`
#: raised by the generator. The generator no longer refuses an unrouted agent
#: (see the leniency note in gen_catalog.py), so the hint moved here with the
#: assertion that needs it rather than staying behind as a constant nothing in
#: the module used.
THEME_HINT = (
    "If the philosopher theme is applied to this checkout, run "
    "`python scripts/apply_theme.py functional` before regenerating -- the "
    "published catalog ships the functional names."
)


def roster_mismatch(repo_dir: Path) -> tuple[set[str], set[str]]:
    """Compare `AGENT_GROUPS` against `agents/*.md`, both directions.

    Returns ``(unrouted, phantom)``: agents on disk no bucket routes, and names
    routed by a bucket with no file behind them. Both empty means the table
    equals the directory listing as a set.

    Keys off the file *stem*, not the frontmatter `name`: the stem is what
    `agent_paths()` and `apply_theme.py` both work in, and a stem/name mismatch
    has its own warning in the generator.
    """
    on_disk = {path.stem for path in gen_catalog.agent_paths(repo_dir)}
    routed = {name for _, bucket in gen_catalog.AGENT_GROUPS for name in bucket}
    return on_disk - routed, routed - on_disk


def roster_failure_message(unrouted: set[str], phantom: set[str]) -> str:
    """Name the offending agents, say what to do, and carry the theme hint."""
    problems: list[str] = []
    if unrouted:
        problems.append(
            "no group routes these agents: " + ", ".join(sorted(unrouted))
        )
    if phantom:
        problems.append(
            "these names are routed but have no definition on disk: "
            + ", ".join(sorted(phantom))
        )
    return (
        "AGENT_GROUPS must list exactly the agents in agents/ -- no more, no "
        "fewer. " + "; ".join(problems) + ". Add the missing bucket entry (or "
        "drop the stale one) in docs_site/gen_catalog.py, then rerun "
        "`python docs_site/gen_catalog.py`. " + THEME_HINT
    )


#: The fixture roster is derived from the routing table rather than retyped:
#: what most of these tests want is "a repo whose agents/ matches
#: AGENT_GROUPS", so that the pages render into their real buckets and an
#: unrouted-agent warning is a signal rather than the fixture's own noise.
#: Adding a real agent must not require an edit here. Whether AGENT_GROUPS
#: matches the *real* tree is covered by TestAgainstTheRealRepo, which is the
#: right place for that assertion.
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
        # expected here; nothing else is. (The agent side produces none: the
        # fixture roster is derived from AGENT_GROUPS, so it matches exactly.)
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
        """Unlisted skills render under 'Other' and warn."""
        _make_repo(self.repo, {}, {"brand-new-skill": "Does a thing."})
        pages, warnings = gen_catalog.build_pages(self.repo)
        self.assertIn("### `brand-new-skill`", pages["skills.md"])
        self.assertIn(f"## {gen_catalog.UNGROUPED_TITLE}", pages["skills.md"])
        self.assertTrue(any("brand-new-skill" in w for w in warnings))

    def test_unrouted_agent_still_renders_under_other(self) -> None:
        """Agents are lenient too: an unrouted one renders, under 'Other'.

        Was `test_unrouted_agent_is_fatal`, which asserted a `CatalogError`.
        Refusing here meant an agent nobody routed failed the docs deploy --
        strictly worse than an untidy bucket on a site that still ships. See
        the leniency note above AGENT_GROUPS in gen_catalog.py.

        The strict promise did not disappear; it moved to
        TestAgainstTheRealRepo.test_agent_groups_routes_exactly_the_roster,
        which runs in the non-required `docs-tests` job. What was a build
        failure is now a test failure -- not nothing.
        """
        _make_repo(self.repo, {"brand-new-agent": "Does a thing."}, {})
        pages, warnings = gen_catalog.build_pages(self.repo)
        self.assertIn("### `brand-new-agent`", pages["agents.md"])
        self.assertIn(f"## {gen_catalog.UNGROUPED_TITLE}", pages["agents.md"])
        self.assertTrue(any("brand-new-agent" in w for w in warnings), warnings)

    def test_routed_name_with_no_definition_warns(self) -> None:
        """The other direction: a table entry nothing on disk answers to.

        Was `test_routed_name_with_no_definition_is_fatal`. Still observed and
        still named in the output -- as a warning on a page that renders,
        rather than a refusal to render it. Set equality in this direction is
        pinned by TestAgainstTheRealRepo.
        """
        (self.repo / "agents" / "reviewer.md").unlink()
        pages, warnings = gen_catalog.build_pages(self.repo)
        self.assertNotIn("### `reviewer`", pages["agents.md"])
        self.assertTrue(
            any("reviewer" in w and "no such definition" in w for w in warnings),
            warnings,
        )

    def test_no_duplicate_names_across_group_tables(self) -> None:
        for label, groups in (("agents", gen_catalog.AGENT_GROUPS), ("skills", gen_catalog.SKILL_GROUPS)):
            names = [n for _, bucket in groups for n in bucket]
            self.assertEqual(len(names), len(set(names)), f"duplicate in {label} groups")


class TestThemedRosterIsRefused(unittest.TestCase):
    """A philosopher-themed checkout must never publish philosopher names.

    `scripts/apply_theme.py philosopher` renames every file in `agents/`
    (`planner.md` -> `plato.md`, and so on). The published catalog ships the
    *functional* roster, and the roster-equality check is what enforces that:
    the aliases are not in AGENT_GROUPS, so a themed tree reds the `docs-tests`
    job instead of quietly renaming the whole crew on the public site.

    THE GENERATOR NO LONGER REFUSES A THEMED TREE. It renders the aliases under
    'Other' and warns, which is how the site stays deployable -- see the
    leniency note above AGENT_GROUPS in gen_catalog.py. That makes the
    assertions below the only thing between a themed checkout and philosopher
    names on the public site, so they are made directly against AGENT_GROUPS
    rather than through a build that raises.

    Without this test that refusal is emergent -- it holds only because nobody
    has routed the aliases yet -- and a future author could delete it by adding
    them to the table, with no test going red. The failure message carries the
    `apply_theme.py functional` hint, because an unexplained "eleven unrouted
    agents" is the one failure mode whose cause does not resemble its symptom.
    """

    #: **Every** alias `apply_theme.py philosophers` can produce, not a sample.
    #:
    #: A subset is worse than useless here: this is the only guard on the
    #: refusal, and an earlier four-name version stayed green when `socrates`
    #: alone -- or `euclid`, `cato`, `cicero`, `callimachus` and `archimedes`
    #: together -- was routed into AGENT_GROUPS. In precisely the scenario the
    #: test exists to catch, it did not fire.
    #:
    #: Source of truth: `scripts/_crew_common.PAIRS` (the nine word-pairs) plus
    #: `_crew_common.TIERED_AGENTS` resolved through `themed_name` (the two
    #: `archimedes-*` tier variants). Kept as a literal on purpose --
    #: `docs_site/` must not import from `scripts/`, because the docs build has
    #: to work with nothing from `scripts/` on PYTHONPATH. That makes this list
    #: a hand-maintained copy: adding a PAIRS entry means adding it here.
    #:
    #: (An earlier version also listed `sisyphus`, which the theme script never
    #: produces -- it is the `.sisyphus/` plan directory, not an agent.)
    THEMED_AGENTS = {
        "plato": "Plans the work.",
        "aristotle": "Advises on architecture.",
        "pyrrho": "Audits the built code.",
        "socrates": "Challenges the plan.",
        "archimedes": "Implements one scoped task.",
        "archimedes-simple": "Implements one simple task.",
        "archimedes-standard": "Implements one standard task.",
        "euclid": "Writes the tests.",
        "cato": "Guards the quality gate.",
        "callimachus": "Researches the documentation.",
        "cicero": "Writes the documentation.",
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
        """Re-pointed at the roster-equality check, which now owns this.

        Was an `assertRaises(CatalogError)` on `build_pages`; a themed tree no
        longer raises, it renders under 'Other'. Pinned instead: the roster
        check reports every one of the eleven aliases as unrouted. Routing any
        of them -- the exact move that would publish philosopher names --
        shrinks this set and reds the test, which is the same protection the
        refusal gave.

        The generator's lenient path over the same tree is asserted too, so the
        deploy-survives half of the trade is not taken on trust.
        """
        unrouted, _ = roster_mismatch(self.repo)
        self.assertEqual(
            unrouted,
            set(self.THEMED_AGENTS),
            "the roster check no longer reports every philosopher alias as "
            "unrouted, so an alias has been added to AGENT_GROUPS -- which "
            "would publish philosopher names to the public site. " + THEME_HINT,
        )
        # And the site still builds: aliases land in 'Other', with a warning.
        pages, warnings = gen_catalog.build_pages(self.repo)
        self.assertIn(f"## {gen_catalog.UNGROUPED_TITLE}", pages["agents.md"])
        for alias in self.THEMED_AGENTS:
            self.assertIn(f"### `{alias}`", pages["agents.md"])
        self.assertTrue(any("plato" in w for w in warnings), warnings)

    def test_roster_failure_message_names_offenders_and_hints(self) -> None:
        """The message a maintainer actually reads when the roster drifts."""
        message = roster_failure_message(*roster_mismatch(self.repo))
        for alias in self.THEMED_AGENTS:
            self.assertIn(alias, message)
        self.assertIn("AGENT_GROUPS", message)
        self.assertIn("apply_theme.py functional", message)

    def test_no_philosopher_alias_is_routed(self) -> None:
        """Asserted against the *whole* alias set -- see THEMED_AGENTS above.

        Routing any one of the eleven reds this, which is the property the
        four-name version lacked.
        """
        routed = {n for _, bucket in gen_catalog.AGENT_GROUPS for n in bucket}
        self.assertEqual(routed & set(self.THEMED_AGENTS), set())

    def test_alias_set_is_the_whole_roster(self) -> None:
        """A weak tripwire, kept for one specific failure: silent shrinkage.

        It cannot verify the names (that would need `scripts/_crew_common`,
        which `docs_site/` may not import). It only makes deleting an entry
        require a deliberate second edit, so the fixture cannot quietly rot back
        into the partial set that let a routed `socrates` through. The count is
        nine `_crew_common.PAIRS` entries plus two `TIERED_AGENTS` variants.
        """
        self.assertEqual(len(self.THEMED_AGENTS), 11)


class TestCountGuard(FixtureRepoMixin):
    def test_passes_when_page_matches_listing(self) -> None:
        page = "### `a`\n### `b`\n"
        paths = [self.repo / "agents" / "orchestrator.md", self.repo / "agents" / "scout.md"]
        self.assertEqual(gen_catalog.check_count("agents", page, paths, self.repo), 2)

    def test_fires_when_a_definition_never_reaches_the_page(self) -> None:
        """The core guarantee: a file on disk that vanished during rendering."""
        original = gen_catalog._group

        # Signature tracks `_group`'s. It carried a `strict=` keyword while
        # agent grouping was fatal; that parameter is gone, and a stub still
        # accepting it would quietly diverge from the function under test.
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
        # `newcomer` is deliberately left unrouted. An earlier revision patched
        # AGENT_GROUPS here because strict grouping made an unrouted agent
        # fatal; it is not any more, and the un-patched version is the case
        # that matters -- a contributor who adds an agent and routes nothing
        # must still get a page with their agent on it.
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
        # Grouping keys off the frontmatter `name`, so the typo is unrouted and
        # `scout` has nothing behind it -- two warnings, both lenient, neither
        # masking the name/location one this test is about. (An earlier
        # revision had to patch AGENT_GROUPS here to route the typo, because
        # strict grouping turned both into fatal errors.)
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

    def test_agent_groups_routes_exactly_the_roster(self) -> None:
        """AGENT_GROUPS equals `agents/*.md` as a set, in both directions.

        This is the strict guarantee, and this is now the only place holding
        it. It used to live inside `_group(..., strict=True)`, where an
        unrouted agent failed the docs build, and -- while
        `gen_catalog.py --check` sat in the required `tests` job -- blocked the
        merge as well. Both were removed on purpose: the docs site is
        presentation, and gating outside contributions on it made adding an
        agent require an editorial judgement plus a regenerated artefact. The
        site self-heals instead (docs.yml regenerates before `mkdocs build`),
        so an unrouted agent lands under 'Other' on a site that still deploys.

        What is left is this assertion, in the non-required `docs-tests` job:
        maintainers see the drift and can route the agent properly;
        contributors are not blocked by it.
        """
        unrouted, phantom = roster_mismatch(self.repo)
        self.assertEqual(
            (unrouted, phantom),
            (set(), set()),
            roster_failure_message(unrouted, phantom),
        )

    def test_committed_pages_are_up_to_date(self) -> None:
        gen_catalog.generate(self.repo, check_only=True)


if __name__ == "__main__":
    unittest.main()
