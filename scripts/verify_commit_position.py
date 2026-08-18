#!/usr/bin/env python3
"""Verify a reported commit actually landed on the branch it was meant for.

The controller's independent check after an implementer wave. Implementer
subagents sometimes run `git commit` while the worktree `HEAD` is **detached**:
the commit succeeds, prints a sha, and the agent reports success — but the commit
lands on *no branch*. The controller's next `git log <branch>` then reads state
that predates the work and reports green for a change that isn't there. Observed
twice in real subagent-driven runs; one commit was silently orphaned.

The general defect is one of trust: the controller took an agent's word about git
state instead of checking it. This script is the check. It answers one question —
*is the reported sha reachable from the branch tip?* — plus the condition that
produces orphans in the first place, a detached `HEAD`.

Three checks, deliberately unequal in severity:

  1. **Orphan** (hard failure). `git merge-base --is-ancestor <sha> <branch>`.
     If the commit is not reachable from the branch tip it orphaned, and the
     message says how to recover it.
  2. **Detached HEAD** (hard failure). `git symbolic-ref -q HEAD`. This is the
     condition that *causes* orphans, so it is worth catching even on a run where
     the reported sha happens to be fine — the next commit is the one that gets
     lost.
  3. **Base freshness** (warning only, never changes the exit code). With
     `--base`, whether the branch is built on top of that base ref. Feature
     branches legitimately diverge from their base, and failing here would cry
     wolf on a normal branch — which is how a guard gets ignored. It warns and
     nothing more. It also requires the caller to have fetched, so an
     unresolvable base ref degrades to a warning too, not an error.

Exit codes are three-valued so a caller can tell "the check failed" from "the
check could not run":

  0  checks passed (a base warning does not change this)
  1  a hard check failed — the commit orphaned, or HEAD is detached
  2  could not check — not a git repo, unknown sha, or unknown branch

Every git call goes through `subprocess.run` with a list argv and an explicit
`cwd`; there is no `shell=True` and no shell syntax anywhere, so this behaves
identically on Windows and POSIX.

Usage:
    python scripts/verify_commit_position.py <sha> <branch>
    python scripts/verify_commit_position.py <sha> <branch> --base origin/main
    python scripts/verify_commit_position.py <sha> <branch> --repo /path/to/repo
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

# Exit codes. Kept named so the distinction between "failed" and "could not
# check" is explicit at every return site.
EXIT_PASS = 0
EXIT_CHECK_FAILED = 1
EXIT_ERROR = 2

# `git merge-base --is-ancestor` exits 0 for yes and 1 for no; anything else is a
# real git failure (bad object, broken repo) and must not be read as "no".
_ANCESTOR_YES = 0
_ANCESTOR_NO = 1

_BRANCH_PREFIX = "refs/heads/"
_SHORT = 12


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run `git <args>` in `cwd`, capturing text output; never raises on exit code.

    Mirrors `_hygiene_common.run`: callers here branch on `returncode` (notably
    `merge-base --is-ancestor`, whose whole contract is its exit status), so a
    raising wrapper would be wrong. A missing `git` still raises `OSError` from
    subprocess and is caught at the one place that can report it usefully.
    """
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


def _detail(proc: subprocess.CompletedProcess[str]) -> str:
    """Full stderr (falling back to stdout) from a failed call — never tailed."""
    return proc.stderr.strip() or proc.stdout.strip()


