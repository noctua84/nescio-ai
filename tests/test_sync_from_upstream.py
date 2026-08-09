import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import sync_from_upstream as sfu  # noqa: E402


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _make_checkout(root: Path) -> None:
    """A minimal tree that passes the Nescio-checkout sanity check."""
    _write(root / "install.py", "# installer\n")
    _write(root / "agents" / "explore.md", "explore\n")


class PlanSyncTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.up = base / "upstream"
        self.dst = base / "dest"
        _make_checkout(self.up)
        _make_checkout(self.dst)

    def tearDown(self):
        self._tmp.cleanup()

    def test_detects_added_updated_deleted_within_framework(self):
        # upstream: new skill + changed agent; dest: an extra agent to be deleted
        _write(self.up / "skills" / "s" / "SKILL.md", "new\n")
        _write(self.up / "agents" / "explore.md", "explore CHANGED\n")
        _write(self.dst / "agents" / "stale.md", "remove me\n")

        added, updated, deleted = sfu.plan_sync(self.up, self.dst)
        # plan_sync returns OS-native separators (backslash on Windows); compare
        # on a normalized posix form so the assertion holds on every platform.
        as_posix = lambda xs: [Path(x).as_posix() for x in xs]
        self.assertIn("skills/s/SKILL.md", as_posix(added))
        self.assertIn("agents/explore.md", as_posix(updated))
        self.assertIn("agents/stale.md", as_posix(deleted))

    def test_memory_and_non_framework_paths_are_ignored(self):
        # differences outside the allowlist must never be reported
        _write(self.up / "memory" / "concepts" / "a.md", "upstream note\n")
        _write(self.dst / "memory" / "repo" / "private.md", "my private note\n")
        _write(self.up / "README.md", "upstream readme\n")
        _write(self.dst / "README.md", "my readme\n")
        _write(self.dst / "docs" / "design.md", "my design\n")

        added, updated, deleted = sfu.plan_sync(self.up, self.dst)
        all_paths = added + updated + deleted
        self.assertEqual(all_paths, [], f"non-framework paths leaked: {all_paths}")

    def test_in_sync_yields_empty_plan(self):
        added, updated, deleted = sfu.plan_sync(self.up, self.dst)
        self.assertEqual((added, updated, deleted), ([], [], []))


class ApplySyncTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.up = base / "upstream"
        self.dst = base / "dest"
        _make_checkout(self.up)
        _make_checkout(self.dst)

    def tearDown(self):
        self._tmp.cleanup()

    def test_apply_copies_and_deletes_framework_only(self):
        _write(self.up / "skills" / "s" / "SKILL.md", "new\n")
        _write(self.up / "agents" / "explore.md", "explore CHANGED\n")
        _write(self.dst / "agents" / "stale.md", "remove me\n")
        # private content that must survive untouched
        _write(self.dst / "memory" / "repo" / "private.md", "keep me\n")

        sfu.apply_sync(self.up, self.dst)

        self.assertEqual((self.dst / "skills" / "s" / "SKILL.md").read_text(), "new\n")
        self.assertEqual((self.dst / "agents" / "explore.md").read_text(), "explore CHANGED\n")
        self.assertFalse((self.dst / "agents" / "stale.md").exists())
        # memory untouched
        self.assertEqual((self.dst / "memory" / "repo" / "private.md").read_text(), "keep me\n")

    def test_apply_is_idempotent(self):
        _write(self.up / "skills" / "s" / "SKILL.md", "new\n")
        sfu.apply_sync(self.up, self.dst)
        added, updated, deleted = sfu.plan_sync(self.up, self.dst)
        self.assertEqual((added, updated, deleted), ([], [], []))


class RenderDiffTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.up = base / "upstream"
        self.dst = base / "dest"
        _make_checkout(self.up)
        _make_checkout(self.dst)

    def tearDown(self):
        self._tmp.cleanup()

    def test_updated_file_shows_minus_plus_change(self):
        _write(self.dst / "agents" / "explore.md", "line one\nold line\n")
        _write(self.up / "agents" / "explore.md", "line one\nnew line\n")

        added, updated, deleted = sfu.plan_sync(self.up, self.dst)
        out = sfu.render_diff(self.up, self.dst, added, updated, deleted)

        # normalize the header path to posix so the assertion is Windows-safe
        self.assertIn("agents/explore.md", out)
        self.assertIn("-old line", out)
        self.assertIn("+new line", out)

    def test_added_file_marked_net_new(self):
        _write(self.up / "skills" / "s" / "SKILL.md", "brand new\n")

        added, updated, deleted = sfu.plan_sync(self.up, self.dst)
        out = sfu.render_diff(self.up, self.dst, added, updated, deleted)

        self.assertIn("skills/s/SKILL.md", out)
        self.assertIn("NET-NEW", out)
        self.assertIn("+brand new", out)
        self.assertIn("net-new: 1 added file(s)", out)

    def test_deleted_file_is_noted(self):
        _write(self.dst / "agents" / "stale.md", "remove me\n")

        added, updated, deleted = sfu.plan_sync(self.up, self.dst)
        out = sfu.render_diff(self.up, self.dst, added, updated, deleted)

        self.assertIn("--- DELETED", out)
        self.assertIn("agents/stale.md", out)

    def test_in_sync_yields_empty_diff(self):
        added, updated, deleted = sfu.plan_sync(self.up, self.dst)
        out = sfu.render_diff(self.up, self.dst, added, updated, deleted)
        self.assertEqual(out, "")


class MainCliTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.up = base / "upstream"
        self.dst = base / "dest"
        _make_checkout(self.up)
        _make_checkout(self.dst)

    def tearDown(self):
        self._tmp.cleanup()

    def test_rejects_non_checkout_upstream(self):
        bogus = Path(self._tmp.name) / "bogus"
        bogus.mkdir()
        rc = sfu.main(["--upstream", str(bogus), "--dest", str(self.dst)])
        self.assertEqual(rc, 2)

    def test_rejects_same_upstream_and_dest(self):
        rc = sfu.main(["--upstream", str(self.up), "--dest", str(self.up)])
        self.assertEqual(rc, 2)

    def test_dry_run_does_not_write(self):
        _write(self.up / "skills" / "s" / "SKILL.md", "new\n")
        rc = sfu.main(["--upstream", str(self.up), "--dest", str(self.dst)])
        self.assertEqual(rc, 0)
        self.assertFalse((self.dst / "skills" / "s" / "SKILL.md").exists())

    def test_apply_writes(self):
        _write(self.up / "skills" / "s" / "SKILL.md", "new\n")
        rc = sfu.main(["--upstream", str(self.up), "--dest", str(self.dst), "--apply"])
        self.assertEqual(rc, 0)
        self.assertTrue((self.dst / "skills" / "s" / "SKILL.md").exists())


if __name__ == "__main__":
    unittest.main()
