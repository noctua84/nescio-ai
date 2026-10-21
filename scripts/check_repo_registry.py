#!/usr/bin/env python3
"""Validate `repo-registry.toml` against `memory/repo/` and `adr-publish.toml`.

The loud, strict half of `_repo_registry.py`. The alias lookups the readiness and
harvest tools consume are deliberately lenient — a malformed registry degrades to
"no aliases" there rather than derailing a harvest — so the mistakes that
leniency hides need a gate that shouts. This is that gate for a human;
`tests/test_repo_registry.py` is the one CI runs.

Reports every finding in one pass rather than the first, because the registry is
hand-edited and stopping at one misspelling costs an edit/run cycle per mistake.

Exit codes: 0 healthy, 1 problems found, 2 the registry is absent or unparseable.
An absent registry is 2 and not 0: on an instance that has not written one the
alias silently does nothing, and reporting that as "healthy" is the one answer
that would keep a reader from noticing.

Usage:
    python scripts/check_repo_registry.py
    python scripts/check_repo_registry.py --registry P --memory-root P
    python scripts/check_repo_registry.py --no-adr-check
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _repo_registry as rr  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Validate repo-registry.toml against memory/repo/ and "
                    "adr-publish.toml (read-only).",
    )
    ap.add_argument("--registry", default=str(rr.DEFAULT_REGISTRY_PATH),
                    help="path to repo-registry.toml (default: this repo's)")
    ap.add_argument("--memory-root", default=str(rr.DEFAULT_MEMORY_ROOT),
                    help="path to the brain's memory/ root (default: this repo's)")
    ap.add_argument("--adr-config", default=str(rr.DEFAULT_ADR_CONFIG_PATH),
                    help="path to adr-publish.toml; cross-checked only if it exists")
    ap.add_argument("--no-adr-check", action="store_true",
                    help="skip the adr-publish.toml cross-check entirely")
    args = ap.parse_args(argv)

    # The report contains ✓/✗ and em dashes; a legacy Windows console defaults to
    # cp1252 and would raise UnicodeEncodeError mid-report. Same guard as
    # `scrub_check.py` et al, pinned by `tests/test_console_encoding_guard.py`.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass

    try:
        registry = rr.load_registry(args.registry)
    except rr.RegistryError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 2

    problems = rr.validate(
        registry,
        memory_root=args.memory_root,
        adr_config=None if args.no_adr_check else args.adr_config,
    )

    print(f"{Path(args.registry).as_posix()}: {len(registry.entries)} dir(s) registered.")
    for entry in registry.entries:
        github = entry.github or "(slug withheld)"
        aliases = [k for k in entry.trail_keys if k != entry.dir]
        bits = [github]
        if aliases:
            bits.append("aliases: " + ", ".join(f"`{a}`" for a in aliases))
        if not entry.clone_expected:
            bits.append("no local clone expected")
        print(f"  {entry.dir} — {'; '.join(bits)}")
    if registry.shared_slugs:
        print()
        print("declared shared-slug exceptions (convergences in flight):")
        for slug, dirs in sorted(registry.shared_slugs.items()):
            print(f"  {slug} — {', '.join(dirs)}")

    print()
    if problems:
        print(f"✗ {len(problems)} problem(s):")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("✓ no problems found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
