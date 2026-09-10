# tests/test_sync_theme_audit.py
"""Regression pins for the QA audit of the theme-aware sync
(`docs/reports/2026-09-10-theme-aware-sync-audit.md`, issue noctua84/nescio-ai#133).

Each class below reproduces one audit finding at the level the operator
meets it — `sync_from_upstream.main()` with a real upstream/dest pair — and
pins the corrected behaviour. The unit-level pins for the classifier itself
live in `tests/test_theme_common.py`; these are the end-to-end ones.

Theme-agnostic throughout: this repo may itself be on either theme, so every
fixture that needs "the real crew" copies `agents/` and converges it with the
production renderer (`_make_full_checkout`, mirroring
`tests/test_sync_theme_guards.py` and the `_current_theme`/`_themed` pattern
at `tests/test_agent_definitions.py:118-141`). Must not read this repo's
`.github/` (`docs_site/test_ci_coverage.py:20-34`: `tests/` itself ships
downstream).
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
    path.write_text(text, encoding="utf-8", newline="")


def _make_checkout(root: Path) -> None:
    """The P1 fixture shape: install.py + a single theme-invariant charter.

    Zero representatives AND zero theme-specific roster stems, so it must keep
    classifying as "crewless" and taking today's path — see the audit's
    Serious #3 pin below, which is careful not to widen the new guard onto
    this shape.
    """
    _write(root / "install.py", "# installer\n")
    _write(root / "agents" / "explore.md", "---\nname: explore\n---\nexplore\n")


def _make_full_checkout(root: Path, theme: str) -> None:
    """install.py + a copy of this repo's real `agents/`, converged to `theme`."""
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


