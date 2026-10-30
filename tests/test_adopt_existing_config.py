# tests/test_adopt_existing_config.py
"""The conflict -> stage -> mark-adopted -> relink loop has to be able to close.

`install.py` refuses to overwrite a real file sitting where it wants a symlink.
Instead it stages the conflict for review (`adopt_existing_config.py`), waits
for it to be recorded terminal in the ledger (`mark_adopted.py`), and only then
lets `--relink` swap it. Every step of that is keyed on the *content hash of the
conflicting path* — so a LINKS target the adopt scan does not know about can
never acquire a ledger entry, and the installer asks for a review that is
impossible to complete: a default run re-stages nothing, `--relink` warns
forever, and the settings/CLAUDE.md/hooks integration stays gated.

`scripts/` was exactly that gap (it is a LINKS target; it was not a SOURCES
entry), which is why the structural test below is structural: it fails for the
*next* LINKS addition too, not just for the two that were missing.
"""

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import install  # noqa: E402
import mark_adopted  # noqa: E402

import _adopt_common  # noqa: E402
from scripts import _adopt_common as _adopt_common_pkg  # noqa: E402

# install.py imports `scripts.adopt_existing_config`; `import adopt_existing_config`
# would be a *second* module object with its own globals (both spellings are
# importable, and both are in sys.modules), so patches applied to the bare one
# would miss the copy install actually calls. Same reason both `_adopt_common`
# spellings are imported above: `adopt_existing_config` resolves its LEDGER
# through the bare one, `install` through the packaged one.
adopt = install.adopt_existing_config


class AdoptSourcesCoverInstallTargetsTest(unittest.TestCase):
    """Every path the installer can collide with must be adoptable.

    A LINKS target that is not an adopt source is not a cosmetic omission: it
    is a conflict the two-stage flow cannot retire, because the ledger is keyed
    by the hash of what the scan copied. Asserted over the whole of LINKS so
    the next entry added there cannot reopen the hole.
    """

    #: LINKS targets deliberately left out of the adopt scan. Empty by design.
    #: A new LINKS entry gets a SOURCES entry — or an entry here, with the
    #: reason it can never be a conflict worth reviewing written next to it.
    EXCLUDED_FROM_ADOPTION: frozenset = frozenset()

    def _adopt_source_names(self):
        """SOURCES entries expressed relative to `~/.claude`."""
        names = set()
        for _label, path in adopt.SOURCES:
            try:
                names.add(path.relative_to(adopt.CLAUDE_DIR).as_posix())
            except ValueError:
                continue  # claude_desktop_config.json lives outside ~/.claude
        return names

    def test_the_two_scripts_agree_on_where_claude_lives(self):
        """Precondition for the comparison below being meaningful at all."""
        self.assertEqual(install.CLAUDE_DIR, adopt.CLAUDE_DIR)

    def test_every_link_target_is_an_adopt_source(self):
        covered = self._adopt_source_names()
        self.assertTrue(covered, "adopt_existing_config.SOURCES names nothing under ~/.claude")
        for _src_name, dst_name in install.LINKS:
            if dst_name in self.EXCLUDED_FROM_ADOPTION:
                continue
            with self.subTest(target=dst_name):
                self.assertIn(
                    dst_name,
                    covered,
                    f"install.LINKS symlinks ~/.claude/{dst_name}, but "
                    f"adopt_existing_config.SOURCES never stages it: a real "
                    f"~/.claude/{dst_name} blocks the install and can never be "
                    f"recorded adopted, so the review the installer asks for cannot "
                    f"be completed",
                )

    def test_scripts_and_hooks_are_adopt_sources(self):
        """The two that were missing, named outright.

        The structural test above would pass again if both LINKS and SOURCES
        lost them together. These two are load-bearing for other reasons —
        `hooks/` is wired into settings.json, `scripts/` is what agent prompts
        resolve `~/.claude/scripts/<name>.py` against — so their absence from
        LINKS would be the bigger regression, and this pins them from the other
        side.
        """
        covered = self._adopt_source_names()
        self.assertIn("scripts", covered)
        self.assertIn("hooks", covered)

    def test_the_exclusion_list_is_not_a_place_to_hide_a_live_target(self):
        """Whatever is excluded must at least still be a LINKS target."""
        targets = {dst for _src, dst in install.LINKS}
        self.assertTrue(
            self.EXCLUDED_FROM_ADOPTION <= targets,
            f"EXCLUDED_FROM_ADOPTION names "
            f"{sorted(self.EXCLUDED_FROM_ADOPTION - targets)}, which install.LINKS "
            f"does not link — stale exclusions silently widen the gap this test "
            f"class exists to close",
        )


