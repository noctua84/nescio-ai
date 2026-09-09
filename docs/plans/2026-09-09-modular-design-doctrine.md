# Modular Design Doctrine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the crew a cohesion tripwire, a behaviour-preserving split procedure, and an opt-in layered-service shape, so files stop growing without limit and nothing imposes an architecture on projects that did not ask for one.

**Architecture:** Three delivery surfaces. A read-only Python scanner (`scripts/module_scan.py`) supplies the numbers. Two on-demand skills supply the judgment — `modular-design` (the rule and the split procedure) and `layered-api-design` (one worked shape, gated behind a project declaration). Five agent charters get surgical edits so prevention happens at write time. No new agent, and no change to `agents/orchestrator.md`, whose existing `<out-of-scope>` → DELIVER path already routes boundary findings to spawned tasks.

**Tech Stack:** Python 3.13 stdlib only (`argparse`, `json`, `subprocess`, `pathlib`). `unittest` for tests, run via `python -m unittest`. Markdown with YAML frontmatter for skills and agent charters. `docs_site/gen_catalog.py` regenerates the docs-site catalog.

## Global Constraints

- **Python 3.13+, standard library only.** `pyproject.toml` declares `requires-python = ">=3.13"` and `dependencies = []`. Do not add a dependency.
- **`unittest`, not `pytest`.** CI runs `PYTHONPATH=scripts python -m unittest discover -s tests -v`. Tests are `unittest.TestCase` subclasses in `tests/test_<module>.py`.
- **Tests build real throwaway git repos** in `tempfile` dirs and run real `git`, per the house pattern in `tests/test_verify_commit_position.py`. Set `user.email`, `user.name`, and `commit.gpgsign=false` locally inside each temp repo; never touch global git config.
- **Never name a crew agent inside a `SKILL.md`.** `scripts/apply_theme.py` renames `agents/*.md` only (`builder` → `archimedes` and back). A skill hardcoding `builder` goes stale the moment a theme is applied. Skills say "your implementer", "the reviewing agent", "the crew". Agent charters *may* name other agents — they are themed together.
- **Default tripwire: `400` physical lines.** Strictly greater than — a 400-line file is not reported; a 401-line file is.
- **`module_scan.py` always exits 0 for any completed scan; a malformed invocation exits 2 via `argparse`.** It is a report, not a gate — a rejected command line is not a report, so it is not covered by that promise.
- **Commit prefixes:** `[impl]` production code, `[fix]` bug fix, `[chore]` tooling/config, `[docs]` documentation, `[test]` tests, and the new `[refactor]` behaviour-preserving module split. The bracket coexists with conventional-commit type — `feat: [impl] …`. The doubling in `refactor: [refactor] …` is deliberate and must not be "cleaned up": the conventional type serves release tooling, the bracket serves the phase-scoped review paper trail.
- **Spec of record:** `docs/specs/2026-09-09-modular-design-doctrine-design.md`.

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `scripts/module_scan.py` | create | Enumerate tracked files, count physical lines, report those over the tripwire. Read-only. |
| `tests/test_module_scan.py` | create | Boundary, exclusion, encoding, and JSON-shape coverage for the scanner. |
| `skills/modular-design/SKILL.md` | create | The three tests, the tripwire, the six-step split procedure, the shape catalogue. |
| `skills/layered-api-design/SKILL.md` | create | endpoints / manager / repository, behind an explicit opt-in gate. |
| `agents/planner.md` | modify | §Plan Structure Context line; §Maximise Parallelism extraction-first rule. |
| `agents/builder.md` | modify | §You DO NOT, §1 Orient (length check), §5 Commit table row, §Output Contract (module-check), §Anti-Patterns. |
| `agents/builder-standard.md` | modify | Identical five edits. |
| `agents/builder-simple.md` | modify | Identical five edits. |
| `agents/reviewer.md` | modify | §1 Scope Definition gains the `[refactor]` bracket; §5 Maintainability Assessment gains a module-boundary bullet. |
| `CLAUDE.md` | modify | Optional `## Architecture` section — the opt-in declaration. |
| `README.md` | modify | Name the two new skills in the Skills paragraph. |
| `docs_site/gen_catalog.py` | modify | Add both skills to the "Development workflow" group. |
| `docs_site/docs/skills.md` | regenerate | Generated output — never hand-edited. |

**Execution waves.** Tasks 1, 3, and 4 are independent and may run in parallel. Task 2 consumes Task 1's CLI surface. Task 5 requires Tasks 2 and 3 to exist on disk.

---

### Task 1: The scanner — `scripts/module_scan.py`

**Files:**
- Create: `scripts/module_scan.py`
- Test: `tests/test_module_scan.py`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces, relied on by Tasks 2 and 4:
  - CLI: `python scripts/module_scan.py [--repo PATH] [--tripwire N] [--top N] [--exclude GLOB]... [--json]`
  - `scan(repo: Path, tripwire: int, excludes: tuple[str, ...]) -> dict` returning
    `{"tripwire": int, "scanned": int, "over": [{"path": str, "lines": int}, ...]}`
    with `over` sorted by `lines` descending, then `path` ascending.
  - `count_lines(path: Path) -> int | None` — `None` means binary or unreadable.
  - `main(argv: list[str] | None = None) -> int` — always returns `0`.

- [ ] **Step 1: Write the failing test file**

Create `tests/test_module_scan.py`:

