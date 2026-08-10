#!/usr/bin/env python3
"""Lint a markdown knowledge store.

Reports, per note in scope:
  - missing frontmatter fields (name / description / type)
  - dangling [[links]] (target matches no note name or filename stem in scope)
  - orphan notes (no inbound [[link]] and not referenced by any in-scope
    MEMORY.md markdown link)

`--check` exits non-zero when there is at least one finding (for CI).

Usage:
    python scripts/wiki_lint.py --dir memory
    python scripts/wiki_lint.py --store operational --check
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from _wiki_common import REPO_DIR, extract_wikilinks, iter_notes, load_stores

_MDLINK_RE = re.compile(r"\]\(([^)]+\.md)\)")
_REQUIRED_FIELDS = ("name", "description", "type")

# Known operational files that live in a store but are not notes. They are valid
# link targets but are not themselves linted (no required frontmatter, their body
# links aren't checked, and they can't be orphans).
NON_NOTE_NAMES = {"CONVENTIONS.md", "glossary.md", "learning-log.md", "readiness.md"}


def _is_note(path: Path, fm: dict[str, object]) -> bool:
    """A .md is a note iff it has a frontmatter block AND isn't a known operational file."""
    return bool(fm) and path.name not in NON_NOTE_NAMES


def _memory_referenced(dir_path: Path, recursive: bool) -> set[Path]:
    """Resolved paths of notes linked from any in-scope MEMORY.md."""
    refs: set[Path] = set()
    globber = dir_path.rglob("MEMORY.md") if recursive else dir_path.glob("MEMORY.md")
    for idx in globber:
        for m in _MDLINK_RE.finditer(idx.read_text(encoding="utf-8")):
            refs.add((idx.parent / m.group(1)).resolve())
    return refs


def lint(dir_path: Path, *, recursive: bool = True) -> list[str]:
    entries = list(iter_notes(dir_path, recursive=recursive))
    # Non-notes remain valid LINK TARGETS, so build the resolution maps from ALL
    # files; a note linking [[glossary]] must not newly dangle.
    stem_to_path = {p.stem: p for p, _, _ in entries}
    name_to_path = {str(fm["name"]): p for p, fm, _ in entries if fm.get("name")}
    inbound: dict[Path, int] = {p: 0 for p, fm, _ in entries if _is_note(p, fm)}

    findings: list[str] = []
    for p, fm, body in entries:
        if not _is_note(p, fm):
            continue  # operational files aren't linted (fields or their body links)
        for field in _REQUIRED_FIELDS:
            if not fm.get(field):
                findings.append(f"{p}: missing frontmatter field '{field}'")
        for target in extract_wikilinks(body):
            tp = name_to_path.get(target) or stem_to_path.get(target)
            if tp is None:
                findings.append(f"{p}: dangling link [[{target}]]")
            elif tp != p and tp in inbound:
                inbound[tp] += 1

    referenced = _memory_referenced(dir_path, recursive)
    for p, fm, _ in entries:
        if not _is_note(p, fm):
            continue  # only notes can be orphans
        if inbound.get(p, 0) == 0 and p.resolve() not in referenced:
            findings.append(f"{p}: orphan")
    return findings


def _resolve_dir(args: argparse.Namespace) -> Path | None:
    if args.dir:
        return (REPO_DIR / args.dir).resolve()
    store = load_stores().get(args.store)
    path = store.get("path") if store else None
    return (REPO_DIR / path).resolve() if path else None


def main() -> int:
    ap = argparse.ArgumentParser(description="Lint a markdown knowledge store.")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dir", help="folder (relative to repo root) to lint")
    g.add_argument("--store", help="store name from stores.json")
    ap.add_argument("--check", action="store_true", help="exit 1 if any finding")
    ap.add_argument("--no-recursive", action="store_true", help="lint only the top folder")
    args = ap.parse_args()

    dir_path = _resolve_dir(args)
    if dir_path is None or not dir_path.is_dir():
        print(f"error: could not resolve a directory (dir={args.dir!r} store={args.store!r})")
        return 1

    findings = lint(dir_path, recursive=not args.no_recursive)
    for f in findings:
        print(f)
    print(f"{len(findings)} finding(s)")
    return 1 if (args.check and findings) else 0


if __name__ == "__main__":
    raise SystemExit(main())
