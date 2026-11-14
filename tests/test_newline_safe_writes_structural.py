r"""Structural guard for issue 84: every production `write_text` call passes `newline=`.

DO NOT DELETE THIS AS REDUNDANT WITH `test_newline_safe_writes.py`.

`Path.write_text(s)` expands "\n" to `os.linesep`, so on Windows it writes CRLF
into files `.gitattributes` pins to LF. The byte-comparing tests in
`test_newline_safe_writes.py` are the right *behavioural* check, but they only
have teeth on Windows: on Linux the unguarded call already emits LF, so every
one of them passes with or without `newline=""`. Every CI job in this repo runs
on `ubuntu-latest`, so those tests give CI zero regression protection.

This file asserts on the *call* instead of the output, which fails identically
on every platform -- it is the check that actually runs in CI.

It uses `ast`, not a line-oriented grep, on purpose: a multi-line call whose
`newline=""` keyword sits several lines below the `write_text(` token (see
`scripts/adopt_existing_config.py`) is invisible to a regex and would be a false
positive. Do not "simplify" this into a grep.

Scope is production code only -- `scripts/**/*.py`, `hooks/**/*.py` and
`install.py`. `tests/` is excluded: fixtures legitimately write with default
newline handling.
"""

import ast
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _production_files() -> list[Path]:
    files = sorted((ROOT / "scripts").rglob("*.py"))
    files += sorted((ROOT / "hooks").rglob("*.py"))
    files.append(ROOT / "install.py")
    return files


def _write_text_calls(source: str | bytes) -> list[tuple[int, bool]]:
    """Return (lineno, has_newline_kwarg) for every `<expr>.write_text(...)` call."""
    calls = []
    for node in ast.walk(ast.parse(source)):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "write_text"):
            has_newline = any(kw.arg == "newline" for kw in node.keywords)
            calls.append((node.lineno, has_newline))
    return calls


def _scan(files: list[Path], root: Path = ROOT) -> tuple[int, list[str], list[str]]:
    """Return (total calls seen, offending "path:line" strings, unparseable files)."""
    total, offenders, skipped = 0, [], []
    for path in files:
        rel = path.relative_to(root).as_posix()
        try:
            calls = _write_text_calls(path.read_bytes())
        except (SyntaxError, ValueError):
            # An unrelated syntax problem must not mask this check for every
            # other file; it is surfaced by the rest of the suite instead.
            skipped.append(rel)
            continue
        total += len(calls)
        offenders += [f"{rel}:{line}" for line, ok in calls if not ok]
    return total, offenders, skipped


class DetectorTest(unittest.TestCase):
    """The detector itself -- so a vacuous detector cannot make the guard pass."""

    def test_call_without_newline_is_flagged_with_its_line(self):
        src = 'import pathlib\n\npathlib.Path("x").write_text("a", encoding="utf-8")\n'
        self.assertEqual(_write_text_calls(src), [(3, False)])

    def test_multiline_call_with_newline_far_below_the_token_is_not_flagged(self):
        src = (
            'p.write_text(\n'
            '    "a"\n'
            '    + "b"\n'
            '    + "c"\n'
            '    + "d",\n'
            '    encoding="utf-8",\n'
            '    newline="",\n'
            ')\n'
        )
        self.assertEqual(_write_text_calls(src), [(1, True)])

    def test_double_star_kwargs_does_not_count_as_newline(self):
        # `**kw` may or may not carry newline; the guard cannot see it, so it
        # must not be accepted as proof.
        self.assertEqual(_write_text_calls("p.write_text(s, **kw)\n"), [(1, False)])

    def test_unparseable_file_is_skipped_not_raised(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "broken.py").write_bytes(b"def (:\n")
            (root / "bad.py").write_bytes(b"p.write_text(s)\n")
            total, offenders, skipped = _scan(
                [root / "broken.py", root / "bad.py"], root=root)
        # The broken file is skipped, and does not stop the next file being checked.
        self.assertEqual(skipped, ["broken.py"])
        self.assertEqual((total, offenders), (1, ["bad.py:1"]))


class ProductionWriteTextIsNewlineSafeTest(unittest.TestCase):
    def test_every_production_write_text_call_passes_newline(self):
        files = _production_files()
        total, offenders, _skipped = _scan(files)
        # Guard against a vacuous pass from a broken glob or a moved tree.
        self.assertTrue((ROOT / "install.py").is_file(), "install.py not found at repo root")
        self.assertGreater(total, 0, "scan found no write_text calls -- scope is broken")
        self.assertEqual(
            offenders, [],
            "Path.write_text without newline= emits CRLF on Windows (issue 84). "
            "Add newline=\"\" at:\n  " + "\n  ".join(offenders),
        )


if __name__ == "__main__":
    unittest.main()
