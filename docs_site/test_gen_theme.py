"""Tests for the philosopher-theme fragment generator (``gen_theme.py``).

Named ``test_gen_*.py`` on purpose: that glob is what the docs job's test step
collects (`.github/workflows/tests.yml`), and `test_ci_coverage.py`'s
`ScannerTest` fails CI for any `docs_site/` test module no `-p` pattern
reaches. Renaming this file to anything outside `test_gen_*.py` silently drops
it from CI -- and then trips the scanner.

Lives in `docs_site/`, NOT `tests/`. `tests/` is on FRAMEWORK_PATHS and syncs
into derived instances, which never receive `docs_site/` -- a test there
importing this module would break `python -m unittest` for every downstream
user.

Run from the repo root:

    python -m unittest discover -s docs_site -p "test_gen_*.py"

Oracle policy: every assertion derives at least one side from
`scripts/_crew_common` rather than restating the rendered prose, so the tests
cannot pass a roster that has drifted. The single deliberate exception is the
"nine pairs" count in `PairRationaleTest`, an outside oracle in the spirit of
`ThemeNamePinTest` -- a pair appearing or vanishing should take a human
decision, not slide through on self-consistency.
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

import gen_theme
from catalog_core import ITEM_HEADING_RE, REPO_DIR

# Mirrors the top-level insert in `gen_theme.py` (see its docstring) rather
# than relying on that import having happened first: `scripts/__init__.py`
# exists, so the repo root on `sys.path` is enough for `from scripts import
# _crew_common`, and `_crew_common` is stdlib-only pure data.
sys.path.insert(0, str(REPO_DIR))

from scripts import _crew_common  # noqa: E402  (needs the insert above)

AGENTS_PAGE = Path(REPO_DIR) / "docs_site" / "docs" / "agents.md"

THEME_HEADING = "## The philosopher theme"

#: Ditto marks a rationale cell must never use. README's old hand-written
#: table pointed `advisor`/`critic` back at `planner`'s cell with these; the
#: whole point of moving the prose into `PAIR_RATIONALE` is that a generator
#: cannot render a ditto into a standalone table row.
DITTO_MARKS = ('"', "''", "〃", "″", "”", "——")

TABLE_ROW_RE = re.compile(r"^\| `([^`]+)` \| `([^`]+)` \| (.+) \|$")


def rendered_rows(fragment: str) -> list[tuple[str, str, str]]:
    """Parse the ``| functional | philosopher | why |`` rows of a fragment."""
    rows = []
    for line in fragment.splitlines():
        match = TABLE_ROW_RE.match(line)
        if match:
            rows.append(
                (match.group(1), match.group(2), match.group(3).strip())
            )
    return rows


class PairRationaleTest(unittest.TestCase):
    """`PAIR_RATIONALE` is the data the table's "why" column renders from."""

    def test_rationale_keys_match_pairs(self) -> None:
        functional = {name for name, _ in _crew_common.PAIRS}
        self.assertEqual(
            set(_crew_common.PAIR_RATIONALE),
            functional,
            "add a why line to `scripts/_crew_common.PAIR_RATIONALE` when you "
            "add a pair to `PAIRS` (and drop it when you remove one); "
            "missing rationale: "
            f"{sorted(functional - set(_crew_common.PAIR_RATIONALE))}, "
            "rationale with no pair: "
            f"{sorted(set(_crew_common.PAIR_RATIONALE) - functional)}",
        )

    def test_pair_count_is_nine(self) -> None:
        # Deliberate outside oracle -- see the module docstring.
        self.assertEqual(len(_crew_common.PAIRS), 9)

    def test_every_rationale_is_non_empty(self) -> None:
        for functional, why in _crew_common.PAIR_RATIONALE.items():
            with self.subTest(functional=functional):
                self.assertTrue(
                    why.strip(),
                    f"`{functional}` has an empty rationale",
                )

    def test_no_rationale_uses_a_ditto_mark(self) -> None:
        for functional, why in _crew_common.PAIR_RATIONALE.items():
            for mark in DITTO_MARKS:
                with self.subTest(functional=functional, mark=mark):
                    self.assertNotIn(
                        mark,
                        why,
                        f"`{functional}`'s rationale uses a ditto mark; each "
                        "row renders standalone, so spell the reason out",
                    )

    def test_no_rationale_is_a_duplicate_of_another(self) -> None:
        # Ditto marks are one way to say "same as above"; a verbatim copy is
        # the other, and reads as drift rather than intent.
        values = [why.strip() for why in _crew_common.PAIR_RATIONALE.values()]
        self.assertEqual(len(values), len(set(values)))


class ThemeTableTest(unittest.TestCase):
    """The rendered table is `PAIRS`, in order, with both names."""

    def setUp(self) -> None:
        self.fragment = gen_theme.render_theme_section()
        self.rows = rendered_rows(self.fragment)

    def test_rows_are_pairs_in_order(self) -> None:
        self.assertEqual(
            [(functional, philosopher) for functional, philosopher, _ in self.rows],
            [(functional, philosopher) for functional, philosopher in _crew_common.PAIRS],
        )

    def test_row_count_matches_pairs(self) -> None:
        self.assertEqual(len(self.rows), len(_crew_common.PAIRS))

    def test_each_row_carries_its_rationale(self) -> None:
        for functional, _, why in self.rows:
            with self.subTest(functional=functional):
                self.assertEqual(
                    why, _crew_common.PAIR_RATIONALE[functional].strip()
                )

    def test_table_has_a_header_and_separator(self) -> None:
        self.assertIn("| functional | philosopher | why |", self.fragment)
        self.assertIn("| --- | --- | --- |", self.fragment)

    def test_fragment_starts_with_the_theme_heading(self) -> None:
        self.assertTrue(self.fragment.startswith(THEME_HEADING + "\n"))