def _run(up: Path, dst: Path, *extra: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = sfu.main(["--upstream", str(up), "--dest", str(dst), *extra])
    return rc, out.getvalue(), err.getvalue()


def _add_strays(agents_dir: Path) -> None:
    """The two entries from the audit's Serious #2 reproduction.

    A Latin-1 `.md` (not decodable as UTF-8) and a *directory* whose name
    ends in `.md`. Both match `agents_dir.glob("*.md")`; neither is a charter.
    """
    (agents_dir / "notes.md").write_bytes(b"caf\xe9 notes\n")
    (agents_dir / "x.md").mkdir()


class UnreadableAgentsEntriesTest(unittest.TestCase):
    """Audit Serious #2 — `desynced_agents` crashed the sync on a non-UTF-8
    (or directory) `agents/*.md` in dest, on every path including the
    untheme'd one whose contract is today's behaviour exactly."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.up = base / "upstream"
        self.dst = base / "dest"

    def tearDown(self):
        self._tmp.cleanup()

    def test_untheme_d_dest_with_strays_mirrored_upstream_is_output_identical(self):
        """P1 pin: with the strays present on BOTH sides the plan is empty, so
        the run must be byte-identical (stdout and stderr) to a run without
        them. Before the fix it was a `UnicodeDecodeError` traceback."""
        _make_checkout(self.up)
        _make_checkout(self.dst)
        clean = _run(self.up, self.dst)

        _add_strays(self.up / "agents")
        _add_strays(self.dst / "agents")
        with_strays = _run(self.up, self.dst)

        self.assertEqual(clean, with_strays)
        self.assertEqual(with_strays[0], 0)
        self.assertEqual(with_strays[2], "")
        self.assertIn("framework already in sync — nothing to do.", with_strays[1])

    def test_untheme_d_dest_with_strays_only_in_dest_gets_todays_plan(self):
        """BASE behaviour, restored: the stray file is simply listed under
        `- delete` by the untouched `plan_sync`, and nothing is said about it
        on stderr — the classifier has no opinion on a file it cannot read."""
        _make_checkout(self.up)
        _make_checkout(self.dst)
        _add_strays(self.dst / "agents")

        rc, out, err = _run(self.up, self.dst)

        self.assertEqual(rc, 0)
        self.assertEqual(err, "")
        self.assertIn("would change: 0 added, 0 updated, 1 deleted", out)
        self.assertIn(str(Path("agents") / "notes.md"), out)
        self.assertNotIn("x.md", out, "an empty directory is not a file to delete")

    def test_themed_dest_with_strays_syncs_without_a_spurious_warning(self):
        """Same two entries in a THEMED dest: no crash, no desync warning."""
        _make_full_checkout(self.up, "functional")
        _make_full_checkout(self.dst, "philosophers")
        _add_strays(self.dst / "agents")

        rc, out, err = _run(self.up, self.dst)

        self.assertEqual(rc, 0)
        self.assertEqual(err, "", "no desync warning is expected for a non-charter")
        self.assertIn("instance theme: philosophers", out)
        self.assertIn("would change: 0 added, 0 updated, 1 deleted", out)
        self.assertIn(str(Path("agents") / "notes.md"), out)


class LostRepresentativeTest(unittest.TestCase):
    """Audit Serious #3 — a themed dest missing only its representative
    (`agents/plato.md`) has zero representatives, classifies as crewless, and
    got the silent 11-added/3-updated/10-deleted plan. It must refuse."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.up = base / "upstream"
        self.dst = base / "dest"

    def tearDown(self):
        self._tmp.cleanup()

    def test_themed_dest_missing_only_its_representative_refuses(self):
        _make_full_checkout(self.up, "functional")
        _make_full_checkout(self.dst, "philosophers")
        (self.dst / "agents" / "plato.md").unlink()
        self.assertEqual(apply_theme.theme_representatives(self.dst / "agents"), {},
                         "precondition: zero representatives")
        self.assertEqual(apply_theme.desynced_agents(self.dst / "agents"), [],
                         "precondition: the survivors are self-consistent, so the desync "
                         "warning cannot be what catches this")

        before = _snapshot(self.dst)
        rc, out, err = _run(self.up, self.dst, "--apply")

        self.assertEqual(rc, 2)
        self.assertEqual(_snapshot(self.dst), before, "dest was written to despite the refusal")
        self.assertNotIn("would change", out)
        self.assertNotIn("synced:", out)
        # Names the roster files found and the missing representative.
        for stem in ("aristotle", "archimedes-simple", "cato", "cicero"):
            self.assertIn(f"agents/{stem}.md (philosophers)", err)
        self.assertIn("missing: agents/plato.md", err)
        # And says what a sync in this state would have done.
        self.assertIn("deleting every charter listed above", err)
        self.assertNotIn("plato.md (philosophers)", err,
                         "the missing representative is not among the files *found*")

    def test_crewless_dest_still_takes_todays_path(self):
        """Decision 4 stays: the P1 fixture (`agents/explore.md` only) has zero
        representatives AND zero theme-specific roster stems — `explore` is
        theme-invariant, present in both rosters, evidence of neither — and
        must keep syncing exactly as before, with nothing on stderr."""
        _make_checkout(self.up)
        _make_checkout(self.dst)

        rc, out, err = _run(self.up, self.dst)

        self.assertEqual(rc, 0)
        self.assertEqual(err, "")
        self.assertIn("framework already in sync — nothing to do.", out)

    def test_functional_dest_missing_planner_is_not_refused(self):
        """A functional crew that lost `agents/planner.md` is genuinely
        untheme'd: today's path re-adds the missing charter and nothing is
        destroyed, so the guard must not fire on functional stems alone."""
        _make_full_checkout(self.up, "functional")
        _make_full_checkout(self.dst, "functional")
        (self.dst / "agents" / "planner.md").unlink()

        rc, out, err = _run(self.up, self.dst)

        self.assertEqual(rc, 0)
        self.assertEqual(err, "")
        self.assertIn("would change: 1 added, 0 updated, 0 deleted", out)
        self.assertIn(str(Path("agents") / "planner.md"), out)

    def test_helper_excludes_theme_invariant_stems(self):
        agents = self.dst / "agents"
        _write(agents / "explore.md", "---\nname: explore\n---\nx\n")
        _write(agents / "scout.md", "---\nname: scout\n---\nx\n")
        self.assertEqual(sfu._roster_without_representative(agents), {})
        _write(agents / "cato.md", "---\nname: cato\n---\nx\n")
        _write(agents / "builder.md", "---\nname: builder\n---\nx\n")
        self.assertEqual(sfu._roster_without_representative(agents),
                         {"functional": ["builder.md"], "philosophers": ["cato.md"]})


class ResidueRefusalRemediationTest(unittest.TestCase):
    """Audit Serious #1 — upstream adding `agents/builder-fast.md` (a new
    tier, or any `<roster-word>-<suffix>.md`) makes dest's older renderer
    leave residue; #137 refuses; P2 refuses the sync; the new roster that
    would fix it is never delivered. The structural fix is #142. Here the
    refusal must stay a refusal (P2) but tell the operator what actually
    works, instead of quoting advice about a deleted temp directory."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.up = base / "upstream"
        self.dst = base / "dest"

    def tearDown(self):
        self._tmp.cleanup()

    def test_refusal_carries_the_working_remediation_and_cites_142(self):
        _make_full_checkout(self.up, "functional")
        _make_full_checkout(self.dst, "philosophers")
        src = (self.up / "agents" / "builder-simple.md").read_text(encoding="utf-8")
        self.assertIn("name: builder-simple", src)
        _write(self.up / "agents" / "builder-fast.md",
               src.replace("name: builder-simple", "name: builder-fast", 1))

        before = _snapshot(self.dst)
        rc, out, err = _run(self.up, self.dst, "--apply")

        # P2, unsoftened: still a refusal, still nothing written.
        self.assertEqual(rc, 2)
        self.assertEqual(_snapshot(self.dst), before, "dest was written to despite the refusal")
        self.assertIn("could not render upstream's crew", err)
        # The renderer's stderr is still quoted (it says WHAT failed)...
        self.assertIn("builder-fast.md", err)
        # ...and the working remediation follows it, in order, citing #142.
        self.assertIn("python scripts/apply_theme.py functional", err)
        self.assertIn(f"python scripts/sync_from_upstream.py --upstream {self.up.resolve()} "
                      "--apply", err)
        self.assertIn("python scripts/apply_theme.py philosophers", err)
        self.assertLess(err.index("apply_theme.py functional"),
                        err.index("sync_from_upstream.py --upstream"))
        self.assertLess(err.index("sync_from_upstream.py --upstream"),
                        err.index("apply_theme.py philosophers"))
        self.assertIn("#142", err)

    def test_module_docstring_no_longer_claims_a_later_pass_converges(self):
        """The R8 paragraph said an added/retargeted pair "converges only on a
        later pass". Since #137 the render refuses and the later pass never
        comes. The docstring must say so and cite #142."""
        doc = sfu.__doc__
        self.assertNotIn("converges only on a later pass", doc)
        self.assertIn("#142", doc)
        self.assertIn("builder-fast.md", doc)


if __name__ == "__main__":
    unittest.main()
