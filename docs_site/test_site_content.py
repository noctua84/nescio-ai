"""Tests for the hand-written site content: hero, inlined diagrams, 404, footer.

Lives in `docs_site/`, NOT `tests/`. `tests/` is on FRAMEWORK_PATHS and syncs
into derived instances, which never receive `docs_site/` -- a test there
importing this module would break `python -m unittest` for every downstream
user. Same rule as test_gen_catalog.py.

Run from the repo root:

    python -m unittest discover -s docs_site

What these guard, and why each one is worth a test:

  * The diagrams must be the **tokenised** sources, not the generated
    `-light`/`-dark` twins. The twins carry concrete hexes, so a page that
    inlined one would look right in whichever scheme happened to be active and
    silently stop following the toggle. Nothing else in the build notices.
  * The diagrams must reach the page as inline `<svg>`, never `<img>` — that is
    the whole point of hooks/inline_svg.py (design-system.md §6).
  * The hero order is a spec decision (§5: install commands ABOVE the buttons)
    that reads as an arbitrary preference to anyone tidying the file later.
  * The 404 and footer copy is quoted verbatim from §7.
  * No external request may leave the built site (§3).
  * The diagrams fit their column and open at natural size in a modal, without
    ever making the page body scroll sideways or sliding under the sidebars.
    DiagramLayoutTest pins that: the artwork fits, the modal is what keeps it
    legible, no viewport units at all, and no negative margins on the wrapper.
  * The homepage hides the table of contents but NOT the navigation rail.
    Hiding the rail is a navigation regression that shipped once and is pinned
    against here, not a layout preference.
  * The modal is reachable by keyboard. DiagramModalTest pins the parts of that
    which are easy to lose in a refactor: a real <button> from the hook, and the
    dialog semantics, escape, focus trap and focus return in the script.
"""

from __future__ import annotations

import re
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

_DOCS_SITE = Path(__file__).resolve().parent
_REPO_ROOT = _DOCS_SITE.parent

_INDEX = _DOCS_SITE / "docs" / "index.md"
_DIAGRAMS = _DOCS_SITE / "docs" / "assets" / "diagrams"
_CSS = _DOCS_SITE / "docs" / "assets" / "css" / "nescio.css"
_JS = _DOCS_SITE / "docs" / "assets" / "js" / "diagram-lightbox.js"
_MKDOCS_YML = _DOCS_SITE / "mkdocs.yml"
_OVERRIDES = _DOCS_SITE / "overrides"

#: design-system.md §7, verbatim. Whitespace is normalised before comparing so
#: the template may wrap the line however it likes.
_404_COPY = (
    "I do not know where this page is. The owl of Minerva flies at dusk; "
    "this one appears to have flown off entirely."
)
_FOOTER_TAGLINE = "The owl of Minerva flies at dusk."

#: Anything that would make the built site phone home (§3: no CDN, no
#: third-party request at runtime).
_EXTERNAL_ASSET_RE = re.compile(
    r"(?:src|href)\s*=\s*[\"']https?://(?!github\.com|claude\.com|squidfunk\.github\.io)"
)


def _squash(text: str) -> str:
    return " ".join(text.split())


def _strip_css_comments(css: str) -> str:
    """Drop /* … */ so a rule cannot be satisfied by a comment that mentions it."""
    return re.sub(r"/\*.*?\*/", " ", css, flags=re.S)


def _rule(css: str, selector: str) -> str:
    """The declaration block for `selector`, with comments already stripped.

    Naive on purpose: nescio.css has no nested at-rules other than @media, and
    every selector asserted below is unique within the file.
    """
    match = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", _strip_css_comments(css))
    if match is None:  # pragma: no cover - assertion failure path
        raise AssertionError(f"no `{selector}` rule in nescio.css")
    return match.group(1)


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


