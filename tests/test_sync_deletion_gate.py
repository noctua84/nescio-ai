# tests/test_sync_deletion_gate.py
"""The deletion gate added for #138: `--apply` may not delete without opt-in.

Deliberately its own file rather than additions to `tests/test_sync_from_upstream.py`
or `tests/test_sync_theme_*.py`. Those are the safety net this change is checked
against — `DeletionMirroringTest` pins that a genuine upstream deletion reaches
the themed file, and `SyncThemeGuardsTest` pins where the desync warning runs —
and both had to keep passing with only an added `--allow-deletes`, which is
easiest to see when nothing here has touched them.

Two things are pinned, and they are different claims:

1. **Behaviour** — a plan containing deletions refuses under `--apply` unless
   `--allow-deletes` is given, and refuses *before writing anything*. Additions
   and updates are never gated.
2. **Legibility** — deletions are reported as their own headed section, the
   `  - delete  <path>` line shape is preserved because
   `tests/test_sync_theme_mirroring.py` parses the plan back out of stdout with
   `^  - delete\\s+(.+)$`, and the recoverability annotation distinguishes
   "git can restore these" from "git cannot" from "unknown".

The third state matters more than it looks. Presenting *unknown* as *recoverable*
is the failure that would make this gate worthless: it is the reassurance an
operator acts on. So the annotation says "assume none" when it cannot tell, and
there is a test that it does.
"""

import contextlib
import io
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import sync_from_upstream as sfu  # noqa: E402

_DELETE_LINE_RE = re.compile(r"^  - delete\s+(.+)$", re.MULTILINE)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _make_checkout(root: Path) -> None:
    """A minimal tree that passes the Nescio-checkout sanity check."""
    _write(root / "install.py", "# installer\n")
    _write(root / "agents" / "explore.md", "explore\n")


def _git(repo: Path, *args: str) -> bool:
    proc = subprocess.run(["git", *args], cwd=str(repo),
                          capture_output=True, text=True)
    return proc.returncode == 0


