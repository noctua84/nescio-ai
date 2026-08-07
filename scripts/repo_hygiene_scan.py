#!/usr/bin/env python3
"""Read-only scan that classifies git-cleanup candidates for the hygiene skill.

Stage 1 of the two-script hygiene flow (the sibling `repo_hygiene_apply.py` is
the mutating half). This script inspects three dimensions and prints an aligned
table per dimension plus a safe/unsafe/needs-review summary. It optionally emits
a machine-readable JSON manifest that the apply script consumes.

It mutates NOTHING — no branch, worktree, remote, or `gh` write is ever issued.
The single filesystem effect it can have is writing the `--json` manifest to the
throwaway path you pass; without `--json` it touches no file at all. It always
exits 0 so it is safe to wire into read-only automation.

Three dimensions:

  1. Worktrees      registered worktrees + orphan directories under
                    `.claude/worktrees/` that git no longer tracks.
  2. Branches       stale local branches already merged into the default branch.
  3. GitHub         report-only housekeeping (merged PRs with a still-open linked
                    issue; local branches already merged on GitHub). Never writes.

The verdict vocabulary is `safe` / `unsafe` / `needs-review`. The load-bearing
safety rule (inherited from `_hygiene_common.is_merged`) is that an INDETERMINATE
merge check — could-not-confirm-offline, returned as `None` — is `needs-review`,
never a delete. Only a confirmed merge on a clean tree earns `safe`.
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from _hygiene_common import (
    Worktree,
    branch_ahead_count,
    current_branch,
    current_git_common_dir,
    default_branch,
    dir_has_files,
    gh_available,
    is_merged,
    list_registered_worktrees,
    repo_root,
    run,
    run_git,
    worktree_is_clean,
)

GENERATED_BY = "scripts/repo_hygiene_scan.py"

SAFE = "safe"
UNSAFE = "unsafe"
NEEDS_REVIEW = "needs-review"


@dataclass
class Row:
    """One classified cleanup candidate.

    `target` is the human-facing identifier shown in the console table. `path`
    and `branch` are the machine-facing anchors the apply script keys on — a
    worktree/orphan row carries `path`, a branch row carries `branch`, a worktree
    row often carries both. `action` is the concrete command the apply step would
    run for a `safe` row (empty for unsafe/needs-review, which apply skips).
    """

    dimension: str
    target: str
    verdict: str
    reason: str
    signals: str = ""
    path: str | None = None
    branch: str | None = None
    action: str = ""


# --------------------------------------------------------------------------- #
# gh helpers (all read-only: only `pr list` / `issue list`, never a write)
# --------------------------------------------------------------------------- #

def _gh_json(args: list[str]) -> list | None:
    """Run a read-only `gh ... --json ...` call, returning the parsed list.

    Returns None on any failure (missing binary, non-zero exit, empty or
    non-JSON output) so callers degrade gracefully instead of raising — the
    scan must never abort on a `gh` hiccup.
    """
    try:
        proc = run(["gh", *args])
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
    return data if isinstance(data, list) else None


def open_pr_number(branch: str, *, use_gh: bool) -> int | None:
    """Number of an open PR whose head is `branch`, or None if none/unknown."""
    if not (use_gh and gh_available()):
        return None
    data = _gh_json(["pr", "list", "--state", "open", "--head", branch,
                     "--json", "number"])
    if data:
        num = data[0].get("number")
        return int(num) if isinstance(num, int) else None
    return None


# --------------------------------------------------------------------------- #
# Dimension 1 — worktrees + orphan directories
# --------------------------------------------------------------------------- #

def classify_registered_worktree(
    wt: Worktree, default: str, *, use_gh: bool
) -> Row:
    """Classify one registered worktree (never self/main — caller filters)."""
    name = wt.path.name
    branch = wt.branch or "(detached)"
    target = f"{name} [{branch}]"
    base = dict(dimension="worktrees", target=target,
                path=str(wt.path), branch=wt.branch)

    # An open PR means the branch is live work — never a delete, whatever the
    # merge signal says. Checked first so it can't be masked by a stale merge.
    if wt.branch:
        pr = open_pr_number(wt.branch, use_gh=use_gh)
        if pr is not None:
            return Row(verdict=UNSAFE, reason=f"open-pr #{pr}",
                       signals="open-pr", **base)

    if wt.branch is None or wt.head is None:
        return Row(verdict=NEEDS_REVIEW, reason="detached-head",
                   signals="detached", **base)

    verdict_merged, signal = is_merged(
        wt.branch, wt.head, default, use_gh=use_gh
    )
    clean = worktree_is_clean(wt.path)

    if verdict_merged is True and clean:
        return Row(
            verdict=SAFE,
            reason=f"merged ({signal})",
            signals=f"{signal}; clean",
            action=f"git worktree remove {wt.path} + git branch -d {wt.branch}",
            **base,
        )
    if not clean:
        return Row(verdict=UNSAFE, reason="uncommitted-or-unpushed",
                   signals=f"{signal}; dirty", **base)
    if verdict_merged is False:
        return Row(verdict=UNSAFE, reason="not-merged",
                   signals=signal, **base)
    # verdict_merged is None → could not confirm merge → never a blind delete.
    return Row(verdict=NEEDS_REVIEW, reason="unconfirmed-offline",
               signals=signal, **base)


def _orphan_is_own_worktree(orphan: Path) -> bool:
    """True only if `orphan` is its own valid git working tree.

    A de-registered worktree whose `.git` linkage was deleted is still a plain
    directory nested inside the main working tree, so `rev-parse --show-toplevel`
    from inside it walks *up* and resolves to the parent repo, not to itself.
    We therefore require the reported toplevel to equal the directory itself;
    anything else (a parent path, or a non-zero exit) means the worktree
    identity is gone — a broken orphan.
    """
    proc = run(["git", "-C", str(orphan), "rev-parse", "--show-toplevel"])
    if proc.returncode != 0:
        return False
    top = proc.stdout.strip()
    if not top:
        return False
    return Path(top).resolve() == orphan.resolve()


def classify_orphan(orphan: Path, default: str, *, use_gh: bool) -> Row:
    """Classify a directory under `.claude/worktrees/` git no longer tracks."""
    name = orphan.name
    base = dict(dimension="worktrees", target=f"{name} (orphan)",
                path=str(orphan))

    if _orphan_is_own_worktree(orphan):
        # Still a real, if de-registered, worktree: apply the normal clean+merged
        # gate against its own branch/HEAD.
        branch = run_git(["-C", str(orphan), "branch", "--show-current"]) or None
        head = run_git(["-C", str(orphan), "rev-parse", "HEAD"])
        clean = worktree_is_clean(orphan)
        merged, signal = (
            is_merged(branch, head, default, use_gh=use_gh)
            if branch
            else (None, "detached")
        )
        if clean and merged is True:
            return Row(
                verdict=SAFE, reason="orphan-dir-merged",
                signals=f"{signal}; clean", branch=branch,
                action=f"rm -rf {orphan}", **base,
            )
        return Row(verdict=UNSAFE, reason="orphan-dir-dirty",
                   signals=f"{signal}; {'clean' if clean else 'dirty'}",
                   branch=branch, **base)

    # Broken orphan: its worktree identity is gone. There is no git-tracked work
    # to lose here; the only risk is stray user files. An empty leftover is a
    # safe `rm -rf`; anything with files goes to a human.
    if dir_has_files(orphan):
        return Row(verdict=UNSAFE, reason="orphan-dir-dirty",
                   signals="broken; has-files", **base)
    return Row(verdict=SAFE, reason="orphan-dir-invalid",
               signals="broken; empty", action=f"rm -rf {orphan}", **base)


def scan_worktrees(
    registered: list[Worktree],
    registered_paths: set[Path],
    worktrees_dir: Path,
    self_path: Path,
    main_root: Path,
    default: str,
    *,
    use_gh: bool,
) -> list[Row]:
    """Dimension 1: registered worktrees (minus self/main) plus orphan dirs."""
    rows: list[Row] = []

    for wt in registered:
        if wt.bare or wt.path == self_path or wt.path == main_root:
            continue
        # Per-row isolation: one malformed ref must not sink the whole scan.
        try:
            rows.append(classify_registered_worktree(wt, default, use_gh=use_gh))
        except Exception as exc:  # noqa: BLE001 - one bad row → needs-review, not abort
            branch = wt.branch or "(detached)"
            rows.append(Row(
                dimension="worktrees", target=f"{wt.path.name} [{branch}]",
                verdict=NEEDS_REVIEW, reason=f"scan-error: {exc}",
                path=str(wt.path), branch=wt.branch,
            ))

    if worktrees_dir.is_dir():
        for entry in os.scandir(worktrees_dir):
            # Refuse symlinks: never resolve one to its target and treat the
            # target as an orphan. follow_symlinks=False makes is_dir() False for
            # a symlinked dir; the explicit is_symlink() guard states the intent.
            if entry.is_symlink() or not entry.is_dir(follow_symlinks=False):
                continue
            orphan = Path(entry.path).resolve()
            if orphan in registered_paths or orphan == self_path:
                continue
            try:
                rows.append(classify_orphan(orphan, default, use_gh=use_gh))
            except Exception as exc:  # noqa: BLE001 - one bad row → needs-review, not abort
                rows.append(Row(
                    dimension="worktrees", target=f"{orphan.name} (orphan)",
                    verdict=NEEDS_REVIEW, reason=f"scan-error: {exc}",
                    path=str(orphan),
                ))

    return rows


# --------------------------------------------------------------------------- #
# Dimension 2 — stale merged local branches
# --------------------------------------------------------------------------- #

def scan_branches(
    excluded: set[str], default: str, *, use_gh: bool
) -> list[Row]:
    """Dimension 2: local branches not backing a live/self/default checkout."""
    rows: list[Row] = []
    out = run_git(["branch", "--format",
                   "%(refname:short)%09%(objectname)%09%(upstream)"])
    for line in out.splitlines():
        parts = line.split("\t")
        if not parts or not parts[0]:
            continue
        name = parts[0]
        tip = parts[1] if len(parts) > 1 else ""
        if name in excluded or name == default:
            continue

        base = dict(dimension="branches", target=name, branch=name)
        # Per-row isolation: one malformed ref must not sink the whole scan.
        try:
            # An open PR means live work — never a delete, mirroring the
            # registered-worktree path. Checked first so a stale merge can't mask it.
            pr = open_pr_number(name, use_gh=use_gh)
            if pr is not None:
                rows.append(Row(verdict=UNSAFE, reason=f"open-pr #{pr}",
                                signals="open-pr", **base))
                continue

            verdict_merged, signal = is_merged(name, tip, default, use_gh=use_gh)
            if verdict_merged is True:
                # A `gh-merged` PR proves the merged commits are integrated, not
                # that a since-advanced local tip is. If the branch carries
                # commits ahead of its integration point, a `-D` would destroy
                # them, so it is not `safe` — hand it to a human.
                if signal == "gh-merged" and branch_ahead_count(name, default) > 0:
                    rows.append(Row(verdict=UNSAFE, reason="has-unpushed-commits",
                                    signals=f"{signal}; ahead", **base))
                else:
                    rows.append(Row(verdict=SAFE, reason=f"merged ({signal})",
                                    signals=signal, action=f"git branch -d {name}",
                                    **base))
            elif verdict_merged is False:
                rows.append(Row(verdict=UNSAFE, reason="not-merged",
                                signals=signal, **base))
            else:
                rows.append(Row(verdict=NEEDS_REVIEW, reason="unconfirmed-offline",
                                signals=signal, **base))
        except Exception as exc:  # noqa: BLE001 - one bad row → needs-review, not abort
            rows.append(Row(verdict=NEEDS_REVIEW, reason=f"scan-error: {exc}",
                            **base))
    return rows


# --------------------------------------------------------------------------- #
# Dimension 3 — GitHub housekeeping (report only)
# --------------------------------------------------------------------------- #

def report_github(branch_rows: list[Row], *, use_gh: bool) -> None:
    """Print-only GitHub notes. Issues no `gh` write of any kind."""
    print("\nDimension 3 - GitHub housekeeping (report only)")
    if not (use_gh and gh_available()):
        print("  skipped - gh offline")
        return

    merged_prs = _gh_json(["pr", "list", "--state", "merged", "--limit", "50",
                           "--json", "number,title,headRefName,"
                           "closingIssuesReferences"]) or []
    open_issues = _gh_json(["issue", "list", "--state", "open",
                            "--json", "number"]) or []
    open_nums = {i.get("number") for i in open_issues if isinstance(i, dict)}

    flagged = []
    for pr in merged_prs:
        for ref in pr.get("closingIssuesReferences") or []:
            if ref.get("number") in open_nums:
                flagged.append(
                    f"  PR #{pr.get('number')} merged but issue "
                    f"#{ref.get('number')} still open — {pr.get('title', '')}"
                )
    if flagged:
        print("  Merged PRs with a still-open linked issue:")
        for line in flagged:
            print(line)
    else:
        print("  No merged PR left a linked issue open.")

    gh_merged = [r.branch for r in branch_rows
                 if r.branch and r.signals == "gh-merged"]
    if gh_merged:
        print("  Local branches already merged on GitHub:")
        for b in gh_merged:
            print(f"    - {b}")
    else:
        print("  No local branch is confirmed merged on GitHub.")


# --------------------------------------------------------------------------- #
# Console rendering
# --------------------------------------------------------------------------- #

def print_table(title: str, rows: list[Row]) -> None:
    """Print `rows` as a column-aligned table (adopt-script house style)."""
    print(f"\n{title}")
    if not rows:
        print("  (none)")
        return
    headers = ["verdict", "target", "reason", "signals", "action"]
    table = [headers] + [
        [r.verdict, r.target, r.reason, r.signals, r.action] for r in rows
    ]
    widths = [max(len(row[c]) for row in table) for c in range(len(headers))]
    for i, row in enumerate(table):
        cells = "  ".join(row[c].ljust(widths[c]) for c in range(len(headers)))
        print(f"  {cells.rstrip()}")
        if i == 0:
            print("  " + "  ".join("-" * widths[c] for c in range(len(headers))))


# --------------------------------------------------------------------------- #
# Manifest
# --------------------------------------------------------------------------- #

def write_manifest(
    path: Path,
    default: str,
    self_info: dict,
    rows: list[Row],
) -> None:
    """Write the machine-readable manifest the apply script consumes."""
    manifest = {
        "generated_by": GENERATED_BY,
        "default_branch": default,
        "self": self_info,
        "rows": [asdict(r) for r in rows],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

def run_scan(args: argparse.Namespace) -> None:
    use_gh = (not args.no_gh) and gh_available()
    default = default_branch()

    # Anchor everything on the *main* checkout. `current_git_common_dir()` points
    # at the shared `.git`; its parent is the main working tree — which is where
    # `.claude/worktrees/` and every worktree directory actually live. When the
    # scan is run from the main checkout this equals `repo_root()`; from inside a
    # worktree it does not, and only the common-dir parent finds the orphans.
    main_root = current_git_common_dir().parent.resolve()
    self_path = repo_root().resolve()
    self_branch = current_branch()
    worktrees_dir = main_root / ".claude" / "worktrees"

    registered = list_registered_worktrees()
    registered_paths = {wt.path.resolve() for wt in registered}
    backing_branches = {wt.branch for wt in registered if wt.branch}

    print("repo-hygiene scan (read-only)")
    print(f"  default branch: {default}")
    print(f"  gh:             {'online' if use_gh else 'offline (skipped)'}")
    print(f"  main checkout:  {main_root}")
    print(f"  current - skipped (self): {self_path} "
          f"[{self_branch or '(detached)'}]")

    wt_rows = scan_worktrees(
        registered, registered_paths, worktrees_dir,
        self_path, main_root, default, use_gh=use_gh,
    )
    # Branches backing a live worktree, the current branch, and the default are
    # off-limits for branch pruning.
    excluded_branches = set(backing_branches)
    if self_branch:
        excluded_branches.add(self_branch)
    branch_rows = scan_branches(excluded_branches, default, use_gh=use_gh)

    print_table("Dimension 1 - Worktrees", wt_rows)
    print("  note: apply will also run `git worktree prune` to clear stale "
          "metadata for the inverse case (registered but directory gone).")
    print_table("Dimension 2 - Stale merged local branches", branch_rows)
    report_github(branch_rows, use_gh=use_gh)

    all_rows = wt_rows + branch_rows
    counts = {SAFE: 0, UNSAFE: 0, NEEDS_REVIEW: 0}
    for r in all_rows:
        counts[r.verdict] = counts.get(r.verdict, 0) + 1
    print(f"\nSummary: {counts[SAFE]} safe, {counts[UNSAFE]} unsafe, "
          f"{counts[NEEDS_REVIEW]} needs-review "
          f"({len(all_rows)} candidate(s); self excluded).")

    if args.json:
        self_info = {"path": str(self_path), "branch": self_branch or None}
        write_manifest(Path(args.json).resolve(), default, self_info, all_rows)
        print(f"\nWrote manifest -> {Path(args.json).resolve()}")


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Read-only scan classifying git-cleanup candidates "
                    "(worktrees, branches, GitHub housekeeping).",
    )
    ap.add_argument("--json", metavar="PATH",
                    help="write the machine-readable manifest to PATH "
                         "(a scratch/throwaway path — the only file written)")
    ap.add_argument("--no-gh", action="store_true",
                    help="force the offline path (skip gh; exercise the "
                         "ancestor-only merge fallback)")
    args = ap.parse_args()

    # Read-only tool: never fail the caller. Any unexpected error is reported
    # but the exit stays 0 so it is safe in automation.
    try:
        run_scan(args)
    except Exception as exc:  # noqa: BLE001 - deliberate: guarantee exit 0
        print(f"scan aborted (reported, non-fatal): {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