class DiagramLayoutTest(unittest.TestCase):
    """How the inlined artwork is sized — nescio.css §3, "Wide diagrams".

    THE "NEVER SCALE THE ARTWORK" RULE WAS RETIRED, DELIBERATELY. Read this
    before "restoring" it.

    The artwork used to be authored at 1400px — wider than any column here — so
    it rendered at natural size and scrolled inside its wrapper, and this class
    asserted exactly that: `max-width: none` on the svg, with `max-width: 100%`
    called out by name as the tempting one-line fix that makes the diagram fit
    and simultaneously unreadable. That reasoning held only while there was
    nowhere else to see the diagram.

    Two things changed it. The artwork is now authored on a 1000px canvas
    (brand/make_diagrams.py, widths derived rather than hardcoded), so it very
    nearly fits as drawn; and it is wrapped in a real <button> that opens the
    same tokenised SVG at natural size, panning, in the modal that
    docs/assets/js/diagram-lightbox.js builds. Legibility moved one click away
    rather than being traded off, so fitting the column — which costs the reader
    nothing and removes a scrollbar most readers never found — became the better
    default. The old assertions were not weakened; they were replaced by the new
    contract, and DiagramModalTest pins the half that pays for it.

    What did NOT change: the wrapper stays inside its column, and no viewport
    unit appears anywhere in the sheet. Before either rule existed, a break-out
    pulled the wrapper over both rails with negative margins and a viewport-
    derived bleed; measured at 1440x900 that put 63 SVG elements under a sticky
    sidebar, and the opaque-scrollwrap mitigation covered 12-15% of the
    collision while punching a hole through the artwork where it did. Those
    tests stand.
        """

    @classmethod
    def setUpClass(cls) -> None:
        cls.css = _CSS.read_text(encoding="utf-8")
        cls.bare = _strip_css_comments(cls.css)
        cls.wrapper = _rule(cls.css, ".md-typeset .nescio-diagram")
        cls.artwork = _rule(cls.css, ".md-typeset .nescio-diagram__trigger > svg")
        cls.stage = _rule(cls.css, ".nescio-lightbox__stage")

    def test_artwork_fits_its_column(self) -> None:
        # The new contract. `max-width: none` here is what put two thirds of
        # every diagram outside the visible box behind a scrollbar; the full
        # picture belongs on the page and the full SIZE belongs in the modal.
        self.assertIn("max-width: 100%", self.artwork)
        self.assertIn("height: auto", self.artwork)
        self.assertNotRegex(
            self.artwork, r"max-width:\s*none",
            "the artwork is back at its natural width, so it overflows its "
            "column again. Fitting is the deliberate default -- the modal in "
            "diagram-lightbox.js is what keeps the labels legible.",
        )
        self.assertNotRegex(
            self.artwork, r"(?<!max-)\bwidth:", "do not pin the artwork's width "
            "in CSS -- it comes from the SVG's own width attribute, and "
            "brand/make_diagrams.py owns that number.",
        )

    def test_wrapper_no_longer_needs_to_scroll(self) -> None:
        # A box whose content can never exceed it cannot scroll, so the
        # scrollbar gutter and overflow on the wrapper would be dead weight
        # that only ever reserves space nothing uses.
        self.assertNotIn("overflow", self.wrapper)
        # Centred if the canvas is ever narrower than the column.
        self.assertIn("margin-inline: auto", self.artwork)

    def test_the_scroll_affordance_moved_to_the_modal(self) -> None:
        """The affordance was not deleted; it went where scrolling still happens.

        The layered-gradient technique is only meaningful on a box that can
        overflow. Inline, that is now nothing; in the modal, it is the stage,
        which holds the artwork at natural size and pans. Same technique, same
        §2 tokens, so it follows the scheme toggle with the artwork -- a literal
        hex here would strand the affordance in one scheme.
        """
        self.assertIn("background-attachment: local, local, scroll, scroll", self.stage)
        self.assertIn("overflow: auto", self.stage)
        self.assertIn("var(--md-default-bg-color)", self.stage)
        self.assertIn("var(--md-default-fg-color--lightest)", self.stage)
        self.assertNotRegex(
            self.stage, r"#[0-9a-fA-F]{3,6}",
            "the scroll affordance carries a literal hex; it would not repaint "
            "on the scheme toggle. Use a §2 token.",
        )

    def test_modal_chrome_carries_no_literal_hex(self) -> None:
        """Every modal rule, not just the stage.

        The modal frames artwork that repaints on the scheme toggle. A hardcoded
        border or ground would sit there unchanged around it -- the exact defect
        the hex check on the diagram rules was written to catch, one selector
        over.
        """
        for selector in (
            ".nescio-lightbox",
            ".nescio-lightbox__pane",
            ".nescio-lightbox__bar",
            ".nescio-lightbox__title",
            ".nescio-lightbox__close",
            ".nescio-lightbox__stage",
            ".md-typeset .nescio-diagram__trigger:focus-visible",
        ):
            with self.subTest(selector=selector):
                self.assertNotRegex(_rule(self.css, selector), r"#[0-9a-fA-F]{3,6}")

    def test_modal_is_a_fixed_overlay_not_a_viewport_sized_box(self) -> None:
        """`position: fixed; inset: 0` instead of `100vw`/`100vh`.

        A fixed box already takes its size from the viewport, and unlike a
        viewport unit it excludes the classic scrollbar -- which is the whole
        subject of test_no_viewport_units_anywhere below. This is the rule most
        likely to grow a `100vh` in a hurry, so it is asserted directly.
        """
        overlay = _rule(self.css, ".nescio-lightbox")
        self.assertIn("position: fixed", overlay)
        self.assertIn("inset: 0", overlay)

    def test_no_viewport_units_anywhere(self) -> None:
        """The page body must never scroll sideways (§5).

        `100vw` counts the classic scrollbar and `documentElement.clientWidth`
        does not -- measured 15px apart in Chrome on Windows -- so anything
        sized off the viewport overflows the page by exactly the scrollbar.
        Nothing in this sheet needs the viewport: every length comes from the
        containing block, which is already scrollbar-correct. The one former
        exception, the break-out's `--nescio-bleed`, went out with the break-out
        itself, so the rule is now simply "no viewport units at all".
        """
        offenders = sorted(set(re.findall(r"\b\d*\.?\d+(?:vw|vh|vmin|vmax|dvw|dvh|svw|svh|lvw|lvh)\b", self.bare)))
        self.assertEqual(
            [], offenders,
            "a viewport unit is back in nescio.css. Every length here must come "
            "from the containing block -- viewport units count the classic "
            "scrollbar and the client box does not, which is a sideways-"
            "scrolling page by exactly that difference.",
        )

    def test_wrapper_never_escapes_its_column(self) -> None:
        """Regression: the wrapper must not pull itself out over the sidebars.

        This is the bug that was shipped and reverted. Negative margins on the
        wrapper slide the artwork under Material's two sticky sidebars, which
        paint above the article -- 63 SVG elements ended up behind a rail at
        1440x900 -- and no opaque ground on the rails fixes it, because the
        rails are content-height and the diagram is 849px tall. The wrapper
        stays inside its column; the page makes the column wide instead.
        """
        self.assertNotRegex(
            self.wrapper, r"margin[-\w]*:\s*[^;]*(?<![\w)])-\s*[\d.]",
            "a negative margin is back on the diagram wrapper. That is the "
            "sidebar overlap: the wrapper leaves the article column and the "
            "sticky rails paint straight over the artwork.",
        )
        self.assertNotRegex(
            self.bare,
            r"\.nescio-diagram\s*\{[^}]*margin[-\w]*:\s*[^;]*(?<![\w)])-\s*[\d.]",
            "a negative margin is back on the diagram wrapper, in a media query "
            "or a second rule. Same bug, different block.",
        )
        self.assertNotRegex(
            self.wrapper, r"(?<!max-)(?<!background-)\bwidth:",
            "the wrapper must stay `width: auto` so its size comes from the "
            "content column rather than from the viewport.",
        )

    def test_homepage_hides_the_toc_but_keeps_the_nav_rail(self) -> None:
        """`hide: toc` only. `hide: navigation` is a navigation regression.

        Hiding the TOC costs nothing: the homepage is a landing page with four
        headings whose every destination is already linked twice in the body
        (hero buttons, then "Where to go next").

        Hiding `navigation` costs everything, and this is the guard against it
        coming back. It does not merely drop the left rail. Measured on the
        deployed site at desktop widths (>=76.25em) it ALSO makes Material set
        the header hamburger, `.md-header__button[for="__drawer"]`, to
        display:none and omit the footer prev/next block -- rail, hamburger and
        prev/next gone at once, leaving the GitHub icon as the only persistent
        link on the page. Mobile is unaffected, because the drawer CSS overrides
        the `hidden` attribute below that breakpoint, which is exactly why the
        regression shipped unnoticed. The diagrams are narrower with the rail
        present and scroll more; that trade was made deliberately.

        MkDocs only parses a YAML block that starts at the very first byte, so
        this also pins the front matter to the top of the file: preceded by so
        much as a blank line it is inert and the TOC comes back silently.
        """
        source = _INDEX.read_text(encoding="utf-8")
        self.assertTrue(
            source.startswith("---\n") or source.startswith("---\r\n"),
            "docs/index.md must open with YAML front matter on line 1 -- MkDocs "
            "ignores a block that starts anywhere else.",
        )
        front_matter = source.split("---", 2)[1]
        self.assertRegex(
            front_matter, r"(?m)^hide:",
            "docs/index.md has front matter but no `hide:` key.",
        )
        self.assertRegex(
            front_matter, r"(?m)^\s*-\s*toc\s*$",
            "the homepage must hide `toc` -- a four-entry table of contents on a "
            "landing page whose links are already in the body twice.",
        )
        self.assertNotRegex(
            front_matter, r"(?m)^\s*-\s*navigation\s*$",
            "the homepage must NOT hide `navigation`. At >=76.25em that removes "
            "the nav rail, the header hamburger and the footer prev/next block "
            "simultaneously, leaving the GitHub icon as the only persistent link "
            "on the page. Mobile still works, so this does not look broken until "
            "someone opens the site on a laptop. Diagram width is not worth it -- "
            "re-author the diagrams narrower instead.",
        )

    def test_measure_cap_sits_on_the_article_blocks(self) -> None:
        """§5's ~68ch measure, on an article that is no longer capped itself.

        The article is uncapped so the diagram wrapper can use the whole content
        column: `width: auto` on a child can never exceed its containing block,
        and a capped article would pin the diagram to 68ch. The cap moves to the
        article's blocks instead -- which is then the ONLY thing holding prose to
        the measure anywhere on the site. --nescio-measure has to be a
        *registered* property for that to be
        equivalent: unregistered, `68ch` is substituted as a token stream and
        re-resolved against each block's own font, so `68ch` on an h1 comes out
        nearly twice the paragraph measure.
        """
        self.assertRegex(
            self.bare,
            r"@property\s+--nescio-measure\s*\{[^}]*syntax:\s*\"<length>[^\"]*\""
            r"[^}]*inherits:\s*true",
            "--nescio-measure must be registered as an inherited <length>, or "
            "the headings quietly outrun the measure.",
        )
        self.assertIn("max-width: none", _rule(self.css, ".md-content__inner.md-typeset"))
        self.assertIn("68ch", _rule(self.css, ".md-content__inner.md-typeset"))
        self.assertIn(
            "max-width: var(--nescio-measure)",
            _rule(self.css, ".md-content__inner.md-typeset > *"),
        )


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

    def test_periwinkle_rule_is_86_by_3(self) -> None:
        css = _CSS.read_text(encoding="utf-8")
        rule = re.search(r"\.nescio-hero__rule\s*\{[^}]*\}", css, re.S)
        self.assertIsNotNone(rule, "no .nescio-hero__rule block in nescio.css")
        assert rule is not None
        self.assertIn("width: 86px", rule.group(0))
        self.assertIn("height: 3px", rule.group(0))
        self.assertIn("#8fb0d9", rule.group(0))


