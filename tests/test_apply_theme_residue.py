# tests/test_apply_theme_residue.py
"""Regression coverage for `apply_theme`'s residue check running on *both* branches.

`apply_theme.py` classifies a run as a *repair* (`current == target`) or a
*switch* (`current != target`), and used to re-run `desynced_agents` — the
oracle for "does every charter's `name:` frontmatter agree with its own
filename" — only on the repair branch. A direction switch can produce exactly
the same residue as a repair, because the two mechanisms a switch drives are
governed by different derivations: `_transform` rewrites `name:` frontmatter
by *word*, and `-` is a non-word character, so `\\breviewer\\b` matches inside
an out-of-roster stem like `reviewer-lite`; `renamed_agents` is a roster
*membership* lookup over `PAIRS + TIERED_AGENTS`, which has no entry for such
a stem, so the file itself is never renamed to match. The switch branch used
to print "switched crew: X -> Y" and exit 0 over that mismatch. This file pins
that it no longer does, in both directions, while leaving the repair branch's
own coverage in `tests/test_apply_theme.py` untouched.

Deliberately its own file, not added to `tests/test_apply_theme.py`: that file
is the safety net this change is checked against —
`test_a_desync_the_theme_cannot_fix_is_reported_and_fails` (the repair
direction, unaffected by this change) and `ApplyThemeRoundTripTest` (the real
tree, both directions) both have to keep passing *unedited*, which stays
easiest to see when nothing here has touched them.

Theme-agnostic like its sibling: `tests/` ships to downstream instances that
may already be running the philosopher theme, so every fixture normalises a
fresh copy of the real `agents/` tree to a *known* starting theme before
seeding a synthetic out-of-roster file, rather than assuming this repo's own
`agents/` is on 'functional' today. Follows the `_current_theme` / `_themed`
pattern in `tests/test_agent_definitions.py`. Never reads this repo's
`.github/` — see `docs_site/test_ci_coverage.py` for why that boundary
matters: `tests/` is a framework path shipped to every downstream instance,
`.github/` is not, and a test that depended on it would pass here and fail
the moment it ran anywhere else.
"""

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import _crew_common  # noqa: E402
import apply_theme  # noqa: E402

AGENTS_DIR = ROOT / "agents"


def _other_theme(theme: str) -> str:
    """The theme that is not `theme`."""
    return next(t for t in apply_theme.THEMES if t != theme)


def _seed_agents_copy(tmp_dir: Path) -> Path:
    """A fresh `agents/` copy under `tmp_dir`, seeded from the real tree.

    Never operates on `AGENTS_DIR` itself — every test below writes into this
    copy only.
    """
    agents_dir = tmp_dir / "agents"
    agents_dir.mkdir()
    for src in AGENTS_DIR.glob("*.md"):
        (agents_dir / src.name).write_bytes(src.read_bytes())
    return agents_dir


def _normalize_theme(agents_dir: Path, theme: str) -> None:
    """Switch `agents_dir` onto `theme` if it is not already there.

    The real `agents/` tree this copy is seeded from may already be on either
    theme — a downstream instance may have run `apply_theme.py` long before
    these tests ever run. Every fixture below needs a *known* starting theme
    so it can seed its synthetic out-of-roster file under the right name, so
    it gets there explicitly rather than assuming 'functional'.
    """
    if apply_theme.detect_theme(agents_dir) != theme:
        with contextlib.redirect_stdout(io.StringIO()):
            rc = apply_theme.apply_theme(agents_dir, theme)
        assert rc == 0, f"failed to normalise the fixture onto the '{theme}' theme"


def _lite_stem(theme: str) -> str:
    """The out-of-roster synthetic agent's stem under `theme`: 'reviewer-lite'
    (functional) or 'pyrrho-lite' (philosophers).

    The base word is themed via `_crew_common.themed_name('reviewer', theme)`
    rather than hard-coded, so the fixture tracks `PAIRS` if that table is
    ever edited. The `-lite` suffix is not, and must never become, a real
    tier: `TIERED_AGENTS` names only `builder`, so this stem is guaranteed to
    stay outside `renamed_agents`' membership lookup no matter what `PAIRS`
    says — which is exactly the class of stem this whole file exists to
    reproduce. Picking a stem `TIERED_AGENTS` might one day contain would
    silently stop reproducing the bug instead of pinning it.
    """
    return f"{_crew_common.themed_name('reviewer', theme)}-lite"


def _seed_synthetic_agent(agents_dir: Path, theme: str) -> Path:
    """Write the out-of-roster synthetic agent, themed to `theme`, return its path.

    Declares a `name:` equal to its own stem — an ordinary, loadable charter
    — so the desync under test is produced entirely by the *run*, not baked
    into the fixture. A fixture that started already-desynced would be
    testing `desynced_agents` on a hand-crafted mismatch, not the residue a
    real theme switch leaves behind.
    """
    stem = _lite_stem(theme)
    path = agents_dir / f"{stem}.md"
    path.write_text(
        f"---\nname: {stem}\n---\nA synthetic out-of-roster agent, for residue coverage.\n",
        encoding="utf-8", newline="",
    )
    return path


