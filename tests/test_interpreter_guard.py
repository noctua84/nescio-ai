"""The interpreter floor guard in the repo-root ``conftest.py``.

A developer ran the suite through a local `pytest` shim that silently resolved
to an unrelated project's virtualenv pinned to Python 3.12 — one minor version
under the declared floor. The run produced **78** errors, 71 of them

    TypeError: Path.read_text() got an unexpected keyword argument 'newline'

because ``pathlib.Path.read_text``/``write_text`` only grew ``newline`` in 3.13.
None of those were bugs. ``newline=""`` is a deliberate repo-wide idiom (see
``scripts/apply_theme.py``) that stops a rewritten file coming back as CRLF
against a ``.gitattributes`` pinning ``eol=lf``; deleting it is the *wrong* fix,
which is why ``CONTRIBUTING.md`` already warns about this symptom in prose.

Prose only helps a reader who thinks to look. The guard turns those 78
misleading tracebacks into one legible line naming ``sys.executable`` — the
single fact that identifies the stray venv, and whose absence made the original
diagnosis take as long as it did.

Testing it is awkward: the guard fires at *import* of ``conftest``, and the
suite necessarily runs on a supported interpreter, so the failing branch never
fires naturally. Hence ``interpreter_floor_violation()`` is a pure function
taking the version tuple and the pyproject path as arguments — these tests call
it with ``(3, 12)`` directly, no subprocess and no interpreter juggling.

The degradation cases matter at least as much as the firing case: a guard that
breaks the suite it exists to protect is worse than no guard, so an absent,
truncated, or exotically-specified ``requires-python`` must let the run proceed.
"""

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import conftest  # noqa: E402