class OverridesTest(unittest.TestCase):
    """The theme overrides that carry the §7 copy."""

    def test_404_is_a_template_override(self) -> None:
        # A docs/404.md would build to 404/index.html, which GitHub Pages never
        # serves. 404.html is one of Material's static_templates, so the copy
        # has to live in an override.
        self.assertTrue((_OVERRIDES / "404.html").is_file())
        self.assertFalse(
            (_DOCS_SITE / "docs" / "404.md").exists(),
            "a 404.md would not produce _site/404.html -- use the override",
        )

    def test_404_carries_the_spec_copy(self) -> None:
        html = (_OVERRIDES / "404.html").read_text(encoding="utf-8")
        body = html.split("{% block content %}", 1)[-1]
        self.assertIn("nescio.", body)
        self.assertIn(_404_COPY, _squash(body))

    def test_footer_tagline(self) -> None:
        partial = _OVERRIDES / "partials" / "copyright.html"
        self.assertTrue(partial.is_file())
        self.assertIn(_FOOTER_TAGLINE, _squash(partial.read_text(encoding="utf-8")))


class MaterialPinTest(unittest.TestCase):
    """The `mkdocs-material==` pin is duplicated across two workflows. Detect drift.

    `.github/workflows/docs.yml` installs Material to **deploy** the site;
    `.github/workflows/tests.yml` installs it to **validate** the site via
    `BuiltSiteTest`. Bump one and not the other and `docs-tests` certifies a
    Material the deploy never uses. `mkdocs build --strict` cannot catch that:
    the coupling is to CSS *variable names* (`--md-primary-fg-color` and
    friends, see the comment above the pin in docs.yml), and a variable that
    vanished in a release reverts the scheme to the stock palette without
    emitting a single warning. Prose in tests.yml asks the two to be kept in
    step; this is the thing that notices when they are not.

    The version itself is deliberately NOT asserted -- pinning it here would
    make every legitimate bump a three-file edit. Only the *agreement* is
    pinned.

    Half the coupling stays manual. These also name 9.7.7 in prose, and no test
    reads them:

      * `docs_site/docs/assets/css/nescio.css:75` and `:653`
      * `docs_site/hooks/inline_svg.py:47`
      * `docs_site/overrides/404.html:11`
      * `docs/design/design-system.md` (:465, :704, :712, :719, :777, :867)
      * `memory/repo/nescio/adr/0001-no-agent-frameworks-in-nescio.md:55`

    (`docs_site/mkdocs.yml` does not cite a version, despite what you may read
    elsewhere -- it was checked.) Those are all "verified against" notes rather
    than executable pins, so a bump means re-reading them, not just editing a
    number. Stdlib regex only: no YAML parser, so this adds no dependency to a
    suite that must run in a bare checkout.
    """

    #: Matches the pip requirement, not the prose mentions -- the `==` is what
    #: distinguishes "this workflow installs it" from "this comment discusses it".
    _PIN_RE = re.compile(r"mkdocs-material==([0-9][^\s'\"]*)")

    _WORKFLOWS = ("docs.yml", "tests.yml")

    def _pins(self, name: str) -> list[str]:
        path = _REPO_ROOT / ".github" / "workflows" / name
        self.assertTrue(path.is_file(), f"{name} is missing")
        return self._PIN_RE.findall(path.read_text(encoding="utf-8"))

    def test_each_workflow_pins_material_exactly_once(self) -> None:
        for name in self._WORKFLOWS:
            with self.subTest(workflow=name):
                self.assertEqual(
                    1, len(self._pins(name)),
                    f"expected exactly one `mkdocs-material==` pin in {name}; a "
                    "second one would make the agreement check below ambiguous",
                )

    def test_both_workflows_pin_the_same_material(self) -> None:
        found = {name: self._pins(name) for name in self._WORKFLOWS}
        versions = {name: pins[0] for name, pins in found.items() if pins}
        self.assertEqual(
            len(set(versions.values())), 1,
            "the deploy and the docs-tests job install different mkdocs-material "
            f"versions, so the tested site is not the shipped site: {versions}",
        )


