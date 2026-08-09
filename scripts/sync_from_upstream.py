#!/usr/bin/env python3
"""Overlay-sync framework files from an upstream Nescio checkout into this instance.

A downstream instance (your private fork) runs this to update its *framework*
from the canonical public repo. It copies a fixed allowlist of framework paths
from the upstream checkout into this repo, mirroring additions, updates, and
deletions **within those paths only**. It NEVER touches your memory records or
anything outside the allowlist — `memory/`, `docs/`, notes, and instance config
are left exactly as they are.

Why copy instead of `git pull`: the public and private repos have unrelated git
histories (the public repo was extracted as a fresh scaffold), so a merge is not
meaningful. This overlay keeps each instance's own history intact.

Usage:
    python scripts/sync_from_upstream.py --upstream /path/to/nescio-ai            # dry run
    python scripts/sync_from_upstream.py --upstream /path/to/nescio-ai --apply    # perform

After --apply, if your instance uses the philosopher theme, re-render it:
    python scripts/apply_theme.py philosophers
"""

from __future__ import annotations

import argparse
import difflib
import filecmp
import shutil
import sys
from pathlib import Path

# Framework paths a downstream instance syncs FROM upstream. Everything NOT listed
# here is instance-owned and never touched — notably `memory/` (your records),
# `docs/` (your design bundle), `README.md`, `CLAUDE.md`, `settings.json`,
# `.github/`, `.gitignore`, and any private trees.
FRAMEWORK_PATHS = [
    "agents",
    "skills",
    "commands",
    "hooks",
    "scripts",
    "github-action",
    "tests",
    "install.py",
    "pyproject.toml",
    "uv.lock",
    "CONTRIBUTING.md",
    "LICENSE",
    "stores.example.json",
    "serena.mcp.example.json",
    "CLAUDE.local.md.example",
    "scrub-terms.local.example",
]


def _is_nescio_checkout(root: Path) -> bool:
    """A directory that looks like a Nescio instance/framework checkout."""
    return (root / "install.py").is_file() and (root / "agents").is_dir()


def _iter_files(base: Path):
    """Yield base-relative paths of real files under `base` (skips caches)."""
    if not base.exists():
        return
    for p in sorted(base.rglob("*")):
        if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc":
            yield p.relative_to(base)


def plan_sync(upstream: Path, dest: Path, paths=FRAMEWORK_PATHS):
    """Compute (added, updated, deleted) dest-relative file paths, no writes.

    Only the allowlisted `paths` are considered; anything else in `dest` is
    invisible to this function and will never be reported or changed.
    """
    added: list[str] = []
    updated: list[str] = []
    deleted: list[str] = []
    for entry in paths:
        up = upstream / entry
        dst = dest / entry
        if up.is_dir():
            up_files = set(_iter_files(up))
            dst_files = set(_iter_files(dst))
            for rel in sorted(up_files):
                target = dst / rel
                rel_str = str(Path(entry) / rel)
                if not target.exists():
                    added.append(rel_str)
                elif not filecmp.cmp(up / rel, target, shallow=False):
                    updated.append(rel_str)
            for rel in sorted(dst_files - up_files):
                deleted.append(str(Path(entry) / rel))
        elif up.is_file():
            if not dst.exists():
                added.append(entry)
            elif not filecmp.cmp(up, dst, shallow=False):
                updated.append(entry)
        else:
            # Framework path absent upstream — mirror the removal downstream.
            if dst.is_dir():
                for rel in sorted(_iter_files(dst)):
                    deleted.append(str(Path(entry) / rel))
            elif dst.exists():
                deleted.append(entry)
    return added, updated, deleted


def apply_sync(upstream: Path, dest: Path, paths=FRAMEWORK_PATHS):
    """Perform the sync computed by :func:`plan_sync`; return the same triple."""
    added, updated, deleted = plan_sync(upstream, dest, paths)
    for rel in deleted:
        (dest / rel).unlink()
    for rel in added + updated:
        src = upstream / rel
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)
    return added, updated, deleted


def _read_text(path: Path):
    """Return the file's UTF-8 text as a list of lines, or None if it's binary."""
    try:
        return path.read_text(encoding="utf-8").splitlines(keepends=True)
    except (UnicodeDecodeError, ValueError):
        return None