class _PyprojectTempDir:
    """Context manager yielding a directory path with an optional pyproject."""

    def __init__(self, text=None):
        self._text = text
        self._tmp = None

    def __enter__(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        path = root / "pyproject.toml"
        if self._text is not None:
            path.write_text(self._text, encoding="utf-8")
        return path

    def __exit__(self, *exc):
        self._tmp.cleanup()
        return False


REAL_PYPROJECT = ROOT / "pyproject.toml"

WELL_FORMED = '[project]\nname = "nescio"\nrequires-python = ">=3.13"\n'


class FloorParsingTest(unittest.TestCase):
    def test_reads_the_floor_from_the_real_pyproject(self):
        # No second hardcoded (3, 13): the floor comes from the same
        # requires-python that pip and CI read.
        self.assertEqual(conftest.python_floor(REAL_PYPROJECT), (3, 13))

    def test_accepts_a_compound_specifier(self):
        # ">=3.13,<4.0" is the other shape a maintainer might plausibly write.
        with _PyprojectTempDir(
            '[project]\nrequires-python = ">=3.13,<4.0"\n'
        ) as path:
            self.assertEqual(conftest.python_floor(path), (3, 13))

    def test_missing_file_yields_no_floor(self):
        with _PyprojectTempDir(None) as path:
            self.assertIsNone(conftest.python_floor(path))

    def test_malformed_toml_yields_no_floor(self):
        with _PyprojectTempDir("[project\nrequires-python = >=3.13\n") as path:
            self.assertIsNone(conftest.python_floor(path))

    def test_absent_requires_python_yields_no_floor(self):
        with _PyprojectTempDir('[project]\nname = "nescio"\n') as path:
            self.assertIsNone(conftest.python_floor(path))

    def test_unrecognised_specifier_yields_no_floor(self):
        # "~=3.13" has real semantics the guard does not implement. Guessing at
        # a specifier grammar is how a guard starts blocking valid interpreters.
        for spec in ('"~=3.13"', '"<4.0"', '">=three.thirteen"', '""'):
            with self.subTest(spec=spec):
                with _PyprojectTempDir(
                    f"[project]\nrequires-python = {spec}\n"
                ) as path:
                    self.assertIsNone(conftest.python_floor(path))


class ViolationTest(unittest.TestCase):
    def test_below_floor_fires(self):
        msg = conftest.interpreter_floor_violation((3, 12, 3), REAL_PYPROJECT)
        self.assertIsNotNone(msg)

    def test_at_floor_passes(self):
        self.assertIsNone(
            conftest.interpreter_floor_violation((3, 13, 0), REAL_PYPROJECT)
        )

    def test_above_floor_passes(self):
        self.assertIsNone(
            conftest.interpreter_floor_violation((3, 14, 6), REAL_PYPROJECT)
        )

    def test_running_interpreter_passes(self):
        # Whatever is executing this file is in contract by construction; if
        # this ever fails the guard is rejecting the interpreter CI uses.
        self.assertIsNone(
            conftest.interpreter_floor_violation(sys.version_info, REAL_PYPROJECT)
        )

    def test_missing_pyproject_degrades_to_passing(self):
        with _PyprojectTempDir(None) as path:
            self.assertIsNone(
                conftest.interpreter_floor_violation((3, 12, 3), path)
            )

    def test_malformed_pyproject_degrades_to_passing(self):
        with _PyprojectTempDir("[project\nnot toml at all\n") as path:
            self.assertIsNone(
                conftest.interpreter_floor_violation((3, 12, 3), path)
            )

    def test_absent_requires_python_degrades_to_passing(self):
        with _PyprojectTempDir('[project]\nname = "nescio"\n') as path:
            self.assertIsNone(
                conftest.interpreter_floor_violation((3, 12, 3), path)
            )


class MessageTest(unittest.TestCase):
    def setUp(self):
        self.msg = conftest.interpreter_floor_violation(
            (3, 12, 3), REAL_PYPROJECT
        )
        self.assertIsNotNone(self.msg)

    def test_names_sys_executable(self):
        # The load-bearing fact. The original diagnosis stalled precisely
        # because nothing in 78 tracebacks said *which* python was running.
        self.assertIn(sys.executable, self.msg)

    def test_names_sys_version(self):
        # Normalised to one line so the message stays a legible block; compare
        # against the same normalisation rather than the raw multi-line value.
        self.assertIn(" ".join(sys.version.split()), self.msg)

    def test_names_the_offending_and_required_versions(self):
        self.assertIn("3.12.3", self.msg)
        self.assertIn("3.13", self.msg)

    def test_names_the_canonical_command(self):
        self.assertIn(
            "PYTHONPATH=scripts python -m unittest discover -s tests", self.msg
        )

    def test_points_at_the_documented_symptom(self):
        # Connects the one-line abort back to the prose a reader may already
        # have seen, and pre-empts the wrong fix.
        self.assertIn("CONTRIBUTING.md", self.msg)
        self.assertIn("newline", self.msg)

    def test_is_ascii_only(self):
        # This string is printed by a *rejected* interpreter onto a console that
        # may be cp1252 (see tests/test_console_encoding_guard.py). A single em
        # dash would raise UnicodeEncodeError and hand the operator the
        # traceback the guard exists to prevent.
        self.msg.encode("ascii")

    def test_is_a_single_plain_string(self):
        # pytest renders a UsageError verbatim; anything but str would render
        # as a repr and defeat the point.
        self.assertIsInstance(self.msg, str)
        self.assertNotIn("Traceback", self.msg)


class WiringTest(unittest.TestCase):
    def test_conftest_exposes_a_configure_hook(self):
        # The check runs at module scope (before the sys.path edits), but is
        # *reported* from pytest_configure: raising from the module body gets
        # wrapped in ConftestImportFailure and rendered as a traceback, whereas
        # a UsageError from the hook prints "ERROR: <message>" and nothing else.
        self.assertTrue(callable(conftest.pytest_configure))

    def test_sys_path_carries_the_repo_roots(self):
        # The guard must not have displaced conftest's original job.
        for entry in (ROOT, ROOT / "hooks", ROOT / "scripts"):
            with self.subTest(entry=entry):
                self.assertIn(str(entry), sys.path)


if __name__ == "__main__":
    unittest.main()
