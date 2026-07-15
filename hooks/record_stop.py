#!/usr/bin/env python3
"""Deterministic Claude Code Stop-hook recorder.

Fires when a turn ends. Appends one JSONL line describing the turn to a
machine-local learning trail, then exits 0 — always, fast, and silently. It
never calls a model and must never break a session: the whole body is wrapped
so that empty stdin, a missing git, or an unwritable path all still exit 0.

The trail lives under `<config>/learning-trail/<repo_key>.jsonl` where
`<config>` is `$CLAUDE_CONFIG_DIR` or `~/.claude`. It is deliberately
machine-local and never synced — it is raw, unreviewed session exhaust that a
later harvest step distils into durable memory.

The hot path is a single O_APPEND write of one line, which is atomic for small
lines even when several windows/worktrees on the same repo (and overlapping
`async` hooks) fire at once. Pruning is decoupled from the append: it happens
only opportunistically, when the file grows past a threshold, via an atomic
temp-file rewrite that can never fail the hook.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PREVIEW_MAX = 500
RETENTION_DAYS = 14
GIT_TIMEOUT = 5  # seconds; a hung git degrades to the fallback, never blocks.

# Prune only when the trail grows past this many bytes. Keeps the append path
# O(1) on every turn and reserves the read-modify-write cost for the rare case
# where the file has actually accumulated. Overridable in tests.
PRUNE_SIZE_THRESHOLD = 1_000_000

ABSOLUTE_MAX_RECORDS = 10_000  # backstop: never keep more than this many records, even un-harvested (bounds a never-harvested trail). Overridable in tests.

# Secret shapes that must never be written to the trail. A hit on ANY of these
# blanks the whole preview rather than trying to surgically mask — cheaper and
# safer than partial redaction.
SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),               # OpenAI-style hyphen keys
    re.compile(r"(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{10,}"),  # Stripe/underscore keys
    re.compile(r"gh[oprsu]_[A-Za-z0-9]{20,}"),          # GitHub gho_/ghp_/ghr_/ghs_/ghu_
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),        # GitHub fine-grained PATs
    re.compile(r"AKIA[0-9A-Z]{16}"),                    # AWS access key IDs
    re.compile(r"AIza[0-9A-Za-z_-]{20,}"),              # Google API keys
    re.compile(r"npm_[A-Za-z0-9]{20,}"),                # npm tokens
    re.compile(r"xox[baprscd]-[A-Za-z0-9-]{10,}"),      # Slack tokens
    re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"),  # JWTs
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),  # PEM private key blocks
    re.compile(r"https?://[^/\s:@]+:[^/\s:@]+@"),       # URL-embedded credentials
)


def config_dir() -> Path:
    """Base config dir: $CLAUDE_CONFIG_DIR if set, else ~/.claude."""
    env = os.environ.get("CLAUDE_CONFIG_DIR")
    return Path(env) if env else Path.home() / ".claude"


def trail_dir() -> Path:
    """Machine-local learning-trail directory, created if absent."""
    d = config_dir() / "learning-trail"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _git(cwd: str, *args: str) -> str:
    """Run a git command in `cwd`; return stripped stdout or "" on any failure.

    A `timeout` bounds hung invocations; `TimeoutExpired` is a `SubprocessError`,
    so it degrades to "" via the existing handler instead of leaking a process.
    """
    try:
        out = subprocess.run(
            ["git", "-C", cwd, *args],
            capture_output=True,
            text=True,
            check=True,
            timeout=GIT_TIMEOUT,
        )
        return out.stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return ""


def git_root(cwd: str) -> str:
    """Toplevel of the git repo containing `cwd`; fall back to `cwd` itself."""
    return _git(cwd, "rev-parse", "--show-toplevel") or cwd


def git_branch(cwd: str) -> str:
    """Current branch name, or "" when unavailable (detached, no repo, no git).

    Uses `git branch --show-current` rather than `rev-parse --abbrev-ref HEAD`:
    the latter exits non-zero on an unborn branch (fresh `git init`, no commits),
    which — masked by `git_root`'s `or cwd` fallback — produced an empty branch
    while the root still resolved. `--show-current` reports the branch on both
    normal and unborn branches and returns "" only on a genuine detached HEAD.
    """
    return _git(cwd, "branch", "--show-current")


def repo_key(git_root_path: str) -> str:
    """Collision-resistant slug for the trail filename.

    A pure `[^0-9A-Za-z] -> "-"` slug maps distinct roots (e.g. `foo/bar` and
    `foo-bar`) onto the same file, cross-contaminating their trails. Appending a
    short hash of the original path keeps filenames readable while making
    collisions effectively impossible.
    """
    slug = re.sub(r"[^0-9A-Za-z]", "-", git_root_path)
    digest = hashlib.sha256(git_root_path.encode("utf-8")).hexdigest()[:8]
    return f"{slug[:80]}-{digest}"


def redact(text: str) -> str:
    """Blank the whole preview if any secret pattern matches, else return as-is."""
    for pat in SECRET_PATTERNS:
        if pat.search(text):
            return "[redacted]"
    return text


def message_preview(message: str) -> str:
    """Collapse to one line, redact secrets, then truncate to PREVIEW_MAX chars.

    Redaction runs on the full collapsed text *before* truncation so that a
    secret straddling the PREVIEW_MAX boundary — whose identifying prefix would
    otherwise be severed by an earlier truncation — is still caught.
    """
    collapsed = " ".join(str(message).split())
    return redact(collapsed)[:PREVIEW_MAX]


def build_record(event: dict, *, now: datetime | None = None) -> dict:
    """Turn a Stop event into the JSONL record. Absent fields degrade to empty."""
    cwd = str(event.get("cwd") or os.getcwd())
    root = git_root(cwd)
    ts = (now or datetime.now(timezone.utc)).isoformat()
    return {
        "ts": ts,
        "session_id": event.get("session_id", ""),
        "git_root": root,
        "git_branch": git_branch(cwd),
        "prompt_id": event.get("prompt_id"),
        "message_preview": message_preview(event.get("last_assistant_message", "")),
    }


def _within_retention(ts: str, cutoff: datetime) -> bool:
    """True if `ts` parses to a time at/after `cutoff`.

    An unparseable `ts` is treated as prunable (returns False) so that corrupted
    lines age out on the next prune rather than persisting forever.
    """
    try:
        parsed = datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed >= cutoff


def watermark_path(trail_path: Path) -> Path:
    """The harvest-watermark file paired with a trail (``<repo_key>.watermark``)."""
    return trail_path.with_suffix(".watermark")


def read_watermark(path: Path) -> datetime | None:
    """Last-harvest timestamp for a trail, or None if never harvested / unreadable."""
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except (ValueError, TypeError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def write_watermark(path: Path, ts: datetime) -> None:
    """Atomically stamp the harvest watermark (temp write + ``os.replace``)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # Per-process temp name so two racing writers never collide on a fixed name;
    # os.replace keeps the swap atomic.
    tmp = path.parent / (path.name + f".{os.getpid()}.tmp")
    tmp.write_text(ts.isoformat(), encoding="utf-8")
    os.replace(tmp, path)


