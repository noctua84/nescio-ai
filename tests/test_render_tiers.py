# tests/test_render_tiers.py
"""The builder tier charters are generated, and the generator keeps the contract shared.

`scripts/render_tiers.py` renders `agents/builder.md`, `builder-standard.md`
and `builder-simple.md` from `agents/_src/tiers.md.tmpl`. Two properties are
worth pinning:

* **The committed charters are the rendering.** A hand edit to one charter is
  exactly the drift the generator exists to stop, so it must fail here, with a
  message that says which command fixes it.
* **The shared contract is shared by construction.** Tier blocks may appear only
  above `## Your Purpose`. Everything from that heading on is the contract the
  orchestrator parses and escalates on, and the template must give it no way to
  differ between tiers. `TestBuilderTierParity` in test_agent_definitions.py
  checks the same property on the committed files; this checks the source, so a
  tier block added to the contract fails even before anyone regenerates.

These tests ship to instances that may be on the philosopher theme, so the
theme is detected rather than assumed. The themed case is also exercised
directly on a temp copy: the generator must produce the same bytes that
`apply_theme.py`, and therefore `sync_from_upstream.py`, produces.
"""

import contextlib
import io
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import apply_theme  # noqa: E402
import render_tiers  # noqa: E402
from _crew_common import themed_name  # noqa: E402

AGENTS_DIR = ROOT / "agents"
TEMPLATE = AGENTS_DIR / "_src" / "tiers.md.tmpl"

#: Everything from this heading onward is the shared contract.
SHARED_CONTRACT_HEADING = "## Your Purpose"


def _quiet(fn, *args, **kwargs):
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return fn(*args, **kwargs)


class TestCommittedChartersAreTheRendering(unittest.TestCase):
    def test_no_charter_is_stale(self):
        stale = render_tiers.stale_charters(AGENTS_DIR, TEMPLATE)
        self.assertEqual(
            stale, [],
            f"{[p.name for p in stale]} differ from {TEMPLATE.name}. Edit the template, "
            f"not the charter, then run `python scripts/render_tiers.py`.",
        )

    def test_a_hand_edit_is_caught(self):
        with tempfile.TemporaryDirectory() as d:
            agents = Path(d) / "agents"
            shutil.copytree(AGENTS_DIR, agents)
            target = next(iter(render_tiers.rendered_charters(agents)))
            target.write_text(target.read_text(encoding="utf-8") + "\nstray line\n",
                              encoding="utf-8", newline="")
            self.assertEqual(_quiet(render_tiers.main, ["--check", "--agents-dir", str(agents)]), 1)
            self.assertEqual(_quiet(render_tiers.main, ["--agents-dir", str(agents)]), 0)
            self.assertEqual(_quiet(render_tiers.main, ["--check", "--agents-dir", str(agents)]), 0)

    def test_each_charter_declares_its_own_name(self):
        theme = render_tiers._theme_of(AGENTS_DIR)
        for tier in render_tiers.TIERS:
            with self.subTest(tier=tier):
                text = render_tiers.render(TEMPLATE.read_text(encoding="utf-8"), tier)
                self.assertIn(f"\nname: {tier}\n", text)
                self.assertTrue((AGENTS_DIR / f"{themed_name(tier, theme)}.md").exists())

    def test_no_marker_reaches_a_charter(self):
        for path, text in render_tiers.rendered_charters(AGENTS_DIR, TEMPLATE).items():
            with self.subTest(charter=path.name):
                self.assertNotIn("<!--", text)


