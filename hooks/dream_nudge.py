#!/usr/bin/env python3
"""The "dream due" reminder, run from the SessionStart hook.

`scripts/dream.py` reviews past session transcripts and stamps
``<config>/dreams/<repo_key>/last-dream.json`` (``{"since": <ISO UTC>}``) when
it writes a proposal. Nothing calls it on a schedule (see
`docs/design/dreaming.md`, section 3), so this module prints one line when a
dream is due for *this repo*:

* **Dreamt before:** the watermark is at least ``CLAUDE_DREAM_NUDGE_DAYS`` old
  (default 7) **and** at least ``CLAUDE_DREAM_NUDGE_SESSIONS`` sessions
  (default 10) have ended since it.
* **Never dreamt** (no watermark, or one that does not parse): at least
  ``CLAUDE_DREAM_NUDGE_FIRST_SESSIONS`` sessions (default 30) ended in the last
  ``FIRST_WINDOW_DAYS`` (14). Silence would leave the feature undiscoverable;
  the ordinary bar would nag everyone who has not opted in. The higher bar
  speaks up only where a first dream has plenty to read, and the window is the
  one `dream.py` itself reads on a first run (its ``DEFAULT_DAYS``), so the
  count never promises sessions the dream would not look at.

``CLAUDE_DREAM_NUDGE=0`` turns the reminder off. A non-integer or negative
threshold falls back to its default, as ``CLAUDE_HARVEST_NUDGE_THRESHOLD`` does.

**Counting is cheap by construction.** A "session that ended" is a top-level
transcript ``*.jsonl`` in one of this repo's transcript directories (the main
checkout's slug and its ``--claude-worktrees-`` children — the same set
`dream.transcript_dirs` reads) whose mtime is after the baseline. That is one
directory listing plus one ``stat`` per transcript: no transcript is opened,
and the scan stops as soon as the threshold is met. The learning trail was the
alternative and was rejected: the canonical trail undercounts worktree
sessions (see `harvest_nudge.nudge`), and mtimes are exactly the selection
`dream.select_sessions` makes, so the nudge and the dream agree on what is
waiting. The current session's own transcript is excluded.

**Repo identity mirrors `dream.py`, not the trail.** `dream.main_root` returns
a ``Path.resolve()``-d root, so on Windows its ``repo_key`` hashes a
backslashed path while `record_stop.git_roots` returns git's forward-slashed
one — the same repository, two different keys. This module resolves the root
the way `dream.py` does so it reads the watermark `dream.py` writes;
`tests/test_dream_nudge.py` pins the two together. Like `memory_trigger_nudge`,
it never imports `scripts/` (the hook must not depend on it being importable);
the small pieces it needs are duplicated and pinned by tests instead.

`harvest_nudge.main()` calls `dream_nudge()` and prints its result *in
addition* to the other reminders — a dream being due is a separate subject.
Every failure degrades to '' rather than raising.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import record_stop as rs  # noqa: E402

# Duplicated from harvest_nudge.NUDGE_SOURCES, not imported: harvest_nudge
# imports this module for main(), so importing back would be a cycle.
NUDGE_SOURCES = {"startup", "resume"}

DEFAULT_DAYS = 7
DEFAULT_SESSIONS = 10
DEFAULT_FIRST_SESSIONS = 30
# Must equal dream.DEFAULT_DAYS (the window a first dream reads); pinned by test.
FIRST_WINDOW_DAYS = 14
# Must equal dream.STATE_NAME; pinned by test.
STATE_NAME = "last-dream.json"
WORKTREE_INFIX = "--claude-worktrees-"


def _env_int(name: str, default: int) -> int:
    """Non-negative int from the environment, or ``default`` on anything else."""
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError:
        return default
    return value if value >= 0 else default


def _enabled() -> bool:
    return os.environ.get("CLAUDE_DREAM_NUDGE", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def _slug(path: str) -> str:
    """Claude Code's transcript-directory name for a path (= dream.slug)."""
    return re.sub(r"[^0-9A-Za-z]", "-", path)


def dream_root(repo_root: str) -> str:
    """The repository root spelled the way `dream.main_root` spells it."""
    try:
        return str(Path(repo_root).resolve())
    except (OSError, RuntimeError, ValueError):
        return str(Path(repo_root))


