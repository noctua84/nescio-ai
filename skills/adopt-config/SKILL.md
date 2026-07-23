---
name: adopt-config
description: Discover pre-existing Claude config on this machine (files install.py won't overwrite, plus other known sources) and integrate the worthwhile parts into this repo. Two-stage flow (adopt inbox -> adopted archive) with a tracked ledger so nothing is evaluated twice. Use when setting up on a new machine, when the installer reports "exists and is not a symlink", or to learn from prior config/memory.
user-invocable: true
---

# /adopt-config

Adopt Claude configuration that already exists on this machine into the repo, so
the setup can absorb — and learn from — what was here before it was managed.

## The two-stage model

| Location | Role | Tracked? |
|----------|------|----------|
| `eval/adopt/<ts>/` | **Inbox** — discovered, needs evaluation | no (gitignored) |
| `eval/adopted/<ts>/` | **Archive** — processed runs | no (gitignored) |
| `memory/adoption-log.md` | **Ledger** — what was adopted, when, and its disposition (≤150 lines) | **yes** |

The ledger is the dedup source: it's keyed by a short content hash, so a scan on
any machine skips sources already recorded terminal (`integrated` / `no-change` /
`dropped`). `pending` items re-surface into the inbox until resolved. The raw
`eval/` trees stay machine-local — only the compact ledger syncs.

## When to use

- The installer reported `N existing real file(s) block symlinking:` — a real
  file/dir (e.g. `~/.claude/agents`, `memory`, or `skills`) sitting where it wants
  a symlink. (`settings.json` and `CLAUDE.md` are integrated by the `--settings` /
  `--claude-md` consent steps, not symlinked, so they never appear here.)
- Setting up on a machine that already had Claude Code / Desktop use.
- Pulling prior per-project memory (`~/.claude/projects/*/memory/`) into the repo.

## Step 1 — Discover & stage (mechanical)

```bash
python scripts/adopt_existing_config.py     # or python3
```

Copies not-yet-processed sources into `eval/adopt/<ts>/` with a `MANIFEST.md`
(and a machine-readable `sources.json`). Skips sources already recorded terminal
in the ledger, and sources already symlinked into the repo. Prints how many were
staged vs skipped.

## Step 2 — Review the inbox

Read `eval/adopt/<ts>/MANIFEST.md`. Each row shows the source, its `sha8`, and
whether it's `new` or `pending since <date>`.

## Step 3 — Integrate (judgment)

Reconcile each item into the tracked repo. Never blind-copy — merge intent.

| Item | How to integrate |
|------|------------------|
| `CLAUDE.md` | Diff against the repo's; merge instructions not already present; machine-specific lines go to `CLAUDE.local.md`. |
| `settings.json` | Merge permissions / `enabledPlugins` / model into the repo's; keep the union of `allow` rules. |
| `settings.local.json` | **Do not commit.** Merge into the repo's (gitignored) `settings.local.json`. |
| `dot-claude.json`, `claude_desktop_config.json` | Inspect for MCP servers / plugins worth declaring in the tracked `settings.json`. **Secrets never enter tracked files** — `CLAUDE.local.md` / OS keychain only. |
| `agents/`, `commands/`, `skills/` | Copy any good definitions not already in the repo into the matching folder. |
| `project-memory/<slug>/` | Curate into `memory/` via `/harvest-memory` — per-repo learnings to `memory/repo/<repo>/`, broader to `memory/projects/<project>/` or `memory/feedback/`. |

## Step 4 — Archive & record (closes the loop)

Once a run is integrated, promote it — this moves it to the archive and writes
the ledger so it's never re-evaluated:

```bash
python scripts/mark_adopted.py <ts> --status integrated --note "what you did"
```

`--status`: `integrated` (merged), `no-change` (nothing to merge), `dropped`
(deliberately discarded) — all terminal — or `pending` (leave for later; it will
re-surface on the next scan). Use `--note` for a one-line disposition; hand-edit
`memory/adoption-log.md` afterwards if individual items need different notes.
Keep the ledger under 150 lines — compact oldest entries when the script warns.

## Step 5 — Re-run the installer

Once merged, turn the superseded real files under `~/.claude` into symlinks:

```bash
python install.py --relink        # back up each real file to *.pre-adopt-<ts>.bak, then symlink
python install.py --relink --dry-run   # preview first
```

`--relink` never deletes — it backs up each conflicting real file to
`*.pre-adopt-<ts>.bak`, then symlinks it. `settings.json` and `CLAUDE.md` are the
exceptions: they're **not** symlinked. `settings.json` is deep-merged into a real
`~/.claude/settings.json` (the adopted keys win; your `allow` list and other keys
are preserved) per the `--settings` choice, and `CLAUDE.md` is integrated per
`--claude-md` (import / replace / skip). You can instead back up the files by hand
and re-run `python install.py` (which detects the conflict and stages it for review).

## Guardrails

- **Copy-and-catalogue only** — scripts never edit `~/.claude`; you decide what merges.
- **Secrets never enter tracked files** — tokens/keys/hostnames go to `CLAUDE.local.md` / keychain.
- **Don't hand-delete `eval/adopted/`** — it's the local audit trail; the ledger is the synced record.

## Tier-2: harvesting a target repo's review-learnings

Repos wired with the Claude PR-review action (see `github-action/`) accumulate
learnings in their own `.claude/memory/review-learnings/`. To pull the
non-employer-specific ones into this brain: clone/pull the target repo, then
treat its `.claude/memory/review-learnings/` as a source — copy the worthwhile
notes into `memory/repo/<repo>/` here (curate, don't bulk-copy), the same way
`/harvest-memory` promotes per-project memory. Employer-specific learnings stay
in the target repo.