```python
"""Tests for scripts/module_scan.py.

These build real throwaway git repositories and run real `git ls-files`, because
the scanner's whole contract is "what git tracks, minus what is not source" --
mocking git would test the mock. `user.email` / `user.name` / `commit.gpgsign`
are set inside each temp repo so this passes on a clean CI machine and on a
developer box with global commit signing enabled.
"""

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import module_scan  # noqa: E402


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    if proc.returncode != 0:
        raise AssertionError(
            f"`git {' '.join(args)}` failed in {repo} (exit {proc.returncode}):\n"
            f"{proc.stderr.strip() or proc.stdout.strip()}"
        )
    return proc.stdout.strip()


def _init_repo(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "commit.gpgsign", "false")
    return repo


def _write(repo: Path, rel: str, lines: int) -> Path:
    """Write `rel` with exactly `lines` physical lines, then track it."""
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x\n" * lines, encoding="utf-8")
    _git(repo, "add", "--", rel)
    return path


class ModuleScanTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = _init_repo(Path(self._tmp.name))

    def paths_over(self, **kw) -> list[str]:
        result = module_scan.scan(
            self.repo, kw.get("tripwire", 400), kw.get("excludes", ())
        )
        return [entry["path"] for entry in result["over"]]


class TestTripwireBoundary(ModuleScanTestCase):
    def test_only_files_strictly_over_the_tripwire_are_reported(self):
        """400 is not over 400. Off-by-one here would flag every file at the limit."""
        _write(self.repo, "under.py", 399)
        _write(self.repo, "exactly.py", 400)
        _write(self.repo, "over.py", 401)
        self.assertEqual(self.paths_over(), ["over.py"])

    def test_tripwire_override_is_honoured(self):
        _write(self.repo, "small.py", 60)
        _write(self.repo, "medium.py", 120)
        self.assertEqual(self.paths_over(tripwire=100), ["medium.py"])

    def test_over_list_is_sorted_by_size_descending(self):
        _write(self.repo, "big.py", 900)
        _write(self.repo, "bigger.py", 1200)
        _write(self.repo, "biggest.py", 1500)
        self.assertEqual(
            self.paths_over(), ["biggest.py", "bigger.py", "big.py"]
        )


class TestExclusions(ModuleScanTestCase):
    def test_generated_vendored_and_lockfiles_are_omitted(self):
        _write(self.repo, "real.py", 500)
        _write(self.repo, "api_pb2.py", 500)
        _write(self.repo, "bundle.min.js", 500)
        _write(self.repo, "node_modules/dep/index.js", 500)
        _write(self.repo, "migrations/0001_initial.py", 500)
        _write(self.repo, "uv.lock", 500)
        self.assertEqual(self.paths_over(), ["real.py"])

    def test_binary_files_are_skipped_not_counted(self):
        blob = self.repo / "image.bin"
        blob.write_bytes(b"\x00\x01" * 5000)
        _git(self.repo, "add", "--", "image.bin")
        result = module_scan.scan(self.repo, 400, ())
        self.assertEqual(result["over"], [])
        self.assertEqual(result["scanned"], 0)

    def test_untracked_and_ignored_files_are_omitted(self):
        _write(self.repo, "tracked.py", 500)
        (self.repo / "untracked.py").write_text("x\n" * 500, encoding="utf-8")
        (self.repo / ".gitignore").write_text("ignored.py\n", encoding="utf-8")
        _git(self.repo, "add", "--", ".gitignore")
        (self.repo / "ignored.py").write_text("x\n" * 500, encoding="utf-8")
        self.assertEqual(self.paths_over(), ["tracked.py"])

    def test_extra_exclude_globs_are_applied(self):
        _write(self.repo, "keep.py", 500)
        _write(self.repo, "CHANGELOG.md", 500)
        self.assertEqual(
            self.paths_over(excludes=("CHANGELOG.md",)), ["keep.py"]
        )


class TestLineCounting(ModuleScanTestCase):
    def test_a_non_utf8_file_is_counted_not_crashed_on(self):
        """Latin-1 bytes are not valid UTF-8. Counting is done on bytes for this."""
        path = self.repo / "latin.py"
        path.write_bytes(("caf\xe9\n" * 500).encode("latin-1"))
        _git(self.repo, "add", "--", "latin.py")
        self.assertEqual(self.paths_over(), ["latin.py"])

    def test_a_final_line_without_a_newline_still_counts(self):
        path = self.repo / "noeol.py"
        path.write_text("x\n" * 400 + "last", encoding="utf-8")
        _git(self.repo, "add", "--", "noeol.py")
        self.assertEqual(module_scan.count_lines(path), 401)

    def test_an_empty_file_counts_zero(self):
        path = self.repo / "empty.py"
        path.write_text("", encoding="utf-8")
        self.assertEqual(module_scan.count_lines(path), 0)


class TestReportAndExit(ModuleScanTestCase):
    def test_an_empty_repo_reports_cleanly_and_exits_zero(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = module_scan.main(["--repo", str(self.repo)])
        self.assertEqual(rc, 0)

    def test_exit_is_zero_even_when_files_are_over(self):
        """It is a report, not a gate. A non-zero exit would make it a CI blocker."""
        _write(self.repo, "huge.py", 5000)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = module_scan.main(["--repo", str(self.repo)])
        self.assertEqual(rc, 0)

    def test_json_output_shape_is_stable(self):
        _write(self.repo, "huge.py", 1200)
        result = module_scan.scan(self.repo, 400, ())
        payload = json.loads(json.dumps(result))
        self.assertEqual(payload["tripwire"], 400)
        self.assertEqual(payload["scanned"], 1)
        self.assertEqual(payload["over"], [{"path": "huge.py", "lines": 1200}])

    def test_scanned_counts_every_eligible_file_not_just_the_over_ones(self):
        _write(self.repo, "small.py", 10)
        _write(self.repo, "huge.py", 1200)
        result = module_scan.scan(self.repo, 400, ())
        self.assertEqual(result["scanned"], 2)
        self.assertEqual(len(result["over"]), 1)


class TestFormatReport(ModuleScanTestCase):
    def test_clean_report_names_no_files_over(self):
        _write(self.repo, "small.py", 10)
        result = module_scan.scan(self.repo, 400, ())
        report = module_scan.format_report(result, None)
        self.assertIn("no files over tripwire (>400 lines)", report)
        self.assertIn("1 files scanned", report)

    def test_top_truncates_rows_but_not_the_total(self):
        _write(self.repo, "a.py", 1000)
        _write(self.repo, "b.py", 900)
        _write(self.repo, "c.py", 800)
        result = module_scan.scan(self.repo, 400, ())
        report = module_scan.format_report(result, 2)
        self.assertIn("a.py", report)
        self.assertIn("b.py", report)
        self.assertNotIn("c.py", report)
        self.assertIn("3 files over, 3 scanned", report)

    def test_top_zero_does_not_falsely_report_clean_when_files_are_over(self):
        """Regression: `--top 0` truncates the displayed rows to nothing, but the
        report must still say files are over -- not fall into the "clean" branch,
        which is keyed on the full `over` list, not the truncated display."""
        _write(self.repo, "huge.py", 5000)
        result = module_scan.scan(self.repo, 400, ())
        report = module_scan.format_report(result, 0)
        self.assertNotIn("no files over tripwire", report)
        self.assertIn("1 files over, 1 scanned", report)
        self.assertNotIn("huge.py", report)


class TestArgumentValidation(unittest.TestCase):
    """Validation happens before the repo is ever touched, so these do not need
    the real-git-repo fixture from ModuleScanTestCase -- an arbitrary --repo
    value is enough."""

    def test_top_zero_is_rejected(self):
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            with self.assertRaises(SystemExit) as cm:
                module_scan.main(["--repo", "unused", "--top", "0"])
        self.assertEqual(cm.exception.code, 2)
        self.assertIn("--top", buf.getvalue())
        self.assertIn("at least 1", buf.getvalue())

    def test_top_negative_is_rejected(self):
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            with self.assertRaises(SystemExit) as cm:
                module_scan.main(["--repo", "unused", "--top", "-1"])
        self.assertEqual(cm.exception.code, 2)
        self.assertIn("--top", buf.getvalue())
        self.assertIn("at least 1", buf.getvalue())

    def test_negative_tripwire_is_rejected(self):
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            with self.assertRaises(SystemExit) as cm:
                module_scan.main(["--repo", "unused", "--tripwire", "-1"])
        self.assertEqual(cm.exception.code, 2)
        self.assertIn("--tripwire", buf.getvalue())
        self.assertIn("must not be negative", buf.getvalue())


class TestMissingGit(unittest.TestCase):
    """tracked_files must survive missing git executable."""

    def test_tracked_files_returns_empty_list_when_git_is_unavailable(self):
        """When git is not on PATH, tracked_files returns [] rather than raising."""
        repo = Path("/nonexistent")
        with mock.patch("module_scan.subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError("git not found")
            result = module_scan.tracked_files(repo)
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
python -m unittest tests.test_module_scan -v
```

