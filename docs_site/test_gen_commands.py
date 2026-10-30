"""Tests for the Commands page generator (`docs_site/gen_commands.py`).

Lives in `docs_site/`, NOT `tests/`, for the reason stated at the top of
`test_gen_catalog.py`: `tests/` is on FRAMEWORK_PATHS and syncs into derived
instances that never receive `docs_site/`.

Shape follows `test_gen_catalog.py`: a temporary fixture repo for the parsing,
lead-extraction, error and rendering contracts, plus one class that reads the
real `commands/` tree so that a command added on disk and dropped on the way to
the page is a failure here.

The real-repo class deliberately calls `discover_commands`/`render_commands`
directly rather than `gen_catalog.build_pages`: this module's contract is those
two functions plus `command_paths`, and the wiring into `build_pages` is owned
elsewhere.

Run from the repo root:

    python -m unittest discover -s docs_site -p "test_gen_commands.py"
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import catalog_core
import gen_commands
from catalog_core import CatalogError

COMMAND_MD = """---
name: {name}
description: {description}
user-invocable: true
---

# /{name}

{lead}

## Details

Prose under a later heading, which must never reach the lead.
"""


def _write_command(repo: Path, name: str, *, text: str) -> Path:
    (repo / "commands").mkdir(parents=True, exist_ok=True)
    path = repo / "commands" / f"{name}.md"
    path.write_text(text, encoding="utf-8")
    return path


def _make_repo(root: Path, commands: dict[str, str]) -> Path:
    """Fixture repo with one `commands/<name>.md` per entry, lead = the value."""
    (root / "commands").mkdir(parents=True, exist_ok=True)
    for name, lead in commands.items():
        _write_command(
            root,
            name,
            text=COMMAND_MD.format(
                name=name, description=f"Fixture description for {name}.", lead=lead
            ),
        )
    return root


class FixtureRepoMixin(unittest.TestCase):
    COMMANDS = {
        "assess-repo": "Scans a target repo and reports readiness.",
        "harvest-memory": "Promotes machine-local learnings into repo memory.",
    }

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        # Resolved: `_rewrite_relative_links` resolves link targets before
        # taking them relative to the repo dir, and on Windows a
        # TemporaryDirectory path can be the 8.3 short form of its resolved
        # self -- an unresolved fixture root would make every rewrite look like
        # an escape from the repo.
        self.repo = _make_repo(Path(self._tmp.name).resolve(), self.COMMANDS)


class TestDiscovery(FixtureRepoMixin):
    def test_command_paths_is_the_sorted_live_listing(self) -> None:
        self.assertEqual(
            [p.name for p in gen_commands.command_paths(self.repo)],
            ["assess-repo.md", "harvest-memory.md"],
        )

    def test_non_markdown_files_are_not_commands(self) -> None:
        (self.repo / "commands" / "notes.txt").write_text("x", encoding="utf-8")
        self.assertEqual(
            [p.name for p in gen_commands.command_paths(self.repo)],
            ["assess-repo.md", "harvest-memory.md"],
        )

    def test_every_file_becomes_an_item_with_its_frontmatter(self) -> None:
        catalog = gen_commands.discover_commands(self.repo)
        self.assertEqual(
            [item.name for item in catalog.items], ["assess-repo", "harvest-memory"]
        )
        by_name = {item.name: item for item in catalog.items}
        self.assertEqual(
            by_name["assess-repo"].description, "Fixture description for assess-repo."
        )
        self.assertEqual(by_name["assess-repo"].rel_path, "commands/assess-repo.md")
        self.assertEqual(
            by_name["assess-repo"].meta["lead"],
            "Scans a target repo and reports readiness.",
        )
        self.assertEqual(by_name["assess-repo"].meta["user-invocable"], "true")
        self.assertEqual([], catalog.warnings)

    def test_a_missing_commands_directory_is_fatal(self) -> None:
        with TemporaryDirectory() as empty:
            with self.assertRaises(CatalogError) as ctx:
                gen_commands.discover_commands(Path(empty))
            self.assertIn("commands", str(ctx.exception))

    def test_an_empty_commands_directory_is_fatal(self) -> None:
        for path in gen_commands.command_paths(self.repo):
            path.unlink()
        with self.assertRaises(CatalogError) as ctx:
            gen_commands.discover_commands(self.repo)
        self.assertIn("no command definitions", str(ctx.exception))


class TestLeadProse(FixtureRepoMixin):
    """The lead is the prose between `# /name` and the next heading."""

    def _lead(self, name: str, text: str) -> str:
        _write_command(self.repo, name, text=text)
        catalog = gen_commands.discover_commands(self.repo)
        return {item.name: item for item in catalog.items}[name].meta["lead"]

    def test_multiple_paragraphs_are_kept_whole(self) -> None:
        lead = self._lead(
            "multi",
            "---\nname: multi\ndescription: d\nuser-invocable: true\n---\n\n"
            "# /multi\n\nFirst paragraph.\n\nSecond paragraph.\n\n"
            "## Later\n\nNot the lead.\n",
        )
        self.assertEqual(lead, "First paragraph.\n\nSecond paragraph.")

    def test_a_heading_of_any_level_terminates_the_lead(self) -> None:
        for marker in ("##", "###", "######"):
            with self.subTest(marker=marker):
                lead = self._lead(
                    "anylevel",
                    "---\nname: anylevel\ndescription: d\nuser-invocable: true\n---\n\n"
                    f"# /anylevel\n\nThe lead.\n\n{marker} Next\n\nNot the lead.\n",
                )
                self.assertEqual(lead, "The lead.")

    def test_a_fenced_block_containing_headings_does_not_end_the_lead(self) -> None:
        """`commands/harvest-memory.md` is ~25 KB of exactly this shape.

        A ```-fenced block can hold `## `-prefixed lines; mistaking one for the
        terminating heading truncates the lead mid-example.
        """
        lead = self._lead(
            "fenced",
            "---\nname: fenced\ndescription: d\nuser-invocable: true\n---\n\n"
            "# /fenced\n\nBefore the fence.\n\n"
            "```markdown\n## Not a real heading\n```\n\n"
            "After the fence.\n\n## Real heading\n\nNot the lead.\n",
        )
        self.assertIn("## Not a real heading", lead)
        self.assertIn("After the fence.", lead)
        self.assertNotIn("Not the lead.", lead)

    def test_a_tilde_fence_is_also_honoured(self) -> None:
        lead = self._lead(
            "tilde",
            "---\nname: tilde\ndescription: d\nuser-invocable: true\n---\n\n"
            "# /tilde\n\nBefore.\n\n"
            "~~~\n### Inside a tilde fence\n~~~\n\nAfter.\n\n## Real\n\nNope.\n",
        )
        self.assertIn("### Inside a tilde fence", lead)
        self.assertIn("After.", lead)
        self.assertNotIn("Nope.", lead)

    def test_a_body_with_no_command_heading_is_fatal(self) -> None:
        _write_command(
            self.repo,
            "headless",
            text="---\nname: headless\ndescription: d\nuser-invocable: true\n---\n\n"
            "Body with no `# /headless` heading.\n",
        )
        with self.assertRaises(CatalogError) as ctx:
            gen_commands.discover_commands(self.repo)
        message = str(ctx.exception)
        self.assertIn("commands/headless.md", message)
        self.assertIn("# /headless", message)

    def test_a_command_whose_lead_is_its_whole_body_is_fine(self) -> None:
        lead = self._lead(
            "whole",
            "---\nname: whole\ndescription: d\nuser-invocable: true\n---\n\n"
            "# /whole\n\nAll of it.\n",
        )
        self.assertEqual(lead, "All of it.")


class TestLinkRewriting(FixtureRepoMixin):
    """Repo-relative links must become absolute blob URLs.

    `mkdocs build --strict` fails on a broken internal link, and a path
    relative to `commands/` does not resolve from `docs/commands.md` at all.
    """

    def _lead_with_links(self, body: str) -> str:
        _write_command(
            self.repo,
            "linky",
            text="---\nname: linky\ndescription: d\nuser-invocable: true\n---\n\n"
            f"# /linky\n\n{body}\n\n## Later\n\nNot the lead.\n",
        )
        catalog = gen_commands.discover_commands(self.repo)
        return {item.name: item for item in catalog.items}["linky"].meta["lead"]

    def test_a_repo_relative_link_becomes_an_absolute_blob_url(self) -> None:
        lead = self._lead_with_links("See [the script](../scripts/assess.py).")
        self.assertEqual(
            lead,
            "See [the script]("
            f"{catalog_core.REPO_BLOB_BASE}/scripts/assess.py).",
        )

    def test_a_sibling_link_resolves_inside_commands(self) -> None:
        lead = self._lead_with_links("See [the other one](assess-repo.md).")
        self.assertIn(
            f"({catalog_core.REPO_BLOB_BASE}/commands/assess-repo.md)", lead
        )

    def test_absolute_and_in_page_links_are_left_alone(self) -> None:
        body = (
            "See [upstream](https://example.com/x), [plain](http://example.com/y) "
            "and [below](#anchor)."
        )
        self.assertEqual(self._lead_with_links(body), body)

    def test_a_target_outside_the_repo_is_left_alone(self) -> None:
        """Left as written rather than guessed at -- it has no blob URL."""
        body = "See [elsewhere](../../../outside/thing.md)."
        self.assertEqual(self._lead_with_links(body), body)


class TestErrorsAndWarnings(FixtureRepoMixin):
    def test_a_missing_description_is_fatal(self) -> None:
        _write_command(
            self.repo,
            "assess-repo",
            text="---\nname: assess-repo\nuser-invocable: true\n---\n\n"
            "# /assess-repo\n\nLead.\n",
        )
        with self.assertRaises(CatalogError) as ctx:
            gen_commands.discover_commands(self.repo)
        message = str(ctx.exception)
        self.assertIn("commands/assess-repo.md", message)
        self.assertIn("description", message)

    def test_absent_frontmatter_is_fatal(self) -> None:
        _write_command(self.repo, "assess-repo", text="# /assess-repo\n\nLead.\n")
        with self.assertRaises(CatalogError):
            gen_commands.discover_commands(self.repo)

    def test_a_name_that_disagrees_with_the_filename_is_fatal(self) -> None:
        """Fatal for commands, unlike agents/skills where it only warns.

        The slash command a user types *is* the filename, so a mismatch would
        have the page advertise a command that invokes something else.
        """
        _write_command(
            self.repo,
            "assess-repo",
            text="---\nname: asses-repo\ndescription: d\nuser-invocable: true\n---\n\n"
            "# /asses-repo\n\nLead.\n",
        )
        with self.assertRaises(CatalogError) as ctx:
            gen_commands.discover_commands(self.repo)
        message = str(ctx.exception)
        self.assertIn("commands/assess-repo.md", message)
        self.assertIn("filename", message)
        self.assertIn("assess-repo", message)

    def test_a_missing_user_invocable_warns_and_renders_no(self) -> None:
        _write_command(
            self.repo,
            "assess-repo",
            text="---\nname: assess-repo\ndescription: d\n---\n\n"
            "# /assess-repo\n\nLead.\n",
        )
        catalog = gen_commands.discover_commands(self.repo)
        self.assertTrue(
            any(
                "commands/assess-repo.md" in w and "user-invocable" in w
                for w in catalog.warnings
            ),
            catalog.warnings,
        )
        page, _ = gen_commands.render_commands(catalog)
        section = page.split("### `/assess-repo`")[1].split("### `")[0]
        self.assertIn("**User-invocable** no", section)

    def test_user_invocable_true_renders_yes_without_a_warning(self) -> None:
        catalog = gen_commands.discover_commands(self.repo)
        page, _ = gen_commands.render_commands(catalog)
        self.assertEqual([], catalog.warnings)
        self.assertIn("**User-invocable** yes", page)
        self.assertNotIn("**User-invocable** no", page)

    def test_user_invocable_false_renders_no(self) -> None:
        _write_command(
            self.repo,
            "assess-repo",
            text="---\nname: assess-repo\ndescription: d\nuser-invocable: false\n---\n\n"
            "# /assess-repo\n\nLead.\n",
        )
        catalog = gen_commands.discover_commands(self.repo)
        page, _ = gen_commands.render_commands(catalog)
        self.assertEqual([], catalog.warnings)
        section = page.split("### `/assess-repo`")[1].split("### `")[0]
        self.assertIn("**User-invocable** no", section)


class TestRendering(FixtureRepoMixin):
    def setUp(self) -> None:
        super().setUp()
        self.catalog = gen_commands.discover_commands(self.repo)
        self.page, self.warnings = gen_commands.render_commands(self.catalog)

    def test_render_returns_no_warnings_of_its_own(self) -> None:
        """The one warning this module raises is produced at discovery time."""
        self.assertEqual([], self.warnings)

    def test_the_page_opens_with_the_generated_banner(self) -> None:
        """The page opens with a banner naming its source.

        This renderer now emits the correct `generated_banner("commands/*.md")`
        directly, so what is pinned here is that the page opens with that
        specific banner.
        """
        expected_banner = catalog_core.generated_banner("commands/*.md")
        self.assertTrue(self.page.startswith(expected_banner), self.page[:120])
        self.assertIn("Do not edit by hand", expected_banner)

    def test_the_count_comes_from_the_catalog_not_a_literal(self) -> None:
        self.assertIn(f"{len(self.catalog.items)} slash commands", self.page)

    def test_the_at_a_glance_table_precedes_the_detail_sections(self) -> None:
        glance = self.page.index("## At a glance")
        header = self.page.index("| Command | What it does |")
        first_detail = self.page.index("### `/")
        self.assertLess(glance, header)
        self.assertLess(header, first_detail)

    def test_every_command_has_a_table_row_and_a_detail_section(self) -> None:
        for item in self.catalog.items:
            with self.subTest(command=item.name):
                row = f"| `/{item.name}` | {item.description} |"
                self.assertIn(row, self.page)
                heading = f"### `/{item.name}`"
                self.assertIn(heading, self.page)
                self.assertLess(self.page.index(row), self.page.index(heading))

    def test_a_detail_section_carries_description_lead_and_source_link(self) -> None:
        item = self.catalog.items[0]
        section = self.page.split(f"### `/{item.name}`")[1].split("### `")[0]
        self.assertIn(item.description, section)
        self.assertIn(item.meta["lead"], section)
        self.assertIn(
            f"[`{item.rel_path}`]({catalog_core.REPO_BLOB_BASE}/{item.rel_path})",
            section,
        )

    def test_the_page_ends_with_exactly_one_newline(self) -> None:
        self.assertTrue(self.page.endswith("\n"))
        self.assertFalse(self.page.endswith("\n\n"))

    def test_no_hardcoded_counts_in_the_generator(self) -> None:
        """The plan's "no magic numbers" rule, as pinned for `gen_catalog`."""
        source = Path(gen_commands.__file__).read_text(encoding="utf-8")
        code = "\n".join(
            line for line in source.splitlines() if not line.lstrip().startswith("#")
        )
        for magic in ("== 2", "!= 2", "== 10", "!= 10"):
            self.assertNotIn(magic, code)


