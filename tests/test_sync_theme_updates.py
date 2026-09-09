"""T8 (issue #133): real upstream changes to a themed instance still surface,
and the one upstream edit the theme render makes invisible by construction
(R9) is pinned as a documented property, not rediscovered as a defect.

The materialisation fix (`scripts/sync_from_upstream.py`'s `main()`) renders a
themed copy of upstream's `agents/` before comparing, so a themed instance in
step with upstream sees an empty plan instead of the historical
`11 added, 3 updated, 11 deleted` (issue #133). The risk that fix introduces is
that theme-transforming upstream *before* comparing could mask a genuine
upstream change: if two different upstream texts render to the same bytes
under the theme, the sync cannot tell them apart. This module proves that
does NOT happen for ordinary edits — including edits that touch the exact
words the theme rewrites — and pins the one narrow case where it is chosen to
happen on purpose (R9, the many-to-one word mapping).

Fixtures are entirely synthetic: a four-file `agents/` tree built directly by
this module, never copied from this repo's own `agents/`. `planner.md` is a
`PAIRS` member (the theme renames its file); `orchestrator.md`, `scout.md`
and `validator.md` are three of `THEME_INVARIANT_ROSTER`'s real names (the
theme never renames their files, only rewrites their prose — see
`scripts/apply_theme.py`'s module docstring and the "R3" note in
`.sisyphus/plans/theme-aware-sync-plan.md`). Because nothing here reads this
repo's own `agents/` or asks what theme this checkout is currently on, every
test is theme-agnostic by construction — there is nothing in it that could
depend on the answer (compare `tests/test_agent_definitions.py:118-141`'s
`_current_theme` / `_themed` pattern, which exists for tests that DO touch
this repo's real `agents/`).

Does not read this repo's `.github/` (`docs_site/test_ci_coverage.py:20-34`).
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


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # newline="" mirrors apply_theme.py's own writes: no universal-newline
    # translation, so the fixture's "\n" lands on disk as LF regardless of
    # platform, matching what the production renderer itself produces.
    path.write_text(text, encoding="utf-8", newline="")


PLANNER_V1 = (
    "---\nname: planner\n---\n"
    "You are the planner. Draft the plan before work begins.\n"
)
ORCHESTRATOR_V1 = (
    "---\nname: orchestrator\n---\n"
    "Dispatch tasks. Consult the advisor before finalizing scope.\n"
)
SCOUT_V1 = (
    "---\nname: scout\n---\n"
    "Scout the request. Flag risks for the planner.\n"
)
VALIDATOR_V1 = (
    "---\nname: validator\n---\n"
    "Validate the plan before the builder starts.\n"
)


def _make_checkout(root: Path, *, planner: str, orchestrator: str, scout: str,
                    validator: str) -> None:
    """A minimal Nescio checkout: `install.py` plus a four-file `agents/` tree.

    `planner.md` stands in for the nine `PAIRS` members the theme renames.
    `orchestrator.md`, `scout.md` and `validator.md` stand in for the three
    theme-invariant charters the plan calls out by name (issue #133's
    reproduction: their filenames never change, but their prose does).
    """
    _write(root / "install.py", "# installer\n")
    _write(root / "agents" / "planner.md", planner)
    _write(root / "agents" / "orchestrator.md", orchestrator)
    _write(root / "agents" / "scout.md", scout)
    _write(root / "agents" / "validator.md", validator)


def _themed_bytes(agents_dir: Path, theme: str, filename: str) -> bytes:
    """Render a FRESH copy of `agents_dir` into `theme`; return `filename`'s bytes.

    This is the oracle every "applied with themed bytes" assertion below uses.
    It calls the production `apply_theme.apply_theme` renderer directly rather
    than hand-computing the expected rename/rewrite from `PAIRS`, so an
    expectation here can never silently drift from what the renderer actually
    does — the two would have to actually disagree to fail together.
    """
    with tempfile.TemporaryDirectory() as tmp:
        rendered = Path(tmp) / "agents"
        shutil.copytree(agents_dir, rendered)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = apply_theme.apply_theme(rendered, theme)
        if rc != 0:
            raise AssertionError(f"fixture render of {agents_dir} failed: {err.getvalue()}")
        return (rendered / filename).read_bytes()


def _run(argv):
    """Run `sfu.main(argv)`, returning `(rc, stdout, stderr)`."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = sfu.main(argv)
    return rc, out.getvalue(), err.getvalue()