Expected: `ModuleNotFoundError: No module named 'module_scan'` — the whole module is collected as an error before any test runs.

- [ ] **Step 3: Write the scanner**

Create `scripts/module_scan.py`:

```python
#!/usr/bin/env python3
"""Report tracked files that have crossed the module-size tripwire.

A read-only companion to the `modular-design` skill. It answers exactly one
question -- *which files are large enough to be worth asking about?* -- and
answers nothing else. It does not decide whether a file should be split; that
judgment needs cohesion, which no line counter has access to.

Deliberate design decisions, each of which has a failure mode behind it:

  * **`git ls-files`, not a filesystem walk.** `.gitignore` is respected for
    free, build output and virtualenvs never appear, and the tool is correct
    inside a git worktree without special-casing one.

  * **Always exits 0 for any completed scan; a malformed invocation exits 2 via
    argparse.** This is a report, not a gate. The first person to pipe a
    non-zero-exiting scanner into a CI workflow turns an advisory number into a
    build failure by accident, and the number is not good enough to carry that.
    A rejected command line is not a report, so it is not covered by that
    promise -- argparse's usual exit 2 stands.

  * **Physical lines, counted on bytes.** Not logical lines, not statements. The
    count exists to prompt a human-legible judgment, so precision buys nothing
    and stripping blanks or comments only adds argument surface. Counting bytes
    rather than decoded text means a Latin-1 or otherwise non-UTF-8 source file
    is counted rather than skipped or crashed on.

  * **Denylist, not allowlist, for what counts as source.** An allowlist of
    known code extensions silently ignores every language nobody thought of.
    Anything tracked and textual counts, minus generated, vendored, and lockfile
    paths. Prose files therefore appear too -- which is correct in a repository
    whose source *is* prose.

Usage:
    python scripts/module_scan.py
    python scripts/module_scan.py --tripwire 500 --top 10
    python scripts/module_scan.py --exclude 'CHANGELOG.md' --exclude 'docs/**'
    python scripts/module_scan.py --json
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import subprocess
import sys
from pathlib import Path

DEFAULT_TRIPWIRE = 400

# How much of a file to sniff for NUL bytes before calling it binary.
_SNIFF_BYTES = 8192

# Any path segment equal to one of these excludes the file. Directory names
# only -- matching on substrings would eat `src/buildings/`.
EXCLUDED_DIR_NAMES = frozenset(
    {
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "migrations",
        "node_modules",
        "target",
        "third_party",
        "vendor",
        "vendored",
    }
)

# Exact filenames that are never source.
EXCLUDED_FILENAMES = frozenset(
    {
        "Cargo.lock",
        "Gemfile.lock",
        "composer.lock",
        "package-lock.json",
        "pnpm-lock.yaml",
        "poetry.lock",
        "uv.lock",
        "yarn.lock",
    }
)

# Filename endings that mark generated or minified output.
GENERATED_ENDINGS = (
    ".g.dart",
    ".min.css",
    ".min.js",
    ".pb.go",
    "_generated.go",
    "_pb2.py",
    "_pb2_grpc.py",
)


def tracked_files(repo: Path) -> list[str]:
    """Repo-relative paths of every file git tracks, POSIX-separated.

    `-z` because a filename may legally contain a newline; splitting on `\\n`
    would corrupt such a path into two.
    """
    try:
        proc = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=repo,
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        print(f"module_scan: could not run git in {repo}: {exc}", file=sys.stderr)
        return []
    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", errors="replace").strip()
        print(
            f"module_scan: `git ls-files` failed in {repo} (exit "
            f"{proc.returncode}): {stderr}",
            file=sys.stderr,
        )
        return []
    raw = proc.stdout.decode("utf-8", errors="surrogateescape")
    return [name for name in raw.split("\0") if name]


def is_excluded(rel: str, excludes: tuple[str, ...]) -> bool:
    """True when `rel` is generated, vendored, a lockfile, or user-excluded."""
    parts = rel.split("/")
    if any(part in EXCLUDED_DIR_NAMES for part in parts[:-1]):
        return True
    name = parts[-1]
    if name in EXCLUDED_FILENAMES:
        return True
    if name.endswith(GENERATED_ENDINGS):
        return True
    return any(
        fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(name, pattern)
        for pattern in excludes
    )


def count_lines(path: Path) -> int | None:
    """Physical line count, or None when the file is binary or unreadable.

    An unreadable file returns None rather than raising: a scan that dies on one
    odd file reports nothing about the other two hundred.
    """
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if b"\0" in data[:_SNIFF_BYTES]:
        return None
    if not data:
        return 0
    count = data.count(b"\n")
    if not data.endswith(b"\n"):
        count += 1
    return count


def scan(repo: Path, tripwire: int, excludes: tuple[str, ...]) -> dict:
    """Count every eligible tracked file; return the ones over the tripwire.

    `over` is sorted by size descending, ties broken by path ascending, so the
    report is stable across runs and across filesystems.
    """
    scanned = 0
    over: list[dict] = []
    for rel in tracked_files(repo):
        if is_excluded(rel, excludes):
            continue
        lines = count_lines(repo / rel)
        if lines is None:
            continue
        scanned += 1
        if lines > tripwire:
            over.append({"path": rel, "lines": lines})
    over.sort(key=lambda entry: (-entry["lines"], entry["path"]))
    return {"tripwire": tripwire, "scanned": scanned, "over": over}


def format_report(result: dict, top: int | None) -> str:
    """Format the scan result as a human-readable report for terminal output.

    The "no files over" message is chosen from `result["over"]` (the full list),
    never from the `--top`-truncated view -- otherwise `--top 0` (or any `--top`
    smaller than the count) prints "no files over tripwire" while files are, in
    fact, over it.
    """
    over = result["over"]
    displayed = over if top is None else over[:top]
    lines = [""]
    if not over:
        lines.append(
            f"  no files over tripwire (>{result['tripwire']} lines)"
        )
        lines.append("")
        lines.append(f"  {result['scanned']} files scanned")
        lines.append("")
        return "\n".join(lines)

    lines.append(f"  over tripwire (>{result['tripwire']} lines)")
    lines.append("  " + "-" * 36)
    for entry in displayed:
        lines.append(f"  {entry['lines']:>5}  {entry['path']}")
    lines.append("")
    lines.append(
        f"  {len(over)} files over, {result['scanned']} scanned"
    )
    lines.append(
        "  run the modular-design skill on any of these to get a proposed split"
    )
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Report tracked files over the module-size tripwire.",
    )
    parser.add_argument(
        "--repo", type=Path, default=Path.cwd(), help="repository root"
    )
    parser.add_argument(
        "--tripwire",
        type=int,
        default=DEFAULT_TRIPWIRE,
        help=f"lines above which a file is reported (default {DEFAULT_TRIPWIRE})",
    )
    parser.add_argument(
        "--top", type=int, default=None, help="show only the N largest"
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="GLOB",
        help="additional path or filename glob to skip (repeatable)",
    )
    parser.add_argument(
        "--json", action="store_true", help="emit machine-readable JSON"
    )
    args = parser.parse_args(argv)

    # parser.error() exits with code 2, not 0 -- but that does not violate this
    # module's "always exits 0" contract. That contract is about *reporting*: a
    # scan that completes always reports rather than failing a CI gate. A
    # malformed invocation (`--top 0`, a negative tripwire) never produces a
    # report at all, so there is nothing for the contract to cover.
    if args.top is not None and args.top < 1:
        parser.error("--top must be at least 1")
    if args.tripwire < 0:
        parser.error("--tripwire must not be negative")

    result = scan(args.repo, args.tripwire, tuple(args.exclude))

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(format_report(result, args.top))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
python -m unittest tests.test_module_scan -v
```

