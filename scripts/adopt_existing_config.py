#!/usr/bin/env python3
"""Discover pre-existing Claude config on this machine and stage it for review.

Stage 1 of the two-stage adoption flow: copies known Claude config sources into
a timestamped folder under `eval/adopt/` (the inbox) for inspection. Items whose
content hash is already recorded with a terminal status in
`memory/adoption-log.md` are skipped, so nothing is evaluated twice. Once you've
reviewed and integrated a run, promote it with `scripts/mark_adopted.py`.

Nothing is modified in place — this is copy-and-catalogue. `eval/` is gitignored,
so staged material stays machine-local; the tracked ledger is the dedup source.
Sources already symlinked into this repo are skipped (adopted already).
"""

from __future__ import annotations

import json
import platform
import shutil
from datetime import datetime
from pathlib import Path

from _adopt_common import ADOPT, is_done, parse_ledger, sha8

HOME = Path.home()
CLAUDE_DIR = HOME / ".claude"


def desktop_config_path() -> Path:
    system = platform.system()
    if system == "Darwin":
        return HOME / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    if system == "Windows":
        import os

        appdata = os.environ.get("APPDATA", str(HOME / "AppData" / "Roaming"))
        return Path(appdata) / "Claude" / "claude_desktop_config.json"
    return HOME / ".config" / "Claude" / "claude_desktop_config.json"


# (label, source path)
SOURCES: list[tuple[str, Path]] = [
    ("claude-code/CLAUDE.md", CLAUDE_DIR / "CLAUDE.md"),
    ("claude-code/settings.json", CLAUDE_DIR / "settings.json"),
    ("claude-code/settings.local.json", CLAUDE_DIR / "settings.local.json"),
    # ~/.claude.json is intentionally excluded: it's volatile runtime/identity
    # state (counters, caches, machineID, oauthAccount) rewritten every session,
    # so it never dedups cleanly and holds nothing repo-worthy.
    ("claude-code/agents", CLAUDE_DIR / "agents"),
    ("claude-code/commands", CLAUDE_DIR / "commands"),
    ("claude-code/skills", CLAUDE_DIR / "skills"),
    ("claude-code/memory", CLAUDE_DIR / "memory"),
    ("claude-desktop/claude_desktop_config.json", desktop_config_path()),
]


def copy_source(src: Path, dest: Path) -> int:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        shutil.copytree(src, dest, symlinks=True, dirs_exist_ok=True)
        return sum(1 for p in dest.rglob("*") if p.is_file())
    shutil.copy2(src, dest)
    return 1


def project_memory_sources() -> list[tuple[str, Path]]:
    """Prior per-project learnings from ~/.claude/projects/<slug>/memory/."""
    out: list[tuple[str, Path]] = []
    projects = CLAUDE_DIR / "projects"
    if projects.is_dir():
        for slug in sorted(projects.iterdir()):
            mem = slug / "memory"
            if mem.is_dir() and any(mem.rglob("*")):
                out.append((f"claude-code/project-memory/{slug.name}", mem))
    return out


def main() -> int:
    ledger = parse_ledger()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = ADOPT / stamp

    print(f"Machine: {platform.system()}")
    print(f"Ledger:  {len(ledger)} recorded item(s)")

    records: list[dict] = []   # staged, for sources.json + manifest
    skipped: list[str] = []    # already-done, for manifest

    for label, src in SOURCES + project_memory_sources():
        if not src.exists() or src.is_symlink():
            continue
        h = sha8(src)
        if is_done(h, ledger):
            date, status = ledger[h]
            skipped.append(f"| `{label}` | `{h}` | {status} on {date} |")
            print(f"  - skip (already {status} {date}): {src}")
            continue
        run_dir.mkdir(parents=True, exist_ok=True)
        n = copy_source(src, run_dir / label)
        pend = ledger.get(h)
        note = f"pending since {pend[0]}" if pend else "new"
        records.append({"label": label, "source": str(src), "kind": "dir" if src.is_dir() else "file", "files": n, "sha8": h, "state": note})
        print(f"  + staged {src} -> {run_dir / label}  [{note}]")

    if not records:
        print("\nNothing new to adopt — every source is already recorded terminal in the ledger.")
        return 0

    (run_dir / "sources.json").write_text(json.dumps(records, indent=2), encoding="utf-8")

    rows = "\n".join(
        f"| `{r['label']}` | `{r['source']}` | {r['kind']} | {r['files']} | `{r['sha8']}` | {r['state']} |"
        for r in records
    )
    (run_dir / "MANIFEST.md").write_text(
        f"# Adopt inbox — {stamp}\n\nMachine: {platform.system()}\n\n"
        "Staged for evaluation. `eval/` is gitignored. After integrating the\n"
        "worthwhile parts, run `scripts/mark_adopted.py " + stamp + " --status "
        "integrated --note \"...\"` to archive this run and record it in the ledger.\n\n"
        "| Staged as | Source | Kind | Size | sha8 | State |\n"
        "|-----------|--------|------|------|------|-------|\n" + rows + "\n"
        + ("\n## Skipped (already done)\n\n| Item | sha8 | Status |\n|------|------|--------|\n"
           + "\n".join(skipped) + "\n" if skipped else ""),
        encoding="utf-8",
    )

    print(f"\nStaged {len(records)} item(s) into {run_dir}")
    print(f"Skipped {len(skipped)} already-done. Review MANIFEST.md, then mark_adopted.py {stamp}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
