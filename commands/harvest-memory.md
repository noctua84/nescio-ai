---
name: harvest-memory
description: Promote durable learnings from the machine-local per-project memory store into the version-controlled repo memory/ so they sync across machines.
user-invocable: true
---

# /harvest-memory

Promote learnings from the **machine-local** per-project store
(`~/.claude/projects/<path-slug>/memory/`) into the **version-controlled** repo
`memory/` tree, so they persist across machines and can be shared.

## Why this exists

Two memory stores coexist:

- `~/.claude/projects/<path-slug>/memory/` — where session-captured memory lands
  automatically. Keyed by the absolute clone path → **machine-local, not synced,
  not portable**.
- repo `memory/` (symlinked to `~/.claude/memory` by `install.py`) —
  **version-controlled and synced** across machines.

This command curates the former into the latter. Nothing here is automatic;
you review each item before it's committed to the repo.

## Sources

Three producers feed the same promotion. All are machine-local, unreviewed, and
never synced on their own — this command is the one gate that distils them into
durable repo memory:

- `~/.claude/projects/<path-slug>/memory/` — session-captured auto-memory (the
  original source).
- `<config>/learning-trail/*.jsonl` — the per-turn activity trail written by the
  `record_stop.py` Stop hook, where `<config>` is `$CLAUDE_CONFIG_DIR` or
  `~/.claude`. One JSONL file per repo (`<repo-key>.jsonl`), pruned to a rolling
  window; raw session exhaust, not conclusions.
- the current project's `.claude/memory/review-learnings/` — durable
  regression / security / architecture notes the GitHub PR-review action
  committed into the target repo (see `github-action/`). Present only in repos
  wired with that pipeline.

## Destination layout

- `memory/repo/<repo-name>/` — learnings scoped to one repository.
- `memory/projects/<project-name>/` — broader learnings spanning several repos
  under one initiative (e.g. `webplatform` covering `web-app`,
  `web-api`, `shared-ui`).
- `memory/glossary.md`, `memory/people/`, `memory/context/` — cross-cutting
  global facts.

## Steps

1. **Read the sources.** First, capture a **read-time UTC timestamp** and hold
   onto it for the watermark step (step 8):

   ```bash
   python -c "from datetime import datetime,timezone; print(datetime.now(timezone.utc).isoformat())"
   ```

   Then, for the current project, list and read every producer under
   [Sources](#sources): the auto-memory store, the learning-trail JSONL (when
   present), and `.claude/memory/review-learnings/` (when present). If all three
   are absent or empty, report that and stop.
2. **Classify each learning** by scope:
   - Specific to one repo → `memory/repo/<repo-name>/`
   - Spans multiple repos in an initiative → `memory/projects/<project-name>/`
   - Global (glossary term, person, standing preference) → the matching
     top-level `memory/` file.