Expected: `OK` — 21 tests.

- [ ] **Step 5: Run the scanner on this repo and confirm the spec's success criterion**

```bash
python scripts/module_scan.py --json | grep orchestrator
```

Expected: a JSON entry for `agents/orchestrator.md`. `--top` is a display filter,
not a query — do not use it to prove a specific file is present.

- [ ] **Step 6: Run the full suite to confirm nothing regressed**

```bash
python -m unittest discover -s tests -v
```

Expected: `OK`.

- [ ] **Step 7: Commit**

```bash
git add scripts/module_scan.py tests/test_module_scan.py
git commit -m "feat: [impl] add module_scan, a read-only file-size tripwire report"
```

---

### Task 2: `skills/modular-design/SKILL.md`

**Files:**
- Create: `skills/modular-design/SKILL.md`

**Interfaces:**
- Consumes from Task 1: the CLI `python scripts/module_scan.py [--tripwire N] [--json]`.
- Produces, relied on by Tasks 3, 4 and 5: the skill name `modular-design`, and the three test names — **reasons to change**, **shared private state**, **name test** — which the agent charters and the sibling skill reference by name.

- [ ] **Step 1: Create the skill directory and write the file**

```bash
mkdir -p skills/modular-design
```

Write `skills/modular-design/SKILL.md`:

```markdown
---
name: modular-design
description: Use when a file has grown large, when deciding how to split a module, or when a task would add code to an already-oversized file. Applies a cohesion test rather than a line limit, and refuses splits that would separate shared state. Triggers on "this file is too big", "split this module", "god class", "refactor into modules", "where should this code live", "module boundaries".
user-invocable: true
---

# Modular design

## Overview

Files grow because nothing is ever obliged to notice. This skill supplies the
obligation and, more importantly, the judgment — because "keep files small" on
its own is worse than no rule at all. It produces ten fifty-line files with
circular imports and calls that an improvement.

The rule this skill enforces is not about size. It is:

> A unit does one thing, can be named without "and", and hides how it does it.

## When this applies

- A file crossed the tripwire (below) and someone has to decide what that means.
- A task would add code to a file that is already over it.
- A module's responsibilities feel tangled and you want a defensible boundary.
- Someone asked for a split and you need to check whether it is the right one.

## The tripwire

Default **400 physical lines**. A project may override it in its `CLAUDE.md`
`## Architecture` section (`Module tripwire: 500 lines.`).

Get the numbers instead of guessing at them:

```bash
python scripts/module_scan.py
python scripts/module_scan.py --tripwire 500 --top 10
python scripts/module_scan.py --json          # for programmatic use
```

**Crossing the tripwire does not mandate a split.** It mandates running the
three tests below and stating the outcome. A cohesive 900-line file passes and
is left alone. Say so explicitly — an unstated "I looked and it was fine" is
indistinguishable from not looking, and the next agent re-litigates it.

## The three tests

Apply in order. **Tests 2 and 3 are veto gates**: test 1 can say "split", and
either of the others can overrule it.

### 1. Reasons to change

How many distinct reasons would make someone edit this file?

Count causes, not functions. "The pricing rules changed", "we moved to a new
payment provider", and "the invoice PDF layout changed" are three reasons. Ten
functions that all change when the pricing rules change are one reason.

- **1 reason** → cohesive. Leave it, whatever its length.
- **2 reasons** → borderline. Split only if the halves are genuinely independent.
- **3+ reasons** → split along those reasons.

### 2. Shared private state (veto)

Would the two halves share mutable private state — a cache, a connection, a
counter, an accumulated buffer, an initialization order?

**If yes, they are one unit. Do not split them.** A split here does not remove
the coupling; it makes it invisible, converts a local variable into a
cross-module contract, and turns a bug you could see into one you cannot.

Read-only shared *constants* do not trigger this veto. Shared *mutable* state
does.

### 3. Name test (veto)

Can each proposed half be given a name that says what it does, without "and",
and without falling back to `utils`, `helpers`, `common`, `misc`, `core`,
`base`, or a bare `manager`?

**If the best name you can find is `utils.py`, the boundary is wrong.** That name
is what a leftover pile is called. Find a different cut, or leave the file whole.

## Deciding, and recording the decision