class ThemeRosterTest(unittest.TestCase):
    """Counts and roster lists are derived, never typed as literals."""

    def setUp(self) -> None:
        self.fragment = gen_theme.render_theme_section()

    def test_every_tiered_agent_is_named(self) -> None:
        for name in _crew_common.TIERED_AGENTS:
            with self.subTest(name=name):
                self.assertIn(f"`{name}`", self.fragment)

    def test_every_invariant_agent_is_named(self) -> None:
        for name in _crew_common.THEME_INVARIANT_ROSTER:
            with self.subTest(name=name):
                self.assertIn(f"`{name}`", self.fragment)

    def test_invariant_agents_are_listed_in_sorted_order(self) -> None:
        expected = sorted(_crew_common.THEME_INVARIANT_ROSTER)
        positions = [self.fragment.index(f"`{name}`") for name in expected]
        self.assertEqual(positions, sorted(positions))

    def test_renamed_total_is_derived(self) -> None:
        expected = len(_crew_common.PAIRS) + len(_crew_common.TIERED_AGENTS)
        self.assertIn(
            f"{expected} files are renamed in all",
            self.fragment,
            "the 'files renamed in all' figure must equal "
            "len(PAIRS) + len(TIERED_AGENTS)",
        )

    def test_pairs_figure_is_derived(self) -> None:
        self.assertIn(f"the {len(_crew_common.PAIRS)} pairs above", self.fragment)

    def test_no_themed_name_leaks_into_the_invariant_sentence(self) -> None:
        # A philosopher name in the invariant list would mean the theme script
        # and this page disagree about what gets renamed.
        sentence = next(
            line
            for line in self.fragment.splitlines()
            if "keep their functional" in line
        )
        for _, philosopher in _crew_common.PAIRS:
            with self.subTest(philosopher=philosopher):
                self.assertNotIn(f"`{philosopher}`", sentence)

    def test_apply_theme_invocations_are_documented(self) -> None:
        self.assertIn("python scripts/apply_theme.py philosophers", self.fragment)
        self.assertIn("python scripts/apply_theme.py functional", self.fragment)


class HeadingShapeTest(unittest.TestCase):
    """The fragment must not disturb the agents-page count guard.

    `catalog_core.ITEM_HEADING_RE` (``^### ``) counts the rendered agent
    detail headings. The fragment is appended after that guard runs, so a
    backtick-leading `###` heading in it would corrupt a later count.
    """

    def test_fragment_has_no_item_heading(self) -> None:
        fragment = gen_theme.render_theme_section()
        self.assertEqual(ITEM_HEADING_RE.findall(fragment), [])

    def test_committed_page_count_is_unaffected_by_the_fragment(self) -> None:
        page = AGENTS_PAGE.read_text(encoding="utf-8")
        head, _, _ = page.partition(THEME_HEADING)
        self.assertEqual(
            len(ITEM_HEADING_RE.findall(page)),
            len(ITEM_HEADING_RE.findall(head)),
        )


class CommittedAgentsPageTest(unittest.TestCase):
    """The committed, generated page carries the fragment -- wiring guard."""

    def setUp(self) -> None:
        self.page = AGENTS_PAGE.read_text(encoding="utf-8")

    def test_page_ends_with_a_fresh_render_of_the_fragment(self) -> None:
        self.assertTrue(
            self.page.endswith(gen_theme.render_theme_section()),
            "docs_site/docs/agents.md does not end with the rendered theme "
            "fragment; re-run `python docs_site/gen_catalog.py`",
        )

    def test_committed_rows_are_pairs_in_order(self) -> None:
        # `ThemeTableTest.test_rows_are_pairs_in_order` derives both sides
        # from `PAIRS` at call time, so a reordering of `PAIRS` cannot fail
        # it. The committed page is the independent artifact: it only matches
        # again once someone regenerates it, which is exactly the review step
        # a roster reorder should go through.
        self.assertEqual(
            [
                (functional, philosopher)
                for functional, philosopher, _ in rendered_rows(
                    self.page[self.page.index(THEME_HEADING):]
                )
            ],
            [
                (functional, philosopher)
                for functional, philosopher in _crew_common.PAIRS
            ],
            "docs_site/docs/agents.md's theme table is out of step with "
            "`scripts/_crew_common.PAIRS`; re-run "
            "`python docs_site/gen_catalog.py`",
        )

    def test_theme_heading_appears_once(self) -> None:
        self.assertEqual(self.page.count(THEME_HEADING), 1)

    def test_at_a_glance_still_precedes_the_detail_sections(self) -> None:
        glance = self.page.index("## At a glance")
        first_detail = ITEM_HEADING_RE.search(self.page)
        self.assertIsNotNone(first_detail)
        self.assertLess(glance, first_detail.start())
        self.assertLess(first_detail.start(), self.page.index(THEME_HEADING))


if __name__ == "__main__":
    unittest.main()
