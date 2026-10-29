"""Tests for the inlined diagrams: the committed sources and their modal.

Lives in `docs_site/`, NOT `tests/` -- see site_under_test.py for why.

Run from the repo root:

    python -m unittest discover -s docs_site -p "test_site_*.py"

What these guard, and why each one is worth a test:

  * The diagrams must be the **tokenised** sources, not the generated
    `-light`/`-dark` twins. The twins carry concrete hexes, so a page that
    inlined one would look right in whichever scheme happened to be active and
    silently stop following the toggle. Nothing else in the build notices.
  * The diagrams must reach the page as inline `<svg>`, never `<img>` — that is
    the whole point of hooks/inline_svg.py (design-system.md §6).
  * The modal is reachable by keyboard. DiagramModalTest pins the parts of that
    which are easy to lose in a refactor: a real <button> from the hook, and the
    dialog semantics, escape, focus trap and focus return in the script.
"""

from __future__ import annotations

import re
import sys
import unittest

from site_under_test import _DIAGRAMS, _DOCS_SITE, _JS, _MKDOCS_YML, _REPO_ROOT


class DiagramSourcesTest(unittest.TestCase):
    """The committed SVGs under docs/assets/diagrams/."""

    NAMES = ("diagram-crew.svg", "diagram-loop.svg")

    def test_both_diagrams_are_committed(self) -> None:
        # hooks/inline_svg.py searches docs/assets/diagrams/ first and
        # brand/dist/ second. brand/dist/ is gitignored, so CI only ever has the
        # first -- an uncopied diagram builds locally and fails in CI.
        for name in self.NAMES:
            with self.subTest(name=name):
                self.assertTrue((_DIAGRAMS / name).is_file(), f"{name} not committed")

    def test_sources_are_tokenised_not_twins(self) -> None:
        for name in self.NAMES:
            with self.subTest(name=name):
                svg = (_DIAGRAMS / name).read_text(encoding="utf-8")
                self.assertIn(
                    "var(--diagram-", svg,
                    f"{name} carries no --diagram-* tokens, so it is a generated "
                    f"twin, not the tokenised source. The twins cannot follow the "
                    f"scheme toggle.",
                )

    def test_no_twins_were_copied_in(self) -> None:
        strays = sorted(
            p.name for p in _DIAGRAMS.glob("*.svg")
            if p.stem.endswith(("-light", "-dark"))
        )
        self.assertEqual([], strays, "generated twins do not belong here")

    def test_no_background_rect(self) -> None:
        # §6 authoring rule: the page supplies the ground. A background <rect>
        # would punch a light box into the dark scheme.
        for name in self.NAMES:
            with self.subTest(name=name):
                svg = (_DIAGRAMS / name).read_text(encoding="utf-8")
                self.assertNotRegex(svg, r"<rect[^>]*\bwidth=\"100%\"")

    def test_committed_copies_match_the_generator(self) -> None:
        # These files are a *copy* of brand/dist/, which is gitignored and so
        # absent in CI. A copy can drift the moment make_diagrams.py is re-run
        # and nobody re-copies -- and the drift is invisible, because the stale
        # SVG still renders. Regenerate in memory and compare. §8: "the brand is
        # code, not files."
        sys.path.insert(0, str(_REPO_ROOT))
        try:
            from brand import make_diagrams
        finally:
            sys.path.pop(0)

        for stem, make in make_diagrams.DIAGRAMS.items():
            with self.subTest(stem=stem):
                committed = (_DIAGRAMS / f"{stem}.svg").read_text(encoding="utf-8")
                self.assertEqual(
                    make(), committed,
                    f"docs_site/docs/assets/diagrams/{stem}.svg is stale. Re-run "
                    f"`python brand/make_diagrams.py` and copy the tokenised "
                    f"source (not the twins) back over it.",
                )

    def test_hook_resolves_every_marker_in_every_page(self) -> None:
        sys.path.insert(0, str(_DOCS_SITE / "hooks"))
        try:
            import inline_svg
        finally:
            sys.path.pop(0)

        markers = set()
        for page in (_DOCS_SITE / "docs").rglob("*.md"):
            markers.update(inline_svg._MARKER.findall(page.read_text(encoding="utf-8")))
        self.assertTrue(markers, "no diagram markers found in any page")
        for name in sorted(markers):
            with self.subTest(marker=name):
                inline_svg._resolve(name)  # raises FileNotFoundError if missing



