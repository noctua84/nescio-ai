"""Tests for the Material theme: the §7 overrides and the version pin.

Lives in `docs_site/`, NOT `tests/` -- see site_under_test.py for why.

Run from the repo root:

    python -m unittest discover -s docs_site -p "test_site_*.py"

What these guard, and why each one is worth a test:

  * The 404 and footer copy is quoted verbatim from §7.
  * The deploy and the docs-tests job install the same mkdocs-material.
"""

from __future__ import annotations

import re
import unittest

from site_under_test import (
    _404_COPY,
    _DOCS_SITE,
    _FOOTER_TAGLINE,
    _OVERRIDES,
    _REPO_ROOT,
    _squash,
)


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


if __name__ == "__main__":
    unittest.main()