class TestTemplateKeepsTheContractShared(unittest.TestCase):
    def test_tier_blocks_end_before_the_shared_contract(self):
        lines = TEMPLATE.read_text(encoding="utf-8").split("\n")
        self.assertIn(SHARED_CONTRACT_HEADING, lines,
                      f"{TEMPLATE.name}: no `{SHARED_CONTRACT_HEADING}` heading to anchor on")
        contract = lines[lines.index(SHARED_CONTRACT_HEADING):]
        markers = [line for line in contract if line.startswith("<!-- tier")
                   or line.startswith("<!-- end tier")]
        self.assertEqual(
            markers, [],
            f"{TEMPLATE.name}: tier markers below `{SHARED_CONTRACT_HEADING}`. That is the "
            f"contract the orchestrator relies on being identical; tier-specific text "
            f"belongs above it.",
        )

    def test_every_tier_gets_a_different_preamble(self):
        """Parity by deletion is not parity: each tier must still say which it is."""
        template = TEMPLATE.read_text(encoding="utf-8")
        preambles = {
            tier: render_tiers.render(template, tier).split(SHARED_CONTRACT_HEADING)[0]
            for tier in render_tiers.TIERS
        }
        self.assertEqual(len(set(preambles.values())), len(preambles))


class TestTemplateSyntax(unittest.TestCase):
    def test_unknown_tier_is_refused(self):
        with self.assertRaisesRegex(render_tiers.TemplateError, "unknown tier"):
            render_tiers.render("<!-- tier: builder-fast -->\nx\n<!-- end tier -->", "builder")

    def test_unclosed_block_is_refused(self):
        with self.assertRaisesRegex(render_tiers.TemplateError, "ends inside"):
            render_tiers.render("<!-- tier: builder -->\nx", "builder")

    def test_stray_end_is_refused(self):
        with self.assertRaisesRegex(render_tiers.TemplateError, "no open block"):
            render_tiers.render("x\n<!-- end tier -->", "builder")

    def test_malformed_marker_is_refused(self):
        with self.assertRaisesRegex(render_tiers.TemplateError, "malformed"):
            render_tiers.render("<!-- tier builder -->\nx", "builder")

    def test_blocks_select_and_notes_vanish(self):
        template = ("<!-- note: dropped -->\nshared\n<!-- tier: builder builder-simple -->\n"
                    "top-and-bottom\n<!-- tier: builder-standard -->\nmiddle\n"
                    "<!-- end tier -->\ntail")
        self.assertEqual(render_tiers.render(template, "builder"), "shared\ntop-and-bottom\ntail")
        self.assertEqual(render_tiers.render(template, "builder-standard"), "shared\nmiddle\ntail")


class TestGeneratorFollowsTheTheme(unittest.TestCase):
    def test_other_theme_renders_what_apply_theme_renders(self):
        """Switch a temp copy to the other theme; the generator must agree with it.

        This is the brain's path: sync copies the template unthemed (apply_theme
        rewrites only top-level charters) and themes the charters, and a later
        `render_tiers.py` run there must not see them as stale.
        """
        current = render_tiers._theme_of(AGENTS_DIR)
        other = "functional" if current == "philosophers" else "philosophers"
        with tempfile.TemporaryDirectory() as d:
            agents = Path(d) / "agents"
            shutil.copytree(AGENTS_DIR, agents)
            self.assertEqual(_quiet(apply_theme.apply_theme, agents, other), 0)
            self.assertEqual(
                (agents / "_src" / "tiers.md.tmpl").read_bytes(), TEMPLATE.read_bytes(),
                "apply_theme rewrote the template; it must stay on functional names",
            )
            stale = render_tiers.stale_charters(agents, agents / "_src" / "tiers.md.tmpl")
            self.assertEqual([p.name for p in stale], [])
            for tier in render_tiers.TIERS:
                self.assertTrue((agents / f"{themed_name(tier, other)}.md").exists())

    def test_theme_text_matches_apply_theme(self):
        for tier in render_tiers.TIERS:
            with self.subTest(tier=tier):
                text = render_tiers.render(TEMPLATE.read_text(encoding="utf-8"), tier)
                self.assertNotEqual(apply_theme.theme_text(text, "philosophers"), text)
        with self.assertRaises(ValueError):
            apply_theme.theme_text("x", "romans")


if __name__ == "__main__":
    unittest.main()