class DiagramModalTest(unittest.TestCase):
    """The full-size view that pays for fitting the artwork to the column.

    Fitting is only defensible because natural size is one activation away. If
    the modal quietly stops working, the page keeps rendering shrunken diagrams
    and nothing else in the build notices — which is what these guard.

    The keyboard assertions are the ones worth writing down. The activator is a
    real <button type="button"> rather than a <div> with a click handler, so it
    is focusable and Enter/Space fire `click` with no keydown branch of our own;
    a <div> would need tabindex, role and that branch, and would be one tidy-up
    away from losing them silently. Escape, the focus trap, and returning focus
    to the opener are the three things a hand-rolled dialog most often ships
    without, and none of them show up in a screenshot.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _JS.read_text(encoding="utf-8")
        # The file is one long comment plus one IIFE; strip the comments so a
        # rule cannot be satisfied by prose that merely mentions it.
        cls.code = re.sub(r"/\*.*?\*/", " ", cls.js, flags=re.S)
        cls.code = re.sub(r"(?m)//.*$", " ", cls.code)

    def test_hook_wraps_the_artwork_in_a_real_button(self) -> None:
        sys.path.insert(0, str(_DOCS_SITE / "hooks"))
        try:
            import inline_svg
        finally:
            sys.path.pop(0)

        html = inline_svg.on_page_content("<!-- diagram: crew -->")
        self.assertIn('<button type="button"', html)
        self.assertIn(f'class="{inline_svg.TRIGGER_CLASS}"', html)
        self.assertIn("<svg", html)
        self.assertNotRegex(
            html, r"<div[^>]*onclick", "the activator must be a <button>, not a "
            "<div> with a click handler -- the button is focusable and "
            "Enter/Space-activatable for free.",
        )

    def test_button_says_what_it_opens(self) -> None:
        sys.path.insert(0, str(_DOCS_SITE / "hooks"))
        try:
            import inline_svg
        finally:
            sys.path.pop(0)

        # The SVG has no <title>, so without an explicit label the button's
        # accessible name would be every text node in the artwork, run together.
        for marker, expected in (("crew", "the crew diagram"), ("loop", "the loop diagram")):
            with self.subTest(marker=marker):
                html = inline_svg.on_page_content(f"<!-- diagram: {marker} -->")
                self.assertIn(f'aria-label="Open {expected} full size"', html)
                self.assertIn(f'data-diagram-title="The {marker} diagram"', html)

    def test_hook_title_accepts_every_marker_spelling(self) -> None:
        sys.path.insert(0, str(_DOCS_SITE / "hooks"))
        try:
            import inline_svg
        finally:
            sys.path.pop(0)

        for spelling in ("crew", "diagram-crew", "diagram-crew.svg", "crew.svg"):
            with self.subTest(spelling=spelling):
                self.assertEqual("The crew diagram", inline_svg._title(spelling))

    def test_script_is_registered(self) -> None:
        self.assertTrue(_JS.is_file(), "docs/assets/js/diagram-lightbox.js is missing")
        config = _MKDOCS_YML.read_text(encoding="utf-8")
        self.assertRegex(
            config, r"(?m)^extra_javascript:",
            "the modal script is not registered; extra_css above it is the "
            "pattern to follow.",
        )
        self.assertIn("assets/js/diagram-lightbox.js", config)

    def test_script_makes_no_external_request(self) -> None:
        # §3 again: no CDN, no third-party request at runtime. A modal is the
        # classic excuse to reach for a library.
        self.assertIsNone(re.search(r"https?://", self.code))
        for forbidden in ("import ", "require(", "fetch(", "XMLHttpRequest"):
            with self.subTest(token=forbidden):
                self.assertNotIn(forbidden, self.code)

    def test_dialog_semantics(self) -> None:
        self.assertIn('"role", "dialog"', self.code)
        self.assertIn('"aria-modal", "true"', self.code)
        self.assertIn("aria-labelledby", self.code)

    def test_escape_closes(self) -> None:
        self.assertRegex(self.code, r'key\s*===\s*"Escape"')

    def test_focus_is_trapped_and_returned(self) -> None:
        # Trapped: Tab is intercepted and wrapped inside the dialog.
        self.assertRegex(self.code, r'key\s*!==\s*"Tab"')
        self.assertIn("pane.contains(", self.code)
        # Returned: without this, focus falls to <body> on close and a keyboard
        # reader loses their place in the page.
        self.assertIn("opener.focus()", self.code)

    def test_backdrop_click_closes(self) -> None:
        self.assertRegex(self.code, r"event\.target\s*===\s*overlay")

    def test_background_scroll_is_locked(self) -> None:
        # And the scrollbar it removes is compensated with the measured width --
        # the one number CSS cannot see, which is why nescio.css needs no
        # viewport unit for it.
        self.assertIn('document.body.style.overflow = "hidden"', self.code)
        self.assertIn("window.innerWidth - document.documentElement.clientWidth", self.code)

    def test_modal_shows_the_tokenised_svg_itself(self) -> None:
        """A clone of the inlined SVG, not a second copy of the artwork.

        The --diagram-* tokens are declared on the element carrying
        data-md-color-scheme, so a clone anywhere in the document inherits them
        and the scheme toggle repaints page and modal together. An <img> or a
        re-fetched file would break the toggle in the modal only -- invisible
        until someone flips the theme with it open.
        """
        self.assertIn("cloneNode(true)", self.code)
        self.assertNotIn("<img", self.code)


if __name__ == "__main__":
    unittest.main()
