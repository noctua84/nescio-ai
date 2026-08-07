#!/usr/bin/env python3
"""Regenerate a folder's MEMORY.md index from its notes' frontmatter.

Produces one `- [<name>](<file.md>) — <description>` line per note directly in
the target folder (non-recursive), sorted by filename. `--check` exits non-zero
when the on-disk index differs from the regenerated one (for CI), writing
nothing.

Link text is the note's frontmatter `name`; a note wanting a different index
label should set `name` accordingly.

Usage:
    python scripts/wiki_index.py --dir memory/concepts
    python scripts/wiki_index.py --store operational --check
"""

from __future__ import annotations

import argparse
from pathlib import Path

from _wiki_common import REPO_DIR, iter_notes, load_stores


def build_index(dir_path: Path) -> str:
    lines: list[str] = []
    for p, fm, _ in iter_notes(dir_path, recursive=False):
        name = str(fm.get("name") or p.stem)
        desc = str(fm.get("description") or "")
        lines.append(f"- [{name}]({p.name}) — {desc}" if desc else f"- [{name}]({p.name})")
    return "\n".join(lines) + ("\n" if lines else "")


def regenerate(dir_path: Path, *, check: bool = False) -> tuple[int, list[str]]:
    index_path = dir_path / "MEMORY.md"
    new = build_index(dir_path)
    old = index_path.read_text(encoding="utf-8") if index_path.exists() else ""
    if new == old:
        return 0, [f"up-to-date: {index_path}"]
    if check:
        return 1, [f"stale: {index_path} (run without --check to regenerate)"]
    index_path.write_text(new, encoding="utf-8")
    return 0, [f"wrote: {index_path}"]


def _resolve_dir(args: argparse.Namespace) -> Path | None:
    if args.dir:
        return (REPO_DIR / args.dir).resolve()
    stores = load_stores()
    store = stores.get(args.store)
    if not store:
        return None
    return (REPO_DIR / store["path"]).resolve()


def main() -> int:
    ap = argparse.ArgumentParser(description="Regenerate a folder's MEMORY.md index.")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dir", help="folder (relative to repo root) to index")
    g.add_argument("--store", help="store name from stores.json")
    ap.add_argument("--check", action="store_true", help="exit 1 if stale; write nothing")
    args = ap.parse_args()

    dir_path = _resolve_dir(args)
    if dir_path is None or not dir_path.is_dir():
        print(f"error: could not resolve a directory (dir={args.dir!r} store={args.store!r})")
        return 1
    rc, summary = regenerate(dir_path, check=args.check)
    for line in summary:
        print(line)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
