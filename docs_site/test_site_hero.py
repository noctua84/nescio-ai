"""Tests for the homepage hero in docs/index.md.

Lives in `docs_site/`, NOT `tests/` -- see site_under_test.py for why.

Run from the repo root:

    python -m unittest discover -s docs_site -p "test_site_*.py"

What these guard, and why each one is worth a test:

  * The hero order is a spec decision (§5: install commands ABOVE the buttons)
    that reads as an arbitrary preference to anyone tidying the file later.
  * No external request may leave the built site (§3).
"""

from __future__ import annotations

import re
import unittest

from site_under_test import _CSS, _INDEX, _REPO_ROOT

#: Anything that would make the built site phone home (§3: no CDN, no
#: third-party request at runtime).
_EXTERNAL_ASSET_RE = re.compile(
    r"(?:src|href)\s*=\s*[\"']https?://(?!github\.com|claude\.com|squidfunk\.github\.io)"
)



class HeroTest(unittest.TestCase):
    """docs/index.md — the §5 hero."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = _INDEX.read_text(encoding="utf-8")
        # Strip the file's own explanatory comment so it cannot satisfy an
        # assertion by merely *mentioning* the thing being asserted.
        cls.body = re.sub(r"<!--(?!\s*diagram:).*?-->", "", cls.source, flags=re.S)

    def test_hero_element_order_is_spec_5(self) -> None:
        order = [
            "nescio-hero__lockup",
            "nescio-hero__gloss",
            "nescio-hero__descriptor",
            "nescio-hero__rule",
            "nescio-hero__claim",
            "```bash",                 # the install commands ...
            "nescio-hero__buttons",    # ... which sit ABOVE the buttons (§5)
        ]
        positions = []
        for token in order:
            index = self.body.find(token)
            self.assertNotEqual(-1, index, f"hero is missing {token!r}")
            positions.append(index)
        self.assertEqual(
            sorted(positions), positions,
            "hero elements are out of order. §5 fixes it: lockup, gloss, "
            "descriptor, rule, claim, install commands, buttons -- the install "
            "block is above the buttons on purpose.",
        )

    def test_name_gloss_is_present(self) -> None:
        self.assertIn("I do not know", self.body)

    def test_owl_uses_the_dark_pairing(self) -> None:
        # §4: on an ink ground the body is periwinkle and the cutouts are the
        # ground colour. White cutouts here would halo.
        owl = re.search(r'<svg class="nescio-hero__owl".*?</svg>', self.body, re.S)
        self.assertIsNotNone(owl, "the hero owl is not inlined")
        assert owl is not None
        self.assertIn("#8fb0d9", owl.group(0))
        self.assertIn("#0e1319", owl.group(0))
        self.assertNotIn("#ffffff", owl.group(0))

    def test_both_diagrams_are_inlined_by_marker(self) -> None:
        for name in ("crew", "loop"):
            with self.subTest(name=name):
                self.assertRegex(self.source, rf"(?m)^<!--\s*diagram:\s*{name}\s*-->$")

    def test_no_external_assets(self) -> None:
        self.assertIsNone(_EXTERNAL_ASSET_RE.search(self.body))

    def test_crew_sentence_names_the_current_specialist_count(self) -> None:
        """"## The crew" must say how many specialists there are, in words.

        The number is hand-typed prose, not derived from anything, so it goes
        stale exactly like the diagram caption CrewRosterTest guards against --
        except nothing else notices this one, because it is not artwork. Spell
        out the count from `agents/*.md` (orchestrator excluded) and fail loudly
        if the sentence's number word no longer matches.
        """
        _NUMBER_WORDS = {
            1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six",
            7: "seven", 8: "eight", 9: "nine", 10: "ten", 11: "eleven",
            12: "twelve", 13: "thirteen", 14: "fourteen", 15: "fifteen",
            16: "sixteen", 17: "seventeen", 18: "eighteen", 19: "nineteen",
            20: "twenty",
        }
        on_disk = {p.stem for p in (_REPO_ROOT / "agents").glob("*.md")}
        self.assertIn("orchestrator", on_disk, "agents/orchestrator.md has gone missing")
        specialist_count = len(on_disk) - 1
        expected_word = _NUMBER_WORDS[specialist_count]
        crew_section = self.source.split("## The crew", 1)[1].split("##", 1)[0]
        self.assertIn(
            expected_word, crew_section.lower(),
            f"docs/index.md's \"## The crew\" section does not say "
            f"'{expected_word}' specialists, but agents/*.md now has "
            f"{specialist_count} agents besides the orchestrator. Update the "
            f"sentence to match.",
        )

    def test_periwinkle_rule_is_86_by_3(self) -> None:
        css = _CSS.read_text(encoding="utf-8")
        rule = re.search(r"\.nescio-hero__rule\s*\{[^}]*\}", css, re.S)
        self.assertIsNotNone(rule, "no .nescio-hero__rule block in nescio.css")
        assert rule is not None
        self.assertIn("width: 86px", rule.group(0))
        self.assertIn("height: 3px", rule.group(0))
        self.assertIn("#8fb0d9", rule.group(0))


if __name__ == "__main__":
    unittest.main()
