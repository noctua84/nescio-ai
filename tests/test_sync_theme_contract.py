# tests/test_sync_theme_contract.py
"""The core invariant of theme-aware sync (issue #133): contract (a) and (b).

Materialisation's whole argument is that a themed instance exactly in step
with upstream gets a genuinely empty plan, not a permanent `11 added, 3
updated, 11 deleted`. That argument rests on two facts that must both hold at
once:

  (a) the themed bytes `apply_sync` writes are EXACTLY what `apply_theme`
      itself would produce — so re-running `apply_theme` afterwards is a
      real no-op, not one that happens to look clean because the plan was
      never actually applied; and
  (b) the two `plan_sync` calls the themed branch drives — one against a
      materialised, themed copy of upstream's `agents/`, one against real
      upstream for everything else — combine into three empty lists when
      dest is already in step.

These two tests ARE the invariant, not merely examples of it. If either one
can go red, the implementation has drifted from the design in
`.sisyphus/plans/theme-aware-sync-plan.md`, and the correct response is to
fix `scripts/sync_from_upstream.py`'s materialisation — never to loosen
either assertion here to make the suite pass again.

Alongside them: the headline case (the end-to-end message an operator
actually sees) and the identity path, which pins P1 — an untheme'd instance
must execute literally today's code, with no temp directory and no import of
the theme renderer at all.

Theme-agnostic throughout (this repo's own `agents/` may itself be on either
theme — see `_functional_agents_snapshot` below, which mirrors the
`_current_theme` pattern at `tests/test_agent_definitions.py:118-141`), and
this module never reads this repo's `.github/` (`tests/` ships downstream —
see `docs_site/test_ci_coverage.py:20-34`).
"""

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import apply_theme  # noqa: E402
import sync_from_upstream as sfu  # noqa: E402

AGENTS_DIR = ROOT / "agents"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _make_checkout(root: Path, agents_bytes: dict[str, bytes]) -> None:
    """A minimal Nescio-checkout-shaped tree: `install.py` + the given charters."""
    _write(root / "install.py", "# installer\n")
    agents_dir = root / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    for name, data in agents_bytes.items():
        (agents_dir / name).write_bytes(data)


def _functional_agents_snapshot() -> dict[str, bytes]:
    """{filename: bytes} for the real crew, normalised to the functional theme.

    This repo's own `agents/` may already be on the philosophers theme — these
    tests ship downstream to instances that run `apply_theme.py` themselves,
    so the starting theme is *detected*, never assumed (the
    `_current_theme`/`_themed` pattern at `tests/test_agent_definitions.py:
    118-141`). The real `agents/` directory is only ever read from, never
    written to: a scratch copy is converged instead, and the snapshot is
    taken from that copy.
    """
    with tempfile.TemporaryDirectory() as tmp:
        scratch = Path(tmp) / "agents"
        scratch.mkdir()
        for src in AGENTS_DIR.glob("*.md"):
            (scratch / src.name).write_bytes(src.read_bytes())
        current = apply_theme.detect_theme(scratch)
        assert current in apply_theme.THEMES, (
            f"could not detect a theme in a copy of the real agents/ tree: {current!r}"
        )
        if current != "functional":
            with contextlib.redirect_stdout(io.StringIO()):
                rc = apply_theme.apply_theme(scratch, "functional")
            assert rc == 0, "could not converge the real crew to functional for the fixture"
        return {p.name: p.read_bytes() for p in sorted(scratch.glob("*.md"))}


def _build_upstream_and_themed_dest(base: Path) -> tuple[Path, Path]:
    """A functional `upstream` and a `dest` themed 'philosophers' from the same crew.

    Both checkouts start from the identical functional snapshot, so `dest` is
    upstream's crew, rendered into the philosophers theme, and nothing else —
    exactly the "in step" state the whole invariant is about.
    """
    functional = _functional_agents_snapshot()
    upstream = base / "upstream"
    dest = base / "dest"
    _make_checkout(upstream, functional)
    _make_checkout(dest, functional)
    with contextlib.redirect_stdout(io.StringIO()):
        rc = apply_theme.apply_theme(dest / "agents", "philosophers")
    assert rc == 0, "could not seed the themed dest fixture"
    return upstream, dest


def _tree_snapshot(root: Path) -> dict[str, bytes]:
    """relative-posix-path -> raw bytes for every real file under `root`.

    Bytes, not text: a byte-for-byte comparison is the point of contract (a) —
    a text comparison would be blind to a rewrite that changed only line
    endings or trailing whitespace.
    """
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file() and "__pycache__" not in p.parts
    }