3. **Deduplicate.** Check the destination first. Update an existing note in
   place rather than creating a near-duplicate; drop anything already captured
   or since proven wrong. (The promote tool also skips anything already in
   `memory/learning-log.md` by body hash — this step is the human pass that
   catches near-duplicates the hash won't.)
4. **Rewrite for portability.** Strip machine-specific absolute paths where a
   repo-relative path works. Keep the *why*, not just the *what*.
5. **Draft nominations into a staging manifest.** Write the candidates to a
   gitignored `eval/learnings/<timestamp>/manifest.json` (mirrors the adopt
   flow's `eval/adopt/<ts>/` staging inbox — nothing is committed yet). The
   manifest is a JSON list of nomination objects:

   | Field | Meaning |
   |---|---|
   | `scope` | Top-level `memory/` bucket the note lands in: `repo/<name>` \| `projects/<name>` \| `context` \| `feedback` \| `people` \| `glossary`. The bucket (part before any `/`) is validated. |
   | `target` | The note's real path under `memory/`, e.g. `repo/myrepo/readiness-loop.md` or `feedback/bar.md`. Must stay inside `memory/`. |
   | `name` | Short identifier / note title. |
   | `description` | One-line index summary (the text used in the `MEMORY.md` link). |
   | `type` | The note's frontmatter type, e.g. `feedback` \| `context` \| `adr` \| `convention` \| `preference` \| `regression` \| `security` \| `architecture`. Open-ended; checked only for presence. |
   | `body` | The note body (markdown), portability-rewritten per step 4. |
   | `source` | Source class: `user override` \| `empirical` \| `agent inference`. |
   | `date` | `YYYY-MM-DD` the learning was observed. |

   All fields are required; a nomination missing any of them (or naming a
   `scope` bucket / `source` outside the sets above, or a `target` that escapes
   `memory/`) is rejected before anything is written.

   Pick `source` by where the learning actually came from — an explicit user
   instruction is a `user override`, an observed test/CI/runtime outcome is
   `empirical`, and a conclusion you reasoned to is `agent inference`. It drives
   the provenance tag and contradiction resolution the promote tool applies
   (precedence `user override` > `empirical` > `agent inference`, ties broken by
   recency); you don't render the tag yourself.

   Example nomination:

   ```json
   [
     {
       "scope": "repo/myrepo",
       "target": "repo/myrepo/install-relink-symlink.md",
       "name": "install --relink keeps ~/.claude intact",
       "description": "why --relink backs up before symlinking; the no-symlink fallback",
       "type": "convention",
       "body": "`install.py --relink` backs up each real file to `*.pre-adopt-<ts>.bak` before symlinking...",
       "source": "empirical",
       "date": "2026-07-12"
     }
   ]
   ```

6. **Present a summary** of the drafted nominations — scope, target, source
   class, and date for each — and ask for explicit confirmation before anything
   is written or committed.
7. **Promote.** On confirmation, run the committer against the manifest:

   ```bash
   python scripts/promote_learnings.py eval/learnings/<timestamp>/manifest.json
   ```

   It writes each note under `memory/`, tags it with the provenance line,
   resolves contradictions against any existing note, appends to
   `memory/learning-log.md`, and prints one summary line per note it wrote or
   updated. It does **no git work at all** — nothing is staged, and freshly
   created notes are left untracked. Keep that summary: it is the list of paths
   you stage by hand in step 10. Do not restate its logic here; read
   `scripts/promote_learnings.py` and `scripts/_learning_common.py` for the
   details.
8. **Stamp the harvest watermark (GLOBAL, at the read-time).** Run, passing the
   read-time timestamp captured in step 1:

   ```bash
   python scripts/mark_harvested.py --at "<read-time-ISO8601>"
   ```

   This is **global**: `/harvest-memory` reads every repo's trail, so stamping
   covers **all** trails under `<config>/learning-trail/`, not just the current
   repo's. Each trail's `.watermark` is set to the read-time, so the Stop-hook
   pruner treats everything the harvest could have seen as reviewed and protects
   only newer (un-harvested) records from the retention window.

   Two consequences of the global model to be aware of:

   - Anything you **read but consciously did not promote** is now marked
     reviewed up to the read-time and will age out on the normal retention
     window — that is intended under the global model, not a bug.
   - Records written **after** the read-time — including this harvest session's
     own turns — are newer than the watermark and stay protected. Stamping the
     read-time rather than `now()` is what prevents the harvest from marking its
     own in-flight exhaust as harvested and aging it out undistilled.
9. **Update readiness.** For each repo touched, update
   `memory/repo/<repo>/readiness.md` — bump `last_updated`, refresh the rolling
   outcome summary, and add or clear recurring flags. This is the tracked
   summary Phase 3's autonomy dial reads; see `memory/repo/myrepo/readiness.md`
   for the format. Stage only that file.
10. **Deliver via branch + PR — never commit the harvest on `main`.** The
    harvest itself has to run in the **main checkout**, not a worktree:
    `~/.claude/memory` symlinks to `<repo>/memory` and
    `scripts/promote_learnings.py` writes relative to the repo root, so promoted
    notes necessarily land in the shared clone's working tree. Deliver them from
    a branch rather than committing where you happen to be standing:

    ```bash
    # staged changes travel with the switch
    git switch -c chore/memory-harvest-<YYYY-MM-DD>

    # the exact paths this harvest wrote: every note from step 7's summary, the
    # ledger, and the readiness file from step 9 — enumerated, never globbed
    PATHS="memory/<scope>/<note>.md memory/learning-log.md memory/repo/<repo>/readiness.md"

    # stage by path. This step is on you: promote_learnings.py stages nothing,
    # and a newly created note is untracked until it is added.
    git add $PATHS

    # commit scoped to those same paths, so unrelated working-tree noise
    # (.idea/, …) and any concurrent session's staged work stay out of it.
    # Do NOT use `git commit memory/ -m ...`: that form commits tracked
    # modifications only and silently drops every note just created.
    git commit -m "chore(memory): harvest <session> learnings" -- $PATHS

    git push -u origin chore/memory-harvest-<YYYY-MM-DD>

    # PR body: summarise each promoted note (scope, target, source class) and
    # reference the issue
    gh pr create --base main

    # hand the shared clone back
    git switch main
    ```

    **Why:** `main` is unprotected, so a direct commit lands unreviewed. The PR
    is the review gate and the audit trail for content every future session will
    read as authoritative.

    **Caveat:** keep the branch switch brief — the clone is shared with
    concurrent sessions (an active instance routinely has several worktrees and
    parallel harvests open). Commit promptly and switch back to `main`. If
    another session has staged work sitting in the index, do **not** sweep it
    into your commit; commit only the paths this harvest wrote.

## Guardrails

- Never promote credentials, tokens, internal hostnames, or anything that
  shouldn't live in a shareable repo — those belong in `CLAUDE.local.md` only.
- Nothing is written or committed without the explicit human confirmation in
  step 6.
- Never `git add -A`. The promote tool stages nothing at all, so staging is the
  operator's job: `git add` each promoted note (from the tool's summary), the
  ledger, and the readiness update — every one of them by path.
- Never commit the harvest on `main` — deliver through a branch + PR (step 10).
  `main` is unprotected, and an unreviewed memory note silently misleads every
  future session that reads it.
- Do not delete the source stores unless the user asks; harvesting is a copy +
  curate, not a move. The learning-trail pruning is now harvest-aware: records
  newer than the last harvest watermark (stamped by step 8's
  `scripts/mark_harvested.py`) are never pruned; the 14-day retention window
  applies only to already-harvested records.
