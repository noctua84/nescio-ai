#!/usr/bin/env python3
"""Scrub check — fail if private or identifying content would be published.

Two layers:

  1. Baseline (built in): high-signal secret patterns (FAIL) and absolute
     home-directory paths (WARN).
  2. Your own terms: a gitignored ``scrub-terms.local`` at the repo root — one
     Python regex per line (blank lines and ``#`` comments ignored). Any match
     FAILS. Copy ``scrub-terms.local.example`` and fill in your employer / repo /
     personal identifiers.

Usage (from the repo root):

    python scripts/scrub_check.py [PATH]

Exit status: 0 if clean (WARN-only is still 0), 1 on any FAIL match, 2 on a bad
custom regex.

Note: ``scrub-terms.local`` is gitignored, so it does not exist in CI — there,
only the baseline runs. Run this **locally before publishing** to catch your own
terms; CI enforces the secret/path baseline for everyone.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()

# Directories never scanned.
SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__", ".idea",
             ".mypy_cache", ".ruff_cache", ".pytest_cache"}

# Files never scanned — they legitimately contain the patterns themselves, or
# the author's name/attribution by design (LICENSE).
SKIP_FILES = {"scrub_check.py", "scrub-terms.local", "scrub-terms.local.example",
              "LICENSE"}

# Baseline FAIL — high-signal secrets.
SECRET_PATTERNS = [
    ("private key block", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----")),
    ("AWS access key id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("GitHub token", re.compile(r"\b(?:ghp|gho|ghs|ghr|github_pat)_[A-Za-z0-9_]{20,}")),
    ("Slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}")),
    ("secret assignment", re.compile(
        r"(?i)(?:api[_-]?key|secret|password|passwd|access[_-]?token)\s*[:=]\s*"
        r"['\"][A-Za-z0-9/+_\-]{16,}['\"]")),
]

# Baseline WARN — machine-specific absolute home paths (portable config shouldn't
# hardcode these; usually a stray example path).
# The `<>` exclusion lets template placeholders like `<you>` / `<user>` pass
# while real usernames (e.g. /Users/marku/) still warn.
PATH_PATTERNS = [
    ("home path", re.compile(r"(?:/Users/|/home/)[^/\s'\"<>]+/")),
    ("windows home path", re.compile(r"[Cc]:[\\/]+Users[\\/]+[^\\/\s'\"<>]+")),
]


def load_custom_terms() -> list[tuple[str, re.Pattern]]:
    path = ROOT / "scrub-terms.local"
    out: list[tuple[str, re.Pattern]] = []
    if not path.exists():
        return out
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        try:
            out.append((f"custom term (scrub-terms.local:{i})", re.compile(s)))
        except re.error as exc:
            print(f"scrub-terms.local:{i}: invalid regex {s!r}: {exc}", file=sys.stderr)
            sys.exit(2)
    return out


def iter_files(root: Path):
    for p in root.rglob("*"):
        if p.is_dir():
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        if p.name in SKIP_FILES:
            continue
        yield p


def main() -> int:
    custom = load_custom_terms()
    fails: list[tuple[str, Path, int, str]] = []
    warns: list[tuple[str, Path, int, str]] = []

    for p in iter_files(ROOT):
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # binary or unreadable — skip
        rel = p.relative_to(ROOT)
        for lineno, line in enumerate(text.splitlines(), 1):
            for label, rx in SECRET_PATTERNS:
                if rx.search(line):
                    fails.append((label, rel, lineno, line.strip()[:120]))
            for label, rx in custom:
                if rx.search(line):
                    fails.append((label, rel, lineno, line.strip()[:120]))
            for label, rx in PATH_PATTERNS:
                if rx.search(line):
                    warns.append((label, rel, lineno, line.strip()[:120]))

    if warns:
        print("WARN (review — machine-specific paths):")
        for label, rel, lineno, snip in warns:
            print(f"  {rel}:{lineno}: [{label}] {snip}")

    if fails:
        print("\nFAIL (private/secret content — must not publish):")
        for label, rel, lineno, snip in fails:
            print(f"  {rel}:{lineno}: [{label}] {snip}")
        print(f"\n{len(fails)} forbidden match(es). Fix before publishing.")
        return 1

    loaded = "no custom terms" if not custom else f"{len(custom)} custom term(s)"
    print(f"scrub: clean (baseline + {loaded}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