class ScriptsConflictAdoptionLoopTest(unittest.TestCase):
    """Drive the real loop over temp dirs: stage, record, re-run, relink.

    Nothing here touches the real `~/.claude`, the real `eval/` tree or the
    real ledger: `install`, `adopt_existing_config`, `mark_adopted` and both
    `_adopt_common` copies are pointed at temp directories, and SOURCES is
    rebuilt from the shipped list by relocating each `~/.claude`-relative entry
    (which also drops `claude_desktop_config.json`, the one source that lives
    elsewhere on the machine). Relocating rather than hand-writing the list is
    what keeps this a test of the shipped SOURCES.

    `symlink`/`can_symlink` are stubbed because Windows only grants symlink
    creation under Developer Mode; the loop under test is about hashes and the
    ledger, not about whether this particular shell may link.
    """

    def setUp(self):
        self.repo = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.home = Path(self.enterContext(tempfile.TemporaryDirectory()))
        eval_root = Path(self.enterContext(tempfile.TemporaryDirectory()))

        for src_name, _dst_name in install.LINKS:
            (self.repo / src_name).mkdir(parents=True, exist_ok=True)
        # install_settings reads this; if the conflict gate ever stopped holding,
        # `agent` would show up in ~/.claude/settings.json and the test would see it.
        (self.repo / "settings.json").write_text(
            '{"agent":"orchestrator"}', encoding="utf-8")
        (self.repo / "CLAUDE.md").write_text("# framework\n", encoding="utf-8")

        # The machine's own ~/.claude/scripts: a real directory where the
        # installer wants a symlink.
        (self.home / "scripts").mkdir()
        (self.home / "scripts" / "mine.py").write_text("print('mine')\n", encoding="utf-8")

        self.adopt_dir = eval_root / "adopt"
        self.adopted_dir = eval_root / "adopted"
        self.ledger = eval_root / "adoption-log.md"
        self.ledger.write_text("# Adoption log\n\n", encoding="utf-8")

        relocated = [
            (label, self.home / path.relative_to(adopt.CLAUDE_DIR))
            for label, path in adopt.SOURCES
            if adopt.CLAUDE_DIR in path.parents
        ]
        self.assertTrue(relocated, "no ~/.claude-relative SOURCES entries to relocate")

        stack = self.enterContext(contextlib.ExitStack())
        patch = stack.enter_context
        patch(mock.patch.object(install, "REPO_DIR", self.repo))
        patch(mock.patch.object(install, "CLAUDE_DIR", self.home))
        patch(mock.patch.object(install, "symlink", lambda src, dst, dry_run: True))
        patch(mock.patch.object(install, "can_symlink", lambda directory: True))
        patch(mock.patch.object(adopt, "CLAUDE_DIR", self.home))
        patch(mock.patch.object(adopt, "SOURCES", relocated))
        patch(mock.patch.object(adopt, "ADOPT", self.adopt_dir))
        patch(mock.patch.object(mark_adopted, "ADOPT", self.adopt_dir))
        patch(mock.patch.object(mark_adopted, "ADOPTED", self.adopted_dir))
        for module in (_adopt_common, _adopt_common_pkg, mark_adopted):
            patch(mock.patch.object(module, "LEDGER", self.ledger))

    # -- helpers ----------------------------------------------------------

    def _run_default(self, ledger=None):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = install.do_default(
                dry_run=False,
                ledger={} if ledger is None else ledger,
                parts=frozenset({"agent"}),
                claudemd_choice="skip",
            )
        return rc, buf.getvalue()

    def _run_relink(self, ledger):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = install.do_relink(
                "20260101-000000",
                dry_run=False,
                ledger=ledger,
                parts=frozenset(),
                claudemd_choice="skip",
            )
        return rc, buf.getvalue()

    def _mark_adopted(self, stamp, status="integrated"):
        argv = ["mark_adopted.py", stamp, "--status", status, "--note", "reviewed in test"]
        with mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(io.StringIO()):
            return mark_adopted.main()

    def _staged_runs(self):
        if not self.adopt_dir.is_dir():
            return []
        return sorted(p for p in self.adopt_dir.iterdir() if p.is_dir())

    # -- the loop ---------------------------------------------------------

    def test_a_real_scripts_dir_is_staged_for_review(self):
        rc, out = self._run_default()

        self.assertEqual(rc, 0)
        self.assertIn(str(self.home / "scripts"), out)
        self.assertIn("needs review", out)

        runs = self._staged_runs()
        self.assertEqual(
            len(runs), 1,
            f"expected one staged adopt run, got {[p.name for p in runs]} — a "
            f"conflict install.py routes to the adopt scan was not staged by it",
        )
        staged = runs[0] / "claude-code" / "scripts" / "mine.py"
        self.assertTrue(
            staged.is_file(),
            f"{staged} missing — the staged run does not contain the conflicting "
            f"~/.claude/scripts, so there is nothing to review and no hash to record",
        )
        self.assertEqual(staged.read_text(encoding="utf-8"), "print('mine')\n")

        records = json.loads((runs[0] / "sources.json").read_text(encoding="utf-8"))
        by_label = {r["label"]: r for r in records}
        self.assertIn("claude-code/scripts", by_label)
        self.assertEqual(
            by_label["claude-code/scripts"]["sha8"],
            install.sha8(self.home / "scripts"),
            "the staged hash differs from the hash install.py looks up in the "
            "ledger — the two halves of the flow would never agree",
        )

    def test_the_conflict_gates_the_settings_integration(self):
        rc, _out = self._run_default()
        self.assertEqual(rc, 0)
        self.assertFalse(
            (self.home / "settings.json").exists(),
            "settings.json was integrated while an unadopted conflict was "
            "outstanding — the conflict gate is the whole reason staging is safe",
        )

    def test_marking_the_staged_run_closes_the_loop(self):
        self._run_default()
        run = self._staged_runs()[0]

        self.assertEqual(self._mark_adopted(run.name), 0)
        self.assertFalse(run.exists(), "the reviewed run was not archived")
        self.assertTrue((self.adopted_dir / run.name).is_dir())

        ledger = install.parse_ledger()
        digest = install.sha8(self.home / "scripts")
        self.assertTrue(
            install.is_done(digest, ledger),
            f"~/.claude/scripts hashes to {digest}, which is not recorded terminal "
            f"in the ledger after mark_adopted — the review cannot be completed and "
            f"the installer stays blocked on it forever. Ledger: "
            f"{self.ledger.read_text(encoding='utf-8')!r}",
        )

        # Second default run: the same real dir is still in the way, but it is
        # no longer re-staged, and the installer now points at --relink.
        rc, out = self._run_default(ledger=ledger)
        self.assertEqual(rc, 0)
        self.assertIn("adopted", out)
        self.assertIn("All conflicts are already adopted", out)
        self.assertNotIn("Staging the not-yet-adopted", out)
        self.assertEqual(
            [p.name for p in self._staged_runs()], [],
            "a second adopt run was staged for an already-adopted conflict",
        )

    def test_relink_stops_warning_once_the_conflict_is_adopted(self):
        """The warning is the visible end of the loop.

        `--relink` backs up and links either way; what changes is whether it
        tells the user it is linking over something that was never reviewed.
        Asserted in both directions, because the "no warning" half alone would
        pass just as well against a `--relink` that never warns at all.
        """
        warning = "not recorded as adopted in the ledger"

        _rc, before = self._run_relink(install.parse_ledger())
        self.assertIn(warning, before)

        # Put the conflict back (relink moved it to a .bak) and run the loop.
        for bak in self.home.glob("scripts.pre-adopt-*.bak"):
            bak.rename(self.home / "scripts")
        self._run_default()
        self._mark_adopted(self._staged_runs()[0].name)

        rc, after = self._run_relink(install.parse_ledger())
        self.assertEqual(rc, 0)
        self.assertNotIn(
            warning, after,
            "--relink still calls ~/.claude/scripts unadopted after a full "
            "stage-and-record cycle",
        )
        self.assertTrue(any(self.home.glob("scripts.pre-adopt-*.bak")))


if __name__ == "__main__":
    unittest.main()
