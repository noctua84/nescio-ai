#!/usr/bin/env python3
"""Path normalisation and repo attribution for the machine-global learning trail.

The learning-trail dir is machine-global: every repo this machine has ever run a
session in owns a `<repo_key>.jsonl` there. A harvest, by contrast, reads one
project. Anything that acts on "the trails a harvest saw" therefore needs a way
to select the current repo's trails out of that global pile — this module is that
selector, and it is *also* the home of the normalisation helpers
`compute_readiness.py` introduced (#42) and re-exports from here, so the two
tools cannot disagree about which repository a record belongs to.

## Attribution

`git_root` is the *worktree* root, so grouping on it raw yields ~86 buckets for
~10 repositories. `resolve_repo_root` normalises each record in this order:

  1. `repo_root` if present — recorded at source since #66, authoritative, but
     itself worktree-collapsed: `git_roots`' degraded branch mirrors the worktree
     toplevel into the field, and that is a degradation, not a repository.
  2. Worktree-pattern parse — a path matching `<repo>/.claude/worktrees/<name>`
     belongs to `<repo>`. Purely textual, so it works on paths that no longer
     exist on disk, which is what recovers records from deleted worktrees.
  3. Live git resolution — only for a path that still exists and matched neither
     of the above. Costs a subprocess, so callers may pass a cache.

Otherwise `git_root` is used unchanged. Separators are normalised to posix
*before* any comparison: git emits forward slashes while `pathlib` emits
backslashes on Windows, and the ~2,100 legacy records predate #66's fix at the
write site, so they carry whichever convention applied when they were written.

## Ownership

Because step 2 already maps a worktree back to the repository that owns it,
deciding whether a trail belongs to a repo is an **equality** test on normalised
posix strings — not an at-or-under path test. That distinction matters: a
worktree created outside the repo tree (`git worktree add ../feature`) is not
*under* the repo root, yet the record resolves to the repo, so equality attributes
it correctly where an at-or-under test would silently drop it.

A second, secondary route matches the repo's own canonical trail by filename.
It exists for exactly one case the record rule cannot cover: a trail with *zero*
records, which has no `git_root` to resolve. Matching is emphatically *not* done
on filename prefix — `repo_key` slugifies the path, so `...-nescio-ai` is a
literal prefix of `...-nescio-ai-docs`, and a prefix rule would pull a sibling
repository's trail into this repo's scope.

Nothing here raises: an unreadable trail, a malformed record, or a path that
cannot be resolved degrades to "does not belong" so a caller iterating the trail
dir can never be derailed by one bad entry.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))
import record_stop as rs  # noqa: E402

# The path segment that identifies a Claude Code worktree checkout. Matched on
# the posix-normalised path; the repository is everything before it.
WORKTREE_MARKER = "/.claude/worktrees/"

# How many parseable records `trail_repo_root` will read before giving up on
# attributing a trail. Generous enough that a run of rootless records at the head
# — legacy lines, a session that never resolved git — does not lose the trail,
# small enough that a corrupt multi-megabyte file is still cheap to reject.
HEAD_SCAN_RECORDS = 50


# ── path + attribution ─────────────────────────────────────────────────────

def posix_path(raw) -> str:
    """Normalise a recorded path to posix separators, without trailing slash.

    Git emits forward slashes on every platform; `pathlib` emits backslashes on
    Windows. Legacy records carry whichever convention applied when they were
    written, so every comparison and every grouping key runs through here first —
    otherwise one repository splits into two buckets.

    Deliberately *not* case-folding, on any platform. Windows paths do compare
    case-insensitively, so folding would be defensible in isolation — but this is
    the single normalisation both `_trail_scope` and `compute_readiness` use, and
    the two bucketing trails differently is the exact failure mode this module
    exists to eliminate. Case handling is therefore one decision, made here, and
    neither caller is allowed a second opinion.
    """
    s = str(raw or "").replace("\\", "/").strip()
    while len(s) > 1 and s.endswith("/"):
        s = s[:-1]
    return s


def strip_worktree(path_posix: str) -> str | None:
    """Repository prefix of a `<repo>/.claude/worktrees/<name>` path, else None.

    Purely textual, so it recovers the repository identity of worktrees that have
    since been deleted from disk. The *first* occurrence is used: a nested
    worktree-of-a-worktree still resolves to the outermost repository.
    """
    idx = path_posix.find(WORKTREE_MARKER)
    if idx <= 0:
        return None
    # Require a non-empty worktree name after the marker — `<repo>/.claude/
    # worktrees` alone is the container directory, not a checkout.
    if len(path_posix) <= idx + len(WORKTREE_MARKER):
        return None
    return path_posix[:idx]


def _live_repo_root(path_posix: str) -> str | None:
    """Resolve an on-disk path to its owning repository via git, or None.

    Delegates to `record_stop.git_roots`, which already encodes the
    submodule/`--separate-git-dir` caveats; anything it cannot resolve (it falls
    back to the input) yields None so the caller keeps its own fallback.
    """
    if not Path(path_posix).is_dir():
        return None
    repo = posix_path(rs.git_roots(path_posix)[1])
    return repo or None


def resolve_repo_root(
    record: dict,
    *,
    resolve_live: bool = True,
    cache: dict[str, str] | None = None,
) -> str:
    """Durable repository root for one trail record. See the module docstring.

    `cache` is keyed on the posix `git_root` so the optional live git resolution
    costs at most one subprocess per distinct path across a whole run.

    `repo_root` is authoritative but not blindly verbatim: `git_roots`' *degraded*
    branch (git < 2.31, or a transient failure of the combined `rev-parse`)
    mirrors the worktree toplevel into `repo_root` rather than leaving it absent.
    A `repo_root` that is literally a `<repo>/.claude/worktrees/<name>` path is
    therefore that degradation, not a distinct repository, so it collapses to the
    repository here — in the one function every caller goes through. Doing it in
    any single caller instead would leave `_trail_scope` and `compute_readiness`
    bucketing those records differently, which is precisely the two-tools-disagree
    failure this module exists to eliminate.

    The other two branches need no such collapse: the worktree parse below already
    returns the repository, and a path that reaches live resolution is by
    construction not a worktree-pattern path.
    """
    repo_root = posix_path(record.get("repo_root"))
    if repo_root:
        return strip_worktree(repo_root) or repo_root

    git_root = posix_path(record.get("git_root"))
    if not git_root:
        return ""

    stripped = strip_worktree(git_root)
    if stripped:
        return stripped

    if not resolve_live:
        return git_root
    if cache is not None and git_root in cache:
        return cache[git_root]
    resolved = _live_repo_root(git_root) or git_root
    if cache is not None:
        cache[git_root] = resolved
    return resolved


# ── trail ownership ────────────────────────────────────────────────────────

def trail_repo_root(
    trail_path: Path, *, cache: dict[str, str] | None = None
) -> str | None:
    """Owning repository of a trail, as a posix path, or None.

    Read from the trail's *head* — every record in one trail file was written from
    one checkout, so any record that carries a root is representative, and a trail
    that runs to megabytes never has to be slurped. The record goes through the
    full `resolve_repo_root` chain (`repo_root` → worktree parse → live git), so
    a trail written from a worktree reports the repository, not the worktree.

    "The head is representative" is an argument about *scope*, not about giving up:
    a first record that parses as a dict but carries neither `repo_root` nor
    `git_root` says nothing about the trail's owner, so the scan continues to the
    next record. Stopping there instead made such a trail permanently
    unattributable — dropped from `trails_for_repo`, so never stamped, so never
    pruned, and reported as UNATTRIBUTED by `unmark_harvested` — on the strength
    of one rootless line.

    The scan is bounded to `HEAD_SCAN_RECORDS` parseable records so a corrupt or
    truncated multi-megabyte trail still cannot be read end to end. A trail whose
    first `HEAD_SCAN_RECORDS` records are all rootless is treated as
    unattributable; if the head really carries no root, neither will the tail, and
    the bound is what keeps the degenerate case cheap.

    `cache` is handed straight to `resolve_repo_root`, so a caller sweeping the
    whole machine-global trail dir pays at most one `git` subprocess per distinct
    recorded path instead of one per trail. Optional, and it can only ever save
    work: the cache is keyed on the recorded path, not on the trail or the repo
    being tested.

    Returns None for an empty, unreadable, or malformed trail and for a head that
    carries no usable root. Never raises.

    Nothing is done to the resolved root here: `resolve_repo_root` already
    collapses a degraded `repo_root` that names a worktree, so every caller — not
    only this one — sees the repository.
    """
    try:
        with open(trail_path, "r", encoding="utf-8", errors="replace") as fh:
            seen = 0
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(rec, dict):
                    continue
                root = resolve_repo_root(rec, cache=cache)
                if root:
                    return root
                seen += 1
                if seen >= HEAD_SCAN_RECORDS:
                    break
    except (OSError, ValueError, TypeError):
        return None
    return None


def _repo_trail_names(repo_root: Path) -> set[str]:
    """Candidate filenames for ``repo_root``'s own canonical trail.

    `record_stop` names a trail after `repo_key(<git_root>)`, and `repo_key`
    hashes the *original string* — so `C:\\x\\y` and `C:/x/y`, one repository in
    two spellings, hash to two different keys.

    The posix form is the canonical one: `git_root` normally comes straight out
    of git, which emits forward slashes on every platform, so `posix_path` is
    what reproduces the key actually written. The native rendering is kept as a
    second candidate — not as a substitute — because `git_roots` has a
    degraded branch that returns the hook's own `cwd` unchanged, and that arrives
    with native separators on Windows. Both keys are hashes of one exact path, so
    accepting both cannot widen the match to any *other* repository.
    """
    return {
        f"{rs.repo_key(posix_path(repo_root))}.jsonl",
        f"{rs.repo_key(str(repo_root))}.jsonl",
    }


def belongs_to_repo(
    trail_path: Path, repo_root: Path, *, cache: dict[str, str] | None = None
) -> bool:
    """True when ``trail_path`` records work done in ``repo_root`` or a worktree of it.

    Equality on the normalised posix roots — see the module docstring for why
    that, and not an at-or-under test, is the correct comparison. The filename
    rule runs first and is the only one that can match a zero-record trail.

    `cache` is passed through to attribution and only ever saves repeated `git`
    subprocesses; it never changes the answer. Optional, so existing callers are
    unaffected.
    """
    if trail_path.name in _repo_trail_names(repo_root):
        return True
    recorded = trail_repo_root(trail_path, cache=cache)
    if not recorded:
        return False
    return recorded == posix_path(repo_root)


def trails_for_repo(
    repo_root: Path, *, cache: dict[str, str] | None = None
) -> list[Path]:
    """Sorted ``*.jsonl`` trails under the learning-trail dir belonging to ``repo_root``.

    This sweeps the *machine-global* trail dir, so on a well-used machine it tests
    ~100 files, and each unattributable-by-filename trail can cost a `git`
    subprocess with a multi-second timeout. Pass one `cache` per run — and reuse
    it across subject repos — to collapse that to one subprocess per distinct
    recorded path.
    """
    return [
        t
        for t in sorted(rs.trail_dir().glob("*.jsonl"))
        if belongs_to_repo(t, repo_root, cache=cache)
    ]


def current_repo_root(cwd: str | None = None) -> Path:
    """Repository root for ``cwd`` (default: the process cwd).

    Deliberately the *repo* root of `git_roots`' `(worktree_root, repo_root)`
    pair, not the worktree root: a linked worktree is ephemeral (this framework's
    own `repo-hygiene` skill deletes them) while the repository that owns it
    outlives every worktree cut from it. Scoping to the repo therefore keeps a
    harvest run from inside a worktree covering the same set of trails as one run
    from the main checkout.
    """
    return Path(rs.git_roots(cwd or os.getcwd())[1])
