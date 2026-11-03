---
name: after a squash merge, gh is the only merge authority
description: why repo_hygiene_scan trusts gh over git merge-base, and why 30 branches read as unsafe
type: context
---
<!-- promoted:begin -->
This repo squash-merges. After a squash the branch tip is **never** an ancestor of the default branch, so `git merge-base --is-ancestor` and `git branch --contains` report the branch as unmerged forever, however completely its content landed.

That is why `scripts/repo_hygiene_scan.py` uses `gh pr list --state merged --head <branch>` as its authority signal and falls back to the ancestor check only when `gh` is unavailable — and why, offline, an ancestor-false branch is classified `needs-review` rather than deleted. Offline it cannot tell a genuinely unmerged branch from an unrecognised squash.

Two practical consequences, measured on 2026-11-02:

- **A large `unsafe` count is mostly conservatism, not risk.** Of 86 candidates, 30 came back unsafe, most flagged `gh-merged; ahead` — the normal post-squash state. Two of them (`fix/test-module-aliasing`, `test/resolve-dir-coverage`) were known with certainty to be fully merged, as `003d94e` and `a0c453c`. The scan is right to withhold; the number should not be read as 30 branches holding real work.
- **The `dirty` signal is driven by unpushed commits, not working-tree dirt.** Of six worktrees labelled `uncommitted-or-unpushed ... dirty`, four reported zero modified files under `git status --porcelain`, and one of the other two had a single `__pycache__` entry. Check the tree directly before believing the label.

Also worth knowing: `gh pr merge --squash --delete-branch` exits non-zero when the default branch is checked out in another worktree (`fatal: 'main' is already used by worktree`) **after** the merge and remote branch deletion have both succeeded. The non-zero exit means the local post-merge checkout failed, not the merge. Verify with `gh pr view --json state,mergeCommit` and `git ls-remote` before concluding anything failed.
[Source: empirical — 2026-11-02]
<!-- promoted:end -->
