# tests/test_sync_theme_mirroring.py
"""Pin R4 — deletion mirroring through the materialised upstream (issue #133).

`.sisyphus/plans/theme-aware-sync-plan.md`, section "R4 — do NOT implement
suppression or filtering ... NOW STRUCTURAL", states the property this module
exists to guard: a themed instance's plan must render upstream's agent set
into dest-space *totally* and then hand it to the same set difference
`plan_sync` has always computed — never suppressing or special-casing an
individual entry. That is what makes deletion mirroring, the safety property
of the whole sync script, hold *structurally* rather than by discipline:
`plan_sync` (`scripts/sync_from_upstream.py:287-323`) is not touched by the
theme-aware materialisation feature at all. Only its *input* changes — a
themed instance's `main()` copies upstream's `agents/` into a temp directory,
renders it into the instance's theme with the existing, unmodified
`apply_theme()`, and then calls the exact same `plan_sync` / `apply_sync`
every untheme'd instance calls. There is nowhere in that design to put a
filter that suppresses a "phantom" add or delete, and there must never become
one — every filtering shortcut considered during design was rejected because
each one swallows a real deletion (see the plan's R4 section for the three
named failure modes).

These tests drive the real CLI entry point, `sync_from_upstream.main()`,
rather than reimplementing the materialisation logic, so they exercise the
actual code path an operator's `--apply` run takes. `main()` does not return
the computed triple as data — `_report` only prints it — so `_parse_plan`
below recovers `(added, updated, deleted)` from the `+ add` / `~ update` /
`- delete` lines `_report` prints. This mirrors the approach the plan's own
guard-test task (T9) takes for other `main()`-level assertions: parse the
printed report rather than reach into internals the materialisation branch
does not export.

Theme-agnostic throughout (this repo's own working tree may itself be on a
theme): the `_current_theme` helper below copies the pattern at
`tests/test_agent_definitions.py:118-126`, and no fixture ever assumes this
repo is on the functional theme. Does not read this repo's `.github/`
(`docs_site/test_ci_coverage.py:20-34` explains why `tests/` must stay
portable to a downstream instance).
"""

from __future__ import annotations

import contextlib
import io
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import apply_theme  # noqa: E402
import sync_from_upstream as sfu  # noqa: E402
from _crew_common import renamed_agents  # noqa: E402

AGENTS_DIR = ROOT / "agents"

# The eleven (functional, themed) filename-stem pairs the theme renames —
# nine PAIRS entries plus the two builder cost tiers. Derived the same way
# `apply_theme.py` derives its own rename list, so this test cannot drift from
# what the renderer actually does.
RENAMES = renamed_agents("philosophers")

# The three charters whose *content* the theme rewrites but whose *filename*
# it leaves alone (`scripts/_crew_common.py:80-87`, THEME_INVARIANT_ROSTER,
# minus the agents that carry no crew-name prose to rewrite).
THEME_INVARIANT_NAMED = ("orchestrator", "scout", "validator")


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _current_theme(agents_dir: Path = AGENTS_DIR) -> str:
    """The theme on disk, normalised to a name `apply_theme.apply_theme` accepts.

    Copies the pattern at `tests/test_agent_definitions.py:118-126`:
    `detect_theme` returns None for a tree it cannot classify (no crew at
    all, or a half-mixed one), and this test suite has no use for that third
    state — it only needs to know whether to converge a *fixture source* to
    functional before use, so None is treated as "not philosophers".
    """
    return ("philosophers" if apply_theme.detect_theme(agents_dir) == "philosophers"
            else "functional")


def _make_functional_checkout(root: Path) -> None:
    """A Nescio checkout at `root` carrying this repo's real, functional agents/.

    Copies the real `agents/` tree rather than a synthetic roster so the
    materialisation this module tests exercises the actual PAIRS-driven
    rename and the actual charter prose, not a hand-picked stand-in that
    might not trip the same code paths. Converges to 'functional' first if
    this repo's own working tree happens to be themed — the theme-agnostic
    requirement (`tests/test_agent_definitions.py:118-141`): a suite that
    assumed this repo's own current theme would silently change behaviour
    the day an instance runs `apply_theme.py philosophers` on itself.
    """
    _write(root / "install.py", "# installer\n")
    shutil.copytree(AGENTS_DIR, root / "agents")
    if _current_theme() != "functional":
        rc = apply_theme.apply_theme(root / "agents", "functional")
        if rc != 0:
            raise RuntimeError("fixture setup: could not converge source tree to functional")