class TestCountGuard(FixtureRepoMixin):
    """The shared count-guard must be able to see a dropped command."""

    def test_the_rendered_page_satisfies_the_guard(self) -> None:
        catalog = gen_commands.discover_commands(self.repo)
        page, _ = gen_commands.render_commands(catalog)
        self.assertEqual(
            catalog_core.check_count(
                "commands", page, gen_commands.command_paths(self.repo), self.repo
            ),
            len(gen_commands.command_paths(self.repo)),
        )

    def test_the_guard_fires_when_a_command_never_reaches_the_page(self) -> None:
        catalog = gen_commands.discover_commands(self.repo)
        dropped = catalog_core.Catalog(catalog.items[1:], catalog.warnings)
        page, _ = gen_commands.render_commands(dropped)
        with self.assertRaises(CatalogError) as ctx:
            catalog_core.check_count(
                "commands", page, gen_commands.command_paths(self.repo), self.repo
            )
        self.assertIn("count-guard", str(ctx.exception))

    def test_adding_a_command_does_not_fire_the_guard(self) -> None:
        _make_repo(self.repo, {"newcomer": "A new command."})
        catalog = gen_commands.discover_commands(self.repo)
        page, _ = gen_commands.render_commands(catalog)
        self.assertEqual(
            catalog_core.check_count(
                "commands", page, gen_commands.command_paths(self.repo), self.repo
            ),
            len(self.COMMANDS) + 1,
        )
        self.assertIn("### `/newcomer`", page)


