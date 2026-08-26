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
  * The diagrams render at their natural size, without ever making the page body
    scroll sideways or sliding under the sidebars. DiagramLayoutTest pins that:
    no scale-to-fit, no viewport units at all, no negative margins on the
    wrapper — and that the homepage hides the table of contents but NOT the
    navigation rail, which is a navigation regression that shipped once.
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

    The artwork is 1400px and a 68ch prose block is 551px. Scaling to fit is NOT
    the alternative: 1400px squeezed into 551px puts the smallest labels at
    ~4.5px. The width comes from the page instead — the measure cap sits on the
    article's blocks rather than the article, so the wrapper gets the whole
    content column (938px at 1440, 1032px at 1920) and scrolls the rest.

    This replaced a break-out that pulled the wrapper out over both rails with
    negative margins and a viewport-derived bleed. Measured at 1440x900 that put
    63 SVG elements under a sticky sidebar; the opaque-scrollwrap mitigation
    covered 12-15% of the collision and punched a hole through the artwork where
    it did. The tests below pin the replacement: no scale-to-fit, no viewport
    units, no negative margins on the wrapper.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.css = _CSS.read_text(encoding="utf-8")
        cls.bare = _strip_css_comments(cls.css)
        cls.wrapper = _rule(cls.css, ".md-typeset .nescio-diagram")
        cls.artwork = _rule(cls.css, ".md-typeset .nescio-diagram > svg")

    def test_artwork_keeps_its_natural_width(self) -> None:
        # The whole point. `max-width: 100%` here is the tempting one-line
        # "fix" that makes the diagram fit and simultaneously unreadable.
        self.assertIn("max-width: none", self.artwork)
        self.assertNotRegex(
            self.artwork, r"max-width:\s*(100%|\d)",
            "the artwork is being scaled to fit. At 1400px authored width its "
            "smallest labels are 11.5px; in a 551px column that is ~4.5px. "
            "Scroll a legible diagram instead.",
        )
        self.assertNotRegex(
            self.artwork, r"(?<!max-)\bwidth:", "do not pin the artwork's width "
            "in CSS -- it comes from the SVG's own width attribute, and "
            "brand/make_diagrams.py owns that number.",
        )

    def test_wrapper_scrolls_and_centres(self) -> None:
        self.assertIn("overflow-x: auto", self.wrapper)
        # Wider than the box -> scrolls from the left edge; narrower -> centred.
        self.assertIn("margin-inline: auto", self.artwork)

    def test_wrapper_shows_that_it_scrolls(self) -> None:
        # The affordance must follow the scheme toggle like the artwork does, so
        # it is built from §2 tokens rather than literal hexes, and it is masked
        # by `local`-attached covers when there is nothing left to scroll to.
        self.assertIn("background-attachment: local, local, scroll, scroll", self.wrapper)
        self.assertIn("var(--md-default-bg-color)", self.wrapper)
        self.assertIn("var(--md-default-fg-color--lightest)", self.wrapper)
        self.assertNotRegex(
            self.wrapper, r"#[0-9a-fA-F]{3,6}",
            "the scroll affordance carries a literal hex; it would not repaint "
            "on the scheme toggle. Use a §2 token.",
        )

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
