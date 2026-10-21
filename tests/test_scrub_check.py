"""Issue #164: `scrub_check.py` never actually loaded custom terms for a sub-path.

Three compounding defects, all in the same script:

1. ``ROOT`` was computed at module level from ``sys.argv[1]``, and
   ``load_custom_terms()`` read ``ROOT / "scrub-terms.local"``. Scanning a
   sub-path (``python scripts/scrub_check.py scripts``) looked for
   ``scripts/scrub-terms.local``, found nothing, and silently ran the
   baseline only — every per-directory invocation passed vacuously.
2. ``iter_files()`` used ``root.rglob("*")``, which yields nothing when the
   target is a file, so a file argument reported clean having scanned zero
   files.
3. The script leaked a real username in its own comment, invisible to the
   gate only because ``SKIP_FILES`` exempts ``scrub_check.py`` by name.

The fix resolves the terms file from the repo root independent of the scan
target, accepts a file or a directory as the scan target, and takes the scan
target through ``main(argv=None)`` instead of a module-level ``ROOT`` so the
script is testable without patching ``sys.argv``.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import scrub_check  # noqa: E402


class CustomTermsVacuousnessRegressionTest(unittest.TestCase):
    """The headline defect: scanning a sub-path must still load repo-root terms."""

    def test_scanning_a_subdirectory_still_catches_a_custom_term(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            (repo / "scrub-terms.local").write_text(
                "acme-internal-codename\n", encoding="utf-8"
            )
            sub = repo / "sub"
            sub.mkdir()
            (sub / "notes.md").write_text(
                "the project is called acme-internal-codename\n", encoding="utf-8"
            )

            rc = scrub_check.main([str(sub), "--terms", str(repo)])

        self.assertEqual(
            rc, 1,
            "scanning the subdirectory must FAIL — this is the defect that made "
            "the custom-terms gate vacuous for every per-directory invocation",
        )

    def test_report_names_the_custom_term_that_matched(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            (repo / "scrub-terms.local").write_text(
                "acme-internal-codename\n", encoding="utf-8"
            )
            sub = repo / "sub"
            sub.mkdir()
            (sub / "notes.md").write_text(
                "the project is called acme-internal-codename\n", encoding="utf-8"
            )

            import io
            from contextlib import redirect_stdout

            out = io.StringIO()
            with redirect_stdout(out):
                scrub_check.main([str(sub), "--terms", str(repo)])

        report = out.getvalue()
        self.assertIn("custom term", report)
        self.assertIn("notes.md", report)


class FileArgumentScanTest(unittest.TestCase):
    """A file argument must scan that file, not zero files."""

    def test_a_file_with_a_baseline_secret_is_detected(self):
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "leaky.env"
            target.write_text(
                "aws_access_key_id = " + "AKIA" + "A" * 16 + "\n", encoding="utf-8"
            )
            rc = scrub_check.main([str(target), "--terms", d])
        self.assertEqual(
            rc, 1, "a file argument containing a baseline secret must FAIL"
        )

    def test_a_clean_file_passes(self):
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "clean.txt"
            target.write_text("nothing sensitive here\n", encoding="utf-8")
            rc = scrub_check.main([str(target), "--terms", d])
        self.assertEqual(rc, 0)


class NoCustomTermsTest(unittest.TestCase):
    def test_terms_dir_without_scrub_terms_local_reports_none_and_exits_clean(self):
        with tempfile.TemporaryDirectory() as terms_dir, \
                tempfile.TemporaryDirectory() as scan_dir:
            (Path(scan_dir) / "fine.md").write_text(
                "nothing to see here\n", encoding="utf-8"
            )

            import io
            from contextlib import redirect_stdout

            out = io.StringIO()
            with redirect_stdout(out):
                rc = scrub_check.main([scan_dir, "--terms", terms_dir])

        self.assertEqual(rc, 0)
        self.assertIn("no custom terms", out.getvalue())


class InvalidRegexTest(unittest.TestCase):
    def test_a_bad_custom_regex_exits_2_and_writes_to_stderr(self):
        with tempfile.TemporaryDirectory() as terms_dir, \
                tempfile.TemporaryDirectory() as scan_dir:
            (Path(terms_dir) / "scrub-terms.local").write_text(
                "[unclosed(\n", encoding="utf-8"
            )
            (Path(scan_dir) / "fine.md").write_text("ok\n", encoding="utf-8")

            import io
            from contextlib import redirect_stderr

            err = io.StringIO()
            with redirect_stderr(err):
                with self.assertRaises(SystemExit) as ctx:
                    scrub_check.main([scan_dir, "--terms", terms_dir])

        self.assertEqual(ctx.exception.code, 2)
        self.assertIn("invalid regex", err.getvalue())


class WarnOnlyTest(unittest.TestCase):
    def test_an_absolute_home_path_with_no_secret_exits_0_with_a_warn_section(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "notes.md").write_text(
                "see C:\\Users\\someone\\notes.txt for details\n", encoding="utf-8"
            )

            import io
            from contextlib import redirect_stdout

            out = io.StringIO()
            with redirect_stdout(out):
                rc = scrub_check.main([d, "--terms", d])

        self.assertEqual(rc, 0, "WARN-only content is still a clean run")
        self.assertIn("WARN", out.getvalue())


class SelfScanGuardTest(unittest.TestCase):
    """Pins defect 3: the shipped script must pass its own scan.

    Before the fix, line 55's real-username home-path example was invisible to the
    gate only because ``SKIP_FILES`` exempts ``scrub_check.py`` by name. This
    test monkeypatches ``SKIP_FILES`` to empty so the script actually reads
    itself, using the real script path and the baseline patterns only (no
    custom terms) — this is what stops the file quietly reacquiring a real
    identifier.
    """

    def test_shipped_script_passes_its_own_scan_without_the_self_exemption(self):
        script_path = ROOT / "scripts" / "scrub_check.py"
        original_skip_files = scrub_check.SKIP_FILES
        scrub_check.SKIP_FILES = set()
        try:
            with tempfile.TemporaryDirectory() as empty_terms_dir:
                import io
                from contextlib import redirect_stdout

                out = io.StringIO()
                with redirect_stdout(out):
                    rc = scrub_check.main(
                        [str(script_path), "--terms", empty_terms_dir]
                    )
        finally:
            scrub_check.SKIP_FILES = original_skip_files

        self.assertEqual(
            rc, 0,
            "scrub_check.py must not contain a real identifier it would itself "
            "flag — report:\n" + out.getvalue(),
        )


class SkipDirsHonouredTest(unittest.TestCase):
    def test_a_secret_inside_node_modules_is_not_reported(self):
        with tempfile.TemporaryDirectory() as d:
            nm = Path(d) / "node_modules"
            nm.mkdir()
            (nm / "bundled.js").write_text(
                "aws_access_key_id = " + "AKIA" + "A" * 16 + "\n", encoding="utf-8"
            )
            rc = scrub_check.main([d, "--terms", d])
        self.assertEqual(rc, 0, "SKIP_DIRS must still exclude node_modules")


if __name__ == "__main__":
    unittest.main()
