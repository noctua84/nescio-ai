#!/usr/bin/env python3
"""Assess how ready a target repository is for autonomous work — read-only.

Phase 2.1b's "freshman orientation" gate. Given a checkout path, it scans two
axes and reports them; it never writes to the target repo (or anywhere). The
signal it produces is what Phase 3's autonomy dial will consume to set a repo's
autonomy cap.

Two axes:

  1. Memory depth — how much durable, version-controlled knowledge the *brain*
     already holds about this repo, under `memory/repo/<name>/`. A repo the brain
     has never learned about is `none`; one with a deep note+ADR corpus is `deep`.
  2. AI-friendliness — how much *the target repo itself* helps an agent work
     safely: tests, CI, typechecking, ADRs, conventions, and a project manifest,
     all detected language-agnostically by filesystem presence (nothing is
     executed).

Everything here is read-only. File reads are guarded so a missing or unreadable
file simply means "signal absent", and scanning is bounded to a shallow,
well-known set of paths so a huge target repo cannot make this slow.

Usage:
    python scripts/assess_repo_readiness.py [repo-path]
    python scripts/assess_repo_readiness.py [repo-path] --json
    python scripts/assess_repo_readiness.py [repo-path] --memory-root <path>
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
DEFAULT_MEMORY_ROOT = REPO_DIR / "memory"

# ── Memory-depth thresholds ────────────────────────────────────────────────
# Count = content `.md` notes under memory/repo/<name>/ (EXCLUDING MEMORY.md)
# PLUS ADRs under that dir's adr/. Boundaries are inclusive lower bounds:
#   0        -> none    (dir absent or empty of content)
#   1..2     -> thin
#   3..9     -> moderate
#   10+      -> deep
MEMORY_THIN_MIN = 1
MEMORY_MODERATE_MIN = 3
MEMORY_DEEP_MIN = 10

# ── AI-friendliness thresholds ─────────────────────────────────────────────
# The "heavy" signals that carry the most weight for safe autonomous work.
HEAVY_SIGNALS = ("tests", "ci", "typecheck")


def _depth_level(count: int) -> str:
    """Map a memory item count to its depth level."""
    if count >= MEMORY_DEEP_MIN:
        return "deep"
    if count >= MEMORY_MODERATE_MIN:
        return "moderate"
    if count >= MEMORY_THIN_MIN:
        return "thin"
    return "none"


def assess_memory_depth(repo_name: str, memory_root: Path) -> dict:
    """How much durable brain-memory exists for ``repo_name``.

    Counts `.md` notes under ``memory_root/repo/<repo_name>/`` (excluding the
    ``MEMORY.md`` index) plus ADRs under its ``adr/`` subdir, and flags the
    presence of ``overview.md`` / ``readiness.md``. An absent dir is ``none``.

    Returns ``{"level", "notes", "adrs", "has_overview", "has_readiness"}``.
    """
    repo_mem = Path(memory_root) / "repo" / repo_name

    notes = 0
    adrs = 0
    has_overview = False
    has_readiness = False

    # Notes count excludes MEMORY.md (the index) and readiness.md. readiness.md
    # is the readiness system's own tracking output (the clean/flagged track
    # record) that Phase 3's dial reads directly as a separate signal — counting
    # it toward memory-depth would double-count the same file. overview.md is
    # genuine repo knowledge and stays counted.
    _EXCLUDED = {"MEMORY.md", "readiness.md"}
    if repo_mem.is_dir():
        for entry in repo_mem.glob("*.md"):
            if entry.is_file() and entry.name not in _EXCLUDED:
                notes += 1
        adr_dir = repo_mem / "adr"
        if adr_dir.is_dir():
            adrs = sum(1 for e in adr_dir.glob("*.md") if e.is_file())
        has_overview = (repo_mem / "overview.md").is_file()
        has_readiness = (repo_mem / "readiness.md").is_file()

    # Depth count: content `.md` notes (excluding MEMORY.md and readiness.md,
    # which the glob above already skips) PLUS ADRs under adr/.
    count = notes + adrs
    return {
        "level": _depth_level(count),
        "notes": notes,
        "adrs": adrs,
        "has_overview": has_overview,
        "has_readiness": has_readiness,
    }


def _read_text(path: Path) -> str:
    """Read a file as text, returning "" on any failure (missing/unreadable)."""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _pyproject_has_section(repo: Path, header_prefix: str) -> bool:
    """True if pyproject.toml contains a section whose header starts with prefix.

    Deliberately a substring match on the raw text (no tomllib) — simple and
    robust; a missing/unreadable pyproject just means the section is absent.
    """
    pyproject = repo / "pyproject.toml"
    if not pyproject.is_file():
        return False
    return header_prefix in _read_text(pyproject)


def _has_any_file(repo: Path, names: tuple[str, ...]) -> bool:
    """True if any of the top-level filenames exists as a file."""
    return any((repo / n).is_file() for n in names)


def _has_any_dir(repo: Path, names: tuple[str, ...]) -> bool:
    """True if any of the given relative dirs exists."""
    return any((repo / n).is_dir() for n in names)


def _detect_tests(repo: Path) -> bool:
    """Detect a test setup by filesystem presence (no execution)."""
    if _has_any_dir(repo, ("tests", "test", "__tests__")):
        return True
    # Shallow glob for common test file names — top level and one dir deep — to
    # stay bounded on huge repos rather than walking the whole tree.
    patterns = (
        "test_*.py",
        "*_test.py",
        "*_test.go",
        "*.test.*",
        "*.spec.*",
    )
    for pat in patterns:
        if next(iter(repo.glob(pat)), None) is not None:
            return True
        if next(iter(repo.glob(f"*/{pat}")), None) is not None:
            return True
    # pytest configuration.
    if _has_any_file(repo, ("pytest.ini", "tox.ini")):
        return True
    if _pyproject_has_section(repo, "[tool.pytest"):
        return True
    # JS/TS test runners.
    for pat in ("vitest.config.*", "jest.config.*"):
        if next(iter(repo.glob(pat)), None) is not None:
            return True
    return False


def _detect_ci(repo: Path) -> bool:
    """Detect a CI pipeline config by filesystem presence."""
    workflows = repo / ".github" / "workflows"
    if workflows.is_dir():
        for pat in ("*.yml", "*.yaml"):
            if next(iter(workflows.glob(pat)), None) is not None:
                return True
    if _has_any_file(repo, (".gitlab-ci.yml", "Jenkinsfile", "azure-pipelines.yml")):
        return True
    if (repo / ".circleci" / "config.yml").is_file():
        return True
    return False


def _detect_typecheck(repo: Path) -> bool:
    """Detect static type-checking configuration by filesystem presence."""
    if _has_any_file(repo, ("tsconfig.json", "mypy.ini", "pyrightconfig.json")):
        return True
    if _pyproject_has_section(repo, "[tool.mypy"):
        return True
    if _pyproject_has_section(repo, "[tool.pyright"):
        return True
    return False


def _detect_adrs(repo: Path) -> bool:
    """Detect an ADR directory (with at least one .md) by filesystem presence."""
    for rel in ("adr", "docs/adr", "doc/adr"):
        adr_dir = repo / rel
        if adr_dir.is_dir() and next(iter(adr_dir.glob("*.md")), None) is not None:
            return True
    return False


def _detect_conventions(repo: Path) -> tuple[bool, bool, bool]:
    """Detect agent conventions and doc scaffolding.

    Returns (has_conventions, has_readme, has_docs). ``has_conventions`` is the
    signal proper (CLAUDE.md); README/docs presence is noted in detail only.
    """
    has_conventions = (repo / "CLAUDE.md").is_file() or (
        repo / ".claude" / "CLAUDE.md"
    ).is_file()
    has_readme = _has_any_file(
        repo, ("README.md", "README.rst", "README.txt", "README")
    )
    has_docs = (repo / "docs").is_dir() or (repo / "doc").is_dir()
    return has_conventions, has_readme, has_docs


def _detect_project(repo: Path) -> bool:
    """Detect a project manifest by filesystem presence."""
    return _has_any_file(
        repo,
        (
            "package.json",
            "pyproject.toml",
            "go.mod",
            "Cargo.toml",
            "build.gradle",
            "pom.xml",
        ),
    )


def _friendliness_level(signals: dict) -> str:
    """Apply the level rule over the detected signals."""
    heavy = all(signals[s] for s in HEAVY_SIGNALS)
    supporting = signals["adrs"] or signals["conventions"]
    if heavy and supporting:
        return "high"
    if signals["tests"] and (signals["ci"] or signals["typecheck"]):
        return "medium"
    return "low"


def assess_ai_friendliness(repo_path) -> dict:
    """How much the target repo helps an agent work safely — read-only.

    Detects tests / ci / typecheck / adrs / conventions / project purely by
    filesystem presence, then applies the level rule:

      high   = all of {tests, ci, typecheck} AND at least one of {adrs, conventions}
      medium = tests AND (ci OR typecheck)
      low    = otherwise

    Returns ``{"level", "signals": {...}, "detail": {...}}``.
    """
    repo = Path(repo_path)

    has_conventions, has_readme, has_docs = _detect_conventions(repo)
    signals = {
        "tests": _detect_tests(repo),
        "ci": _detect_ci(repo),
        "typecheck": _detect_typecheck(repo),
        "adrs": _detect_adrs(repo),
        "conventions": has_conventions,
        "project": _detect_project(repo),
    }
    detail = {
        "has_readme": has_readme,
        "has_docs": has_docs,
    }
    return {
        "level": _friendliness_level(signals),
        "signals": signals,
        "detail": detail,
    }


def missing_items(memory: dict, ai: dict) -> list[str]:
    """Actionable gap strings for each absent signal."""
    gaps: list[str] = []
    signals = ai["signals"]

    if not signals["tests"]:
        gaps.append("No tests detected — add a test suite so changes can be verified")
    if not signals["ci"]:
        gaps.append(
            "No CI config found — add a .github/workflows pipeline (or equivalent)"
        )
    if not signals["typecheck"]:
        gaps.append(
            "No typecheck config found — add tsconfig.json / mypy / pyright config"
        )
    if not signals["adrs"]:
        gaps.append(
            "No ADRs found — record architecture decisions under adr/ or docs/adr/"
        )
    if not signals["conventions"]:
        gaps.append(
            "No CLAUDE.md conventions — add one so agents know the repo's rules"
        )
    if not signals["project"]:
        gaps.append(
            "No project manifest found — add package.json / pyproject.toml / go.mod / etc."
        )

    if memory["level"] == "none":
        gaps.append(
            "No memory/repo/<name>/ notes — the brain has no durable knowledge of "
            "this repo yet"
        )

    return gaps


def assess(repo_path, *, memory_root: Path = DEFAULT_MEMORY_ROOT) -> dict:
    """Compose both axes for ``repo_path`` into a single result dict.

    ``repo_name`` is the resolved basename of the target path. Returns
    ``{"repo", "repo_path", "memory_depth", "ai_friendliness", "missing"}``.
    """
    resolved = Path(repo_path).resolve()
    repo_name = resolved.name

    memory = assess_memory_depth(repo_name, memory_root)
    ai = assess_ai_friendliness(repo_path)
    return {
        "repo": repo_name,
        "repo_path": str(resolved),
        "memory_depth": memory,
        "ai_friendliness": ai,
        "missing": missing_items(memory, ai),
    }


_CHECK = "✓"
_CROSS = "✗"


def _mark(present: bool) -> str:
    return _CHECK if present else _CROSS


def render_markdown(result: dict) -> str:
    """Render a readable report for a result from :func:`assess`."""
    memory = result["memory_depth"]
    ai = result["ai_friendliness"]
    signals = ai["signals"]
    detail = ai["detail"]

    lines: list[str] = []
    lines.append(f"# Repo readiness — {result['repo']}")
    lines.append("")
    lines.append(f"_Path: {result['repo_path']}_")
    lines.append("")

    # Memory depth.
    lines.append("## Memory depth")
    lines.append("")
    lines.append(f"- Level: **{memory['level']}**")
    lines.append(f"- Notes (excl. MEMORY.md): {memory['notes']}")
    lines.append(f"- ADRs: {memory['adrs']}")
    lines.append(f"- overview.md: {_mark(memory['has_overview'])}")
    lines.append(f"- readiness.md: {_mark(memory['has_readiness'])}")
    lines.append("")

    # AI-friendliness.
    lines.append("## AI-friendliness")
    lines.append("")
    lines.append(f"- Level: **{ai['level']}**")
    lines.append("")
    lines.append(f"- {_mark(signals['tests'])} tests")
    lines.append(f"- {_mark(signals['ci'])} ci")
    lines.append(f"- {_mark(signals['typecheck'])} typecheck")
    lines.append(f"- {_mark(signals['adrs'])} adrs")
    lines.append(f"- {_mark(signals['conventions'])} conventions")
    lines.append(f"- {_mark(signals['project'])} project")
    lines.append(f"- {_mark(detail['has_readme'])} readme")
    lines.append(f"- {_mark(detail['has_docs'])} docs")
    lines.append("")

    # Missing.
    lines.append("## What's missing")
    lines.append("")
    if result["missing"]:
        for gap in result["missing"]:
            lines.append(f"- {gap}")
    else:
        lines.append("- Nothing — all tracked signals present.")
    lines.append("")

    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Assess a repo's readiness for autonomous work (read-only).",
    )
    ap.add_argument(
        "repo_path",
        nargs="?",
        default=os.getcwd(),
        help="path to the target repo (default: current directory)",
    )
    ap.add_argument(
        "--json",
        action="store_true",
        help="print the result as JSON instead of a markdown report",
    )
    ap.add_argument(
        "--memory-root",
        default=str(DEFAULT_MEMORY_ROOT),
        help="path to the brain's memory/ root (default: this repo's memory/)",
    )
    args = ap.parse_args(argv)

    # The markdown report uses ✓/✗ glyphs; a legacy Windows console defaults to
    # cp1252 and would raise UnicodeEncodeError on them. Reconfigure to UTF-8
    # when possible (guarded — a redirected StringIO in tests has no reconfigure).
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass

    result = assess(args.repo_path, memory_root=Path(args.memory_root))
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(render_markdown(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
