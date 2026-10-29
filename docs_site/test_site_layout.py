"""Tests for the site's layout rules: nescio.css and the homepage front matter.

Lives in `docs_site/`, NOT `tests/` -- see site_under_test.py for why.

Run from the repo root:

    python -m unittest discover -s docs_site -p "test_site_*.py"

What these guard, and why each one is worth a test:

  * The diagrams fit their column and open at natural size in a modal, without
    ever making the page body scroll sideways or sliding under the sidebars.
    DiagramLayoutTest pins that: the artwork fits, the modal is what keeps it
    legible, no viewport units at all, and no negative margins on the wrapper.
  * The homepage hides the table of contents but NOT the navigation rail.
    Hiding the rail is a navigation regression that shipped once and is pinned
    against here, not a layout preference.
"""

from __future__ import annotations

import re
import unittest

from site_under_test import _CSS, _INDEX


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


if __name__ == "__main__":
    unittest.main()
