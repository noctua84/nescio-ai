"""Issue #55: entry-point scripts must not crash printing their own output.

`scripts/promote_learnings.py` wrote every note, then died with
UnicodeEncodeError formatting its summary, so a fully successful run exited
non-zero. The fix is a guarded ``sys.stdout.reconfigure(encoding="utf-8")`` at
the top of ``main()`` — the same guard `scripts/assess_repo_readiness.py`
already carried.

These tests pin the guard in place for the entry points whose ``main()`` has an
early, side-effect-free error path. The behavioural regression test for
promote_learnings (which prints real glyphs) lives in
``tests/test_promote_learnings.py``.

Hooks need the guard just as badly, and fail worse without it. `harvest_nudge`
interpolates operator-controlled path strings (the read-manifest path recorded
in the pending marker) into its output, and hook stdout is a **pipe**, which on
Windows takes the ANSI codepage rather than the console's. A hook must never
raise, so its ``main()`` ends in a blanket ``except Exception: return 0`` — which
converts UnicodeEncodeError into total silence. The hook stays safe and the
reminder disappears, identically, every session, because the marker persists.
"""

import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import mark_adopted  # noqa: E402
import repo_hygiene_apply  # noqa: E402
import scrub_check  # noqa: E402
import wiki_index  # noqa: E402

from hooks import harvest_nudge, record_stop as rs  # noqa: E402


def _run_with_cp1252_stdout(main, argv):
    """Call ``main()`` under a genuinely cp1252-backed stdout.

    A TextIOWrapper over BytesIO behaves like the legacy Windows console: it
    raises on unencodable characters. Unlike the StringIO used elsewhere in the
    suite it *does* expose ``reconfigure``, so the guard is exercised for real.
    Returns ``(rc, stream)`` — ``stream.encoding`` is the observable proof the
    reconfigure landed.
    """
    stream = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
    with mock.patch.object(sys, "stdout", stream), \
            mock.patch.object(sys, "argv", argv):
        rc = main()
    return rc, stream


class MarkAdoptedGuardTest(unittest.TestCase):
    def test_main_reconfigures_stdout_before_printing(self):
        # An unknown run folder returns 1 on an early error path — after the
        # guard, before any of the script's real work.
        rc, stream = _run_with_cp1252_stdout(
            mark_adopted.main, ["mark_adopted.py", "no-such-timestamp-00000000"]
        )
        self.assertEqual(rc, 1)
        self.assertEqual(stream.encoding.lower().replace("-", ""), "utf8")
        # The run, archive and ledger paths this script echoes are rooted in the
        # user's home and checkout and may be non-ASCII; so are the em dashes in
        # its error strings. They are all encodable on this stream now.
        stream.write("⚠\n")


class RepoHygieneApplyGuardTest(unittest.TestCase):
    def test_main_reconfigures_stdout_before_printing(self):
        with tempfile.TemporaryDirectory() as d:
            missing = Path(d) / "no-such-manifest.json"
            rc, stream = _run_with_cp1252_stdout(
                repo_hygiene_apply.main,
                ["repo_hygiene_apply.py", "--from", str(missing)],
            )
        self.assertEqual(rc, 1)
        self.assertEqual(stream.encoding.lower().replace("-", ""), "utf8")
        # Branch names and git output echoed by this tool may be non-ASCII.
        stream.write("→\n")


class WikiIndexGuardTest(unittest.TestCase):
    def test_main_reconfigures_stdout_before_printing(self):
        # An unresolvable --dir returns 1 on the early error path, before the
        # generator writes anything to disk.
        rc, stream = _run_with_cp1252_stdout(
            wiki_index.main, ["wiki_index.py", "--dir", "no-such-directory-xyz"]
        )
        self.assertEqual(rc, 1)
        self.assertEqual(stream.encoding.lower().replace("-", ""), "utf8")
        # The summary lines this script prints on the success path carry — and ⚠.
        # They are encodable on this stream now.
        stream.write("⚠\n")


