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

1. **Open the harvest, then read the sources.** Before reading anything, declare
   what this pass is about to read:

   ```bash
   python scripts/begin_harvest.py
   ```

   This captures the **read-time** *and* the **trail list** in one act, writing
   `read.json` into a fresh staging dir (`eval/learnings/<UTC timestamp>/` by
   default; override with `--out <dir>`). The manifest records, per trail, the
   file's basename, the repo it belongs to, how many records it holds, and the
   newest record in it (`max_ts`). Keep the printed path — step 5's
   `manifest.json` and step 7's `receipt.json` land in the same directory, and
   step 8 stamps *from* `read.json`.

   Capturing both together is the whole point: it is what makes the later stamp
   **verifiable**. The watermark asserts "these records were read and
   considered", and the Stop-hook pruner deletes on the strength of that
   assertion. If the stamping step had to infer its own scope minutes later, it
   would be guessing — and a guess that overstates coverage silently destroys
   undistilled session exhaust. Because the read and the stamp cite the same
   file, the stamp can only ever cover what this step wrote down.

   By default the subject is the **current repo**. If you genuinely intend to
   read another repository's trail too, widen the scope deliberately:

   ```bash
   python scripts/begin_harvest.py --repo ../other-repo --repo ../third-repo
   ```

   `--repo` is additive and repeatable; the current repo is always included. It
   is the *only* way to widen scope, and it leaves a record in `read.json` —
   an explicit, audited act rather than an invisible default. Do not pass it for
   repos you are not actually going to read.

   `begin_harvest.py` prints the read-time, the `read.json` path, and a per-repo
   trail/record count. A subject repo with no trails is reported rather than
   refused — that just means step 8 will stamp nothing for it.

   Then, for the declared subject, list and read every producer under
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
5. **Draft nominations into a staging manifest.** Write the candidates to
   `manifest.json` inside the gitignored staging dir step 1 created —
   `eval/learnings/<timestamp>/manifest.json`, beside that run's `read.json`
   (mirrors the adopt flow's `eval/adopt/<ts>/` staging inbox — nothing is
   committed yet). The manifest is a JSON list of nomination objects:

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

   Alongside the notes and the ledger it also drops a **`receipt.json`** beside
   the manifest (same `eval/learnings/<timestamp>/` dir), recording what this
   pass actually did: the manifest it consumed, how many notes were promoted and
   skipped, the targets written, and when. The summary names its path. The
   receipt is an **audit record, not a gate** — you can hand it to step 8 with
   `--receipt`, where it produces warnings (notably when `promoted` is 0), but it
   can never block a correctly-declared stamp. `--dry-run` names where the
   receipt would go and writes none.
