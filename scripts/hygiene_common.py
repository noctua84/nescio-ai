"""Shared, read-only helpers for the repo-hygiene skill.

The hygiene skill inspects the repo's git worktrees and branches and classifies
which are safe to prune. This module is the mechanical layer underneath it: thin
`git`/`gh` subprocess wrappers plus the classification predicates that the two
sibling scripts (`repo_hygiene_scan.py`, `repo_hygiene_apply.py`) build on.

Two design rules run through everything here:

  1. Read-only. Nothing in this module mutates the repo, a branch, a worktree,
     or any remote. It only reads state and reports. All destructive action is
     the caller's job, gated behind its own confirmation.
  2. Never swallow stderr. `run_git` raises with the *full* stderr on failure so
     a broken invocation surfaces its root cause instead of degrading to "".
     The few functions that legitimately branch on an exit code (merge detection,
     `gh` availability) use `run` and inspect `returncode` explicitly — they
     never hide an *unexpected* failure, only the expected non-zero outcomes.

The merge check is deliberately two-signal (see `is_merged`): an authoritative
"the PR was merged" from `gh`, or a local "the tip is an ancestor of the default
branch" from git. The critical safety distinction is between "checked online and
it is NOT merged" (a confident False) and "could not check online" (an
INDETERMINATE None) — the caller must treat the latter as needs-review, never a
blind delete.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

# origin/HEAD is only populated once `git remote set-head` (or a clone) has run;
# on a fresh/partial checkout the symbolic-ref lookup fails, so we fall back to
# this literal rather than guess. It is a *fallback*, never the only code path.
DEFAULT_BRANCH_FALLBACK = "main"


@dataclass(frozen=True)
class Worktree:
    """One entry from `git worktree list --porcelain`.

    `path` is always resolved to an absolute path so it compares equal to paths
    produced by `os.scandir`/`Path` elsewhere: porcelain emits forward-slash
    `C:/...` on Windows while scandir yields backslashes, and `Path.resolve()`
    normalises both to the same `WindowsPath`.

    `branch` is the short name (``refs/heads/`` stripped) or ``None`` for a
    detached-HEAD or bare entry. `head` is the checked-out commit sha, or
    ``None`` for a bare worktree.
    """

    path: Path
    branch: str | None
    head: str | None
    bare: bool
    detached: bool


def run(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """Run `args` capturing text stdout/stderr; return the CompletedProcess.

    The general wrapper. It does not raise on a non-zero exit — callers that
    branch on `returncode` (e.g. `merge-base --is-ancestor`, `gh auth status`)
    need the raw result. A missing executable still raises `FileNotFoundError`
    from subprocess; callers that must degrade gracefully catch `OSError`.
    """
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True)


def run_git(args: list[str], cwd: Path | None = None) -> str:
    """Run `git <args>` and return stripped stdout, raising on failure.

    On a non-zero exit the full stderr (falling back to stdout) is embedded in
    the raised `RuntimeError` — stderr is never tailed or swallowed, so the root
    cause of a broken invocation is always visible.
    """
    proc = run(["git", *args], cwd=cwd)
    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip()
        raise RuntimeError(
            f"`git {' '.join(args)}` failed (exit {proc.returncode}):\n{detail}"
        )
    return proc.stdout.strip()


def repo_root() -> Path:
    """Absolute toplevel of the working tree (`git rev-parse --show-toplevel`)."""
    return Path(run_git(["rev-parse", "--show-toplevel"])).resolve()


def current_git_common_dir() -> Path:
    """Absolute path of the shared `.git` common dir.

    `git rev-parse --git-common-dir` may return a path relative to the current
    directory; `resolve()` anchors it to an absolute path. Used to exclude the
    live repo/worktree machinery from pruning decisions (self-exclusion).
    """
    return Path(run_git(["rev-parse", "--git-common-dir"])).resolve()


def current_branch() -> str:
    """Short name of the checked-out branch, or "" when HEAD is detached."""
    return run_git(["branch", "--show-current"])


def default_branch() -> str:
    """Repository default branch, e.g. ``main`` or ``master``.

    Read from `refs/remotes/origin/HEAD` (`git symbolic-ref`), stripping the
    ``refs/remotes/origin/`` prefix. Falls back to `DEFAULT_BRANCH_FALLBACK`
    ("main") when origin/HEAD is unset or the lookup errors — the fallback is
    never the only path, and a configured non-`main` default is respected.
    """
    proc = run(["git", "symbolic-ref", "--quiet", "refs/remotes/origin/HEAD"])
    ref = proc.stdout.strip()
    prefix = "refs/remotes/origin/"
    if proc.returncode == 0 and ref.startswith(prefix):
        name = ref[len(prefix):]
        if name:
            return name
    return DEFAULT_BRANCH_FALLBACK


def list_registered_worktrees() -> list[Worktree]:
    """Parse `git worktree list --porcelain` into `Worktree` records.

    Porcelain groups the attributes of one worktree into a blank-line-delimited
    block: a `worktree <path>` line, then some of `HEAD <sha>`, `branch <ref>`,
    `detached`, `bare`. Paths are resolved (see `Worktree.path`).
    """
    out = run_git(["worktree", "list", "--porcelain"])
    worktrees: list[Worktree] = []

    path: Path | None = None
    branch: str | None = None
    head: str | None = None
    bare = False
    detached = False

    def flush() -> None:
        nonlocal path, branch, head, bare, detached
        if path is not None:
            worktrees.append(Worktree(path, branch, head, bare, detached))
        path, branch, head, bare, detached = None, None, None, False, False

    for line in out.splitlines():
        if not line.strip():
            flush()
            continue
        key, _, value = line.partition(" ")
        if key == "worktree":
            flush()
            path = Path(value).resolve()
        elif key == "HEAD":
            head = value or None
        elif key == "branch":
            branch = value[len("refs/heads/"):] if value.startswith("refs/heads/") else value
        elif key == "detached":
            detached = True
        elif key == "bare":
            bare = True
    flush()

    return worktrees


def gh_available() -> bool:
    """True only if the GitHub CLI is installed *and* authenticated.

    `gh auth status` exits 0 exactly when a usable authenticated session
    exists. A missing `gh` binary (or any other OS error launching it) degrades
    to False rather than raising, so offline callers keep working.
    """
    try:
        return run(["gh", "auth", "status"]).returncode == 0
    except OSError:
        return False


def _gh_pr_merged(branch: str) -> bool | None:
    """Whether a merged PR exists for `branch` per `gh`, or None if unknowable.

    Returns True/False when `gh` gives a parseable answer, and None when the
    call fails, the binary vanished, or the output is empty/non-JSON — i.e. when
    `gh` could not actually be consulted. Keeping "not merged" (False) distinct
    from "could not check" (None) is what makes the caller's safety guarantee
    hold.
    """
    try:
        proc = run(
            ["gh", "pr", "list", "--state", "merged", "--head", branch,
             "--json", "number,mergedAt"]
        )
    except OSError:
        return None
    if proc.returncode != 0:
        return None
    out = proc.stdout.strip()
    if not out:
        return None
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return None
    if isinstance(data, list):
        return len(data) > 0
    return None


def is_merged(
    branch: str, tip: str, default: str, *, use_gh: bool
) -> tuple[bool | None, str]:
    """Two-signal merge check for `branch` (tip commit `tip`) vs `default`.

    Returns `(verdict, signal)`:

    - ``(True, "gh-merged")``      — `gh` reports a merged PR for the branch.
    - ``(True, "ancestor-merged")``— `tip` is an ancestor of `default` locally.
    - ``(False, "not-merged")``    — `gh` was consulted, reported no merged PR,
                                     and `tip` is not an ancestor. A confident No.
    - ``(None, "unconfirmed-offline")`` — could not consult `gh` and `tip` is not
                                     an ancestor. INDETERMINATE: the caller must
                                     treat this as needs-review, never a delete.

    `gh` is consulted only when `use_gh` and `gh_available()`; a `gh` call that
    fails or returns garbage counts as "not consulted", so a genuine offline /
    tooling failure can never masquerade as a confident "not merged".

    An unexpected `merge-base` exit (neither 0 nor 1, e.g. a bad ref) is a real
    error and is raised, not silently reported as None.
    """
    gh_consulted = False
    if use_gh and gh_available():
        merged = _gh_pr_merged(branch)
        if merged is True:
            return True, "gh-merged"
        if merged is False:
            gh_consulted = True
        # merged is None → gh could not be consulted; fall through unconsulted.

    proc = run(["git", "merge-base", "--is-ancestor", tip, default])
    if proc.returncode == 0:
        return True, "ancestor-merged"
    if proc.returncode == 1:
        if gh_consulted:
            return False, "not-merged"
        return None, "unconfirmed-offline"

    detail = proc.stderr.strip() or proc.stdout.strip()
    raise RuntimeError(
        f"`git merge-base --is-ancestor {tip} {default}` failed "
        f"(exit {proc.returncode}):\n{detail}"
    )


def dir_has_files(path: Path) -> bool:
    """Whether the directory tree at `path` holds any regular file (recursively).

    Shared by the scan (to refuse a content-bearing broken-orphan `safe`) and the
    apply (to re-verify emptiness immediately before an `rm -rf`). If the tree
    cannot even be enumerated, it is treated as content-bearing (conservative):
    better to refuse deletion than to delete something we could not inspect.
    """
    try:
        return any(p.is_file() for p in path.rglob("*"))
    except OSError:
        return True


def branch_ahead_count(branch: str, default: str) -> int:
    """Commits on `branch` not integrated into its upstream (or `default`).

    The integration point is the branch's own upstream when it has one
    (`<branch>@{upstream}`), else the repo default branch. Returns
    `git rev-list --count <base>..<branch>` — a count > 0 means `branch` carries
    local commits not represented at that base, i.e. work a force-delete would
    destroy. Used to gate the `-D` escalation: a merged PR proves the *merged*
    commits are integrated, not that a since-advanced local tip is.
    """
    upstream = run(
        ["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name",
         f"{branch}@{{upstream}}"]
    )
    if upstream.returncode == 0 and upstream.stdout.strip():
        base = upstream.stdout.strip()
    else:
        base = default
    count = run_git(["rev-list", "--count", f"{base}..{branch}"])
    return int(count)


def worktree_is_clean(path: Path) -> bool:
    """Whether the worktree at `path` holds no work that a prune would lose.

    Exact rule implemented (all must hold for a True result):

    1. **No local changes.** `git -C <path> status --porcelain` is empty — no
       staged, unstaged, or untracked files.
    2. **No unpushed commits.** If the branch has an upstream, it must be zero
       commits ahead of ``@{upstream}`` (`rev-list --count @{upstream}..HEAD`).
    3. **No un-integrated local work when there is no upstream.** If the branch
       has no upstream, it is treated conservatively: if HEAD is ahead of the
       repo default branch (`rev-list --count <default>..HEAD` > 0), the local
       commits are not yet integrated anywhere, so the worktree is NOT clean.

    Any git error while checking (1) or the ahead-counts is surfaced by
    `run_git`. Only the *upstream existence* probe is allowed to fail quietly —
    a missing upstream is an expected state, not an error.
    """
    if run_git(["-C", str(path), "status", "--porcelain"]):
        return False

    upstream = run(
        ["git", "-C", str(path), "rev-parse", "--abbrev-ref",
         "--symbolic-full-name", "@{upstream}"]
    )
    if upstream.returncode == 0 and upstream.stdout.strip():
        ahead = run_git(["-C", str(path), "rev-list", "--count", "@{upstream}..HEAD"])
        return ahead == "0"

    # No upstream: fall back to the repo default branch. Any local commits not
    # reachable from it are un-integrated work, so the worktree is not clean.
    default = default_branch()
    ahead = run_git(["-C", str(path), "rev-list", "--count", f"{default}..HEAD"])
    return ahead == "0"