class HarvestNudgeGuardTest(unittest.TestCase):
    # A path that is representable in UTF-8 but not in cp1252 — the ANSI codepage
    # a hook's piped stdout takes on a western-European Windows install.
    UNENCODABLE = "eval/learnings/研究/read.json"

    def test_hook_still_emits_its_reminder_on_a_cp1252_stdout(self):
        with tempfile.TemporaryDirectory() as cfg, tempfile.TemporaryDirectory() as work:
            saved_cfg = os.environ.get("CLAUDE_CONFIG_DIR")
            os.environ["CLAUDE_CONFIG_DIR"] = cfg
            try:
                # `git_roots(...)[1]` is the repository root — the identity
                # `nudge()` and `mark_harvested.pending_path()` now use. In a plain
                # TemporaryDirectory it equals the worktree root, so this test
                # cannot distinguish them; `tests/test_harvest_nudge.py`'s
                # WorktreeScopingTest covers that with a real linked worktree.
                marker = rs.trail_dir() / harvest_nudge.pending_name(rs.git_roots(work)[1])
                marker.write_text(
                    json.dumps(
                        {"reason": "read manifest not readable", "read": self.UNENCODABLE}
                    ),
                    encoding="utf-8",
                )
                stream = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
                with mock.patch.object(sys, "stdout", stream), mock.patch.object(
                    sys, "stdin", io.StringIO(json.dumps({"source": "startup", "cwd": work}))
                ):
                    rc = harvest_nudge.main()
                    stream.flush()
                    emitted = stream.buffer.getvalue()
            finally:
                if saved_cfg is None:
                    os.environ.pop("CLAUDE_CONFIG_DIR", None)
                else:
                    os.environ["CLAUDE_CONFIG_DIR"] = saved_cfg

        # The hook's contract is unchanged: always 0, never raises.
        self.assertEqual(rc, 0)
        self.assertEqual(stream.encoding.lower().replace("-", ""), "utf8")
        # ...but 0 with an empty pipe was the silent-loss bug. The reminder, and
        # the path that triggered it, must actually reach the session.
        self.assertNotEqual(emitted, b"", "the reminder was silently dropped")
        text = emitted.decode("utf-8")
        self.assertIn("WITHOUT stamping", text)
        self.assertIn(self.UNENCODABLE, text)


class ScrubCheckGuardTest(unittest.TestCase):
    """`scrub_check.py` echoes file content it does not control, so it needs this most.

    Its failure mode differs from the three entry points above. They crash on an
    early, side-effect-free error path — noisy but harmless. `scrub_check` crashes
    *mid-report*, and because the WARN loop prints before the FAIL block, one
    unencodable character in a benign warning aborts the run before any secret
    finding is shown. The traceback then exits 1, which is also the script's own
    "found forbidden content" status, so a caller cannot distinguish a crash from
    a real leak — and the `scrub` CI job goes red looking like one.

    Fixtures are assembled by concatenation so this file does not itself contain
    the patterns it triggers: `scrub_check.py` scans the whole repo and
    `SKIP_FILES` does not exempt `tests/`.
    """

    # WARNs as "windows home path" and carries U+2192, which cp1252 cannot encode.
    WARN_LINE = "C:" + "/Users/" + "someone" + "/" + "notes.txt" + "  \u2192 see docs"
    # An AWS access key id shape, built at runtime so the literal lands in no file.
    FAIL_LINE = "aws_access_key_id = " + "AKIA" + "A" * 16

    def _run(self, root: Path):
        """Run main() over `root` with a genuinely cp1252-backed stdout."""
        stream = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
        with mock.patch.object(scrub_check, "ROOT", root), \
                mock.patch.object(sys, "stdout", stream), \
                mock.patch.object(sys, "argv", ["scrub_check.py", str(root)]):
            rc = scrub_check.main()
        stream.flush()
        return rc, stream.buffer.getvalue().decode("utf-8"), stream

    def test_main_reconfigures_stdout_before_printing(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "a-warns.md").write_text(self.WARN_LINE + "\n", encoding="utf-8")
            rc, out, stream = self._run(Path(d))
        self.assertEqual(stream.encoding.lower().replace("-", ""), "utf8")
        self.assertEqual(rc, 0, "WARN-only is still a clean run")
        self.assertIn("a-warns.md", out, "the warning must be reported, not swallowed")
        # The arrow that would have raised is now encodable on this stream.
        self.assertIn("\u2192", out)

    def test_a_secret_finding_survives_a_warning_printed_before_it(self):
        # The masking case. Unguarded, the WARN print raises and the FAIL block
        # never runs: a real secret goes unreported while the exit code still
        # reads "found something". Both files must appear, and in that order.
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "a-warns.md").write_text(self.WARN_LINE + "\n", encoding="utf-8")
            (Path(d) / "b-leaks.md").write_text(self.FAIL_LINE + "\n", encoding="utf-8")
            rc, out, _stream = self._run(Path(d))
        self.assertEqual(rc, 1, "a FAIL match must exit 1")
        self.assertIn("FAIL", out, "the FAIL block must be reached")
        self.assertIn("b-leaks.md", out, "the secret finding must survive the warning before it")
        self.assertIn("a-warns.md", out, "and the warning must still be reported")
        self.assertLess(
            out.index("a-warns.md"), out.index("b-leaks.md"),
            "WARN is printed before FAIL; if that ever changes, this test's "
            "premise about which finding gets masked needs re-examining",
        )

    def test_a_clean_tree_reports_clean(self):
        # Guards against the fixture itself being wrong: if WARN_LINE stopped
        # matching, the two tests above would pass vacuously on an empty report.
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "fine.md").write_text("nothing to see here\n", encoding="utf-8")
            rc, out, _stream = self._run(Path(d))
        self.assertEqual(rc, 0)
        self.assertIn("scrub: clean", out)


if __name__ == "__main__":
    unittest.main()
