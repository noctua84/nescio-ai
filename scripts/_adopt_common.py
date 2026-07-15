"""Shared helpers for the config-adoption scripts.

Two-stage flow:
  eval/adopt/<ts>/    inbox   — discovered, needs evaluation (gitignored)
  eval/adopted/<ts>/  archive — processed runs (gitignored)
  memory/adoption-log.md       tracked ledger (<=150 lines) — the dedup source

The ledger is keyed by a short content hash so scans skip what's already been
processed, across machines, without tracking the raw eval/ trees.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
EVAL = REPO_DIR / "eval"
ADOPT = EVAL / "adopt"
ADOPTED = EVAL / "adopted"
LEDGER = REPO_DIR / "memory" / "adoption-log.md"

MAX_LEDGER_LINES = 150

# Statuses that mean "done — don't re-evaluate". `pending` is deliberately NOT
# terminal: pending items re-surface into eval/adopt/ on the next scan (also on
# a fresh machine) until they're marked with a terminal status.
TERMINAL = {"integrated", "no-change", "dropped", "adopted"}


def sha8(path: Path) -> str:
    """Stable short content hash for a file or directory tree."""
    h = hashlib.sha256()
    if path.is_dir():
        for f in sorted(p for p in path.rglob("*") if p.is_file()):
            h.update(str(f.relative_to(path)).encode())
            h.update(f.read_bytes())
    else:
        h.update(path.read_bytes())
    return h.hexdigest()[:12]


def parse_ledger() -> dict[str, tuple[str, str]]:
    """Return {sha8: (date, status)} for every recorded entry."""
    seen: dict[str, tuple[str, str]] = {}
    if not LEDGER.exists():
        return seen
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line.startswith("- "):
            continue
        parts = [p.strip() for p in line[2:].split("|")]
        if len(parts) < 4:
            continue
        date, _source, h, rest = parts[0], parts[1], parts[2], parts[3]
        status = rest.split(":", 1)[0].strip().lower()
        seen[h] = (date, status)
    return seen


def is_done(sha: str, ledger: dict[str, tuple[str, str]]) -> bool:
    entry = ledger.get(sha)
    return bool(entry) and entry[1] in TERMINAL
