"""Pin the four theme-state guards in `scripts/sync_from_upstream.py:main()`,
plus the two refusals whose only job is to keep a themed sync from ever
producing a destructive plan silently.

Issue noctua84/nescio-ai#133 / `.sisyphus/plans/theme-aware-sync-plan.md`
("Decisions already made", R7, and the T5a amendment in TODO 5 step 4) lay out
four states a dest `agents/` tree can be in, plus two upstream-shaped failures
that must never be softened into a warning:

  1. Both theme representatives present in dest (`planner.md` AND `plato.md`)
     -> refuse (decision 2). `detect_theme` answers `None` for exactly this
     tree -- the same answer it gives a crewless one -- so this guard is
     load-bearing: without it the tree falls through to the untheme'd branch
     and produces a fully destructive plan.
  2. Exactly one representative, but `desynced_agents` non-empty (a
     half-renamed tree) -> warn and proceed (decision 3). This is a
     deliberate divergence from #133's original text, which proposed
     refusing here.
  3. Zero representatives, or a clean single-theme tree -> today's behaviour,
     no warning (decisions 4 and the functional case).
  4. A themed `--upstream` against an untheme'd `--dest` -> refuse (R7's
     residual guard; the materialisation branch itself only ever runs when
     the DEST is themed, so it cannot catch this combination on its own).

Two more refusals sit downstream of state (2)/(3) once the dest actually is
themed and materialisation runs:

  - `rc != 0` from the materialising `apply_theme` call refuses the whole
    sync (P2). This is what makes the rename-collision class free -- there
    is exactly one renamer (`apply_theme`'s all-or-nothing pre-flight) and
    P2 makes its refusal load-bearing for `sync_from_upstream.py` too.
  - The ordering of `agents/` entries before every other `FRAMEWORK_PATHS`
    entry in a themed plan is a dependency on `"agents"` being first in that
    list, not a coincidence, and needs its own pin.

The single most important regression here is T5a: a half-renamed dest that
`detect_theme` classifies as **untheme'd** (`agents/planner.md` present, but
declaring `name: plato` in its frontmatter) used to fall straight through the
old code's early return with no warning at all, and got a silent
ten-file-deletion plan. The fix moved the `desynced_agents` check ABOVE the
theme-branch fork in `main()`. `test_half_renamed_dest_that_classifies_as_functional_still_warns`
pins that the check now fires regardless of which branch classification
sends the tree down -- the POSITION of the check relative to the branch is
what is under test, not the wording of the warning it prints.

Theme-agnostic throughout: this repo may itself be on either theme, so every
fixture that needs "the real crew" copies `agents/` and converges it with
`apply_theme.apply_theme`, mirroring the `_current_theme`/`_themed` pattern at
`tests/test_agent_definitions.py:118-141`. Must not read this repo's
`.github/` (`docs_site/test_ci_coverage.py:20-34` explains why: `tests/`
itself ships downstream).
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
    path.write_text(text, encoding="utf-8")


def _make_checkout(root: Path) -> None:
    """A minimal tree that passes the Nescio-checkout sanity check.

    Zero theme representatives: `agents/explore.md` is theme-invariant, so a
    tree seeded with only this file classifies as `detect_theme is None`.
    Its frontmatter `name:` deliberately agrees with its filename stem --
    unlike the same-named helper in `tests/test_sync_from_upstream.py`,
    which needs no frontmatter at all for `plan_sync`/`apply_sync` (neither
    reads it). This module's guard also runs `desynced_agents`, which reads
    the `name:` field, so a fixture meant to exercise the "no warning"
    baseline has to actually be undesynced, not merely low on
    representatives.
    """
    _write(root / "install.py", "# installer\n")
    _write(root / "agents" / "explore.md", "---\nname: explore\n---\nexplore\n")


def _make_full_checkout(root: Path, theme: str) -> None:
    """install.py + a full copy of this repo's real `agents/`, converged to
    `theme`.

    Copies rather than assumes: this repo may itself be on either theme (see
    the module docstring), so every fixture that needs "the real, internally
    consistent crew" goes through here and is driven to the requested theme
    with the production renderer, exactly like an operator would.
    """
    _write(root / "install.py", "# installer\n")
    shutil.copytree(ROOT / "agents", root / "agents")
    if apply_theme.detect_theme(root / "agents") != theme:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = apply_theme.apply_theme(root / "agents", theme)
        assert rc == 0, (
            f"fixture setup: could not converge {root / 'agents'} to "
            f"{theme!r}: {out.getvalue()}"
        )


def _snapshot(root: Path) -> dict[str, bytes]:
    """A byte-for-byte map of every file under `root`, for before/after diffs."""
    return {
        str(p.relative_to(root)): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


class SyncThemeGuardsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.up = base / "upstream"
        self.dst = base / "dest"

    def tearDown(self):
        self._tmp.cleanup()

    # -- decision 2: both representatives in dest -------------------------

    def test_both_representatives_in_dest_refuses(self):
        """`agents/planner.md` AND `agents/plato.md` both present in dest.

        `detect_theme` answers `None` for exactly this tree -- the same
        answer it gives a crewless one -- so without this guard the run
        would fall through to the untheme'd branch and compare a themed
        dest against a functional upstream: the fully destructive plan this
        whole change exists to prevent. The guard must fire first, name
        both files, and write nothing.
        """
        _make_checkout(self.up)
        _write(self.dst / "install.py", "# installer\n")
        _write(self.dst / "agents" / "planner.md", "---\nname: planner\n---\nplan.\n")
        _write(self.dst / "agents" / "plato.md", "---\nname: plato\n---\nplan.\n")

        before = _snapshot(self.dst)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = sfu.main(["--upstream", str(self.up), "--dest", str(self.dst), "--apply"])

        self.assertEqual(rc, 2)
        self.assertIn("planner.md", err.getvalue())
        self.assertIn("plato.md", err.getvalue())
        self.assertEqual(_snapshot(self.dst), before, "dest was written to despite the refusal")

    # -- decision 3: half-renamed THEMED dest warns and proceeds ----------

    def test_half_renamed_themed_dest_warns_and_proceeds(self):
        """Exactly one representative (`plato.md`, so dest classifies as
        'philosophers'), but `desynced_agents` finds a themed charter whose
        `name:` frontmatter disagrees with its filename.

        Decision 3: warn, do not refuse, and let the sync proceed -- a
        cosmetic inconsistency in the theme must not hold a legitimate
        framework update hostage. Proceeding is verified concretely: a
        genuine upstream content change is applied to dest under --apply.
        """
        _make_full_checkout(self.up, "functional")
        _make_full_checkout(self.dst, "philosophers")

        cato = self.dst / "agents" / "cato.md"
        text = cato.read_text(encoding="utf-8")
        desynced_text = text.replace("name: cato", "name: not-cato", 1)
        self.assertNotEqual(desynced_text, text, "fixture setup: could not desync cato.md")
        cato.write_text(desynced_text, encoding="utf-8", newline="")
        self.assertEqual(apply_theme.detect_theme(self.dst / "agents"), "philosophers")
        self.assertIn(("cato.md", "not-cato"), apply_theme.desynced_agents(self.dst / "agents"))

        marker = self.up / "agents" / "explore.md"
        marker.write_text(marker.read_text(encoding="utf-8") + "\nZZZ_PENDING_MARKER_ZZZ\n",
                          encoding="utf-8")

        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = sfu.main(["--upstream", str(self.up), "--dest", str(self.dst), "--apply"])

        self.assertEqual(rc, 0)
        self.assertIn("cato.md", err.getvalue())
        self.assertIn("apply_theme.py", err.getvalue())
        self.assertIn(
            "ZZZ_PENDING_MARKER_ZZZ",
            (self.dst / "agents" / "explore.md").read_text(encoding="utf-8"),
        )

    # -- decisions 4: zero representatives / clean functional dest --------

    def test_zero_representatives_dest_no_warning_todays_behavior(self):
        """A fresh/crewless instance (only `agents/explore.md`, decision 4)
        gets no warning and behaves exactly as it did before this feature.
        """
        _make_checkout(self.up)
        _make_checkout(self.dst)
        _write(self.up / "skills" / "s" / "SKILL.md", "new skill\n")

        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = sfu.main(["--upstream", str(self.up), "--dest", str(self.dst), "--apply"])

        self.assertEqual(rc, 0)
        self.assertEqual(err.getvalue(), "", "no warning or error is expected on this path")
        self.assertTrue((self.dst / "skills" / "s" / "SKILL.md").exists())

    def test_functional_dest_no_warning_todays_behavior(self):
        """A clean, fully-converged functional dest gets no warning and
        behaves exactly as it did before this feature.
        """
        _make_full_checkout(self.up, "functional")
        _make_full_checkout(self.dst, "functional")
        _write(self.up / "skills" / "s" / "SKILL.md", "new skill\n")

        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = sfu.main(["--upstream", str(self.up), "--dest", str(self.dst), "--apply"])

        self.assertEqual(rc, 0)
        self.assertEqual(err.getvalue(), "", "no warning or error is expected on this path")
        self.assertTrue((self.dst / "skills" / "s" / "SKILL.md").exists())

    # -- R7 residual: themed --upstream against an untheme'd dest ---------

    def test_themed_upstream_against_untheme_dest_refuses(self):
        """`--upstream` is itself on the philosophers theme; `--dest` carries
        zero representatives (untheme'd).

        The materialisation branch only ever runs when the DEST is themed,
        so it cannot see -- let alone correct -- this combination; that is
        exactly why the R7 residual guard survives as its own check in
        `main()`, ahead of the branch. Without it, syncing FROM a themed
        instance into an untheme'd one would report every functional
        charter deleted and every philosopher one added: the fully
        destructive plan in the opposite direction.
        """
        _make_full_checkout(self.up, "philosophers")
        _make_checkout(self.dst)

        before = _snapshot(self.dst)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = sfu.main(["--upstream", str(self.up), "--dest", str(self.dst), "--apply"])

        self.assertEqual(rc, 2)
        self.assertIn("philosophers", err.getvalue())
        self.assertIn("plato.md", err.getvalue())
        self.assertEqual(_snapshot(self.dst), before, "dest was written to despite the refusal")

    # -- T5a regression: half-renamed dest that classifies as UNTHEME'D ---

    def test_half_renamed_dest_that_classifies_as_functional_still_warns(self):
        """A dest holding `agents/planner.md` whose frontmatter declares
        `name: plato`, alongside the rest of an otherwise-philosophers tree.

        `theme_representatives` finds only `planner.md` on disk (there is no
        `plato.md` any more -- it was renamed back, not duplicated), so
        `detect_theme` answers 'functional' and this tree takes the
        UNTHEME'D branch in `main()` -- the destructive one for a tree like
        this, because the nine other untouched philosopher charters would
        otherwise read as nine deletions against a functional upstream,
        sight unseen. Before the fix (T5a in the plan), the
        `desynced_agents` check ran only inside the themed branch, so a tree
        routed to the OTHER branch got no warning at all and a silent
        multi-file-deletion plan.

        The property this test pins is WHERE the check runs relative to the
        branch fork, not what it says: a future refactor that moves the
        `desynced_agents` check back down inside the themed-only branch must
        red this test even if it keeps the exact same warning message,
        because this fixture never enters that branch at all.
        """
        _make_full_checkout(self.up, "functional")
        _make_full_checkout(self.dst, "philosophers")

        plato = self.dst / "agents" / "plato.md"
        planner = self.dst / "agents" / "planner.md"
        self.assertTrue(plato.exists())
        self.assertFalse(planner.exists())
        plato.rename(planner)  # filename reverted; frontmatter still says `name: plato`

        # Pin the fixture's own shape before trusting the assertions below.
        self.assertEqual(apply_theme.theme_representatives(self.dst / "agents"),
                          {"functional": "planner.md"})
        self.assertEqual(apply_theme.detect_theme(self.dst / "agents"), "functional")
        self.assertEqual(apply_theme.desynced_agents(self.dst / "agents"),
                          [("planner.md", "plato")])

        marker = self.up / "agents" / "explore.md"
        marker.write_text(marker.read_text(encoding="utf-8") + "\nZZZ_UNTHEMED_MARKER_ZZZ\n",
                          encoding="utf-8")

        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = sfu.main(["--upstream", str(self.up), "--dest", str(self.dst), "--apply"])

        self.assertEqual(rc, 0)
        self.assertIn("planner.md", err.getvalue())
        self.assertIn("plato", err.getvalue())
        self.assertIn(
            "ZZZ_UNTHEMED_MARKER_ZZZ",
            (self.dst / "agents" / "explore.md").read_text(encoding="utf-8"),
        )

    # -- P2: rc != 0 from the materialising render refuses -----------------

    def test_materialising_render_failure_refuses_no_representative_upstream(self):
        """P2, trigger (a): upstream/agents carries NEITHER representative.

        `theme_representatives(upstream/agents)` is `{}` -- falsy -- so
        main()'s step-2 themed-upstream guard passes this upstream through
        untouched; this fixture specifically does NOT qualify for that
        earlier guard, so the refusal asserted below is genuinely exercised
        by the `rc != 0` path materialisation adds, not by step 2. Inside
        the themed branch, `apply_theme` renders the materialised copy of
        `upstream/agents` and returns 2 ("could not detect the crew")
        because `detect_theme` of that copy is None with neither
        representative present. `main()` must refuse (exit 2), frame and
        surface that renderer error on stderr, and write nothing to dest.
        """
        _make_checkout(self.up)  # only agents/explore.md -- zero representatives
        _make_full_checkout(self.dst, "philosophers")

        self.assertEqual(apply_theme.theme_representatives(self.up / "agents"), {})

        before = _snapshot(self.dst)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = sfu.main(["--upstream", str(self.up), "--dest", str(self.dst), "--apply"])

        self.assertEqual(rc, 2)
        self.assertIn("could not render upstream's crew", err.getvalue())
        self.assertIn("could not detect the crew", err.getvalue())
        self.assertEqual(_snapshot(self.dst), before, "dest was written to despite the refusal")

    def test_materialising_render_failure_refuses_a_rename_collision(self):
        """P2, trigger (b): upstream/agents carries BOTH `qa-guard.md` and
        `cato.md`, with only `planner.md` as a representative.

        `theme_representatives(upstream/agents)` is `{'functional':
        'planner.md'}` (neither `qa-guard.md` nor `cato.md` counts as a
        representative file), so the step-2 themed-upstream guard passes --
        this upstream is not itself themed. Materialisation then tries to
        rename `qa-guard.md` -> `cato.md` and finds `cato.md` already
        occupied by an unrelated file: `apply_theme`'s all-or-nothing
        pre-flight (`scripts/apply_theme.py:155-177`) refuses before writing
        anything, and `main()` must turn that refusal into its own exit 2
        with nothing written to dest.

        This is what makes the rename-collision class free: there is
        exactly one renamer in the whole system, and it is the one with the
        pre-flight. This refusal must NEVER be softened into a warning --
        a plan computed against a materialised tree that could not even be
        built is not a plan an operator should be shown at all.
        """
        _write(self.up / "install.py", "# installer\n")
        _write(self.up / "agents" / "planner.md", "---\nname: planner\n---\nplan.\n")
        _write(self.up / "agents" / "qa-guard.md", "---\nname: qa-guard\n---\nguard.\n")
        _write(self.up / "agents" / "cato.md", "---\nname: cato\n---\nunrelated file.\n")
        _make_full_checkout(self.dst, "philosophers")

        self.assertEqual(apply_theme.theme_representatives(self.up / "agents"),
                          {"functional": "planner.md"})

        before = _snapshot(self.dst)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = sfu.main(["--upstream", str(self.up), "--dest", str(self.dst), "--apply"])

        self.assertEqual(rc, 2)
        self.assertIn("could not render upstream's crew", err.getvalue())
        self.assertIn("rename destination(s) already exist", err.getvalue())
        self.assertEqual(_snapshot(self.dst), before, "dest was written to despite the refusal")

    # -- ordering pin: agents/ entries precede other FRAMEWORK_PATHS ------

    def test_agents_entries_ordered_before_other_paths(self):
        """On a themed instance with pending changes in both `agents/` and
        another allowlist path, every `agents/` entry in the reported plan
        must precede every entry from the other path.

        This holds only because `"agents"` is first in `FRAMEWORK_PATHS`
        (`scripts/sync_from_upstream.py:190-208`) and the themed branch
        concatenates `a1` (the `agents/`-only `plan_sync` call) before `a2`
        (everything else) in every triple it builds. That is a dependency
        on list order, not a coincidence -- this test is what keeps a future
        reordering of `FRAMEWORK_PATHS`, or of the `a1`/`a2` concatenation,
        from silently reshuffling a themed instance's plan output.
        """
        _make_full_checkout(self.up, "functional")
        _make_full_checkout(self.dst, "philosophers")

        _write(self.up / "agents" / "zzz-agents-marker.md",
               "---\nname: zzz-agents-marker\n---\nmarker.\n")
        _write(self.up / "skills" / "zzz-skills-marker" / "SKILL.md", "marker skill\n")

        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = sfu.main(["--upstream", str(self.up), "--dest", str(self.dst)])

        self.assertEqual(rc, 0)
        stdout = out.getvalue()
        agents_idx = stdout.find("zzz-agents-marker.md")
        skills_idx = stdout.find("zzz-skills-marker")
        self.assertNotEqual(agents_idx, -1, "expected the new agents/ entry in the plan output")
        self.assertNotEqual(skills_idx, -1, "expected the new skills/ entry in the plan output")
        self.assertLess(agents_idx, skills_idx,
                         "agents/ entries must be listed before other FRAMEWORK_PATHS entries")


if __name__ == "__main__":
    unittest.main()