def _make_themed_dest_in_step_with(upstream_root: Path, dest_root: Path) -> None:
    """A themed instance at `dest_root`, exactly in step with `upstream_root`.

    Copies upstream's already-functional `agents/` (see
    `_make_functional_checkout`) and renders it into 'philosophers' with the
    real, unmodified renderer — the same renderer the materialised sync
    branch calls. Building the dest this way, rather than from a second copy
    of this repo's tree, is what guarantees "in step": the dest is
    byte-derived from the exact upstream a test then mutates.
    """
    _write(dest_root / "install.py", "# installer\n")
    shutil.copytree(upstream_root / "agents", dest_root / "agents")
    rc = apply_theme.apply_theme(dest_root / "agents", "philosophers")
    if rc != 0:
        raise RuntimeError("fixture setup: could not theme dest tree")


def _run_main(argv: list[str]):
    """Drive `sfu.main()` with both output streams captured; return (rc, out, err)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = sfu.main(argv)
    return rc, out.getvalue(), err.getvalue()


# `_report` (`scripts/sync_from_upstream.py`) prints each plan entry as
# "  <label>  <item>" where <label> is one of "+ add   ", "~ update", or
# "- delete" (each padded to 8 characters) and <item> is
# `str(Path(entry) / rel)` — OS-native separators, backslash on Windows. The
# `\s+` gap absorbs the label's own padding plus the two literal spaces
# `_report` inserts either side of it, so these patterns do not depend on the
# exact padding width.
_ADD_RE = re.compile(r"^  \+ add\s+(.+)$", re.MULTILINE)
_UPD_RE = re.compile(r"^  ~ update\s+(.+)$", re.MULTILINE)
_DEL_RE = re.compile(r"^  - delete\s+(.+)$", re.MULTILINE)


def _parse_plan(stdout_text: str):
    """Recover (added, updated, deleted) dest-relative POSIX paths from a run's stdout.

    `main()` does not hand the computed triple back as data on the themed
    path — `_report` only prints it — so this is how these tests observe what
    the materialised sync actually decided. Paths are normalised to POSIX
    (`Path(x).as_posix()`) the same way `tests/test_sync_from_upstream.py`
    does, since `_report` prints OS-native separators.
    """
    return (
        [Path(m).as_posix() for m in _ADD_RE.findall(stdout_text)],
        [Path(m).as_posix() for m in _UPD_RE.findall(stdout_text)],
        [Path(m).as_posix() for m in _DEL_RE.findall(stdout_text)],
    )


class _ThemedFixtureTestCase(unittest.TestCase):
    """Shared setup: a functional `upstream` and a themed `dest` in step with it."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.up = base / "upstream"
        self.dst = base / "dest"
        _make_functional_checkout(self.up)
        _make_themed_dest_in_step_with(self.up, self.dst)

    def tearDown(self):
        self._tmp.cleanup()


class DeletionMirroringTest(_ThemedFixtureTestCase):
    """R4, the headline case: a genuine upstream deletion must survive rendering.

    Verified by hand during design (the plan's "Verified results from the
    orchestrator's spike" section): deleting `agents/qa-guard.md` upstream
    against a themed dest produces `deleted == ['agents/cato.md']`. This test
    pins that both in the *report* (what the operator reads before deciding
    whether to run `--apply`) and in the *filesystem* (what `--apply` actually
    does), because the two are allowed to disagree only if `apply_sync` itself
    is broken — and `apply_sync` is one of the functions this whole design
    promises not to touch.
    """

    def test_upstream_deleting_an_agent_deletes_its_themed_counterpart(self):
        (self.up / "agents" / "qa-guard.md").unlink()
        self.assertTrue((self.dst / "agents" / "cato.md").exists(), "fixture sanity")

        rc, out, err = _run_main(
            ["--upstream", str(self.up), "--dest", str(self.dst), "--apply"]
        )

        self.assertEqual(rc, 0, err)
        added, updated, deleted = _parse_plan(out)
        self.assertEqual(deleted, ["agents/cato.md"], out)
        self.assertNotIn("agents/cato.md", added)
        self.assertFalse((self.dst / "agents" / "cato.md").exists(),
                          "--apply must actually remove the themed file, not just report it")


class AdditionThemedContentTest(_ThemedFixtureTestCase):
    """A genuinely new upstream charter is added, and its written bytes are themed.

    The new file's *name* is not one the renamer touches (it is not in the
    eleven-file roster `renamed_agents` derives from `PAIRS`), but its
    *content* is still passed through the same word-boundary transform every
    other charter in the materialised temp copy receives — `apply_theme`
    rewrites every `*.md` under the agents directory it is pointed at, not
    only the renamed ones. This is the same mechanism that gives the three
    theme-invariant charters (orchestrator/scout/validator) themed prose
    without a themed filename.
    """

    def test_a_new_upstream_charter_is_added_with_themed_content(self):
        _write(
            self.up / "agents" / "newbie.md",
            "---\nname: newbie\n---\nThe newbie works closely with the planner "
            "and hands its output to the reviewer for a final pass.\n",
        )

        rc, out, err = _run_main(
            ["--upstream", str(self.up), "--dest", str(self.dst), "--apply"]
        )

        self.assertEqual(rc, 0, err)
        added, updated, deleted = _parse_plan(out)
        self.assertIn("agents/newbie.md", added, out)

        written = (self.dst / "agents" / "newbie.md").read_text(encoding="utf-8")
        self.assertIn("plato", written)
        self.assertIn("pyrrho", written)
        self.assertNotIn("planner", written)
        self.assertNotIn("reviewer", written)


