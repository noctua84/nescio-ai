"""End-to-end tests against the real, built site.

Lives in `docs_site/`, NOT `tests/` -- see site_under_test.py for why.

Run from the repo root:

    python -m unittest discover -s docs_site -p "test_site_*.py"

What these guard, and why each one is worth a test:

  * The diagrams must reach the page as inline `<svg>`, never `<img>` — that is
    the whole point of hooks/inline_svg.py (design-system.md §6).
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

from site_under_test import (
    _404_COPY,
    _DOCS_SITE,
    _FOOTER_TAGLINE,
    _REPO_ROOT,
    _squash,
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