def render_diff(upstream: Path, dest: Path, added, updated, deleted) -> str:
    """Return a human-readable content diff for a sync plan (no printing).

    For each UPDATED file, a unified diff of dest (current) vs upstream (new);
    binary files get a one-line size note instead. ADDED files are marked
    NET-NEW (with a content preview) and DELETED files get a one-line note.
    Output is deterministic (paths sorted within each section).
    """
    lines: list[str] = []

    for rel in sorted(updated):
        up = upstream / rel
        dst = dest / rel
        posix = Path(rel).as_posix()
        old = _read_text(dst)
        new = _read_text(up)
        if old is None or new is None:
            old_size = dst.stat().st_size if dst.exists() else 0
            new_size = up.stat().st_size if up.exists() else 0
            lines.append(f"~ UPDATED  {posix}")
            lines.append(f"  (binary file, {old_size} bytes -> {new_size} bytes)")
            lines.append("")
            continue
        diff = difflib.unified_diff(
            old, new,
            fromfile=f"a/{posix} (current)",
            tofile=f"b/{posix} (upstream)",
        )
        text = "".join(diff)
        if not text.endswith("\n"):
            text += "\n"
        lines.append(text.rstrip("\n"))
        lines.append("")

    for rel in sorted(added):
        up = upstream / rel
        posix = Path(rel).as_posix()
        lines.append(f"+++ ADDED  {posix}  (NET-NEW)")
        content = _read_text(up)
        if content is None:
            size = up.stat().st_size if up.exists() else 0
            lines.append(f"  (binary file, {size} bytes)")
        else:
            preview = content[:20]
            for pline in preview:
                lines.append(f"  +{pline.rstrip(chr(10))}")
            if len(content) > 20:
                lines.append(f"  ... ({len(content) - 20} more line(s))")
        lines.append("")

    for rel in sorted(deleted):
        posix = Path(rel).as_posix()
        lines.append(f"--- DELETED  {posix}")

    if deleted:
        lines.append("")

    if not (added or updated or deleted):
        return ""

    lines.append(
        f"net-new: {len(added)} added file(s), {len(updated)} updated, "
        f"{len(deleted)} deleted"
    )
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--upstream", required=True, type=Path,
                    help="path to an upstream Nescio checkout (the canonical framework)")
    ap.add_argument("--dest", type=Path, default=None,
                    help="downstream instance root (default: current directory)")
    ap.add_argument("--apply", action="store_true",
                    help="perform the sync (default: dry run, prints the plan only)")
    ap.add_argument("--diff", action="store_true",
                    help="after the summary, show per-file content diffs so you can see "
                         "exactly WHAT would change (works with dry run; no --apply needed)")
    args = ap.parse_args(argv)

    upstream = args.upstream.resolve()
    dest = (args.dest or Path.cwd()).resolve()

    if not _is_nescio_checkout(upstream):
        print(f"error: --upstream {upstream} is not a Nescio checkout "
              "(need install.py + agents/)", file=sys.stderr)
        return 2
    if not _is_nescio_checkout(dest):
        print(f"error: --dest {dest} is not a Nescio instance "
              "(need install.py + agents/)", file=sys.stderr)
        return 2
    if upstream == dest:
        print("error: --upstream and --dest are the same directory", file=sys.stderr)
        return 2

    # Compute the plan first so a --diff preview can read dest files *before*
    # --apply overwrites them (renders "what would/did change" either way).
    added, updated, deleted = plan_sync(upstream, dest)
    diff_text = render_diff(upstream, dest, added, updated, deleted) if args.diff else ""
    if args.apply:
        apply_sync(upstream, dest)
    total = len(added) + len(updated) + len(deleted)

    if total == 0:
        print("framework already in sync — nothing to do.")
        return 0

    verb = "synced" if args.apply else "would change"
    print(f"{verb}: {len(added)} added, {len(updated)} updated, {len(deleted)} deleted")
    for label, items in (("+ add   ", added), ("~ update", updated), ("- delete", deleted)):
        for it in items:
            print(f"  {label}  {it}")

    if diff_text:
        print()
        print(diff_text, end="")

    if args.apply:
        print("\nmemory/ and all non-framework paths were left untouched. "
              "If your instance is themed: python scripts/apply_theme.py philosophers")
    else:
        print("\n(dry run — re-run with --apply to perform)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