class BuiltSiteTest(unittest.TestCase):
    """End-to-end: build the real site and read what actually shipped.

    Skipped when mkdocs is not importable, so `python -m unittest discover -s
    docs_site` still works in a checkout without the docs toolchain.
    """

    site: Path
    index: str
    not_found: str

    @classmethod
    def setUpClass(cls) -> None:
        try:
            import mkdocs  # noqa: F401
        except ImportError:  # pragma: no cover - depends on the environment
            raise unittest.SkipTest("mkdocs is not installed")

        cls._tmp = TemporaryDirectory()
        cls.site = Path(cls._tmp.name) / "site"
        result = subprocess.run(
            [sys.executable, "-m", "mkdocs", "build",
             "-f", str(_DOCS_SITE / "mkdocs.yml"),
             "-d", str(cls.site), "--strict"],
            cwd=_REPO_ROOT, capture_output=True, text=True,
        )
        if result.returncode != 0:  # pragma: no cover - build failure
            cls._tmp.cleanup()
            raise AssertionError(f"mkdocs build failed:\n{result.stdout}\n{result.stderr}")
        cls.index = cls._strip((cls.site / "index.html").read_text(encoding="utf-8"))
        cls.not_found = cls._strip((cls.site / "404.html").read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls) -> None:
        if hasattr(cls, "_tmp"):
            cls._tmp.cleanup()

    @staticmethod
    def _strip(html: str) -> str:
        """Drop HTML comments — index.md's own notes are not rendered content."""
        return re.sub(r"<!--.*?-->", "", html, flags=re.S)

    def test_diagrams_shipped_as_inline_svg(self) -> None:
        wrappers = self.index.count('<div class="nescio-diagram">')
        self.assertEqual(2, wrappers, "expected both diagrams inlined on the home page")
        for chunk in self.index.split('<div class="nescio-diagram">')[1:]:
            block = chunk.split("</div>", 1)[0]
            self.assertIn("<svg", block)
            self.assertNotIn("<img", block)
            self.assertIn(
                "var(--diagram-", block,
                "the inlined artwork carries no tokens -- a generated twin got "
                "inlined instead of the tokenised source",
            )

    def test_diagram_triggers_shipped_as_buttons(self) -> None:
        # The hook can emit a perfect button and the site still ship without it
        # if the marker ever stops being replaced. Read what actually built.
        buttons = re.findall(r'<button type="button" class="nescio-diagram__trigger"[^>]*>', self.index)
        self.assertEqual(2, len(buttons), "expected an activator on both diagrams")
        for button in buttons:
            with self.subTest(button=button):
                self.assertRegex(button, r'aria-label="Open the \w+ diagram full size"')
                self.assertRegex(button, r'data-diagram-title="The \w+ diagram"')

    def test_modal_script_shipped_and_referenced(self) -> None:
        self.assertTrue((self.site / "assets" / "js" / "diagram-lightbox.js").is_file())
        self.assertIn("assets/js/diagram-lightbox.js", self.index)

    def test_no_image_elements_on_the_home_page(self) -> None:
        self.assertEqual([], re.findall(r"<img\b[^>]*>", self.index))

    def test_404_built_at_the_site_root(self) -> None:
        self.assertTrue((self.site / "404.html").is_file())
        self.assertIn(_404_COPY, _squash(self.not_found))
        self.assertNotIn("404 - Not found", self.not_found)

    def test_footer_tagline_on_every_page(self) -> None:
        for name in ("index.html", "404.html", "agents/index.html", "skills/index.html"):
            with self.subTest(page=name):
                html = (self.site / name).read_text(encoding="utf-8")
                self.assertIn(_FOOTER_TAGLINE, _squash(html))

    def test_no_external_requests_anywhere_in_the_build(self) -> None:
        offenders = []
        for path in self.site.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in {".html", ".css", ".js"}:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            if re.search(r"fonts\.(googleapis|gstatic)\.com|//cdn\.", text):
                offenders.append(str(path.relative_to(self.site)))
        self.assertEqual([], offenders)

    def test_self_hosted_faces_shipped(self) -> None:
        fonts = sorted(p.name for p in (self.site / "assets" / "fonts").glob("*.woff2"))
        self.assertTrue(fonts, "no self-hosted faces in the build")


if __name__ == "__main__":
    unittest.main()