State the outcome in one of three forms:

- **"Cohesive — one reason to change (<the reason>). Left whole at N lines."**
- **"Split declined — <k> reasons to change, but <veto 2|veto 3>: <why>. Left
  whole at N lines."**
- **"Split along <k> reasons: <name> (<reason>), <name> (<reason>). Boundary
  passes the state and name tests."**

The second form is the one people forget. A file can fail test 1 and still be
correct to leave whole; reporting that as "cohesive" hides the veto and
guarantees the next agent re-litigates it.

Where it goes, if you are an agent implementing a task: a **proposed boundary**
is a scopeable task and belongs in `<out-of-scope>`. A **cohesive or
declined-split verdict is not a task** — state it in `<module-check>` instead,
so the findings list stays a list of work and not a log of non-findings.

## The split procedure

Only run this when splitting *is* the assigned task.

1. **Target one file.** From `module_scan.py` or named directly.
2. **Inventory.** List every top-level symbol — function, class, constant — and
   group them by reason-to-change. Write the groups down before judging them.
3. **Apply the veto gates.** Shared private state, then the name test. **This
   step may legitimately conclude "do not split"** — record the reasoning and
   stop. That is a successful outcome of this skill, not a failure of it.
4. **Propose.** New file names, what moves to each, and the resulting import
   edges — including any new cycle, which is a sign the boundary is wrong.
   **Stop here and get approval before touching anything.** When the split is
   already an approved task in a work plan, the plan *is* the approval: record
   the boundary in your report and continue to step 5. Return `BLOCKED` only if
   the boundary you found differs materially from the one the task assumed.
5. **Execute as pure moves.** Move code with no logic edits, no signature
   changes, no renames, no opportunistic cleanup. Run the tests after each move.
6. **Only then thin the wrappers**, as separate commits.

**Steps 5 and 6 must not share a commit.** A move that changes no behaviour is
reviewable by inspection. A behaviour change that is not tangled with six
hundred lines of motion is reviewable at all. Together they are neither, and
"the refactor broke something" becomes unbisectable.

Commit moves with the `[refactor]` phase bracket:

```bash
git commit -m "refactor: [refactor] extract pricing rules from billing"
```

## Shape catalogue

If the project declares an architecture in its `CLAUDE.md` `## Architecture`
section, or visibly already uses one, follow it. **Otherwise impose nothing** —
follow the structure that is there.

- **Layered service** — endpoints / manager / repository. See the
  `layered-api-design` skill for the full treatment.
- **Pipeline** — one module per transform stage, with an explicit data contract
  between stages. The contract, not the stage, is the unit that must stay stable.
- **Plugin / registry** — a thin dispatching core plus one module per capability.
  The core must not know any capability by name.
- **Library** — a public surface module over private internals. Everything not
  named in the surface is free to change.

Each layer, stage, or plugin is itself a **thin wrapper over focused
submodules**. A "layer" that is one 2,000-line file has not been decomposed; it
has been labelled.

## Who does what

- **An implementer** that notices an over-tripwire file **does not split it
  mid-task** — that is scope expansion. It runs the three tests and reports the
  proposed boundary in `<out-of-scope>`. A named boundary is a scopeable task; a
  line count is not.
- **A planner** that sees an over-tripwire file in a task's path schedules the
  extraction as its own preceding task.
- **A reviewing agent** raises boundaries as a maintainability finding with the
  count of reasons-to-change it found.

## Anti-patterns

- **Splitting by line count.** Produces even-sized files with arbitrary seams.
- **Splitting by technical layer when the project has no layers.** `models.py`,
  `views.py`, `utils.py` in a project that thinks in features means every feature
  change touches every file.
- **A `utils.py` that survives the split.** It is the pile of everything the
  boundary could not explain, and it will grow faster than what you split.
- **Splitting a file whose halves share a cache.** See veto 2.
- **Renaming and moving in one commit.** The diff shows deletion and creation;
  nobody can see that nothing changed.
- **"I'll clean this up while I'm in here."** That is the change nobody reviewed.
- **Declaring a file cohesive without saying why.** Unfalsifiable, and the next
  agent starts over.
