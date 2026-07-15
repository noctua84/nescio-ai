---
name: repo-hygiene
description: Clean git clutter in this repo — remove merged and orphaned worktrees under .claude/worktrees/, delete stale merged local branches, and report merged-PR / closed-issue housekeeping. Read-only scan by default; destructive steps require an explicit --apply/typed yes and never touch GitHub or the worktree you're standing in. Use when worktrees or branches have piled up after merges.
user-invocable: true
---

# /repo-hygiene

Clean git clutter along three dimensions — leftover **worktrees** under
`.claude/worktrees/`, **stale merged branches** with no worktree, and **GitHub
housekeeping** (merged PRs with still-open issues) — driven by a read-only scan
that runs first and mutates nothing. Nothing destructive happens without an
explicit, typed human `yes`; the two scripts split the work so detection is
always dry-run and removal is always guarded. Safety-first is the whole point:
this skill would rather leave a candidate untouched than delete something a
snapshot got wrong.

## When to use

- After one or more PRs merge and the worktrees / branches they spawned pile up.
- When `git worktree list` has grown long enough to be hard to read, and you
  can't tell at a glance which entries are safe to drop.
- When an orphan directory lingers under `.claude/worktrees/` — a folder whose
  branch is gone, or whose worktree registration git no longer tracks.

## Run from a safe checkout

You cannot remove the worktree you are standing in — git refuses, and so does
this skill. Run it from the main checkout
(e.g. `~/dev/your-repo`) or from any non-target worktree. The
scan self-excludes the current worktree and its branch automatically, so it can
never nominate the ground under your feet as a candidate. But standing in **main**
is still the better habit: from there every sibling worktree is removable, and
nothing you want cleaned gets silently skipped just because you happened to be
inside it.

## The three dimensions

| Dimension | What it covers | Action class |
|-----------|----------------|--------------|
| **Worktrees** | Worktrees whose branch is merged, plus orphan directories under `.claude/worktrees/` (branch gone or registration stale); runs `git worktree prune` to clear dangling metadata. | Destructive (guarded) |
| **Stale merged branches** | Local branches with no attached worktree whose tip is merged into the default branch. | Destructive (guarded) |
| **GitHub housekeeping** | Merged PRs whose linked issue is still open; branches already merged on GitHub. | **Report-only** — never written |

## Step 1 — Scan (read-only)

```bash
python scripts/repo_hygiene_scan.py                 # human-readable tables
python scripts/repo_hygiene_scan.py --json <path>   # also persist a manifest for apply
python scripts/repo_hygiene_scan.py --no-gh         # force the offline path (skip gh)
```

The scan detects candidates across all three dimensions and prints **one
classification table per dimension**. Each row is a single candidate with a
**verdict** and the **reason** behind it:

| Verdict | Meaning |
|---------|---------|
| `safe` | Confirmed removable — merged, clean, not-self, and (for branches) authority-confirmed. |
| `unsafe` | Do not touch — open PR, dirty tree, unmerged, or the current worktree/branch. |
| `needs-review` | Inconclusive — a human must eyeball it (e.g. `gh` was offline so a squash-merge couldn't be confirmed). |

Pass `--json <path>` to write a machine-readable manifest that Step 4 consumes;
`--no-gh` forces the offline ancestor check even when `gh` is available. The scan
mutates nothing and exits `0`.

## Step 2 — Read the table

Verdicts map directly to what the apply step will and won't do:

- `safe` rows are the only ones apply will act on.
- `unsafe` rows are skipped outright — they never become removal candidates, and
  the reason column tells you why (open PR, dirty worktree, unmerged tip, or
  self).
- `needs-review` rows need a human eyeball before anything happens. The usual
  cause is that `gh` was offline or missing, so a squash-merge couldn't be
  confirmed by the authority signal and the fallback couldn't prove the merge
  either (see **How merge is detected**). Treat these as "decide manually," not
  as "delete."

## Step 3 — Confirm

Before anything destructive runs, present the `safe` rows that **would** be
deleted — grouped by dimension — and ask the user for an explicit typed `yes`.
Nothing destructive proceeds without it; silence, an emoji, or an ambiguous
"sure, go on" is not the typed confirmation.

If the user approves only part of the plan ("only the worktrees", "leave the
branches"), do **not** improvise a partial deletion by hand — re-scan and filter
to the approved dimension so the manifest apply consumes matches exactly what was
agreed. Improvising defeats the re-verification contract in Step 4.

## Step 4 — Apply (guarded)

```bash
python scripts/repo_hygiene_apply.py --apply --yes --from <manifest.json>
```

`repo_hygiene_apply.py` reads the manifest produced by `--json` in Step 1 and
**re-verifies each item in-process** immediately before acting — it never trusts
the scan's earlier snapshot. Without `--apply` the script is inert: it prints
exactly what it would do and exits `0`, changing nothing. The `--apply` flag plus
`--yes` (the recorded human confirmation from Step 3) are both required for any
removal to happen. Items that fail re-verification at apply time are skipped and
reported, not forced.

## Step 5 — GitHub housekeeping (report only)

Dimension 3 is surfaced, never executed. The scan lists merged PRs whose linked
issue is still open, and branches already merged on GitHub. The model presents
this list and **stops**. This skill never writes to GitHub — closing an issue,
deleting a remote branch, or commenting on a PR each requires a separate, explicit
instruction from the user in a later step. Reporting is the end of the line here.

## Guardrails

- Self-exclusion: the worktree and branch the skill runs in are detected and never appear as candidates.
- Dry-run by default: scan mutates nothing; apply without `--apply` only prints. Destructive commands require `--apply` + a typed human `yes`.
- Re-verify atomically: apply re-reads worktree list, merged status, clean-tree, and not-self in the same process invocation as each removal — never trusting the scan's earlier snapshot (this repo produced contradictory `git worktree list` output within one session).
- Never force-delete blind: `git branch -D` only when the `gh` authority confirmed merged (`gh-merged` signal) **and** the branch carries no commits ahead of its upstream/default (no un-integrated local work); never on offline-inconclusive.
- `rm -rf` only on a clean, verified orphan; dirty orphans are `unsafe`, and an orphan that gained files after the scan is re-checked and skipped (`not-empty-on-recheck`). Removal targets are confined to `.claude/worktrees/`.
- Open PR or unmerged/uncommitted ⇒ untouchable.
- Default branch is dynamic (resolved from `origin/HEAD`), never hardcoded to `main`.
- `gh` degrades gracefully: missing/offline → fallback ancestor check; ambiguous → `needs-review`, not a silent delete.
- No GitHub writes: dimension 3 is report-only.

## How merge is detected

A branch is only ever called merged on a **two-signal** rule, and understanding
it explains exactly when a row lands in `needs-review`:

- **Authority (online):** `gh pr list --state merged --head <branch>`. This is
  the trustworthy signal because it catches **squash-merges** — where the branch
  tip never becomes an ancestor of the default branch, yet the PR is genuinely
  merged.
- **Fallback (offline / `gh` missing):** `git merge-base --is-ancestor <tip>
  <default>`. This catches **true merge-commits only**. It **misses
  squash-merges**, because after a squash the original tip is not an ancestor of
  the default branch.

So when `gh` is unavailable **and** the ancestor check is false, the branch is
classified `needs-review` — not deleted. An ancestor-false result offline could
be a genuinely unmerged branch, or it could be an unrecognized squash-merge; the
skill refuses to guess and never auto-deletes in that state.
