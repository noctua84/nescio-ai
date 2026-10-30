"""Tests for the orchestrator lifecycle page generator.

Lives in `docs_site/`, NOT `tests/`, for the reason spelled out at the top of
`test_gen_catalog.py`: `tests/` is on FRAMEWORK_PATHS and syncs into derived
instances, which never receive `docs_site/`.

Run from the repo root:

    python -m unittest discover -s docs_site -p "test_gen_lifecycle.py" -v

The suite has two halves, mirroring the page it guards:

* **Facts are parsed, so they are re-derived here, not typed.** The phase list,
  the triage table and the tier table are read out of `agents/orchestrator.md`
  by this test's own fence-aware scan and then located on the committed
  `docs/lifecycle.md`. Nothing below hardcodes a phase name, a phase count or a
  table row; if the agent file renames a phase, these tests follow it, and they
  fail only when the page stops matching the source.
* **Prose is pinned by digest.** `gen_lifecycle`'s hand-written prose summarises
  five named sections of the agent definition. `DIGESTS` below stores the
  sha256 of `section_text(REPO_DIR, key)` for each. A reworded or reversed
  decision in one of those sections changes the digest and fails
  `test_summarised_sections_match_their_pinned_digests`.

**Updating a digest is a deliberate re-blessing, not a reflex to green CI.**
When the pin fires, the required order of work is: read the changed section in
`agents/orchestrator.md`, read the prose in `docs_site/gen_lifecycle.py` that
summarises it, fix the prose if the meaning moved, and only then paste the new
digest in here. Pasting the new digest first -- which the failure message makes
trivially easy -- throws away the entire value of the pin. The orchestrator has
changed meaning without changing a single heading name before (d2dc99c, cd20561,
65aaa28); that is why this exists.
"""

from __future__ import annotations

import hashlib
import re
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import gen_lifecycle
import orchestrator_spine
from catalog_core import REPO_DIR, CatalogError
from gen_lifecycle import SECTION_ANCHORS, render_lifecycle, section_text
from orchestrator_spine import orchestrator_path, parse_phases, tier_table, triage_table

#: sha256 of ``section_text(REPO_DIR, key)`` for every key in
#: ``SECTION_ANCHORS``. See the module docstring before you touch one of these.
DIGESTS: dict[str, str] = {
    "competence_check": "0128cfe0a38bb6ea9f21ebb2d45c376ce0e6078e34c2f9796b3fb2637f2e04ab",
    "discovery_brief_carrying": "bd12bab416b9737a9ce57c5c4d24f0d0a8d801ad3b3df661a1ae389ee382c108",
    "routing_quality_gate": "e2469c3f861d240b2caa25ae99ce90102eff108fb9b153925b581c342fac0857",
    "tiering": "714265e38cc9b43810d1aee24d4ed7b0a36854fb5f4f4ecdbcba09b70c5fa01b",
    "work_placement": "a005f36907e98904068ee00e7a9ed9ac064c4bf5630b52c0769679f023b05d36",
}

_PAGE = REPO_DIR / "docs_site" / "docs" / "lifecycle.md"

# This test's own fence-aware scan, deliberately NOT imported from
# ``orchestrator_spine``. The whole claim under test is "the page carries the
# phases the agent file actually declares"; borrowing the generator's parser to
# check the generator's output would make that claim circular. The two
# implementations agreeing is the evidence.
_FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
_PHASE = re.compile(r"^## PHASE (\d+): +(.+?)\s*$")

#: A count of phases, in digits or words, immediately qualifying "phase(s)".
#: The page must never carry one: the site once shipped "Ten agents" against a
#: roster of sixteen, and a typed phase count is the same failure waiting to
#: happen. Bare "phases" ("between phases", "which phases run") is fine -- it
#: cannot go stale.
_PHASE_COUNT = re.compile(
    r"\b(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|"
    r"dozen)[\s-]+phases?\b",
    re.IGNORECASE,
)