def _is_unharvested(ts: str, watermark: datetime | None) -> bool:
    """True if a record is not yet harvested and must be protected from pruning.

    Un-harvested = ``ts`` strictly newer than the watermark. With no watermark
    (None) nothing has been harvested, so every parseable record is protected.
    An unparseable ``ts`` is never protected (returns False) so corrupt lines age out.
    """
    try:
        parsed = datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    if watermark is None:
        return True
    return parsed > watermark


def prune_lines(
    lines: list[str],
    *,
    now: datetime | None = None,
    watermark: datetime | None = None,
) -> list[str]:
    """Keep JSONL lines that are within retention OR not yet harvested.

    A record is dropped only when it is BOTH older than RETENTION_DAYS AND at or
    below the harvest ``watermark`` (already harvested). Un-harvested records —
    newer than the watermark, or *all* parseable records when no harvest has ever
    run (``watermark is None``) — are kept regardless of age, but only up to the
    ABSOLUTE_MAX_RECORDS ceiling: when the kept set exceeds that count only the
    most-recent ABSOLUTE_MAX_RECORDS entries survive, so a never-harvested trail
    still cannot grow without bound.

    Malformed lines and records with an unparseable ``ts`` are always dropped —
    protection is keyed on the parseable ``ts``, so a record whose ``ts`` cannot
    be parsed is dropped even if it would otherwise count as un-harvested.
    ``build_record`` always writes a valid ISO8601 ``ts``, so this only affects
    externally-corrupted lines.
    """
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=RETENTION_DAYS)
    kept: list[str] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        ts = str(rec.get("ts", ""))
        if _within_retention(ts, cutoff) or _is_unharvested(ts, watermark):
            kept.append(line)
    # Absolute ceiling: append order is chronological, so the tail is newest.
    if len(kept) > ABSOLUTE_MAX_RECORDS:
        kept = kept[-ABSOLUTE_MAX_RECORDS:]
    return kept


def _maybe_prune(path: Path, *, now: datetime | None = None) -> None:
    """Opportunistically prune `path` when it grows past PRUNE_SIZE_THRESHOLD.

    Harvest-aware: records newer than the trail's watermark are never dropped.
    Wrapped whole so a race or I/O error can never fail the hook.
    """
    try:
        if path.stat().st_size <= PRUNE_SIZE_THRESHOLD:
            return
        existing = path.read_text(encoding="utf-8").splitlines()
        watermark = read_watermark(watermark_path(path))
        kept = prune_lines(existing, now=now, watermark=watermark)
        # Skip the rewrite when nothing was dropped. `kept` is always an
        # order-preserving subsequence of the input's non-empty lines, so an
        # equal length means it is identical — no need to touch the file.
        existing_nonempty = [s for s in (ln.strip() for ln in existing) if s]
        if len(kept) == len(existing_nonempty):
            return
        tmp = path.parent / (path.name + ".tmp")
        tmp.write_text(("\n".join(kept) + "\n") if kept else "", encoding="utf-8")
        os.replace(tmp, path)
    except Exception:
        return


def append_record(path: Path, record: dict, *, now: datetime | None = None) -> None:
    """Atomically append `record` as one JSONL line, then prune if oversized.

    The append is a single O_APPEND write — atomic for small lines, so
    overlapping hooks on the same per-repo trail never tear or lose each other's
    records. Pruning is decoupled onto the cold path via `_maybe_prune`.
    """
    line = json.dumps(record, ensure_ascii=False) + "\n"
    with open(path, "a", encoding="utf-8") as f:
        f.write(line)
    _maybe_prune(path, now=now)


def record_event(event: dict, *, now: datetime | None = None) -> Path:
    """End-to-end: build the record and append it to the repo's trail file."""
    record = build_record(event, now=now)
    path = trail_dir() / f"{repo_key(record['git_root'])}.jsonl"
    append_record(path, record, now=now)
    return path


def main() -> int:
    """Read the Stop event from stdin and record it. Never fails a turn."""
    try:
        raw = sys.stdin.read()
        event = json.loads(raw)
        if not isinstance(event, dict):
            return 0
        record_event(event)
    except Exception:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