class _GateFixture(unittest.TestCase):
    """Upstream missing one file the dest still has — the deletion case."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.up = base / "upstream"
        self.dst = base / "dest"
        _make_checkout(self.up)
        _make_checkout(self.dst)
        # Present downstream, absent upstream -> one deletion in the plan.
        _write(self.dst / "agents" / "stale.md", "stale charter\n")
        self.victim = self.dst / "agents" / "stale.md"
        self.assertTrue(self.victim.exists(), "fixture sanity")

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, *extra: str):
        argv = ["--upstream", str(self.up), "--dest", str(self.dst), *extra]
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = sfu.main(argv)
        return rc, out.getvalue(), err.getvalue()

    def _plan(self):
        return sfu.plan_sync(self.up, self.dst)


class DeletionGateTest(_GateFixture):
    def test_the_fixture_really_produces_a_deletion(self):
        # Anti-vacuity: every test below depends on the plan containing a
        # deletion. Without this they would all pass on an empty plan.
        added, updated, deleted = self._plan()
        self.assertIn("agents/stale.md", [d.replace("\\", "/") for d in deleted],
                      f"fixture must produce a deletion; got {deleted!r}")

    def test_apply_with_deletions_and_no_flag_refuses(self):
        rc, out, err = self._run("--apply")
        self.assertEqual(rc, 2, "deletions without --allow-deletes must refuse")
        self.assertTrue(self.victim.exists(),
                        "a refusal must not have deleted anything")
        self.assertIn("explicit opt-in", err)
        self.assertIn("no files were changed", err)
        self.assertIn("--allow-deletes", err,
                      "the refusal must name the flag that authorises it")

    def test_the_refusal_does_not_report_a_successful_sync_on_stdout(self):
        # A caller piping stdout must not see anything that reads as a plan that
        # was carried out.
        rc, out, err = self._run("--apply")
        self.assertEqual(rc, 2)
        self.assertNotIn("synced:", out)
        self.assertIn("stale.md", err, "the file at risk must be named")

    def test_allow_deletes_authorises_the_deletion(self):
        rc, out, err = self._run("--apply", "--allow-deletes")
        self.assertEqual(rc, 0, err)
        self.assertFalse(self.victim.exists(),
                         "--allow-deletes must actually perform the deletion")
        self.assertIn("pre-authorised", out)
        self.assertIn("synced:", out)

    def test_the_dry_run_is_not_gated_and_writes_nothing(self):
        # The dry run is how the operator reviews the list, so it must never be
        # the thing that refuses.
        rc, out, err = self._run()
        self.assertEqual(rc, 0, err)
        self.assertTrue(self.victim.exists(), "a dry run must not delete")
        self.assertIn("would change:", out)
        self.assertIn("1 deleted", out)

    def test_dry_run_lists_deletions_in_their_own_headed_section(self):
        rc, out, err = self._run()
        self.assertEqual(rc, 0, err)
        self.assertIn("would be DELETED from this instance", out,
                      "deletions need their own heading, not a shared list")
        self.assertLess(
            out.index("would change:"),
            out.index("would be DELETED from this instance"),
            "the headed section comes after the headline counts",
        )

    def test_the_delete_line_shape_stays_parseable(self):
        # `tests/test_sync_theme_mirroring.py` recovers the plan from stdout with
        # `^  - delete\\s+(.+)$`. Restructuring the report must not break that
        # contract, so pin it here too rather than only discovering it there.
        rc, out, err = self._run()
        self.assertEqual(rc, 0, err)
        found = _DELETE_LINE_RE.findall(out)
        self.assertEqual([p.replace("\\", "/") for p in found], ["agents/stale.md"],
                         f"the deletion must still print in the parsed shape; got {out!r}")

    def test_a_plan_with_no_deletions_is_not_gated(self):
        # Additions and updates must stay frictionless, or the gate trains
        # operators to pass --allow-deletes habitually and it protects nothing.
        self.victim.unlink()
        _write(self.up / "agents" / "brand-new.md", "new charter\n")
        added, updated, deleted = self._plan()
        self.assertEqual([d for d in deleted], [], "fixture: no deletions now")
        self.assertTrue(added, "fixture: something to add")

        rc, out, err = self._run("--apply")
        self.assertEqual(rc, 0, err)
        self.assertTrue((self.dst / "agents" / "brand-new.md").exists())
        self.assertNotIn("explicit opt-in", err + out)

    def test_the_gate_lists_deletions_up_to_the_cap_and_says_it_stopped(self):
        many = [f"agents/extra-{i:03d}.md" for i in range(sfu._GATE_LIST_CAP + 5)]
        for rel in many:
            _write(self.dst / Path(rel), "x\n")
        total = len(many) + 1  # plus the fixture's own stale.md
        withheld = total - sfu._GATE_LIST_CAP
        rc, out, err = self._run("--apply")
        self.assertEqual(rc, 2)
        self.assertIn(f"... and {withheld} more", err,
                      "a capped list must say how much it withheld")
        listed = _DELETE_LINE_RE.findall(err)
        self.assertEqual(len(listed), sfu._GATE_LIST_CAP,
                         "the gate caps its own listing")

    def test_the_report_is_never_capped(self):
        # The dry run is the artefact the operator reads; capping it would hide
        # exactly what the gate exists to surface.
        many = [f"agents/extra-{i:03d}.md" for i in range(sfu._GATE_LIST_CAP + 5)]
        for rel in many:
            _write(self.dst / Path(rel), "x\n")
        rc, out, err = self._run()
        self.assertEqual(rc, 0, err)
        self.assertEqual(len(_DELETE_LINE_RE.findall(out)), len(many) + 1,
                         "the dry run must list every deletion")
        self.assertNotIn("... and ", out,
                         "the dry run must not truncate with the gate's elision")


class RecoverabilityAnnotationTest(_GateFixture):
    """The three-valued annotation: recoverable, not recoverable, unknown."""

    def test_untracked_deletions_are_called_out_as_unrecoverable(self):
        with mock.patch.object(sfu, "_untracked_deletions",
                               return_value={"agents/stale.md"}):
            rc, out, err = self._run()
        self.assertEqual(rc, 0, err)
        self.assertIn("NOT tracked by git", out)
        self.assertIn("cannot restore", out)

    def test_all_tracked_says_so_without_waiving_the_opt_in(self):
        with mock.patch.object(sfu, "_untracked_deletions", return_value=set()):
            rc, out, err = self._run()
        self.assertEqual(rc, 0, err)
        self.assertIn("all of these are tracked by git", out)
        self.assertIn("the opt-in is still required", out,
                      "recoverable must not read as unconditional")

    def test_unknown_is_reported_as_unknown_and_not_as_recoverable(self):
        # The failure this exists to prevent: an operator told "git can restore
        # these" when the tool could not actually tell.
        with mock.patch.object(sfu, "_untracked_deletions", return_value=None):
            rc, out, err = self._run()
        self.assertEqual(rc, 0, err)
        self.assertIn("could not determine", out)
        self.assertIn("assume none", out)
        self.assertNotIn("all of these are tracked by git", out)


class UntrackedDeletionsTest(unittest.TestCase):
    """`_untracked_deletions` itself, against a real repository."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name)
        if not _git(self.repo, "--version"):
            self.skipTest("git not available")

    def tearDown(self):
        self._tmp.cleanup()

    def test_splits_tracked_from_untracked(self):
        _write(self.repo / "tracked.md", "t\n")
        _write(self.repo / "untracked.md", "u\n")
        _git(self.repo, "init", "-q")
        _git(self.repo, "config", "user.email", "t@e.invalid")
        _git(self.repo, "config", "user.name", "T")
        _git(self.repo, "config", "commit.gpgsign", "false")
        _git(self.repo, "add", "tracked.md")
        _git(self.repo, "commit", "-q", "-m", "seed")

        result = sfu._untracked_deletions(
            self.repo, ["tracked.md", "untracked.md"])
        self.assertEqual(result, {"untracked.md"})

    def test_a_non_repository_returns_none_not_an_empty_set(self):
        # Not a repo -> git exits non-zero -> unknown, never "nothing untracked".
        result = sfu._untracked_deletions(self.repo, ["anything.md"])
        self.assertIsNone(result)

    def test_no_deletions_short_circuits_without_calling_git(self):
        with mock.patch.object(sfu.subprocess, "run",
                               side_effect=AssertionError("git must not be invoked")):
            self.assertEqual(sfu._untracked_deletions(self.repo, []), set())

    def test_windows_separators_are_normalised_before_comparing(self):
        # `plan_sync` builds paths with `Path(entry) / rel`, so they are
        # backslash-separated on Windows while `git ls-files` always emits
        # forward slashes. Without normalisation every path reads as untracked
        # and the annotation cries wolf on the platform that needs it most.
        _write(self.repo / "sub" / "tracked.md", "t\n")
        _git(self.repo, "init", "-q")
        _git(self.repo, "config", "user.email", "t@e.invalid")
        _git(self.repo, "config", "user.name", "T")
        _git(self.repo, "config", "commit.gpgsign", "false")
        _git(self.repo, "add", "sub/tracked.md")
        _git(self.repo, "commit", "-q", "-m", "seed")

        result = sfu._untracked_deletions(self.repo, ["sub\\tracked.md"])
        self.assertEqual(result, set(),
                         "a backslash-separated tracked path must still match")


if __name__ == "__main__":
    unittest.main()