def _declared_phases(path: Path) -> list[tuple[str, str]]:
    """``(number, title)`` for every ``## PHASE n: NAME`` outside a fence."""
    found: list[tuple[str, str]] = []
    open_fence: str | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        fence = _FENCE.match(line)
        if open_fence is not None:
            if fence and fence.group(1).startswith(open_fence):
                open_fence = None
            continue
        if fence:
            open_fence = fence.group(1)[:3]
            continue
        match = _PHASE.match(line)
        if match:
            found.append((match.group(1), match.group(2)))
    return found


#: A minimal orchestrator definition: enough structure for ``render_lifecycle``
#: to run (a PHASE 0 with a triage table, a ``### Per-Task Dispatch`` with a
#: tier table, and all five anchored sections), plus a fenced ``## PHASE``
#: impostor and one phase name no prose exists for.
FIXTURE = """\
# Fixture orchestrator

## PHASE 0: TRIAGE (Every Request)

| Request Type | Phases to Run |
|---|---|
| **Trivial** | -> EXECUTE |

**Competence check (before you commit to a path).** Fixture competence
paragraph, which ends at the blank line below.

Not part of the competence section.

Templates live in fenced blocks, and a naive grep reads them as structure:

```markdown
## PHASE 9: IMPOSTOR

### Per-Task Dispatch

| Tier | Agent |
|---|---|
| fake | fake-agent |
```

## PHASE 1: DISCOVER

Fixture discover body.

## PHASE 2: INVENT

A phase name `PHASE_PROSE` has never heard of.

### Per-Task Dispatch

| Tier | Agent |
|---|---|
| `simple` | `builder-simple` |
| `standard` | `builder-standard` |

### Work Placement: Inline, Subagent, or Spawned Task

Fixture placement body.

### Carry the Discovery Brief (every dispatch, no exceptions)

Fixture brief-carrying body.

**Routing quality gate.** Fixture routing paragraph.
"""


def _write_fixture(root: Path, body: str) -> Path:
    (root / "agents").mkdir(parents=True, exist_ok=True)
    (root / "agents" / "orchestrator.md").write_text(body, encoding="utf-8")
    return root