class TestAgainstTheRealRepo(unittest.TestCase):
    """Regression cover for the actual `commands/` tree."""

    def setUp(self) -> None:
        self.repo = catalog_core.REPO_DIR
        if not (self.repo / "commands").is_dir():
            self.skipTest("not running inside the nescio-ai repo")

    def test_every_real_command_parses_and_reaches_the_page(self) -> None:
        catalog = gen_commands.discover_commands(self.repo)
        page, _ = gen_commands.render_commands(catalog)
        for path in gen_commands.command_paths(self.repo):
            with self.subTest(command=path.stem):
                self.assertIn(f"### `/{path.stem}`", page)
                self.assertIn(f"| `/{path.stem}` |", page)

    def test_rendered_count_equals_the_live_listing(self) -> None:
        catalog = gen_commands.discover_commands(self.repo)
        page, _ = gen_commands.render_commands(catalog)
        self.assertEqual(
            len(catalog_core.ITEM_HEADING_RE.findall(page)),
            len(gen_commands.command_paths(self.repo)),
        )

    def test_every_real_command_has_a_non_empty_lead(self) -> None:
        """The whole reason this generator exists rather than reusing agents'."""
        catalog = gen_commands.discover_commands(self.repo)
        for item in catalog.items:
            with self.subTest(command=item.name):
                self.assertTrue(item.meta["lead"].strip(), f"{item.rel_path}: empty lead")

    def test_no_repo_relative_link_survives_into_the_page(self) -> None:
        """Every rewritable link target is absolute or an in-page anchor."""
        catalog = gen_commands.discover_commands(self.repo)
        for item in catalog.items:
            for match in gen_commands._LINK_RE.finditer(item.meta["lead"]):
                target = match.group(2)
                with self.subTest(command=item.name, target=target):
                    self.assertTrue(
                        target.startswith(("http://", "https://", "#")),
                        f"{item.rel_path}: `{target}` would not resolve in the site",
                    )


if __name__ == "__main__":
    unittest.main()
