#!/usr/bin/env python3
"""Apply the safe prunes from a repo-hygiene scan — guarded and re-verified.

This is the destructive half of the repo-hygiene skill. It consumes the JSON
manifest produced by ``scripts/repo_hygiene_scan.py`` and, for every row the
scan classified ``verdict == "safe"``, RE-VERIFIES the safety conditions *in
this process, immediately before acting*, then performs the removal.

Why re-verify at all? The manifest is a snapshot. Between scan and apply a
worktree can gain uncommitted work, a branch can stop being merged, an orphan
dir can be re-registered, and this very repo has been observed emitting
contradictory ``git worktree list`` output inside a single session. So the
manifest is treated as a *plan of candidates*, never as authority: every row is
re-checked against live state and skipped if the live state no longer supports
the action. Nothing here trusts the scan's snapshot to pull the trigger.

Three hard gates protect the caller:

  1. ``--apply`` is required for ANY destructive action. Without it the script
     prints exactly the commands it *would* run (a second dry-run safety net)
     and exits 0, mutating nothing.
  2. With ``--apply`` but without ``--yes`` it prompts on stdin for a literal
     ``yes`` before touching anything.
  3. Every destructive action re-verifies in-process first (self-guard, still
     clean, still merged, still un/registered as expected) and SKIPS the row —
     never aborting the whole run — when a check fails.

``gh`` is NEVER invoked for writes. The only ``gh`` calls are the read-only
merge probe inside ``is_merged`` (used to distinguish a squash-merge that git
can't see locally). Dimension-3 (GitHub) rows are report-only and ignored here.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from _hygiene_common import (
    branch_ahead_count,
    current_branch,
    current_git_common_dir,
    default_branch,
    dir_has_files,
    is_merged,
    list_registered_worktrees,
    repo_root,
    run,
    worktree_is_clean,
)


class Report:
    """Accumulates outcomes for the final summary."""

    def __init__(self) -> None:
        self.removed_worktrees: list[str] = []
        self.removed_dirs: list[str] = []
        self.removed_branches: list[str] = []
        self.skipped: list[tuple[str, str]] = []  # (target, reason)
        self.errors: list[tuple[str, str]] = []    # (target, detail)

    def skip(self, target: str, reason: str) -> None:
        self.skipped.append((target, reason))
        print(f"  SKIP {target}: {reason}")

    def error(self, target: str, detail: str) -> None:
        self.errors.append((target, detail))
        print(f"  ERROR {target}: {detail}")


def protected_paths() -> set[Path]:
    """Paths that must never be removed: the current worktree and the main repo.

    ``repo_root()`` is the toplevel of the worktree we are running inside.
    ``current_git_common_dir()`` is the shared ``.git`` (the main repo's, even
    from a linked worktree); its parent is the main worktree's toplevel. Both
    are excluded so a self-referential row can never delete the ground we stand
    on.
    """
    out: set[Path] = set()
    try:
        out.add(repo_root())
    except RuntimeError:
        pass
    try:
        # The common-dir's parent is the main worktree's toplevel regardless of
        # the git dir's name (it need not be literally `.git`), so add it
        # unconditionally.
        out.add(current_git_common_dir().parent)
    except RuntimeError:
        pass
    return out


def find_worktree(path: Path, worktrees: list) -> object | None:
    for wt in worktrees:
        if wt.path == path:
            return wt
    return None


def _stderr(proc) -> str:
    return (proc.stderr or proc.stdout or "").strip()


def dim_kind(raw: object) -> str:
    """Normalise the manifest's ``dimension`` to ``worktrees`` / ``branches`` / ``other``.

    The scan emits string dimensions (``"worktrees"``, ``"branches"``); GitHub
    findings are console-only and never written to the manifest. Integer forms
    (``1``/``2``/``3``) are accepted too so hand-crafted manifests keep working.
    Anything else — including a GitHub row that somehow leaks in — maps to
    ``other`` and is ignored (never acted on).
    """
    if raw in ("worktrees", 1, "1"):
        return "worktrees"
    if raw in ("branches", 2, "2"):
        return "branches"
    return "other"


def signal_tokens(raw: object) -> list[str]:
    """Normalise ``signals`` to a lowercase token list.

    The scan stores signals as a single ``"; "``-joined string (e.g.
    ``"gh-merged; clean"``); older/hand-crafted manifests may use a JSON list.
    Both collapse to the same token list so membership tests (`"gh-merged" in
    tokens`) behave identically regardless of source shape.
    """
    if isinstance(raw, str):
        parts = raw.replace(";", ",").split(",")
    elif isinstance(raw, list):
        parts = [str(p) for p in raw]
    else:
        return []
    return [p.strip().lower() for p in parts if p.strip()]


def delete_branch(
    branch: str,
    tip: str,
    signals: list[str],
    default: str,
    *,
    use_gh: bool,
    apply: bool,
    rep: Report,
) -> None:
    """Delete ``branch``, escalating to ``-D`` only for a reconfirmed squash-merge.

    ``git branch -d`` is itself a safety gate: it refuses to delete a branch git
    does not consider merged. We lean on that. The only way to force past it is
    ``-D``, which we allow ONLY when the scan flagged ``gh-merged`` AND a live
    ``is_merged(..., use_gh=True)`` still returns ``gh-merged`` — i.e. GitHub
    authoritatively says the PR merged even though the local squash-merge hides
    the ancestry from git. Never ``-D`` on ``ancestor-merged``-only (``-d`` would
    have succeeded) or on ``unconfirmed-offline``.
    """
    if not apply:
        line = f"git branch -d {branch}"
        if "gh-merged" in signals:
            line += (
                f"   [if -d refuses: escalate to `git branch -D {branch}` "
                "iff gh-merged is reconfirmed live]"
            )
        print(f"  WOULD RUN: {line}")
        return

    proc = run(["git", "branch", "-d", branch])
    if proc.returncode == 0:
        rep.removed_branches.append(branch)
        print(f"  removed branch (-d): {branch}")
        return

    detail = _stderr(proc)
    if "gh-merged" not in signals:
        rep.skip(branch, f"branch -d refused and not gh-merged, refusing -D: {detail}")
        return

    # Squash-merge escalation: reconfirm the authoritative signal live. Honour
    # --no-gh (use_gh=False) so an offline run can never reach a force-delete.
    verdict, signal = is_merged(branch, tip, default, use_gh=use_gh)
    if signal != "gh-merged":
        rep.skip(
            branch,
            f"branch -d refused; -D not escalated (gh no longer reports merged: {signal})",
        )
        return

    # `gh-merged` proves a PR merged for this head ref, NOT that the local tip is
    # contained in what was merged. A squash-merged branch whose tip has since
    # advanced with unpushed commits would be force-deleted here, losing that
    # work. Only `-D` when the branch carries no un-integrated commits (ahead of
    # its upstream, else the default branch) — the true squash case where every
    # local commit is already represented upstream.
    ahead = branch_ahead_count(branch, default)
    if ahead > 0:
        rep.skip(branch, "has-unpushed-commits")
        return

    forced = run(["git", "branch", "-D", branch])
    if forced.returncode == 0:
        rep.removed_branches.append(branch)
        print(f"  removed branch (-D, gh-merged reconfirmed): {branch}")
        return
    rep.error(branch, f"branch -D failed: {_stderr(forced)}")


def handle_worktree_removal(
    wt, row: dict, default: str, *, use_gh: bool, apply: bool, rep: Report
) -> None:
    target = row.get("target") or str(wt.path)
    branch = wt.branch or row.get("branch")

    if not worktree_is_clean(wt.path):
        rep.skip(target, "uncommitted-or-unpushed")
        return

    verdict, signal = is_merged(
        branch or "", wt.head or "", default, use_gh=use_gh and bool(branch)
    )
    if verdict is not True:
        rep.skip(target, f"not-merged-on-recheck ({signal})")
        return

    tokens = signal_tokens(row.get("signals"))
    if not apply:
        print(f"  WOULD RUN: git worktree remove {wt.path}")
        if branch:
            delete_branch(
                branch, wt.head or "", tokens, default,
                use_gh=use_gh, apply=False, rep=rep,
            )
        return

    # No --force: if git refuses (e.g. it re-discovers dirty state), skip.
    proc = run(["git", "worktree", "remove", str(wt.path)])
    if proc.returncode != 0:
        rep.error(target, f"worktree remove refused: {_stderr(proc)}")
        return
    rep.removed_worktrees.append(str(wt.path))
    print(f"  removed worktree: {wt.path}")

    if branch:
        delete_branch(
            branch, wt.head or "", tokens, default,
            use_gh=use_gh, apply=True, rep=rep,
        )


def handle_orphan_dir(path: Path, target: str, *, apply: bool, rep: Report) -> None:
    # Re-confirm it did not become a registered worktree since the scan.
    if find_worktree(path, list_registered_worktrees()) is not None:
        rep.skip(target, "became-registered-since-scan")
        return
    if not path.exists():
        rep.skip(target, "already-gone")
        return

    # Path-containment gate: an orphan MUST live under the main checkout's
    # `.claude/worktrees/`. A manifest path outside it (wrong or crafted) is never
    # rm -rf'd — refuse before any deletion, dry-run included.
    worktrees_dir = (
        current_git_common_dir().parent / ".claude" / "worktrees"
    ).resolve()
    if worktrees_dir not in path.resolve().parents:
        rep.skip(target, "outside-worktrees-dir")
        return

    # If it carries git worktree machinery, only remove it when verifiably clean.
    # A dangling/unverifiable ``.git`` stub is left for `git worktree prune`
    # rather than blindly deleted.
    has_git = (path / ".git").exists()
    if has_git:
        try:
            clean = worktree_is_clean(path)
        except RuntimeError as exc:
            rep.skip(target, f"git-tree-unverifiable, left for prune: {exc}")
            return
        if not clean:
            rep.skip(target, "dirty-on-recheck")
            return

    if not apply:
        print(f"  WOULD RUN: shutil.rmtree({path})")
        return

    # Broken orphan (no `.git`): the scan marked it `safe` only because it was
    # empty at scan time. Re-verify emptiness immediately before rm -rf — if a
    # file landed here since the scan, skip rather than trust the stale snapshot.
    if not has_git and dir_has_files(path):
        rep.skip(target, "not-empty-on-recheck")
        return

    try:
        shutil.rmtree(path)
    except OSError as exc:
        rep.error(target, f"rmtree failed: {exc}")
        return
    rep.removed_dirs.append(str(path))
    print(f"  removed orphan dir: {path}")


def handle_dimension_1(
    row: dict, default: str, *, use_gh: bool, apply: bool, rep: Report
) -> None:
    target = row.get("target") or row.get("path") or "<dim1>"
    raw_path = row.get("path")
    if not raw_path:
        rep.skip(target, "dim1-row-has-no-path")
        return
    path = Path(raw_path).resolve()
    branch = row.get("branch")
    reason = (row.get("reason") or "").lower()

    worktrees = list_registered_worktrees()
    wt = find_worktree(path, worktrees)

    # The scan tags orphan rows with a reason of `orphan-dir-*` and a target of
    # `<name> (orphan)`; a registered worktree's reason is `merged (...)`. Fall
    # back to "not registered and no branch" only if neither marker is present.
    scanned_orphan = (
        reason.startswith("orphan")
        or "(orphan)" in (row.get("target") or "").lower()
        or (wt is None and not branch)
    )

    if scanned_orphan:
        if wt is not None:
            rep.skip(target, "became-registered-since-scan")
            return
        handle_orphan_dir(path, target, apply=apply, rep=rep)
        return

    # Scanned as a registered worktree: it must still be registered.
    if wt is None:
        rep.skip(target, "no-longer-registered-since-scan")
        return
    handle_worktree_removal(wt, row, default, use_gh=use_gh, apply=apply, rep=rep)


def handle_dimension_2(
    row: dict, default: str, *, use_gh: bool, apply: bool, rep: Report
) -> None:
    target = row.get("target") or row.get("branch") or "<dim2>"
    branch = row.get("branch")
    if not branch:
        rep.skip(target, "dim2-row-has-no-branch")
        return

    verify = run(["git", "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"])
    if verify.returncode != 0:
        rep.skip(target, "branch-missing")
        return
    tip = verify.stdout.strip()

    delete_branch(
        branch, tip, signal_tokens(row.get("signals")), default,
        use_gh=use_gh, apply=apply, rep=rep,
    )


def process_row(
    row: dict,
    default: str,
    protected: set[Path],
    cur_branch: str,
    *,
    use_gh: bool,
    apply: bool,
    rep: Report,
) -> None:
    kind = dim_kind(row.get("dimension"))
    target = row.get("target") or row.get("path") or row.get("branch") or "<row>"
    branch = row.get("branch")
    raw_path = row.get("path")
    path = Path(raw_path).resolve() if raw_path else None

    # Self-guard: never remove the ground we stand on.
    if path is not None and path in protected:
        rep.skip(target, "refuses-self")
        return
    if branch and cur_branch and branch == cur_branch:
        rep.skip(target, "refuses-self")
        return

    try:
        if kind == "worktrees":
            handle_dimension_1(row, default, use_gh=use_gh, apply=apply, rep=rep)
        elif kind == "branches":
            handle_dimension_2(row, default, use_gh=use_gh, apply=apply, rep=rep)
        else:
            # GitHub findings are report-only; anything else is unknown → ignore.
            rep.skip(target, f"ignored (dimension={row.get('dimension')!r})")
    except RuntimeError as exc:
        rep.skip(target, f"recheck-failed: {exc}")
    except OSError as exc:
        rep.error(target, f"os-error: {exc}")


def load_manifest(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("rows"), list):
        raise ValueError(
            f"{path}: not a hygiene manifest (missing top-level 'rows' list)"
        )
    return data


def print_summary(rep: Report, *, apply: bool) -> None:
    verb = "removed" if apply else "would remove"
    print("\n=== summary ===")
    print(f"{verb}: {len(rep.removed_worktrees)} worktree(s), "
          f"{len(rep.removed_dirs)} dir(s), {len(rep.removed_branches)} branch(es)")
    if rep.removed_worktrees:
        for p in rep.removed_worktrees:
            print(f"  worktree: {p}")
    if rep.removed_dirs:
        for p in rep.removed_dirs:
            print(f"  dir:      {p}")
    if rep.removed_branches:
        for b in rep.removed_branches:
            print(f"  branch:   {b}")
    print(f"skipped-on-recheck: {len(rep.skipped)}")
    for target, reason in rep.skipped:
        print(f"  - {target}: {reason}")
    print(f"errors: {len(rep.errors)}")
    for target, detail in rep.errors:
        print(f"  - {target}: {detail}")


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Apply the safe prunes from a repo-hygiene scan manifest."
    )
    ap.add_argument("--from", dest="manifest", required=True,
                    help="path to the JSON manifest from repo_hygiene_scan.py")
    ap.add_argument("--apply", action="store_true",
                    help="perform destructive actions; without it, only prints intended commands")
    ap.add_argument("--yes", action="store_true",
                    help="skip the interactive stdin confirmation (a human already typed yes)")
    ap.add_argument("--no-gh", action="store_true",
                    help="never consult gh, even for the read-only merge probe (offline)")
    args = ap.parse_args()

    manifest_path = Path(args.manifest)
    if not manifest_path.is_file():
        print(f"error: no such manifest: {manifest_path}")
        return 1
    try:
        manifest = load_manifest(manifest_path)
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}")
        return 1

    rows = manifest.get("rows", [])
    safe_rows = [
        r for r in rows
        if isinstance(r, dict)
        and r.get("verdict") == "safe"
        and dim_kind(r.get("dimension")) in ("worktrees", "branches")
    ]

    # Live default branch — re-derived, not trusted from the manifest.
    default = default_branch()
    use_gh = not args.no_gh

    mode = "APPLY" if args.apply else "DRY-RUN (no --apply)"
    print(f"repo_hygiene_apply - {mode}")
    print(f"manifest: {manifest_path}  (default branch: {default}, gh: {use_gh})")
    print(f"{len(safe_rows)} safe row(s) to process "
          f"(GitHub findings are report-only and are not acted on).\n")

    if args.apply and not args.yes:
        try:
            answer = input("This will permanently remove worktrees, dirs, and branches. "
                           "Type 'yes' to proceed: ").strip()
        except EOFError:
            answer = ""
        if answer != "yes":
            print("aborted: confirmation not given.")
            return 1

    protected = protected_paths()
    cur_branch = current_branch()

    rep = Report()
    for row in safe_rows:
        process_row(
            row, default, protected, cur_branch,
            use_gh=use_gh, apply=args.apply, rep=rep,
        )

    # Metadata cleanup for the inverse orphan case (admin dirs whose worktree
    # is gone). Read-adjacent and safe, but still gated behind --apply.
    if args.apply:
        prune = run(["git", "worktree", "prune"])
        if prune.returncode == 0:
            print("\nran: git worktree prune")
        else:
            rep.error("git worktree prune", _stderr(prune))
    else:
        print("\n  WOULD RUN: git worktree prune")

    print_summary(rep, apply=args.apply)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