8. **Stamp the harvest watermark (scoped to the trails step 1 declared).** Run,
   passing the `read.json` written by `begin_harvest.py` — and, optionally, the
   receipt from step 7:

   ```bash
   python scripts/mark_harvested.py --read eval/learnings/<timestamp>/read.json \
       --receipt eval/learnings/<timestamp>/receipt.json
   ```

   The manifest **is** the scope. Only the trails `read.json` names are stamped;
   nothing else under `<config>/learning-trail/` is touched. Each of those trails
   gets its **own `max_ts`** — the newest record that file actually held when
   step 1 opened it — never a single global read-time. That is what makes the
   watermark honest: it can never claim coverage past the last record actually
   seen in that file.

   The Stop-hook pruner reads that watermark: records at or below it count as
   reviewed and age out on the normal retention window, and records above it are
   never pruned.

   Three properties worth knowing:

   - **Never backward.** A trail whose watermark is already newer than this
     manifest's `max_ts` is left alone and reported as unchanged. A concurrent or
     later harvest cannot be undone by an older one replaying its manifest.
   - **Records written after the read stay protected.** Anything appended to a
     trail after step 1 scanned it — including this harvest session's own turns —
     is above that trail's `max_ts` and therefore above the watermark. Deriving
     the stamp from what was actually read, rather than from `now()`, is what
     prevents the harvest from marking its own in-flight exhaust as harvested and
     aging it out undistilled.
   - **A trail with nothing in it is skipped, not stamped.** An entry whose
     `max_ts` is null (no parseable records), or whose file has since vanished,
     is reported as skipped. There is no timestamp that was honestly read, so
     none is written.

   **Refusing to stamp is not failing.** If `--read` is missing, unreadable, not
   valid JSON, of an unknown schema version, or names no usable trail, the script
   writes **nothing**, prints a banner with the exact re-run command, drops a
   `.harvest-pending-<repo_key>` marker in the learning-trail dir (keyed per repo, so
   one repo's unfinished harvest never clears or masks another's) — and **returns 0**. That
   is deliberate: this step runs after the notes, the ledger, `MEMORY.md` and
   `readiness.md` are already on disk, so exiting non-zero here would strand you
   with memory changed and the trail unstamped. `hooks/harvest_nudge.py` surfaces
   the pending marker at the next session start so the unfinished harvest is
   remembered; a successful stamp clears it. If you see that banner, fix the
   manifest path and re-run the command it prints — do not hand-edit watermarks.

   Warnings from `--receipt` (an unreadable receipt, a wrong schema version, or
   `promoted: 0`) are printed and then the stamp proceeds. Reading a trail and
   deciding to keep nothing is a legitimate harvest; the trail was still read.

   If a *previous* stamp went wide and marked trails that were never read, see
   [Reverting a bad stamp](#reverting-a-bad-stamp).
9. **Update readiness.** For each repo touched, update
   `memory/repo/<repo>/readiness.md` — bump `last_updated`, refresh the rolling
   outcome summary, and add or clear recurring flags. This is the tracked
   summary Phase 3's autonomy dial reads; see `memory/repo/myrepo/readiness.md`
   for the format. Stage only that file.

   The **counted** part — turns, sessions, span, recency, un-harvested turns,
   promotion density — is computed for you. Preview it, then write it:

   ```bash
   python scripts/compute_readiness.py            # dry run, all repos
   python scripts/compute_readiness.py --apply    # write the generated block
   ```

   It rewrites only the bytes between the `<!-- readiness:generated start -->`
   / `end` markers (adding them if absent) and bumps `last_updated` when the
   block changed. Everything outside stays exactly as you wrote it, and a repo
   with no `memory/repo/<name>/` dir is skipped rather than created. The
   judgement stays yours: the outcome summary and the recurring flags are not
   derivable from the trail, so the script emits an explicit *insufficient
   data* note there instead of a number, and you write the real thing by hand.
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

## Reverting a bad stamp

Not part of the routine flow — only for cleaning up after a watermark that was
written over trails nobody read (a pre-manifest global stamp, or a `--repo` list
that was wider than the actual read). `scripts/unmark_harvested.py` deletes the
watermark files matching one exact stamp, so the records they covered count as
un-harvested again and stop being eligible for pruning:

```bash
# dry run by default — prints the plan, deletes nothing
python scripts/unmark_harvested.py --stamp "<the-bad-ISO8601-instant>" \
    --keep-repo /path/to/the/repo/that/was/really/read

# same command with --apply actually deletes them
python scripts/unmark_harvested.py --stamp "<the-bad-ISO8601-instant>" \
    --keep-repo /path/to/the/repo/that/was/really/read --apply
```

`--stamp` is compared as a parsed datetime, so an equivalent spelling in another
offset still matches. `--keep-repo` is repeatable and exempts the repo whose
stamp was legitimately earned (and its linked worktrees' trails). Always read the
dry run before adding `--apply`.

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
- Never widen the harvest's scope after the read. Scope is declared once, at
  step 1, by `scripts/begin_harvest.py` — including any `--repo` you pass — and
  step 8 stamps that declaration and nothing else. If you realise mid-pass that
  another repo's trail belongs in scope, open a fresh harvest for it rather than
  editing `read.json` to cover records you never opened.
- Do not delete the source stores unless the user asks; harvesting is a copy +
  curate, not a move. The learning-trail pruning is harvest-aware: within each
  trail, records newer than that trail's watermark (stamped by step 8's
  `scripts/mark_harvested.py`, at that trail's own `max_ts`) are never pruned;
  the 14-day retention window applies only to already-harvested records. A trail
  no harvest ever declared has no watermark at all, so age alone never prunes it
  — only the absolute record ceiling does.
