"""pytest bootstrap: interpreter contract first, then ``sys.path``.

This file has always existed to put ``.``, ``hooks/`` and ``scripts/`` on
``sys.path`` so pytest can import what the canonical unittest command gets from
``PYTHONPATH=scripts``. The version guard in front of that is newer, and exists
for a specific, expensive failure.

A `pytest` shim on someone's PATH silently resolved to an unrelated project's
virtualenv pinned to Python 3.12 — one minor version under the declared floor.
The suite produced **78** errors, 71 of them

    TypeError: Path.read_text() got an unexpected keyword argument 'newline'

because ``pathlib.Path.read_text``/``write_text`` only accept ``newline`` from
3.13 onward. Every one of those was noise. ``newline=""`` is a deliberate
repo-wide idiom — ``scripts/apply_theme.py``, ``scripts/compute_readiness.py``,
``scripts/wiki_index.py``, ``docs_site/gen_catalog.py`` and ~15 test sites — that
stops a rewritten file coming back as CRLF against a ``.gitattributes`` pinning
``eol=lf``. Deleting those arguments "fixes" the tracebacks and reintroduces the
bug they were added for, which is why ``CONTRIBUTING.md`` warns about the
symptom in prose. Prose only reaches a reader who thinks to look it up; this
reaches the reader who is already staring at the failure.

Three design notes, each load-bearing:

* The check runs at module scope, ahead of the ``sys.path`` edits, so nothing
  the suite does can produce output before it. It is *reported* from
  ``pytest_configure`` because raising from a conftest module body is caught by
  ``PytestPluginManager._importconftest`` and re-raised as
  ``ConftestImportFailure`` — which renders as an ``ImportError while loading
  conftest`` traceback, the exact genre of output the guard exists to replace.
  A ``pytest.UsageError`` from the hook prints ``ERROR: <message>`` and nothing
  else, and exits ``ExitCode.USAGE_ERROR`` (4), which is what this is: a wrong
  invocation, not a broken repo. ``pytest_configure`` still runs before any test
  module is imported, so no collection error can beat it to the output.
* The floor is read from ``requires-python``, never hardcoded. A second copy of
  ``(3, 13)`` here would drift away from the one pip and CI actually enforce.
* Every parse failure degrades to *running the suite*. A guard that blocks the
  suite it protects — because ``pyproject.toml`` moved, or someone wrote a
  specifier shape this does not model — is worse than no guard at all.

``interpreter_floor_violation()`` is a pure function over an explicit version
tuple and pyproject path precisely so ``tests/test_interpreter_guard.py`` can
exercise the firing branch, which by construction never fires on the supported
interpreter running the suite.
"""

import pathlib
import re
import sys

try:
    import tomllib as _tomllib
except ModuleNotFoundError:  # pragma: no cover - only on the interpreters we reject
    # tomllib is 3.11+. Below that we cannot parse TOML at all, and this is the
    # one path where a regex over the raw text is the right call: we only need
    # the floor in order to tell the operator to stop using this interpreter.
    _tomllib = None

_root = pathlib.Path(__file__).resolve().parent
_PYPROJECT = _root / "pyproject.toml"

# Only ">=X.Y" is honoured. "~=3.13" and "!=" have real semantics this does not
# implement, and inventing them is how a guard starts rejecting valid
# interpreters — so anything else parses to "no floor" and the run proceeds.
_LOWER_BOUND = re.compile(r"^>=\s*(\d+)\.(\d+)(?:\.\d+)?$")
_REQUIRES_PYTHON = re.compile(
    r"""^\s*requires-python\s*=\s*(["'])(?P<spec>.*?)\1""", re.MULTILINE
)


def _floor_from_specifier(spec):
    """``">=3.13,<4.0"`` -> ``(3, 13)``. Anything unmodelled -> ``None``."""
    for clause in str(spec).split(","):
        m = _LOWER_BOUND.match(clause.strip())
        if m:
            return (int(m.group(1)), int(m.group(2)))
    return None


def python_floor(pyproject_path=_PYPROJECT):
    """Lowest supported ``(major, minor)`` per ``requires-python``, or ``None``.

    ``None`` means "could not determine" — missing file, unreadable file,
    invalid TOML, no ``[project]``, no ``requires-python``, or a specifier shape
    ``_floor_from_specifier`` declines to guess at. Callers must treat that as
    permission to continue, never as a failure.
    """
    try:
        raw = pyproject_path.read_bytes()
    except OSError:
        return None

    if _tomllib is not None:
        try:
            spec = _tomllib.loads(raw.decode("utf-8"))["project"]["requires-python"]
        except Exception:
            return None
    else:  # pragma: no cover - only on the interpreters we reject
        m = _REQUIRES_PYTHON.search(raw.decode("utf-8", "replace"))
        if m is None:
            return None
        spec = m.group("spec")

    return _floor_from_specifier(spec)


def interpreter_floor_violation(version_info, pyproject_path=_PYPROJECT):
    """Message explaining why ``version_info`` is out of contract, or ``None``.

    Compares on ``(major, minor)`` only: the incident was a whole minor version
    behind, and ``requires-python`` floors in this repo are never patch-level.
    """
    floor = python_floor(pyproject_path)
    if floor is None or tuple(version_info[:2]) >= floor:
        return None

    detected = ".".join(str(part) for part in version_info[:3])
    required = ".".join(str(part) for part in floor)
    # sys.version is multi-line on most builds; flatten it so the fact block
    # stays a readable column.
    version_line = " ".join(sys.version.split())

    # Deliberately ASCII-only. This message is printed by a *rejected*
    # interpreter, on a console this repo has already been bitten by (see
    # tests/test_console_encoding_guard.py): a legacy Windows console takes the
    # ANSI codepage, and one em dash here would turn the guard into a
    # UnicodeEncodeError traceback -- precisely the output it exists to replace.
    return (
        f"This repo's tests require Python >={required}; "
        f"this interpreter is {detected}.\n"
        "\n"
        f"    sys.executable:  {sys.executable}\n"
        f"    sys.version:     {version_line}\n"
        f"    requires-python: >={required}   (from {pyproject_path})\n"
        "\n"
        "Nothing is wrong with the repo. This is almost always a `pytest` shim\n"
        "resolving to another project's virtualenv -- sys.executable above names\n"
        "it. Forced through, the run yields ~78 bogus errors, most of them\n"
        "`TypeError: Path.read_text() got an unexpected keyword argument "
        "'newline'`,\n"
        "because pathlib only accepts `newline` from 3.13 onward. Those are not\n"
        'failures, and deleting the `newline=""` arguments is NOT the fix: they\n'
        "hold LF endings against a .gitattributes that pins `eol=lf`.\n"
        'See CONTRIBUTING.md, "Running the tests".\n'
        "\n"
        "Re-run on a supported interpreter with the canonical command:\n"
        "\n"
        "    PYTHONPATH=scripts python -m unittest discover -s tests"
    )


_violation = interpreter_floor_violation(sys.version_info)

if _violation is None:
    for _p in (_root, _root / "hooks", _root / "scripts"):
        s = str(_p)
        if s not in sys.path:
            sys.path.insert(0, s)


def pytest_configure(config):
    """Abort the session with one legible line rather than 78 tracebacks."""
    if _violation is not None:
        import pytest

        raise pytest.UsageError(_violation)
