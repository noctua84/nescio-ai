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

  * **Always exits 0.** This is a report, not a gate. The first person to pipe a
    non-zero-exiting scanner into a CI workflow turns an advisory number into a
    build failure by accident, and the number is not good enough to carry that.

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
    except OSError:
        return []
    if proc.returncode != 0:
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
    """Format the scan result as a human-readable report for terminal output."""
    over = result["over"]
    if top is not None:
        over = over[:top]
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
    for entry in over:
        lines.append(f"  {entry['lines']:>5}  {entry['path']}")
    lines.append("")
    lines.append(
        f"  {len(result['over'])} files over, {result['scanned']} scanned"
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

    result = scan(args.repo, args.tripwire, tuple(args.exclude))

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(format_report(result, args.top))
    return 0


if __name__ == "__main__":
    sys.exit(main())