class RealChangesSurviveThemeRenderTest(unittest.TestCase):
    """Shared fixture: a functional `up` and a themed `dst` exactly in step.

    Every test method mutates `up` from this in-sync starting point and then
    asserts on what the sync reports and writes. `setUp` itself asserts the
    fixture starts empty (`already in sync`) — that pins the fixture, not the
    feature under test, so a later failure in a test method can't be confused
    with a broken starting point.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.up = base / "upstream"
        self.dst = base / "dest"
        _make_checkout(
            self.up,
            planner=PLANNER_V1,
            orchestrator=ORCHESTRATOR_V1,
            scout=SCOUT_V1,
            validator=VALIDATOR_V1,
        )

        # dest starts as a byte-identical copy of upstream, then gets themed:
        # a themed instance exactly in step with upstream.
        shutil.copytree(self.up, self.dst)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = apply_theme.apply_theme(self.dst / "agents", "philosophers")
        self.assertEqual(rc, 0, err.getvalue())

        rc, out_text, _ = _run(["--upstream", str(self.up), "--dest", str(self.dst)])
        self.assertEqual(rc, 0)
        self.assertIn("already in sync", out_text)

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_real_content_change_to_a_themed_charter_is_reported_and_applied(self):
        """The ordinary case the whole design exists to keep working: a plain
        upstream edit (no theme words involved) to a PAIRS charter must still
        be reported and, on --apply, written to dest with themed bytes."""
        new_planner = PLANNER_V1 + "\nAlways confirm scope with stakeholders first.\n"
        _write(self.up / "agents" / "planner.md", new_planner)

        rc, out, _ = _run(["--upstream", str(self.up), "--dest", str(self.dst)])
        self.assertEqual(rc, 0)
        self.assertIn("0 added, 1 updated, 0 deleted", out)
        self.assertIn("plato.md", out)

        rc, _, _ = _run(["--upstream", str(self.up), "--dest", str(self.dst), "--apply"])
        self.assertEqual(rc, 0)

        expected = _themed_bytes(self.up / "agents", "philosophers", "plato.md")
        self.assertEqual((self.dst / "agents" / "plato.md").read_bytes(), expected)

    def test_a_change_to_exactly_the_words_the_theme_rewrites_is_still_reported(self):
        """The case most likely to be masked, and the one the plan calls out
        by name: an upstream edit that swaps one theme keyword for ANOTHER —
        `advisor` -> `critic` in agents/orchestrator.md, which renders as
        `aristotle` -> `socrates`. These are two different target words, so
        the rendered bytes genuinely differ and the change must still be
        reported. Contrast with the R9 test below, where the edit reaches the
        SAME target word from two different starting words and is invisible
        by design — the distinguishing fact is whether the *rendered* text
        changed, never whether the *edited* word happens to be theme
        vocabulary."""
        new_orchestrator = (
            "---\nname: orchestrator\n---\n"
            "Dispatch tasks. Consult the critic before finalizing scope.\n"
        )
        _write(self.up / "agents" / "orchestrator.md", new_orchestrator)

        rc, out, _ = _run(["--upstream", str(self.up), "--dest", str(self.dst)])
        self.assertEqual(rc, 0)
        self.assertIn("0 added, 1 updated, 0 deleted", out)
        self.assertIn("orchestrator.md", out)

        rc, _, _ = _run(["--upstream", str(self.up), "--dest", str(self.dst), "--apply"])
        self.assertEqual(rc, 0)

        expected = _themed_bytes(self.up / "agents", "philosophers", "orchestrator.md")
        actual = (self.dst / "agents" / "orchestrator.md").read_bytes()
        self.assertEqual(actual, expected)
        self.assertIn(b"socrates", actual)
        self.assertNotIn(b"aristotle", actual)

    def test_a_theme_invariant_charter_change_is_reported_once_under_its_own_name(self):
        """orchestrator.md, scout.md and validator.md keep their filenames
        under every theme, but their prose is still rewritten (R3). A real
        upstream edit to one of them must be reported exactly ONCE, under its
        own unchanged filename — never split into an add/delete pair — and
        applied with THEMED content, so `subagent_type:` dispatch lines in
        other charters keep resolving against the files actually on disk."""
        new_scout = SCOUT_V1 + "\nEscalate blockers within five minutes.\n"
        _write(self.up / "agents" / "scout.md", new_scout)

        rc, out, _ = _run(["--upstream", str(self.up), "--dest", str(self.dst)])
        self.assertEqual(rc, 0)
        self.assertIn("0 added, 1 updated, 0 deleted", out)

        matches = [ln for ln in out.splitlines() if "scout.md" in ln]
        self.assertEqual(len(matches), 1, out)
        self.assertIn("update", matches[0])
        self.assertNotIn("add", matches[0])
        self.assertNotIn("delete", matches[0])

        rc, _, _ = _run(["--upstream", str(self.up), "--dest", str(self.dst), "--apply"])
        self.assertEqual(rc, 0)

        # filename never moved
        self.assertTrue((self.dst / "agents" / "scout.md").exists())
        self.assertFalse((self.dst / "agents" / "pyrrho.md").exists())

        expected = _themed_bytes(self.up / "agents", "philosophers", "scout.md")
        actual = (self.dst / "agents" / "scout.md").read_bytes()
        self.assertEqual(actual, expected)
        # content is THEMED, not functional: "planner" -> "plato"
        self.assertIn(b"plato", actual)
        self.assertNotIn(b"planner", actual)

    def test_a_change_the_mapping_collapses_is_deliberately_invisible(self):
        """R9, pinned as a chosen property — not rediscovered as a defect.

        The theme's rename mapping is many-to-one: `planner` renders to
        `plato` under the philosopher theme, and a literal upstream `plato`
        renders to `plato` too (there is no rule mapping `plato` to anything,
        since `_mappings("philosophers")` only ever matches the FUNCTIONAL
        side). So an upstream edit that changes exactly the WORD `planner` to
        the WORD `plato` in a charter's body renders identically before and
        after, and this themed instance's sync sees no change at all.

        Practical impact is nil — the instance's own rendering genuinely did
        not change — and this is exactly what `scripts/sync_from_upstream.py`'s
        module docstring ("False negatives: a chosen property...") and
        `scripts/_theme_common.py`'s R9 paragraph both document. This test
        exists so a future reader meets that as a documented decision, not as
        a bug to "fix" by teaching `plan_sync` about the theme — which R4
        forbids for an unrelated, load-bearing reason: a filter capable of
        suppressing this false negative is also a filter capable of
        suppressing a genuine deletion of `qa-guard.md`/`cato.md`, and
        `plan_sync` deliberately has nowhere to put one.
        """
        new_planner = (
            "---\nname: planner\n---\n"
            "You are the plato. Draft the plan before work begins.\n"
        )
        _write(self.up / "agents" / "planner.md", new_planner)

        # Sanity on the premise: the upstream file itself genuinely changed.
        self.assertNotEqual(
            (self.up / "agents" / "planner.md").read_bytes(),
            PLANNER_V1.encode("utf-8"),
        )

        before = (self.dst / "agents" / "plato.md").read_bytes()

        rc, out, _ = _run(["--upstream", str(self.up), "--dest", str(self.dst)])
        self.assertEqual(rc, 0)
        self.assertIn("already in sync", out)

        # Confirmed even under --apply: nothing is written, because nothing
        # was ever reported as a plan entry in the first place.
        rc, out, _ = _run(["--upstream", str(self.up), "--dest", str(self.dst), "--apply"])
        self.assertEqual(rc, 0)
        self.assertIn("already in sync", out)
        self.assertEqual((self.dst / "agents" / "plato.md").read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