class ThemeSyncContractTest(unittest.TestCase):
    """Contract (a) and (b) — together they ARE the theme-aware sync invariant.

    Both tests share one fixture: a functional `upstream` and a `dest` themed
    'philosophers' from the exact same crew, i.e. already in step. Neither
    test drifts the fixture — a genuine content change belongs in
    `tests/test_sync_theme_updates.py`, and a genuine deletion in
    `tests/test_sync_theme_mirroring.py`. This file is only the invariant
    itself: in step in, in step out.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.upstream, self.dest = _build_upstream_and_themed_dest(self.base)

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_materialised_sync_leaves_apply_theme_a_genuine_noop(self):
        """Contract (a): the themed branch writes exactly what apply_theme would.

        Runs a real `--apply` sync of the functional upstream into the themed
        dest (already in step, so this exercises the full materialise ->
        plan -> apply path without expecting any file to actually change),
        then re-runs `apply_theme.apply_theme` directly against dest and
        demands (i) rc == 0, (ii) the exact no-op message, and (iii) zero
        bytes changed anywhere in dest — not just in `agents/`. If the
        materialised bytes ever diverged from what `apply_theme` itself
        would produce, this would either print the "converging" message
        instead of the no-op one, or leave a residue that (iii) catches even
        if (ii) somehow didn't.
        """
        with contextlib.redirect_stdout(io.StringIO()):
            apply_rc = sfu.main([
                "--upstream", str(self.upstream), "--dest", str(self.dest), "--apply",
            ])
        self.assertEqual(apply_rc, 0)

        before = _tree_snapshot(self.dest)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = apply_theme.apply_theme(self.dest / "agents", "philosophers")
        after = _tree_snapshot(self.dest)

        self.assertEqual(rc, 0)
        self.assertIn("already on the 'philosophers' theme — nothing to do.", out.getvalue())
        self.assertEqual(before, after, "apply_theme changed bytes after an in-step sync")

    def test_b_in_step_themed_instance_yields_an_empty_split_plan(self):
        """Contract (b): the two plan_sync calls combine to three empty lists.

        Replicates exactly the split `main()`'s themed branch drives — a
        materialised, philosophers-rendered copy of upstream's `agents/`
        compared with `paths=["agents"]`, and real upstream compared with
        `paths=<everything else>` — using the SAME, unmodified `plan_sync`.
        Nothing here recomputes or re-derives what "in step" means; if this
        combined triple is ever non-empty for this fixture, the materialised
        render disagrees with dest's own bytes and the design has drifted.
        """
        import shutil

        others = [p for p in sfu.FRAMEWORK_PATHS if p != "agents"]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copytree(self.upstream / "agents", root / "agents")
            with contextlib.redirect_stdout(io.StringIO()):
                rc = apply_theme.apply_theme(root / "agents", "philosophers")
            self.assertEqual(rc, 0)

            a1 = sfu.plan_sync(root, self.dest, paths=["agents"])
            a2 = sfu.plan_sync(self.upstream, self.dest, paths=others)

        combined = tuple(x + y for x, y in zip(a1, a2))
        self.assertEqual(combined, ([], [], []))

    def test_headline_case_dry_run_reports_in_sync(self):
        """The end-to-end message an operator actually sees for an in-step themed
        instance: `main()`'s dry run prints the same reassurance an untheme'd
        instance gets, not `11 added, 3 updated, 11 deleted`."""
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = sfu.main(["--upstream", str(self.upstream), "--dest", str(self.dest)])
        self.assertEqual(rc, 0)
        self.assertIn("framework already in sync — nothing to do.", out.getvalue())


class IdentityPathTest(unittest.TestCase):
    """P1 — an untheme'd instance executes LITERALLY today's code path.

    This is the requirement the previously-rejected "identity lens" design
    could only approximate: a lens threaded through `plan_sync` still runs
    through the same machinery for every instance, themed or not, and merely
    behaves like an identity mapping when there is no theme. P1 is strictly
    stronger — for a dest with zero theme representatives, `main()` must
    never construct a temp directory and must never import the theme
    renderer at all, not construct-and-not-use-it.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.up = base / "upstream"
        self.dst = base / "dest"
        seed = {"explore.md": b"explore\n"}
        _make_checkout(self.up, seed)
        _make_checkout(self.dst, seed)

    def tearDown(self):
        self._tmp.cleanup()

    def test_zero_representatives_plan_is_unaffected_by_blocking_materialisation(self):
        # A genuine pending change, so the dry-run report has content to compare
        # rather than trivially matching on an empty plan both times.
        _write(self.up / "skills" / "s" / "SKILL.md", "new\n")

        baseline_out = io.StringIO()
        with contextlib.redirect_stdout(baseline_out):
            baseline_rc = sfu.main(["--upstream", str(self.up), "--dest", str(self.dst)])
        self.assertEqual(baseline_rc, 0)
        self.assertIn("skills/s/SKILL.md", baseline_out.getvalue().replace("\\", "/"))

        class _BoomTemporaryDirectory:
            """Any construction here means the themed branch was reached."""

            def __init__(self, *args, **kwargs):
                raise AssertionError(
                    "P1 violated: an untheme'd dest constructed a temporary directory"
                )

        # A second, independent poison: if the themed branch's lazy import
        # were ever reached, `import apply_theme` resolves this `None` cache
        # entry into an immediate ImportError (see the stdlib import system:
        # a `None` value in sys.modules forces the next import of that name
        # to fail) — which main()'s own except-clause turns into rc == 2, not
        # a raised exception. The tempdir poison above catches the case that
        # slips past this one, and vice versa; between the two, both "no temp
        # directory" and "no renderer import" are pinned independently rather
        # than inferred from one one side-effect.
        guarded_out = io.StringIO()
        with patch.object(sfu.tempfile, "TemporaryDirectory", _BoomTemporaryDirectory), \
             patch.dict(sys.modules, {"apply_theme": None}):
            with contextlib.redirect_stdout(guarded_out):
                guarded_rc = sfu.main(["--upstream", str(self.up), "--dest", str(self.dst)])

        self.assertEqual(guarded_rc, 0)
        self.assertEqual(
            baseline_out.getvalue(), guarded_out.getvalue(),
            "poisoning the theme renderer's import and tempdir changed the untheme'd plan",
        )


if __name__ == "__main__":
    unittest.main()
