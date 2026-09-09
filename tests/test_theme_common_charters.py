# tests/test_theme_common_charters.py
"""T14 regression tests: a non-charter `.md` in `agents/` must not be reported
by `desynced_agents`, and must not make either consumer misbehave.

`scripts/_theme_common.py::_frontmatter_name` used to collapse "no
frontmatter block at all" and "frontmatter block with no `name:` key" into the
same `None`, and `desynced_agents` compared that `None` against the file's
stem exactly like a genuine declared name. A plain doc file such as
`agents/README.md` — no frontmatter, never claiming to be a charter — was
therefore reported as desynced.

That was harmless while `apply_theme.py`'s residue check only ran inside its
`repairing` branch (advisory chatter ahead of a `return 0`). It stopped being
harmless once issue #137 moved that check to run after *every* non-dry-run
pass (`apply_theme.py` now exits 2 on a tree that used to succeed) and once
`sync_from_upstream.py` moved its own warning above the theme classification
(a themed sync now warns on *every single run* against such an instance, with
a message that prints Python's `None` and a fix-with command that cannot fix
it).

These two tests are the regression reproductions named in the T14 task: one
per consumer, each built around a real `agents/README.md`-shaped fixture.
Both are theme-agnostic — this repo may itself be on either theme, so both
tests derive "the other theme" or converge explicitly rather than assuming a
starting point — and neither reads this repo's `.github/`
(`docs_site/test_ci_coverage.py:20-34`: `tests/` itself ships downstream).
"""
from __future__ import annotations

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
import sync_from_upstream as sfu  # noqa: E402

# Plain documentation, no frontmatter, and deliberately free of any roster
# word (`planner`, `plato`, `builder`, ...) so the theme renderer's word-level
# `_transform` is a true no-op over it — this file's content must never
# change shape as a side effect of a theme switch, only its *presence* is
# under test.
_README_TEXT = (
    "# Agents\n\n"
    "This directory holds one YAML-frontmatter charter per agent. See the "
    "project README for how the crew is organised.\n"
)


def _other_theme(theme: str) -> str:
    others = [t for t in apply_theme.THEMES if t != theme]
    assert len(others) == 1, f"expected exactly one other theme, got {others}"
    return others[0]


class ApplyThemeReadmeRegressionTest(unittest.TestCase):
    """`apply_theme` must switch a tree that also carries a non-charter `.md`."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.agents_dir = Path(self._tmp.name) / "agents"
        shutil.copytree(ROOT / "agents", self.agents_dir)

    def tearDown(self):
        self._tmp.cleanup()

    def test_switching_a_tree_with_a_frontmatter_less_readme_exits_zero(self):
        current = apply_theme.detect_theme(self.agents_dir)
        self.assertIn(current, apply_theme.THEMES,
                      "could not detect a theme in the seeded agents/ copy")
        target = _other_theme(current)

        (self.agents_dir / "README.md").write_text(_README_TEXT, encoding="utf-8")

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = apply_theme.apply_theme(self.agents_dir, target)

        self.assertEqual(rc, 0, f"expected exit 0, got {rc}. stdout:\n{out.getvalue()}")
        self.assertIn("switched crew", out.getvalue())
        # The README itself must survive untouched — it carries no roster word.
        self.assertEqual((self.agents_dir / "README.md").read_text(encoding="utf-8"),
                          _README_TEXT)


class SyncReadmeRegressionTest(unittest.TestCase):
    """A themed sync must not warn over a shared, non-charter `agents/README.md`."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.up = base / "upstream"
        self.dst = base / "dest"

    def tearDown(self):
        self._tmp.cleanup()

    def _make_checkout(self, root: Path, theme: str) -> None:
        """install.py + a real, converged `agents/` copy, plus a shared README.

        Converges an actual copy of this repo's `agents/` to `theme` with the
        production renderer (mirroring `tests/test_sync_theme_guards.py`'s own
        `_make_full_checkout` pattern), then adds the identical
        `agents/README.md` fixture used by the sibling checkout — so the file
        is genuinely in sync between upstream and dest, not merely ignored.
        """
        root.mkdir(parents=True)
        (root / "install.py").write_text("# installer\n", encoding="utf-8")
        shutil.copytree(ROOT / "agents", root / "agents")
        if apply_theme.detect_theme(root / "agents") != theme:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = apply_theme.apply_theme(root / "agents", theme)
            self.assertEqual(rc, 0,
                              f"fixture setup: could not converge {root}/agents to "
                              f"{theme!r}: {out.getvalue()}")
        (root / "agents" / "README.md").write_text(_README_TEXT, encoding="utf-8")

    def test_themed_sync_against_shared_readme_reports_already_in_sync(self):
        self._make_checkout(self.up, "functional")
        self._make_checkout(self.dst, "philosophers")

        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = sfu.main(["--upstream", str(self.up), "--dest", str(self.dst), "--apply"])

        self.assertEqual(rc, 0)
        self.assertEqual(err.getvalue(), "",
                          "no desync warning (or anything else) is expected on stderr")
        self.assertIn("framework already in sync — nothing to do.", out.getvalue())


if __name__ == "__main__":
    unittest.main()