def read_last_dream(state: Path) -> datetime | None:
    """The watermark `dream.py` stamped, or None if absent or unparseable."""
    try:
        text = json.loads(state.read_text(encoding="utf-8"))["since"]
        dt = datetime.fromisoformat(str(text).strip().replace("Z", "+00:00"))
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _transcript_dirs(projects: Path, root: str) -> list[Path]:
    """This repo's transcript dirs (= dream.transcript_dirs)."""
    fold = str.casefold if os.name == "nt" else str
    base = fold(_slug(root))
    try:
        entries = list(projects.iterdir())
    except OSError:
        return []
    out = []
    for d in entries:
        name = fold(d.name)
        if (name == base or name.startswith(base + WORKTREE_INFIX)) and d.is_dir():
            out.append(d)
    return out


def count_sessions_since(
    dirs: list[Path], since: datetime, *, limit: int, exclude: str = ""
) -> int:
    """Transcripts in ``dirs`` modified after ``since``, stopping at ``limit``.

    ``exclude`` is the current session's transcript path, which is not a
    session that *ended*. Unreadable entries are skipped, never raised.
    """
    cutoff = since.timestamp()
    skip = os.path.normcase(os.path.abspath(exclude)) if exclude else ""
    n = 0
    for d in dirs:
        try:
            files = list(d.glob("*.jsonl"))
        except OSError:
            continue
        for f in files:
            if skip and os.path.normcase(os.path.abspath(f)) == skip:
                continue
            try:
                if f.stat().st_mtime <= cutoff:
                    continue
            except OSError:
                continue
            n += 1
            if n >= limit:
                return n
    return n


def dream_message(
    repo_root: str, *, now: datetime | None = None, current_transcript: str = ""
) -> str:
    """One reminder line if a dream is due for ``repo_root``, else ''."""
    try:
        if not _enabled():
            return ""
        now = now or datetime.now(timezone.utc)
        root = dream_root(repo_root)
        config = rs.config_dir()
        last = read_last_dream(config / "dreams" / rs.repo_key(root) / STATE_NAME)
        if last is None:
            since = now - timedelta(days=FIRST_WINDOW_DAYS)
            need = _env_int("CLAUDE_DREAM_NUDGE_FIRST_SESSIONS", DEFAULT_FIRST_SESSIONS)
        else:
            days = _env_int("CLAUDE_DREAM_NUDGE_DAYS", DEFAULT_DAYS)
            if now - last < timedelta(days=days):
                return ""
            since = last
            need = _env_int("CLAUDE_DREAM_NUDGE_SESSIONS", DEFAULT_SESSIONS)
        need = max(need, 1)  # zero would fire on an empty repo
        dirs = _transcript_dirs(config / "projects", root)
        if not dirs:
            return ""
        count = count_sessions_since(
            dirs, since, limit=need, exclude=current_transcript
        )
        if count < need:
            return ""
        if last is None:
            return (
                f"{count}+ sessions ended in this repo in the last "
                f"{FIRST_WINDOW_DAYS} days and /dream has never run here. It "
                f"reviews them for recurring mistakes and proposes memory notes "
                f"(silence with CLAUDE_DREAM_NUDGE=0)."
            )
        age = (now - last).days
        return (
            f"A dream is due: {count}+ sessions have ended since the last /dream "
            f"for this repo, {age} days ago. Consider running /dream to review "
            f"them for recurring mistakes."
        )
    except Exception:
        return ""


def dream_nudge(event: dict) -> str:
    """Return the dream-due reminder for this session, or '' to stay silent.

    Gated by the same ``NUDGE_SOURCES`` check as the other reminders, and
    re-resolves the repo root independently, matching `trigger_nudge`.
    """
    try:
        if event.get("source") not in NUDGE_SOURCES or not _enabled():
            return ""  # checked before git_roots: disabled costs no subprocess
        cwd = str(event.get("cwd") or os.getcwd())
        root = rs.git_roots(cwd)[1]
        return dream_message(
            root, current_transcript=str(event.get("transcript_path") or "")
        )
    except Exception:
        return ""