```

- [ ] **Step 2: Verify the frontmatter parses the way the catalog generator expects**

```bash
python -c "import sys; sys.path.insert(0, 'docs_site'); import gen_catalog; fm, _ = gen_catalog.split_frontmatter(open('skills/modular-design/SKILL.md', encoding='utf-8').read()); print(fm['name']); print(fm['description'][:60])"
```

Expected: prints `modular-design` and the first 60 characters of the description. An empty dict means the frontmatter block is malformed.

- [ ] **Step 3: Confirm no crew agent is named in the skill**

```bash
grep -nE '`(builder|builder-simple|builder-standard|planner|reviewer|orchestrator|advisor|critic|scout|validator|explore|librarian|qa-guard|test-writer|doc-writer|doc-researcher|vision)`' skills/modular-design/SKILL.md
grep -nwE '(builder|planner|reviewer|orchestrator|advisor|critic|librarian|validator)' skills/modular-design/SKILL.md
```

Expected: the first grep produces **no output** (exit 1) — that is the binding
check. `apply_theme.py` renames `agents/*.md` only, so a backticked agent name in
a skill is a hard reference that goes stale the moment a theme is applied.

The second grep is advisory: it finds bare role nouns. A hit is fine when the word
reads as English prose ("A planner that sees…"), and a defect only when it is
standing in for a specific crew member. Read each hit; do not reword approved text
to silence it.

Do **not** use the form `grep -E '\b(a|b|c)\b'` here. In the Git Bash grep build
this repo is developed against, a `\b` immediately adjacent to a group never
matches, so that check passes unconditionally and verifies nothing.

- [ ] **Step 4: Commit**

```bash
git add skills/modular-design/SKILL.md
git commit -m "feat: [impl] add modular-design skill"
```

---

### Task 3: `skills/layered-api-design/SKILL.md`

**Files:**
- Create: `skills/layered-api-design/SKILL.md`

**Interfaces:**
- Consumes: the skill name `modular-design` (cross-referenced in the gate).
- Produces, relied on by Task 5: the skill name `layered-api-design`.

- [ ] **Step 1: Create the skill directory and write the file**

```bash
mkdir -p skills/layered-api-design
```

Write `skills/layered-api-design/SKILL.md`:

```markdown
---
name: layered-api-design
description: Use when building or reviewing an HTTP service in a project that has declared a layered architecture — routing, business, and persistence layers as thin wrappers over focused submodules. Applies only on an explicit project declaration, never inferred from "this is an API". Triggers on "endpoints manager repository", "service layer", "repository pattern", "fat controller", "where does this business logic go", "layered architecture".
user-invocable: true
---

# Layered API design

## The gate — read this before anything else

**This skill applies only when the project has declared a layered service
architecture** in its `CLAUDE.md` `## Architecture` section, or already
unmistakably uses one — **all three** layers present as distinct, layer-named
trees, or a documented convention saying so.

A lone `services/` directory is **not** evidence. That name is used for HTTP
client wrappers, background workers, and DI containers at least as often as for a
business layer. When in doubt, treat the shape as undeclared and stop.

**Never infer it from "this is an HTTP API."** Three layers are standard for
CRUD-over-HTTP and actively wrong for a CLI, a batch job, a data pipeline, a
game loop, an event consumer, or a thin proxy. Imposing them where they were not
asked for is the same defect as imposing hexagonal architecture on a script.

If the project has declared no shape, stop here and use the `modular-design`
skill instead — follow the structure that is already there.

## Declaring it

A project opts in with this in its `CLAUDE.md`:

```markdown
## Architecture

Layered service. HTTP handlers validate and format only; managers own the
business rules and the transaction boundary; repositories own SQL.
```

## The three layers

Each layer is a **thin wrapper over focused submodules** — never a single large
file per layer. `managers/billing/` holding `pricing.py` and `invoicing.py`
behind a thin `__init__.py` surface is a layer that has been decomposed. A
2,000-line `managers.py` is a layer that has only been named.

| Layer | Owns | Never touches |
|---|---|---|
| **endpoints** | Parse the request, validate input, call **one** manager function, format the response, map errors to status codes | Business rules, SQL |
| **manager** | Business rules, orchestration across repositories, the transaction boundary | HTTP types in *or* out, SQL |
| **repository** | Persistence; accepts and returns domain types | Business rules |

### Endpoints

An endpoint is a translator between the transport and the domain. It knows what
a 404 is; it does not know why the thing was missing.

Its whole body should read: validate → call one manager function → format. If it
has a branch that is not input validation or error mapping, that branch is a
business rule in the wrong layer.

### Managers

The manager owns the *decisions*. It is where "a refund is allowed within 30
days unless the order shipped" lives. It takes and returns domain types, so the
same function is callable from an HTTP handler, a CLI command, a background job,
or a test — none of which have a `Request` object to hand it.

It also owns the transaction boundary, because it is the only layer that knows
which group of writes must succeed or fail together. A repository that opens its
own transaction per call cannot express that.

### Repositories

The repository owns persistence and nothing else. It accepts and returns domain
types, so the schema can change without the manager changing.

The moment it returns an ORM row, every manager that touches it is coupled to
the schema, and lazy-loading turns a database access into something that can
happen anywhere — including after the transaction closed.

## Anti-patterns

Each has a tell and a fix. Four are greppable; three need reading.

- **Fat controller.** Branching business logic in the handler.
  *Tell:* an `if` in an endpoint that is not input validation or error mapping.
  *Fix:* move the decision into a manager function and call it.

- **SQL in the handler.** The repository layer bypassed entirely.
  *Tell:* a query builder, ORM session, or raw SQL imported into a routing module.
  *Fix:* add the repository method the handler wanted.

- **Anemic manager.** A pass-through that only forwards to a repository.
  *Tell:* every method is one line and that line is `return self.repo.x(...)`.
  *Fix:* **delete the layer.** This is the honest signal that this project does
  not need three layers. Keeping an empty layer costs a file, an indirection, and
  a test per call, and buys nothing. Do not invent work for it.

- **Transport leaking down.** HTTP types reaching the business layer.
  *Tell:* `Request`, `Response`, or a status code imported into a manager module.
  *Fix:* the endpoint translates; the manager takes and returns domain types, so
  the same function stays callable from a CLI command, a job, or a test.

- **Leaky repository.** ORM rows returned upward.
  *Tell:* a manager or endpoint importing an ORM model class.
  *Fix:* map to a domain type at the repository boundary.

- **Logic in the serializer.** Business decisions hidden in output formatting.
  *Tell:* a response formatter that computes, filters by rule, or applies
  entitlement.
  *Fix:* the manager returns the decided value; the serializer only shapes it.

- **Handler orchestrating multiple managers.** An endpoint calling two or three
  managers and combining the results.
  *Tell:* more than one manager import in a routing module.
  *Fix:* the missing thing is a manager function that expresses the operation.
  This is a gap in the business layer, not a licence for the handler to coordinate.

## Reviewing an existing service against this

1. Grep routing modules for ORM/SQL imports → SQL in the handler.
2. Grep routing modules for more than one manager import → handler orchestrating
   multiple managers; the missing thing is a manager function.
3. Read each endpoint for a branch that is not input validation or error mapping
   → fat controller.
4. Grep manager modules for HTTP types (`Request`, `Response`, status codes) →
   transport leaking down.
5. Grep manager modules for ORM imports → leaky repository.
6. Read each manager for one-line pass-throughs → anemic manager; the fix is to
   delete the layer.
7. Read response formatters for computation, rule-based filtering, or entitlement
   → logic in the serializer.
8. Run `python scripts/module_scan.py`. A layer file over the tripwire has not
   been decomposed into submodules — apply the `modular-design` skill to it.
```

- [ ] **Step 2: Verify the frontmatter parses**

```bash
python -c "import sys; sys.path.insert(0, 'docs_site'); import gen_catalog; fm, _ = gen_catalog.split_frontmatter(open('skills/layered-api-design/SKILL.md', encoding='utf-8').read()); print(fm['name'])"
```

Expected: prints `layered-api-design`.

- [ ] **Step 3: Confirm no crew agent is named in the skill**

```bash
grep -nE '`(builder|builder-simple|builder-standard|planner|reviewer|orchestrator|advisor|critic|scout|validator|explore|librarian|qa-guard|test-writer|doc-writer|doc-researcher|vision)`' skills/layered-api-design/SKILL.md
grep -nwE '(builder|planner|reviewer|orchestrator|advisor|critic|librarian|validator)' skills/layered-api-design/SKILL.md
```

Expected: the first grep produces **no output** (exit 1) — that is the binding
check. `apply_theme.py` renames `agents/*.md` only, so a backticked agent name in
a skill is a hard reference that goes stale the moment a theme is applied.

The second grep is advisory: it finds bare role nouns. A hit is fine when the word
reads as English prose ("A planner that sees…"), and a defect only when it is
standing in for a specific crew member. Read each hit; do not reword approved text
to silence it.

Do **not** use the bare-word-boundary-around-a-group form here. In the Git Bash
grep build this repo is developed against, a word boundary escape immediately
adjacent to a group never matches, so that check passes unconditionally and
verifies nothing.

- [ ] **Step 4: Commit**

```bash
git add skills/layered-api-design/SKILL.md
git commit -m "feat: [impl] add layered-api-design skill, gated on project declaration"
```

---

### Task 4: Agent charter edits

**Files:**
- Modify: `agents/planner.md:66-97` (Plan Structure) and `agents/planner.md:114-127` (Maximise Parallelism)
- Modify: `agents/builder.md:39-42` (You DO NOT), `:52-56` (Orient), `:80-85` (Commit table), `:114-117` (Output Contract), `:153-154` (Anti-Patterns)
- Modify: `agents/builder-standard.md` — same five sections, same line numbers
- Modify: `agents/builder-simple.md` — same five sections, same line numbers
- Modify: `agents/reviewer.md:27-30` (§1 Scope Definition commit-bracket list) and `agents/reviewer.md:64-72` (§5 Maintainability Assessment)
- Test: `tests/test_agent_definitions.py` (existing — must still pass)

**Interfaces:**
- Consumes from Task 2: the skill name `modular-design` and the three test names.
- Produces: the `[refactor]` commit bracket, referenced by Task 2's split procedure, and the `<module-check>` output-contract element, referenced by Task 2's "Where it goes" guidance.

**The three builder files are byte-identical apart from frontmatter and lines 16–17.** Apply the same five edits to all three, verbatim. Do not touch lines 16–17 — `tests/test_agent_definitions.py:952` pins the `standard` tier sentence exactly.

- [ ] **Step 1: Add the extraction-first rule to the planner**

In `agents/planner.md`, under `### Maximise Parallelism` (line 114), append this bullet to the existing list:

```markdown
- Run `python scripts/module_scan.py --json` while decomposing — pass
  `--tripwire <N>` when the project's `## Architecture` section declares an
  override, e.g. `python scripts/module_scan.py --json --tripwire 300`; the
  scanner only reports files over whichever tripwire it is given, so a
  declared override never reaches the JSON without it. If a task would add
  code to a file that appears over the tripwire (400 lines by default, or the
  project's `## Architecture` override), schedule the extraction as its own
  **preceding** task, tiered `standard` or `complex`. An implementer will not
  split mid-task, so an unscheduled extraction never happens.
```

In `agents/planner.md`, inside the `### Plan Structure` fenced block, change the `## Context` line (line 73) from:

```markdown
## Context
Background and current state
```

to:

```markdown
## Context
Background and current state. Record the project's declared architecture from
its `CLAUDE.md` `## Architecture` section, if it has one, so implementers
inherit it instead of re-deriving it.
```

- [ ] **Step 2: Add the orient-time length check to all three builder tiers**

In each of `agents/builder.md`, `agents/builder-standard.md`, `agents/builder-simple.md`, append this paragraph to `### 1. Orient before editing` (line 46). It goes here, first, because it is the first thing an agent encounters — and it closes the prior review's Critical finding that nothing measured a file before an agent appended to it:

```markdown
**Check the length of any existing file your task will add to.** Over 400 lines —
or the project's `## Architecture` override, passed as `--tripwire <N>` — run the
three tests from the `modular-design` skill before you append, and report the
outcome as described there. `python scripts/module_scan.py --json --tripwire <N>`
gives you the numbers when an override applies; `wc -l` will do for a single file.
```

- [ ] **Step 3: Add the mid-task split prohibition to all three builder tiers**

In each of `agents/builder.md`, `agents/builder-standard.md`, `agents/builder-simple.md`, append to the `### You DO NOT` list (after line 38):

```markdown
- **Split a large file mid-task.** A file over the module tripwire is *reported*,
  never restructured, unless splitting it is the task you were given. Run the
  three tests from the `modular-design` skill and put the proposed boundary in
  `<out-of-scope>` — a named boundary is a scopeable task, a line count is not.
```

- [ ] **Step 4: Add the `[refactor]` row to the commit table in all three builder tiers**

In each of the three files, in `### 5. Commit`, change the table from:

```markdown
| What you built | Prefix |
|---|---|
| Production code | `[impl]` |
| Bug fix surfaced by a failing test | `[fix]` |
| Tooling or config only | `[chore]` |
```

to:

```markdown
| What you built | Prefix |
|---|---|
| Production code | `[impl]` |
| Bug fix surfaced by a failing test | `[fix]` |
| Tooling or config only | `[chore]` |
| A behaviour-preserving module split | `[refactor]` |
```

- [ ] **Step 5: Add a `<module-check>` element to the Output Contract in all three builder tiers**

The `modular-design` skill (Task 2) tells an agent to state a cohesive-or-declined
verdict, but the contract says "Use the contract below. Nothing else." and had no
element that fit one: `<out-of-scope>` is scopeable findings, and a verdict is not
a task. In each of the three files, in `## Output Contract`, insert a new element
between `</verification>` and `<deviations>`:

```markdown
<verification>
$ <command you ran>
<actual output, trimmed to the relevant lines>
</verification>

<module-check>
For each existing file you added to: its length, and the tripwire verdict from
the `modular-design` skill in one line. "N/A" if your task created only new files.
</module-check>

<deviations>
Where you departed from the task as written, and why. "None" if none.
</deviations>
```

- [ ] **Step 6: Add the anti-pattern to all three builder tiers**

In each of the three files, append to `## Anti-Patterns (DO NOT DO)` (after line 136):

```markdown
- Appending to a file already over the module tripwire without running the
  three tests → run it and report the boundary in `<out-of-scope>`
```

- [ ] **Step 7: Add the module-boundary review dimension**

In `agents/reviewer.md`, append to `### 5. Maintainability Assessment` (after line 68):

```markdown
- Flag files whose responsibilities have diverged: name the file, the number of
  distinct reasons-to-change you found, and the boundary you would draw. A line
  count alone is not a finding — a file is oversized only if it is also
  incohesive, and a cohesive long file is not a defect.
```

- [ ] **Step 8: Add the `[refactor]` bracket to the reviewer's commit-scoping list**

`agents/reviewer.md`'s `### 1. Scope Definition` already tells the reviewer to
scope to the workflow phase under review by naming the typed-commit brackets; it
needs `[refactor]` added to that list alongside the rest. Change:

```markdown
- **Scope to the workflow phase under review (typed-commit projects).** If the
  project uses the `[impl]` / `[test]` / `[fix]` / `[docs]` / `[chore]` commit
  convention, identify the phase being reviewed and resolve its exact commits
  before reading any diff:
```

to:

```markdown
- **Scope to the workflow phase under review (typed-commit projects).** If the
  project uses the `[impl]` / `[test]` / `[fix]` / `[docs]` / `[chore]` /
  `[refactor]` commit convention, identify the phase being reviewed and resolve
  its exact commits before reading any diff:
```

- [ ] **Step 9: Verify the three builder tiers still differ only where they should**

```bash
diff agents/builder.md agents/builder-standard.md
```

Expected: differences confined to lines 2, 3, 4 (frontmatter `name`, `description`, `model`) and lines 16–17 (the tier sentence). Any other difference means an edit was applied to one tier and not another.

- [ ] **Step 10: Run the agent-definition lint suite**

```bash
python -m unittest tests.test_agent_definitions -v
```

Expected: `OK`. This suite pins the writer set, the write-access declarations, boundary sentences, and the exact `standard` tier sentence. A failure here means an edit landed in a pinned region.

- [ ] **Step 11: Run the full suite**

```bash
python -m unittest discover -s tests -v
```

Expected: `OK`.

- [ ] **Step 12: Commit**

```bash
git add agents/planner.md agents/builder.md agents/builder-standard.md agents/builder-simple.md agents/reviewer.md
git commit -m "feat: [impl] teach the crew module boundaries at write and review time"
```

---

### Task 5: Declaration, docs, and catalog

**Files:**
- Modify: `CLAUDE.md` (append the optional `## Architecture` section)
- Modify: `README.md:137-138` (the dev-workflow skills list)
- Modify: `docs_site/gen_catalog.py:198-208` (the "Development workflow" group)
- Regenerate: `docs_site/docs/skills.md`

**Interfaces:**
- Consumes from Tasks 2 and 3: both `SKILL.md` files must exist on disk before `gen_catalog.py` runs, or the catalog will silently omit them.
- Produces: the `## Architecture` declaration that both skills gate on.

- [ ] **Step 1: Add the optional Architecture section to the project brief**

In `CLAUDE.md`, insert this section between `## Engineering defaults` and `## Git / PRs`:

```markdown
## Architecture

This section is optional. This repo declares no shape — the crew follows
whatever structure is already in the tree. That is the default, and deleting
this section changes nothing.

To declare one, replace this text with the shape your project uses and, if you
want it, a tripwire override:

- **Recognised shapes** — layered service, pipeline, plugin/registry, library.
  The `modular-design` skill defines each one; `layered-api-design` covers the
  layered case in full, and applies *only* when a project declares it here.
- **Tripwire** — a line such as `Module tripwire: <N> lines.` overrides the
  400-line default used by `scripts/module_scan.py`.

Nothing in the crew infers an architecture. If this section declares nothing, the
crew imposes nothing.
```

- [ ] **Step 2: Name the new skills in the README**

In `README.md`, change lines 137-138 from:

```markdown
dev-workflow skills (`create-adr`, `repo-hygiene`, `handle-pr-comments`,
`gh-milestones-projects`, `dependency-pr-ci-fix`) and prompt/agent-evaluation skills. Add your own by
```

to:

```markdown
dev-workflow skills (`create-adr`, `repo-hygiene`, `handle-pr-comments`,
`gh-milestones-projects`, `dependency-pr-ci-fix`, `modular-design`,
`layered-api-design`) and prompt/agent-evaluation skills. Add your own by
```

- [ ] **Step 3: Add both skills to the catalog group**

In `docs_site/gen_catalog.py`, change the "Development workflow" group from:

```python
    (
        "Development workflow",
        [
            "code-navigation",
            "create-adr",
            "handle-pr-comments",
            "dependency-pr-ci-fix",
            "gh-milestones-projects",
            "repo-hygiene",
            "adopt-config",
        ],
    ),
```

to:

```python
    (
        "Development workflow",
        [
            "code-navigation",
            "create-adr",
            "modular-design",
            "layered-api-design",
            "handle-pr-comments",
            "dependency-pr-ci-fix",
            "gh-milestones-projects",
            "repo-hygiene",
            "adopt-config",
        ],
    ),
```

An unlisted skill still renders — under "Other", with a warning — so omitting this step degrades the site rather than breaking it. Do it anyway.

- [ ] **Step 4: Regenerate the catalog**

```bash
python docs_site/gen_catalog.py
```

Expected: no warning about ungrouped skills. `docs_site/docs/skills.md` is rewritten — never hand-edit it.

- [ ] **Step 5: Verify the regenerated page picked both skills up**

```bash
grep -n "modular-design\|layered-api-design\|Nescio ships" docs_site/docs/skills.md
```

Expected: the count line now reads `Nescio ships 35 skills`, both names appear in the "Development workflow" row of the at-a-glance table, and each has its own `### ` section with its description reproduced verbatim.

- [ ] **Step 6: Run the docs-site test roots**

```bash
python -m unittest discover -s docs_site -p "test_gen_catalog.py" -v
python -m unittest discover -s docs_site -p "test_site_content.py" -v
python -m unittest discover -s docs_site -p "test_ci_coverage.py" -v
```

Expected: `OK` for all three.

- [ ] **Step 7: Run the main suite one final time**

```bash
python -m unittest discover -s tests -v
```

Expected: `OK`.

- [ ] **Step 8: Commit**

```bash
git add CLAUDE.md README.md docs_site/gen_catalog.py docs_site/docs/skills.md
git commit -m "docs: [docs] document the architecture declaration and the two new skills"
```

---

## Verification — whole plan

Each line below maps to a plan-level check. The spec's three behavioural
criteria (implementer reports rather than splits, planner schedules extraction
first, `modular-design` can decline a split and say why) are prose contracts —
verify them by reading the edited charters and skill, not by running a command.

```bash
python -m unittest discover -s tests -v
python -m unittest discover -s docs_site -p "test_gen_catalog.py" -v
python scripts/module_scan.py --json | grep orchestrator
```

- [ ] `module_scan.py --json` names `agents/orchestrator.md`
- [ ] All three builder tiers carry the same five edits — `diff` shows only frontmatter and the tier sentence
- [ ] Neither `SKILL.md` names a crew agent (the grep in Tasks 2 and 3 is empty)
- [ ] `CLAUDE.md` with the `## Architecture` section deleted causes no layering to be imposed — the gate at the top of `layered-api-design` is the only entry point
- [ ] `docs_site/docs/skills.md` reports 35 skills, both grouped under Development workflow

## Known follow-ups — not this plan

- `agents/orchestrator.md` (669 lines) is a god-file by the rule this plan introduces. Tracked separately; splitting it here would make this change unreviewable.
- Retrofitting the doctrine across the existing 33 skills.
