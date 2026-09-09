import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import sync_from_upstream as sfu  # noqa: E402


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_bytes(path: Path, data: bytes) -> None:
    """Write exact bytes.

    Line-ending behaviour is the thing under test in `LineEndingTest`, and
    `_write` above cannot express it: `Path.write_text` opens in text mode with
    `newline=None`, which rewrites every `\\n` to `os.linesep` — so the same
    call produces LF on Linux and CRLF on Windows. Every EOL-sensitive fixture
    goes through here so the tests assert the same thing on every platform.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


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


class LineEndingTest(unittest.TestCase):
    """A CRLF downstream tree vs an LF upstream must not read as 29 changes.

    Downstream instances are private forks that may carry no `.gitattributes`,
    so Git for Windows' `core.autocrlf=true` leaves their working tree in CRLF
    while this repo pins itself to LF. Byte comparison turned that into phantom
    "updated" entries; these tests pin the text-aware behaviour that replaced it.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.up = base / "upstream"
        self.dst = base / "dest"
        _make_checkout(self.up)
        _make_checkout(self.dst)

    def tearDown(self):
        self._tmp.cleanup()

    def test_crlf_dest_with_identical_text_is_not_updated(self):
        _write_bytes(self.up / "scripts" / "tool.py", b"import os\nprint(os)\n")
        _write_bytes(self.dst / "scripts" / "tool.py", b"import os\r\nprint(os)\r\n")

        added, updated, deleted = sfu.plan_sync(self.up, self.dst)
        self.assertEqual((added, updated, deleted), ([], [], []))

    def test_crlf_dest_identical_text_is_left_byte_for_byte_untouched(self):
        # The point of the fix: a newline-only difference must not cause a copy,
        # so the downstream tree stops churning on every sync.
        original = b"import os\r\nprint(os)\r\n"
        _write_bytes(self.up / "scripts" / "tool.py", b"import os\nprint(os)\n")
        _write_bytes(self.dst / "scripts" / "tool.py", original)

        sfu.apply_sync(self.up, self.dst)

        self.assertEqual((self.dst / "scripts" / "tool.py").read_bytes(), original)

    def test_crlf_dest_with_real_change_is_still_updated_and_applied(self):
        _write_bytes(self.up / "scripts" / "tool.py", b"import os\nprint(os)\n")
        _write_bytes(self.dst / "scripts" / "tool.py", b"import os\r\nprint(sys)\r\n")

        added, updated, deleted = sfu.plan_sync(self.up, self.dst)
        self.assertEqual([Path(x).as_posix() for x in updated], ["scripts/tool.py"])

        sfu.apply_sync(self.up, self.dst)
        self.assertEqual(
            (self.dst / "scripts" / "tool.py").read_bytes(), b"import os\nprint(os)\n"
        )

    def test_lone_cr_dest_with_identical_text_is_not_updated(self):
        # Old-Mac EOLs: `\r` alone must normalise the same way `\r\n` does.
        _write_bytes(self.up / "scripts" / "tool.py", b"alpha\nbeta\n")
        _write_bytes(self.dst / "scripts" / "tool.py", b"alpha\rbeta\r")

        added, updated, deleted = sfu.plan_sync(self.up, self.dst)
        self.assertEqual((added, updated, deleted), ([], [], []))

    def test_binary_differing_only_in_crlf_bytes_is_still_updated(self):
        # Byte semantics are preserved for binary: `.gitattributes` marks the
        # brand assets binary precisely so they compare byte-for-byte, and a
        # `0d 0a` inside a payload is a real difference, not an EOL convention.
        _write_bytes(self.up / "skills" / "brand" / "logo.png", b"\x89PNG\x00\n\x00\xff")
        _write_bytes(self.dst / "skills" / "brand" / "logo.png", b"\x89PNG\x00\r\n\x00\xff")

        added, updated, deleted = sfu.plan_sync(self.up, self.dst)
        self.assertEqual([Path(x).as_posix() for x in updated], ["skills/brand/logo.png"])

    def test_undecodable_dest_is_reported_as_updated_without_raising(self):
        # Valid UTF-8 upstream, latin-1 downstream: must fall back to byte
        # semantics (i.e. report it) rather than let UnicodeDecodeError escape.
        _write_bytes(self.up / "scripts" / "tool.py", "héllo\n".encode("utf-8"))
        _write_bytes(self.dst / "scripts" / "tool.py", "héllo\n".encode("latin-1"))

        added, updated, deleted = sfu.plan_sync(self.up, self.dst)
        self.assertEqual([Path(x).as_posix() for x in updated], ["scripts/tool.py"])

    def test_undecodable_upstream_is_reported_as_updated_without_raising(self):
        _write_bytes(self.up / "scripts" / "tool.py", "héllo\n".encode("latin-1"))
        _write_bytes(self.dst / "scripts" / "tool.py", "héllo\n".encode("utf-8"))

        added, updated, deleted = sfu.plan_sync(self.up, self.dst)
        self.assertEqual([Path(x).as_posix() for x in updated], ["scripts/tool.py"])

    def test_render_diff_on_crlf_dest_shows_only_the_changed_line(self):
        # A retained `\r` on every dest line would make difflib mark the whole
        # file changed, drowning the one real edit.
        _write_bytes(
            self.up / "scripts" / "tool.py",
            b"one\ntwo\nthree NEW\nfour\nfive\n",
        )
        _write_bytes(
            self.dst / "scripts" / "tool.py",
            b"one\r\ntwo\r\nthree OLD\r\nfour\r\nfive\r\n",
        )

        added, updated, deleted = sfu.plan_sync(self.up, self.dst)
        out = sfu.render_diff(self.up, self.dst, added, updated, deleted)

        body = [ln for ln in out.splitlines() if not ln.startswith(("---", "+++"))]
        removed = [ln for ln in body if ln.startswith("-")]
        inserted = [ln for ln in body if ln.startswith("+")]
        self.assertEqual(removed, ["-three OLD"], out)
        self.assertEqual(inserted, ["+three NEW"], out)