def _resolve(ref: str, cwd: Path) -> str | None:
    """Full sha that `ref` names as a commit, or None if it does not resolve.

    `^{commit}` makes this reject refs that exist but are not commits, and
    `--quiet` turns "no such ref" into a silent exit 1 instead of noise on
    stderr. The literal braces are safe because there is no shell involved.
    """
    proc = _run(["rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"], cwd)
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def verify(
    sha: str,
    branch: str,
    base: str | None = None,
    repo: str | Path | None = None,
) -> tuple[int, list[str]]:
    """Check that `sha` is reachable from `branch` and that HEAD is attached.

    Returns ``(exit_code, lines)`` — the caller prints the lines. Both hard
    checks always run, so a report shows the full picture rather than stopping
    at the first failure. The optional `base` check only ever appends a warning.
    """
    cwd = Path(repo).resolve() if repo is not None else Path.cwd()
    if not cwd.is_dir():
        return EXIT_ERROR, [f"error: not a directory: {cwd}"]

    try:
        top = _run(["rev-parse", "--show-toplevel"], cwd)
    except OSError as exc:  # git not installed / not on PATH
        return EXIT_ERROR, [f"error: could not run git: {exc}"]
    if top.returncode != 0:
        return EXIT_ERROR, [f"error: not a git repository: {cwd}"]

    sha_full = _resolve(sha, cwd)
    if sha_full is None:
        return EXIT_ERROR, [f"error: unknown commit: {sha}"]
    branch_full = _resolve(branch, cwd)
    if branch_full is None:
        return EXIT_ERROR, [f"error: unknown branch: {branch}"]

    lines = [
        f"repo:   {top.stdout.strip()}",
        f"commit: {sha} -> {sha_full[:_SHORT]}",
        f"branch: {branch} -> {branch_full[:_SHORT]}",
        "",
    ]
    failed = False

    # 1. Orphan check — the reason this script exists.
    anc = _run(["merge-base", "--is-ancestor", sha_full, branch_full], cwd)
    if anc.returncode == _ANCESTOR_YES:
        lines.append(f"PASS  {sha_full[:_SHORT]} is reachable from {branch}")
    elif anc.returncode == _ANCESTOR_NO:
        failed = True
        lines.append(f"FAIL  {sha_full[:_SHORT]} is NOT reachable from {branch}")
        lines.append(
            "      The commit exists but is on no branch — it orphaned. This is "
            "what a detached-HEAD commit looks like afterwards."
        )
        lines.append(
            f"      Recover it:  git switch {branch} && "
            f"git cherry-pick {sha_full[:_SHORT]}"
        )
    else:
        return EXIT_ERROR, [
            f"error: `git merge-base --is-ancestor` failed: {_detail(anc)}"
        ]

    # 2. Detached-HEAD check — the condition that produces orphans. Worth
    #    failing on even when the reported sha is fine: the *next* commit in this
    #    worktree is the one that gets lost.
    head = _run(["symbolic-ref", "--quiet", "HEAD"], cwd)
    if head.returncode == 0:
        current = head.stdout.strip()
        if current.startswith(_BRANCH_PREFIX):
            current = current[len(_BRANCH_PREFIX):]
        lines.append(f"PASS  HEAD is attached to {current}")
    else:
        failed = True
        lines.append("FAIL  HEAD is detached in this repo")
        lines.append(
            "      Commits made from here land on no branch and are silently "
            f"lost. Reattach:  git switch {branch}"
        )

    # 3. Base freshness — warning only. Never touches the exit code.
    if base is not None:
        base_full = _resolve(base, cwd)
        if base_full is None:
            lines.append(
                f"WARN  base ref '{base}' does not resolve — run `git fetch` "
                "first; base freshness was not checked."
            )
        else:
            fresh = _run(
                ["merge-base", "--is-ancestor", base_full, branch_full], cwd
            )
            if fresh.returncode == _ANCESTOR_YES:
                lines.append(f"ok    {branch} contains {base}")
            elif fresh.returncode == _ANCESTOR_NO:
                lines.append(
                    f"WARN  {branch} does not contain {base} — it may be built "
                    "on a stale base. This is only a warning: branches "
                    "legitimately diverge. Requires a prior `git fetch` to be "
                    "meaningful."
                )
            else:
                lines.append(
                    f"WARN  base-freshness check could not run: {_detail(fresh)}"
                )

    return (EXIT_CHECK_FAILED if failed else EXIT_PASS), lines


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Verify a reported commit landed on the intended branch "
            "(orphan + detached-HEAD guard)."
        ),
    )
    ap.add_argument("sha", help="the commit an implementer reported")
    ap.add_argument("branch", help="the branch it was supposed to land on")
    ap.add_argument(
        "--base",
        default=None,
        help="base ref (e.g. origin/main) to warn about staleness against",
    )
    ap.add_argument(
        "--repo",
        default=None,
        help="path to the repo/worktree to check (default: current directory)",
    )
    args = ap.parse_args(argv)

    # Branch names and git output can be non-ASCII; a legacy Windows console
    # defaults to cp1252 and would raise UnicodeEncodeError. Reconfigure to UTF-8
    # when possible (guarded — a redirected StringIO in tests has no reconfigure).
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass

    rc, lines = verify(args.sha, args.branch, base=args.base, repo=args.repo)
    for line in lines:
        print(line)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
