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
    python scripts/module_scan.py --test-tripwire 1000
    python scripts/module_scan.py --exclude 'CHANGELOG.md' --exclude 'docs/**'
    python scripts/module_scan.py --json
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

# A convention, not an empirical defect threshold: roughly "a file that stops
# fitting in one comfortable read or one reviewable diff". It is a prompt to
# ask the three questions in the `modular-design` skill, nothing more.
DEFAULT_TRIPWIRE = 400

# Test files get a higher bar. Each test case is independent of its siblings --
# a 1,200-line test file is sixty twenty-line cases sharing a fixture, not 1,200
# lines of tangled responsibilities. Length is a weak proxy for "too many
# reasons to change" in production code and a weaker one here, and flagging
# every cohesive test file at the production bar buries the real findings
# (PR 251: three files flagged, one real -- and one of the noise was a test
# file that had simply gained cases).
DEFAULT_TEST_TRIPWIRE = 800

# The CI gate asks for a verdict on an already-over-tripwire file only when it
# grows by at least min(DEFAULT_GROWTH_LINES, ceil(base * DEFAULT_GROWTH_PERCENT
# / 100)) net lines.
#   * The percentage catches proportional ballooning of a mid-size file: a
#     450-line file growing by 113 lines (25%) has changed character, even
#     though 113 is well under the line cap.
#   * The line cap means a very large file cannot absorb a whole new module's
#     worth of code unnoticed: on a 1,000-line file 25% would be 250 lines, so
#     the cap pulls the bar down to 150.
#   * Below that, an edit to a large file is maintenance, not a new
#     responsibility. Nagging about it teaches people to write the verdict
#     without thinking, which is worse than no gate.
# The percentage is rounded up (ceil) so the threshold is always a whole
# number of lines, and the result is floored at 1 so a zero-line change can
# never count as growth.
DEFAULT_GROWTH_LINES = 150
DEFAULT_GROWTH_PERCENT = 25

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


# Filename globs that mark a test file regardless of directory.
TEST_FILENAME_GLOBS = ("test_*.py", "*_test.py", "*.spec.*", "*.test.*")


def is_test_file(rel: str) -> bool:
    """True when `rel` lives under a `tests` directory or is named like a test.

    The directory match is on whole path segments (`tests`, not `latests`); the
    filename match is `fnmatch` on the final segment only, so a directory that
    merely has `test_` in its name does not drag its non-test files in.
    """
    parts = rel.split("/")
    if "tests" in parts[:-1]:
        return True
    name = parts[-1]
    return any(fnmatch.fnmatch(name, pattern) for pattern in TEST_FILENAME_GLOBS)


@dataclass(frozen=True)
class TripwireConfig:
    """Resolved thresholds. Every field falls back to its default on its own."""

    tripwire: int = DEFAULT_TRIPWIRE
    test_tripwire: int = DEFAULT_TEST_TRIPWIRE
    growth_lines: int = DEFAULT_GROWTH_LINES
    growth_percent: int = DEFAULT_GROWTH_PERCENT


