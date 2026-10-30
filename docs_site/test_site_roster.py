"""Tests that the crew diagram, the catalog page and `agents/` name one roster.

Lives in `docs_site/`, NOT `tests/` -- see site_under_test.py for why.

Run from the repo root:

    python -m unittest discover -s docs_site -p "test_site_*.py"

CrewRosterTest is the detector that was missing while both surfaces carried
their own hardcoded, silently-stale copy of the roster.
"""

from __future__ import annotations

import sys
import unittest

import gen_catalog
from site_under_test import _REPO_ROOT


class CrewRosterTest(unittest.TestCase):
    """The crew diagram, the catalog page and `agents/` must name one roster.

    The roster is a hardcoded fact in two independent places —
    `brand/make_diagrams.CREW_GROUPS` and `gen_catalog.AGENT_GROUPS` — and
    nothing before this class compared either against the directory they both
    describe. Both drifted, and neither drift was visible in anything that ran:
    the diagram drew 10 of 17 agents while the catalog claimed 11 in five
    buckets, and each surface renders perfectly happily while lying.

    The caption is what makes the diagram's copy load-bearing rather than merely
    decorative. It reads "One orchestrator, N specialists", with N derived from
    `CREW_GROUPS`, so a bucket that quietly falls behind `agents/` does not just
    omit a card — it prints a wrong number on the page in words, over artwork
    that contradicts it. Deriving the count removed the possibility of the
    caption disagreeing with the drawing; only this test can stop the drawing
    from disagreeing with the repo.

    `gen_catalog` has its own count-guard, but it only compares the rendered page
    against the live listing — an agent missing from `AGENT_GROUPS` still renders
    under "Other" and passes. Nothing there notices that the two grouping tables
    have stopped agreeing with each other, which is what the second and third
    assertions are for.

    Three methods, three distinct failure modes, none of which subsumes another:
    an agent that exists but is drawn nowhere; buckets that no longer match; and
    an agent filed under a different bucket by each table, which is invisible to
    both of the others.
    """

    @staticmethod
    def _make_diagrams():
        sys.path.insert(0, str(_REPO_ROOT))
        try:
            from brand import make_diagrams
        finally:
            sys.path.pop(0)
        return make_diagrams

    def test_diagram_draws_every_agent_but_the_orchestrator(self) -> None:
        # The orchestrator is drawn as the centre stack, not as a column, so it
        # is deliberately absent from CREW_GROUPS -- and it is the only name
        # allowed to be.
        drawn = {
            name
            for _, agents in self._make_diagrams().CREW_GROUPS
            for name, _ in agents
        }
        on_disk = {p.stem for p in (_REPO_ROOT / "agents").glob("*.md")}
        self.assertIn("orchestrator", on_disk, "agents/orchestrator.md has gone missing")
        self.assertEqual(
            on_disk - {"orchestrator"}, drawn,
            "brand/make_diagrams.CREW_GROUPS no longer matches agents/. Add or "
            "remove the card, then re-run `python brand/make_diagrams.py` and "
            "copy the tokenised source back over "
            "docs_site/docs/assets/diagrams/diagram-crew.svg -- the caption's "
            "count comes from this list, so a stale one puts a wrong number on "
            "the page.",
        )

    def test_diagram_headings_match_the_catalog_buckets(self) -> None:
        # The diagram upper-cases its headings for the artwork; the catalog sets
        # them in sentence case. Compare case-insensitively, in order -- the
        # lifecycle order is the point of both tables.
        drawn = [title.casefold() for title, _ in self._make_diagrams().CREW_GROUPS]
        catalog = [
            title.casefold()
            for title, _ in gen_catalog.AGENT_GROUPS
            if title.casefold() != "coordinate"
        ]
        self.assertEqual(
            catalog, drawn,
            "the diagram's buckets and gen_catalog.AGENT_GROUPS have diverged. "
            "They are two hand-maintained copies of one lifecycle; a reader who "
            "sees different buckets on the homepage and the agents page has no "
            "way to tell which is right.",
        )

    def test_both_tables_file_each_agent_under_the_same_bucket(self) -> None:
        """The gap between the two assertions above: an agent changing buckets.

        Neither sibling can see it, by construction. The first flattens the
        roster to a set before comparing, so `qa-guard` filed under BUILD instead
        of VERIFY leaves that set untouched; the second reads only the headings,
        and those do not change either. Both stay green while the homepage and
        the agents page put the same agent in two different phases of the
        lifecycle — which is the divergence the second assertion's own rationale
        is about, one level further down than it can actually look.

        Compared as ordered lists, not sets: within a bucket the order is the
        reading order of the cards on the diagram and of the sections on the
        catalog page, and it is deliberate on both.
        """
        drawn = {
            title.casefold(): [name for name, _ in agents]
            for title, agents in self._make_diagrams().CREW_GROUPS
        }
        catalog = {
            title.casefold(): list(names)
            for title, names in gen_catalog.AGENT_GROUPS
            if title.casefold() != "coordinate"
        }
        self.assertEqual(
            catalog, drawn,
            "brand/make_diagrams.CREW_GROUPS and gen_catalog.AGENT_GROUPS file "
            "an agent under different buckets, or in a different order within "
            "one. Work out which table has it in the wrong phase of the "
            "lifecycle and MOVE THE AGENT there -- do not edit the other table "
            "to agree, or whichever answer was wrong becomes the agreed one and "
            "this test will never mention it again. Then re-run `python "
            "brand/make_diagrams.py`, copy the tokenised source over "
            "docs_site/docs/assets/diagrams/diagram-crew.svg, and re-run "
            "`python docs_site/gen_catalog.py`.",
        )


if __name__ == "__main__":
    unittest.main()