class RealRepoFactsTest(unittest.TestCase):
    """The committed page's facts must still equal the agent definition's."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.page = _PAGE.read_text(encoding="utf-8")
        cls.declared = _declared_phases(orchestrator_path(REPO_DIR))

    def test_fixture_scan_agrees_with_the_generators_parser(self) -> None:
        """Both fence-aware scans must see the same phases, in the same order."""
        self.assertEqual(
            [(phase.number, phase.title) for phase in parse_phases(REPO_DIR)],
            self.declared,
            "this test's independent scan of agents/orchestrator.md disagrees "
            "with orchestrator_spine.parse_phases -- one of the two fence "
            "handlers is wrong",
        )

    def test_every_declared_phase_is_on_the_page_in_source_order(self) -> None:
        self.assertGreaterEqual(len(self.declared), 2, "no phases parsed at all")
        positions: list[int] = []
        for number, title in self.declared:
            heading = f"### PHASE {number}: {title}"
            index = self.page.find(heading)
            self.assertNotEqual(
                index,
                -1,
                f"docs/lifecycle.md is missing {heading!r}, which "
                "agents/orchestrator.md declares. Regenerate the page "
                "(python docs_site/gen_catalog.py).",
            )
            positions.append(index)
        self.assertEqual(
            positions,
            sorted(positions),
            "the phase sections on docs/lifecycle.md are not in the order "
            "agents/orchestrator.md declares them",
        )

    def test_page_carries_no_phase_other_than_the_declared_ones(self) -> None:
        on_page = re.findall(r"(?m)^### PHASE (\d+): +(.+?)\s*$", self.page)
        self.assertEqual([tuple(entry) for entry in on_page], self.declared)

    def test_triage_rows_appear_verbatim(self) -> None:
        page_lines = self.page.splitlines()
        rows = triage_table(REPO_DIR)
        self.assertGreaterEqual(len(rows), 3)
        for row in rows:
            self.assertIn(row, page_lines, f"triage row not on the page: {row!r}")

    def test_tier_rows_appear_verbatim(self) -> None:
        page_lines = self.page.splitlines()
        rows = tier_table(REPO_DIR)
        self.assertGreaterEqual(len(rows), 3)
        for row in rows:
            self.assertIn(row, page_lines, f"tier row not on the page: {row!r}")

    def test_page_states_no_phase_count(self) -> None:
        match = _PHASE_COUNT.search(self.page)
        found = repr(match.group(0)) if match else ""
        self.assertIsNone(
            match,
            f"docs/lifecycle.md states a phase count ({found}), which goes stale "
            "the moment a phase is added or removed. The phase list is parsed; "
            "let the reader count the headings.",
        )

    def test_the_phase_count_guard_can_actually_fire(self) -> None:
        """Guard the guard: a silently non-matching regex would pass forever."""
        for phrase in ("seven phases", "7 phases", "Seven-phase lifecycle"):
            with self.subTest(phrase=phrase):
                self.assertIsNotNone(_PHASE_COUNT.search(phrase))
        for phrase in ("between phases", "which phases run", "| Phases to Run |"):
            with self.subTest(phrase=phrase):
                self.assertIsNone(_PHASE_COUNT.search(phrase))

    def test_render_matches_the_committed_page(self) -> None:
        """The committed page is the exact renderer's output.

        The renderer now emits the correct banner directly, so the full page
        is compared.
        """
        rendered, _ = render_lifecycle(REPO_DIR)
        self.assertEqual(
            rendered,
            self.page,
            "docs/lifecycle.md is stale -- rerun python docs_site/gen_catalog.py",
        )

    def test_every_real_phase_has_prose(self) -> None:
        _, warnings = render_lifecycle(REPO_DIR)
        self.assertEqual(warnings, [], "\n".join(warnings))


class SectionDigestTest(unittest.TestCase):
    """The staleness pin on the five summarised sections."""

    def test_digests_cover_exactly_the_anchored_sections(self) -> None:
        self.assertEqual(
            sorted(DIGESTS),
            sorted(SECTION_ANCHORS),
            "gen_lifecycle.SECTION_ANCHORS and this test's DIGESTS have "
            "diverged: a section was added or removed without pinning it.",
        )

    def test_summarised_sections_match_their_pinned_digests(self) -> None:
        for key in sorted(SECTION_ANCHORS):
            with self.subTest(section=key):
                text = section_text(REPO_DIR, key)
                digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
                self.assertEqual(
                    digest,
                    DIGESTS[key],
                    f"agents/orchestrator.md section '{key}' changed -- re-read "
                    "the matching prose in docs_site/gen_lifecycle.py, update it "
                    "if needed, then update the stored digest in "
                    f"docs_site/test_gen_lifecycle.py:DIGESTS to {digest}. "
                    "Updating the digest without re-reading the prose defeats "
                    "the point of this pin.",
                )

    def test_sections_are_non_trivial(self) -> None:
        """A pin over an accidentally-empty string would never fire."""
        for key in sorted(SECTION_ANCHORS):
            with self.subTest(section=key):
                self.assertGreater(len(section_text(REPO_DIR, key).strip()), 40)

    def test_unknown_section_key_raises(self) -> None:
        with self.assertRaises(CatalogError) as caught:
            section_text(REPO_DIR, "no_such_section")
        message = str(caught.exception)
        self.assertIn("no_such_section", message)
        for key in SECTION_ANCHORS:
            self.assertIn(key, message)

    def test_missing_anchor_raises_rather_than_hashing_nothing(self) -> None:
        with TemporaryDirectory() as tmp:
            root = _write_fixture(
                Path(tmp),
                FIXTURE.replace("**Routing quality gate.**", "**Routing check.**"),
            )
            with self.assertRaises(CatalogError) as caught:
                section_text(root, "routing_quality_gate")
        self.assertIn("routing_quality_gate", str(caught.exception))

    def test_paragraph_section_stops_at_the_blank_line(self) -> None:
        with TemporaryDirectory() as tmp:
            root = _write_fixture(Path(tmp), FIXTURE)
            text = section_text(root, "competence_check")
        self.assertIn("ends at the blank line below", text)
        self.assertNotIn("Not part of the competence section", text)

    def test_heading_section_stops_at_the_next_same_level_heading(self) -> None:
        with TemporaryDirectory() as tmp:
            root = _write_fixture(Path(tmp), FIXTURE)
            text = section_text(root, "work_placement")
        self.assertIn("Fixture placement body", text)
        self.assertNotIn("Fixture brief-carrying body", text)


class FixtureParseTest(unittest.TestCase):
    """Fence awareness, the too-few-phases guard, and the rename warning."""

    def test_fenced_phase_heading_is_not_a_phase(self) -> None:
        with TemporaryDirectory() as tmp:
            phases = parse_phases(_write_fixture(Path(tmp), FIXTURE))
        self.assertEqual(
            [(phase.number, phase.name) for phase in phases],
            [("0", "TRIAGE"), ("1", "DISCOVER"), ("2", "INVENT")],
        )
        self.assertNotIn("IMPOSTOR", [phase.name for phase in phases])

    def test_trailing_parenthetical_is_kept_in_title_and_cut_from_name(self) -> None:
        with TemporaryDirectory() as tmp:
            phases = parse_phases(_write_fixture(Path(tmp), FIXTURE))
        triage = phases[0]
        self.assertEqual(triage.title, "TRIAGE (Every Request)")
        self.assertEqual(triage.name, "TRIAGE")

    def test_tables_inside_fences_are_not_the_tier_table(self) -> None:
        with TemporaryDirectory() as tmp:
            root = _write_fixture(Path(tmp), FIXTURE)
            rows = tier_table(root)
            triage = triage_table(root)
        self.assertNotIn("| fake | fake-agent |", rows)
        self.assertIn("| `simple` | `builder-simple` |", rows)
        self.assertEqual(triage[-1], "| **Trivial** | -> EXECUTE |")

    def test_single_phase_file_raises(self) -> None:
        body = "# Only one\n\n## PHASE 0: TRIAGE\n\nBody.\n"
        with TemporaryDirectory() as tmp:
            with self.assertRaises(CatalogError) as caught:
                parse_phases(_write_fixture(Path(tmp), body))
        self.assertIn("found 1 '## PHASE n: NAME' heading(s)", str(caught.exception))

    def test_all_phases_fenced_away_raises(self) -> None:
        body = "# Nothing outside\n\n```md\n## PHASE 0: A\n## PHASE 1: B\n```\n"
        with TemporaryDirectory() as tmp:
            with self.assertRaises(CatalogError) as caught:
                parse_phases(_write_fixture(Path(tmp), body))
        self.assertIn("found 0 '## PHASE n: NAME' heading(s)", str(caught.exception))

    def test_unreadable_definition_raises(self) -> None:
        with TemporaryDirectory() as tmp:
            with self.assertRaises(CatalogError) as caught:
                parse_phases(Path(tmp))
        self.assertIn("cannot be read", str(caught.exception))

    def test_renamed_phase_warns_and_still_reaches_the_page(self) -> None:
        with TemporaryDirectory() as tmp:
            page, warnings = render_lifecycle(_write_fixture(Path(tmp), FIXTURE))
        self.assertEqual(len(warnings), 1, warnings)
        self.assertIn("INVENT", warnings[0])
        self.assertIn("PHASE_PROSE", warnings[0])
        self.assertIn("### PHASE 2: INVENT", page)
        self.assertIn("no summary has been written yet", page)
        # A warning, never a silent drop: the known phases still render normally.
        self.assertIn("### PHASE 1: DISCOVER", page)
        self.assertIsNone(_PHASE_COUNT.search(page))

    def test_missing_triage_table_raises(self) -> None:
        body = FIXTURE.replace("| **Trivial** | -> EXECUTE |", "").replace(
            "| Request Type | Phases to Run |\n|---|---|\n", ""
        )
        with TemporaryDirectory() as tmp:
            with self.assertRaises(CatalogError) as caught:
                triage_table(_write_fixture(Path(tmp), body))
        self.assertIn("triage table", str(caught.exception))


class ReexportTest(unittest.TestCase):
    """gen_lifecycle re-exports the spine, so importers need one module."""

    def test_spine_names_are_reachable_through_gen_lifecycle(self) -> None:
        for name in ("Phase", "parse_phases", "triage_table", "tier_table",
                     "orchestrator_path", "ORCHESTRATOR_REL"):
            with self.subTest(name=name):
                self.assertIs(
                    getattr(gen_lifecycle, name), getattr(orchestrator_spine, name)
                )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