class ConftestSyncTest(unittest.TestCase):
    """Regression test for issue #128 (first half): `tests/` synced without its
    path wiring.

    `conftest.py` lives at the repo root, not under `tests/`, so before it was
    added to FRAMEWORK_PATHS a downstream instance received the whole test
    suite and the `hooks`/`scripts` packages it imports, but never the
    `conftest.py` that puts those packages on `sys.path`. `pytest` then died in
    collection with `ModuleNotFoundError: No module named 'hooks'`.

    A test that only asserts `"conftest.py" in FRAMEWORK_PATHS` would pass even
    if the file were placed somewhere `apply_sync` never reads from, or if its
    content did nothing. Instead this test reproduces the failure end-to-end on
    a synthetic instance: sync from an upstream carrying the real
    `conftest.py`, then actually execute the synced copy exactly as pytest
    would and use its `sys.path` wiring to import a module that only exists
    under the synced `hooks/` directory. If `conftest.py` is dropped from
    FRAMEWORK_PATHS, `apply_sync` never delivers it and this import fails just
    like it did for the real instance.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.up = base / "upstream"
        self.dst = base / "dest"
        _make_checkout(self.up)
        _make_checkout(self.dst)

    def tearDown(self):
        self._tmp.cleanup()

    def test_synced_conftest_actually_wires_sys_path_for_synced_hooks(self):
        # Upstream carries the real, unmodified root conftest.py plus a hooks
        # module and a test that needs it importable — the exact shape of a
        # real framework sync.
        conftest_text = (ROOT / "conftest.py").read_text(encoding="utf-8")
        _write(self.up / "conftest.py", conftest_text)
        _write(self.up / "hooks" / "__init__.py", "")
        _write(self.up / "hooks" / "_sync128_marker.py", "VALUE = 'wired'\n")
        _write(self.up / "tests" / "test_marker.py",
               "from _sync128_marker import VALUE\n")

        added, updated, deleted = sfu.plan_sync(self.up, self.dst)
        as_posix = lambda xs: [Path(x).as_posix() for x in xs]
        self.assertIn("conftest.py", as_posix(added))

        sfu.apply_sync(self.up, self.dst)
        dst_conftest = self.dst / "conftest.py"
        self.assertTrue(dst_conftest.exists())

        # Execute the synced conftest.py exactly as pytest would (its __file__
        # pointing at the synced instance), then perform the import it exists
        # to make possible: a flat module living under the synced `hooks/`.
        saved_path = list(sys.path)
        saved_module = sys.modules.pop("_sync128_marker", None)
        try:
            namespace = {"__file__": str(dst_conftest)}
            exec(
                compile(dst_conftest.read_text(encoding="utf-8"), str(dst_conftest), "exec"),
                namespace,
            )
            import _sync128_marker  # only resolvable if the sync delivered conftest.py
            self.assertEqual(_sync128_marker.VALUE, "wired")
        finally:
            sys.path[:] = saved_path
            sys.modules.pop("_sync128_marker", None)
            if saved_module is not None:
                sys.modules["_sync128_marker"] = saved_module


class SelfReplacementTest(unittest.TestCase):
    """`_self_was_replaced` detects a sync overwriting its own running script.

    `scripts` is a framework path, so a downstream instance's `--apply` run can
    rewrite the very file Python is executing. These tests exercise the helper
    directly against a fabricated `dest`, patching the module's `__file__` to
    point inside it rather than risking anything near the real script on disk.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.up = base / "upstream"
        self.dst = base / "dest"
        _make_checkout(self.up)
        _make_checkout(self.dst)

    def tearDown(self):
        self._tmp.cleanup()

    def test_true_when_running_script_is_among_the_applied_files(self):
        running = self.dst / "scripts" / "sync_from_upstream.py"
        _write(running, "# old copy\n")

        with patch.object(sfu, "__file__", str(running)):
            replaced = sfu._self_was_replaced(
                self.dst, added=[], updated=["scripts/sync_from_upstream.py"]
            )
        self.assertTrue(replaced)

    def test_false_when_running_script_is_outside_the_applied_files(self):
        # The upstream-checkout-against-a-remote-dest case: the script executing
        # lives outside `dest` entirely, so it can never be among the files a
        # sync into `dest` just wrote.
        running = self.up / "scripts" / "sync_from_upstream.py"
        _write(running, "# upstream's own copy\n")
        _write(self.dst / "scripts" / "sync_from_upstream.py", "# unrelated dest copy\n")

        with patch.object(sfu, "__file__", str(running)):
            replaced = sfu._self_was_replaced(
                self.dst, added=[], updated=["scripts/sync_from_upstream.py"]
            )
        self.assertFalse(replaced)

    def test_false_when_applied_files_do_not_include_the_script(self):
        running = self.dst / "scripts" / "sync_from_upstream.py"
        _write(running, "# old copy\n")

        with patch.object(sfu, "__file__", str(running)):
            replaced = sfu._self_was_replaced(
                self.dst, added=["agents/explore.md"], updated=[]
            )
        self.assertFalse(replaced)

    def test_oserror_from_resolve_is_treated_as_not_replaced(self):
        def _boom(self, strict=False):
            raise OSError("simulated resolve failure")

        with patch.object(sfu, "__file__", str(self.dst / "scripts" / "sync_from_upstream.py")):
            with patch.object(Path, "resolve", _boom):
                replaced = sfu._self_was_replaced(
                    self.dst, added=[], updated=["scripts/sync_from_upstream.py"]
                )
        self.assertFalse(replaced)


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

    def test_apply_warns_when_the_run_replaced_the_running_script(self):
        # `scripts` is a framework path: an --apply run that syncs a new copy of
        # sync_from_upstream.py into dest is overwriting the file Python is
        # executing. Patch __file__ so the running "script" resolves inside
        # dest, matching a real downstream-instance sync.
        _write(self.up / "scripts" / "sync_from_upstream.py", "# new upstream copy\n")
        running = self.dst / "scripts" / "sync_from_upstream.py"
        _write(running, "# old copy\n")

        with patch.object(sfu, "__file__", str(running)):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = sfu.main(["--upstream", str(self.up), "--dest", str(self.dst), "--apply"])
        self.assertEqual(rc, 0)
        self.assertIn("overwrote scripts/sync_from_upstream.py itself", out.getvalue())

    def test_apply_does_not_warn_when_the_script_was_not_replaced(self):
        _write(self.up / "skills" / "s" / "SKILL.md", "new\n")

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = sfu.main(["--upstream", str(self.up), "--dest", str(self.dst), "--apply"])
        self.assertEqual(rc, 0)
        self.assertNotIn("overwrote scripts/sync_from_upstream.py itself", out.getvalue())

    def test_dry_run_never_warns_about_self_replacement(self):
        # Even in the shape that would trigger the warning on --apply, a dry
        # run writes nothing and so can never replace anything.
        _write(self.up / "scripts" / "sync_from_upstream.py", "# new upstream copy\n")
        running = self.dst / "scripts" / "sync_from_upstream.py"
        _write(running, "# old copy\n")

        with patch.object(sfu, "__file__", str(running)):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                rc = sfu.main(["--upstream", str(self.up), "--dest", str(self.dst)])
        self.assertEqual(rc, 0)
        self.assertNotIn("overwrote scripts/sync_from_upstream.py itself", out.getvalue())


if __name__ == "__main__":
    unittest.main()