class NoOverlapBetweenAddedAndDeletedTest(_ThemedFixtureTestCase):
    """No dest path may ever appear in both `added` and `deleted` in one run.

    `apply_sync` deletes before it copies
    (`scripts/sync_from_upstream.py:326-336`): the deletion loop runs first,
    the copy loop (added + updated) runs second. If a path ever landed in
    both lists, which one "wins" would be decided by that ordering rather
    than by any stated semantics — a defect class this module exists
    specifically to rule out for the materialised (concatenated) plan, since
    the concatenation is exactly the step a naive implementation might get
    wrong even though the two halves it concatenates (`plan_sync` over the
    themed temp root, `plan_sync` over the rest of upstream) are each
    individually incapable of this by construction.
    """

    def test_added_and_deleted_never_share_a_path(self):
        # A scenario deliberately touching several files at once, across both
        # halves of the materialised plan (agents/ and a non-agents path), so
        # the concatenated triple has real content to check.
        (self.up / "agents" / "qa-guard.md").unlink()
        _write(self.up / "agents" / "newbie.md", "---\nname: newbie\n---\nnewbie body.\n")
        _write(self.up / "skills" / "s" / "SKILL.md", "a new skill\n")

        rc, out, err = _run_main(["--upstream", str(self.up), "--dest", str(self.dst)])

        self.assertEqual(rc, 0, err)
        added, updated, deleted = _parse_plan(out)
        self.assertTrue(added, "fixture should produce at least one addition")
        self.assertTrue(deleted, "fixture should produce at least one deletion")
        self.assertEqual(set(added) & set(deleted), set(),
                          f"path(s) reported as both added and deleted: "
                          f"{set(added) & set(deleted)}")


class RenamedAgentsAppearOnlyUnderThemedNamesTest(_ThemedFixtureTestCase):
    """The eleven renamed charters show up in a themed plan only by their themed name.

    A themed operator reading a plan wants to see the tree they actually
    have. Functional stems (`agents/planner.md`) are meaningless noise in
    that tree and must never appear in the report; the corresponding themed
    stems (`agents/plato.md`) must.
    """

    def test_functional_stems_never_appear_deleted_names_do(self):
        for functional, _themed in RENAMES:
            path = self.up / "agents" / f"{functional}.md"
            path.write_text(path.read_text(encoding="utf-8") + "\nchanged upstream.\n",
                             encoding="utf-8")

        rc, out, err = _run_main(["--upstream", str(self.up), "--dest", str(self.dst)])

        self.assertEqual(rc, 0, err)
        added, updated, deleted = _parse_plan(out)
        all_paths = set(added) | set(updated) | set(deleted)

        functional_paths = {f"agents/{functional}.md" for functional, _ in RENAMES}
        themed_paths = {f"agents/{themed}.md" for _, themed in RENAMES}

        leaked = all_paths & functional_paths
        self.assertEqual(leaked, set(), f"functional stems leaked into the plan: {leaked}")

        missing = themed_paths - all_paths
        self.assertEqual(missing, set(),
                          f"expected every touched renamed agent under its themed name: "
                          f"missing {missing}")


class ThemeInvariantCharterNamingTest(_ThemedFixtureTestCase):
    """orchestrator.md, scout.md and validator.md appear at most once, unrenamed.

    These three carry themed *content* (crew-name prose) but their filenames
    are not in the theme's rename roster at all, so a materialised plan must
    report each one under its own single, unchanged name — never twice
    (once per half of the concatenated plan) and never under any other
    spelling.
    """

    def test_theme_invariant_charters_reported_once_under_unchanged_names(self):
        for name in THEME_INVARIANT_NAMED:
            path = self.up / "agents" / f"{name}.md"
            path.write_text(path.read_text(encoding="utf-8") + "\nchanged upstream.\n",
                             encoding="utf-8")

        rc, out, err = _run_main(["--upstream", str(self.up), "--dest", str(self.dst)])

        self.assertEqual(rc, 0, err)
        added, updated, deleted = _parse_plan(out)
        all_paths = added + updated + deleted  # a list, not a set: duplicates must show up

        for name in THEME_INVARIANT_NAMED:
            expected = f"agents/{name}.md"
            count = all_paths.count(expected)
            self.assertEqual(count, 1,
                              f"{expected} appeared {count} time(s), expected exactly 1: "
                              f"{all_paths}")
            self.assertIn(expected, updated)


if __name__ == "__main__":
    unittest.main()
