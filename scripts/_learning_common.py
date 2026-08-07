"""Shared helpers for the learning-loop scripts.

The learning loop promotes vetted "nominations" into the synced repo `memory/`
tree with provenance discipline and contradiction resolution — the mechanical
committer, analogous to how `mark_adopted.py` commits an adopt run.

  memory/<target>            promoted note (YAML frontmatter + body + provenance)
  memory/learning-log.md     tracked ledger (<=150 lines) — the dedup source

The ledger is keyed by a 12-hex content hash of the note body so a nomination
that has already been promoted is skipped, across machines, without re-writing
the note.

Contradiction resolution — when a nomination targets an existing note, the
higher-priority source wins; ties break toward the more recent date:

    user override  >  empirical  >  agent inference
"""

from __future__ import annotations

import hashlib
from pathlib import Path

# ``sha8`` hashes a *file* (adopt flow) and is out of scope to rename here; it is
# re-exported only for callers that already depend on it. New learning-loop code
# uses ``content_hash12`` below, whose name reflects the 12 hex chars it returns.
from _adopt_common import sha8, MAX_LEDGER_LINES  # noqa: F401  (re-exported)

REPO_DIR = Path(__file__).resolve().parent.parent
LEARNING_LEDGER = REPO_DIR / "memory" / "learning-log.md"

# Source-of-truth precedence for contradiction resolution. Higher wins.
PRIORITY = {"user override": 3, "empirical": 2, "agent inference": 1}
VALID_SOURCES = set(PRIORITY)


def content_hash12(s: str) -> str:
    """Stable 12-hex content hash for a string (e.g. a note body).

    The first 12 hex chars of SHA-256 — enough to dedup note bodies while
    keeping the ledger line short.
    """
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:12]


def priority(source: str) -> int:
    """Precedence rank of a source; 0 for anything unrecognised."""
    return PRIORITY.get(source, 0)


def parse_ledger(path: Path = LEARNING_LEDGER) -> dict[str, tuple[str, str]]:
    """Return {hash12: (date, target)} for every recorded promotion.

    Line format: ``- <date> | <target> | <hash12> | promoted: <name>``
    """
    seen: dict[str, tuple[str, str]] = {}
    if not path.exists():
        return seen
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line.startswith("- "):
            continue
        parts = [p.strip() for p in line[2:].split("|")]
        if len(parts) < 4:
            continue
        date, target, h = parts[0], parts[1], parts[2]
        seen[h] = (date, target)
    return seen
