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
"""

import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import mark_adopted  # noqa: E402
import repo_hygiene_apply  # noqa: E402


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
        # The ⚠ the ledger-cap warning uses is now encodable on this stream.
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


if __name__ == "__main__":
    unittest.main()