def growth_threshold(base_lines: int, growth_lines: int, growth_percent: int) -> int:
    """Net lines an already-over-tripwire file must gain to need a verdict.

    `min(growth_lines, ceil(base_lines * growth_percent / 100))`, floored at 1.
    Integer arithmetic on purpose: a float product can round the wrong way
    for large operands and move the threshold by a line.
    """
    by_percent = -(-(base_lines * growth_percent) // 100)  # integer ceil
    return max(1, min(growth_lines, by_percent))


# `## Architecture` up to the next `##` heading (or end of file). Searching
# only inside this section means prose elsewhere (e.g. the skill's own
# "Module tripwire: 500 lines." example) can never be mistaken for an override.
_ARCHITECTURE_SECTION_RE = re.compile(
    r"^##\s+Architecture\s*$(.*?)(?=^##\s|\Z)", re.IGNORECASE | re.MULTILINE | re.DOTALL
)

# The literal placeholders documenting each syntax -- not real overrides.
# Stripped before the digits-only patterns below run, so `<N>` / `<P>` never
# get a chance to be read as anything.
_PLACEHOLDER_RE = re.compile(
    r"(?:Module tripwire|Test tripwire):\s*<[A-Za-z]+>\s*lines\."
    r"|Module growth:\s*<[A-Za-z]+>\s*(?:lines|%)\.",
    re.IGNORECASE,
)

# Real overrides: digits only.
_TRIPWIRE_OVERRIDE_RE = re.compile(r"Module tripwire:\s*(\d+)\s*lines\.", re.IGNORECASE)
_TEST_TRIPWIRE_OVERRIDE_RE = re.compile(r"Test tripwire:\s*(\d+)\s*lines\.", re.IGNORECASE)
_GROWTH_LINES_OVERRIDE_RE = re.compile(r"Module growth:\s*(\d+)\s*lines\.", re.IGNORECASE)
_GROWTH_PERCENT_OVERRIDE_RE = re.compile(r"Module growth:\s*(\d+)\s*%\.", re.IGNORECASE)


def resolve_config(claude_md: Path) -> TripwireConfig:
    """Read the `## Architecture` section of `claude_md` for threshold overrides.

    Recognised lines: `Module tripwire: <N> lines.`, `Test tripwire: <N>
    lines.`, `Module growth: <N> lines.` and `Module growth: <P>%.`. Each field
    falls back to its default independently -- a project that only raises the
    test tripwire keeps the production default. A missing file, a missing
    `## Architecture` section, or one holding only the literal placeholders
    (this repo's own case) yields the all-defaults config.
    """
    try:
        text = claude_md.read_text(encoding="utf-8")
    except OSError:
        return TripwireConfig()

    section_match = _ARCHITECTURE_SECTION_RE.search(text)
    if not section_match:
        return TripwireConfig()
    section = _PLACEHOLDER_RE.sub("", section_match.group(1))

    def pick(pattern: re.Pattern[str], default: int) -> int:
        match = pattern.search(section)
        return int(match.group(1)) if match else default

    return TripwireConfig(
        tripwire=pick(_TRIPWIRE_OVERRIDE_RE, DEFAULT_TRIPWIRE),
        test_tripwire=pick(_TEST_TRIPWIRE_OVERRIDE_RE, DEFAULT_TEST_TRIPWIRE),
        growth_lines=pick(_GROWTH_LINES_OVERRIDE_RE, DEFAULT_GROWTH_LINES),
        growth_percent=pick(_GROWTH_PERCENT_OVERRIDE_RE, DEFAULT_GROWTH_PERCENT),
    )


def count_lines_from_bytes(data: bytes) -> int | None:
    """Physical line count of `data`, or None when it looks binary.

    Split out of `count_lines` so a second caller (`module_gate.find_hits`,
    which reads a blob from a ref via `git show` rather than the filesystem)
    can reuse the binary-sniff and trailing-newline logic without a second
    implementation of it. A copy would drift from this one the moment either
    changed, and the binary-detection branch is exactly the part that would.
    """
    if b"\0" in data[:_SNIFF_BYTES]:
        return None
    if not data:
        return 0
    count = data.count(b"\n")
    if not data.endswith(b"\n"):
        count += 1
    return count


def count_lines(path: Path) -> int | None:
    """Physical line count, or None when the file is binary or unreadable.

    An unreadable file returns None rather than raising: a scan that dies on one
    odd file reports nothing about the other two hundred.
    """
    try:
        data = path.read_bytes()
    except OSError:
        return None
    return count_lines_from_bytes(data)


def scan(
    repo: Path,
    tripwire: int,
    excludes: tuple[str, ...],
    test_tripwire: int = DEFAULT_TEST_TRIPWIRE,
) -> dict:
    """Count every eligible tracked file; return the ones over their tripwire.

    A test file (see `is_test_file`) is measured against `test_tripwire`, every
    other file against `tripwire`; each `over` entry carries the `tripwire` that
    applied to it so a reader never has to guess which bar a file crossed.

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
        applicable = test_tripwire if is_test_file(rel) else tripwire
        if lines > applicable:
            over.append({"path": rel, "lines": lines, "tripwire": applicable})
    over.sort(key=lambda entry: (-entry["lines"], entry["path"]))
    return {
        "tripwire": tripwire,
        "test_tripwire": test_tripwire,
        "scanned": scanned,
        "over": over,
    }


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

    header = f"  over tripwire (>{result['tripwire']} lines"
    if "test_tripwire" in result:
        header += f"; test files >{result['test_tripwire']}"
    lines.append(header + ")")
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
    # A non-ASCII tracked file path would appear verbatim in the report; a
    # legacy Windows console (cp1252) would raise UnicodeEncodeError on it.
    # Reconfigure to UTF-8 up front, before any print (guarded -- a
    # redirected StringIO in tests has no reconfigure).
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass

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
        "--test-tripwire",
        type=int,
        default=DEFAULT_TEST_TRIPWIRE,
        help=(
            "lines above which a test file is reported "
            f"(default {DEFAULT_TEST_TRIPWIRE})"
        ),
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
    if args.test_tripwire < 0:
        parser.error("--test-tripwire must not be negative")

    result = scan(args.repo, args.tripwire, tuple(args.exclude), args.test_tripwire)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(format_report(result, args.top))
    return 0


if __name__ == "__main__":
    sys.exit(main())