class ResidueCheckedOnBothBranchesTest(unittest.TestCase):
    """The residue check must fire on a *switch*, not only on a *repair*."""

    def test_switch_to_philosophers_over_a_desyncable_agent_fails_and_names_it(self):
        """functional -> philosophers, with `reviewer-lite.md` in the tree.

        `_transform` rewrites its `name: reviewer-lite` frontmatter to
        `name: pyrrho-lite` (`\\breviewer\\b` matches inside the hyphenated
        stem); `renamed_agents` has no `reviewer-lite` entry, so the file
        itself is not renamed. The pass must therefore refuse to report
        success over the file it just desynced.
        """
        with tempfile.TemporaryDirectory() as tmp:
            agents_dir = _seed_agents_copy(Path(tmp))
            _normalize_theme(agents_dir, "functional")
            _seed_synthetic_agent(agents_dir, "functional")

            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                rc = apply_theme.apply_theme(agents_dir, "philosophers")

            self.assertEqual(rc, 2, "a residue-producing switch must exit non-zero")
            self.assertIn("reviewer-lite.md", err.getvalue(),
                          "the file left declaring a mismatched name must be named "
                          "on stderr")
            self.assertIn("pyrrho-lite", err.getvalue(),
                          "the bogus `name:` it now carries must be named on stderr")
            self.assertNotIn("switched crew", out.getvalue(),
                             "a run that leaves a non-loading agent behind must not "
                             "claim the switch succeeded")

    def test_switch_to_functional_over_a_desyncable_agent_fails_and_names_it(self):
        """The mirror image: philosophers -> functional, with `pyrrho-lite.md` in the tree.

        Same defect, opposite direction: `\\bpyrrho\\b` rewrites the
        frontmatter to `name: reviewer-lite` while `pyrrho-lite.md` itself
        keeps its filename, since `renamed_agents` has no entry for it either.
        """
        with tempfile.TemporaryDirectory() as tmp:
            agents_dir = _seed_agents_copy(Path(tmp))
            _normalize_theme(agents_dir, "philosophers")
            _seed_synthetic_agent(agents_dir, "philosophers")

            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                rc = apply_theme.apply_theme(agents_dir, "functional")

            self.assertEqual(rc, 2, "a residue-producing switch must exit non-zero")
            self.assertIn("pyrrho-lite.md", err.getvalue(),
                          "the file left declaring a mismatched name must be named "
                          "on stderr")
            self.assertIn("reviewer-lite", err.getvalue(),
                          "the bogus `name:` it now carries must be named on stderr")
            self.assertNotIn("switched crew", out.getvalue(),
                             "a run that leaves a non-loading agent behind must not "
                             "claim the switch succeeded")


class CleanSwitchRegressionGuardTest(unittest.TestCase):
    """A clean direction switch over the real `agents/` tree must stay green.

    `desynced_agents` over the real tree is `[]` both before and after a
    philosophers switch today — verified below rather than merely assumed —
    which is what keeps the check added by this fix from becoming a
    false-positive tripwire: if it fired on every switch regardless of
    whether anything was actually desynced, this test is what would catch
    that, not the two tests above (which only prove the check fires when it
    *should*).
    """

    def test_clean_switch_still_exits_zero_and_reports_switched_crew(self):
        with tempfile.TemporaryDirectory() as tmp:
            agents_dir = _seed_agents_copy(Path(tmp))
            start = apply_theme.detect_theme(agents_dir)
            self.assertIn(start, apply_theme.THEMES,
                          "could not detect a theme in the seeded agents/ copy")
            self.assertEqual(apply_theme.desynced_agents(agents_dir), [],
                             "precondition: the real tree must start consistent")
            target = _other_theme(start)

            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = apply_theme.apply_theme(agents_dir, target)

            self.assertEqual(rc, 0, "the new check must not fail a clean switch")
            self.assertIn("switched crew", out.getvalue())
            self.assertEqual(
                apply_theme.desynced_agents(agents_dir), [],
                "the residue check must find nothing to complain about over a "
                "switch of the real, self-consistent roster",
            )


class DryRunExemptionTest(unittest.TestCase):
    """Dry-run stays exempt from the residue check — because it writes nothing.

    Not a loophole: every desync the check could report on a dry run is
    *trivially* still present, because a dry run writes nothing at all — it
    is the same tree, unread by the check, that existed before the call. A
    dry run failing here would not be reporting a real failure; it would be
    reporting the run's own restraint. So the exemption stays, and this test
    pins that a synthetic desync-in-waiting (a file that *would* desync the
    moment a real pass touched it) does not trip it.
    """

    def test_dry_run_exits_zero_over_a_desyncable_agent(self):
        with tempfile.TemporaryDirectory() as tmp:
            agents_dir = _seed_agents_copy(Path(tmp))
            _normalize_theme(agents_dir, "functional")
            path = _seed_synthetic_agent(agents_dir, "functional")
            before = path.read_bytes()

            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = apply_theme.apply_theme(agents_dir, "philosophers", dry_run=True)

            self.assertEqual(rc, 0, "dry-run must stay exempt from the residue check")
            self.assertEqual(path.read_bytes(), before,
                             "dry-run must not have written the synthetic agent")
            self.assertIn("would switch crew", out.getvalue())


if __name__ == "__main__":
    unittest.main()
