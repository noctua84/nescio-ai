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
