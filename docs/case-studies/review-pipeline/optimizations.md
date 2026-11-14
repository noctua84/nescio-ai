# Case study: hardening a Claude PR-review pipeline

**Date:** 2026-11-13 – 2026-11-14
**Companion to** [`pipeline.md`](pipeline.md), which covers what the pipeline does and why.
**Scope:** PR 258, PR 259, PR 261, PR 263 and PR 265 in this repo, plus the follow-ups they raised.

Over two days, five PRs reworked this repo's reusable Claude review workflow
(`github-action/claude-review-core.yml`). This file records what was wrong, how it
was found, which options were weighed, what was chosen and what it cost. It is
raw material for an article, so it also records the mistakes made along the way.

A downstream organisation runs a private fork of the core. Its name is left out
here; it is called **the downstream fork**.

---

## Starting point

Two review setups existed side by side:

| | Scaffold (`.github/workflows/claude-code-review.yml`, PR 258) | Full template (`github-action/claude-review-core.yml`) |
|---|---|---|
| Size | ~45 lines | ~710 lines |
| Engine | the `code-review` plugin, `/code-review:code-review --comment` | a long custom prompt (incremental review, markers, verdict) |
| Merge gate | none | a second job turns the verdict into a formal review |
| Memory | none | "review learnings": notes the reviewer writes back into the repo |
| Consumers | this repo only | installed into other repos by `scripts/install_github_action.py`; forked downstream |

The question was whether the full template was overkill for this repo, and why
"saving review memory does not fully work".

**Decision on scope:** the scaffold stays the engine for this repo, and only gets
the cheap fixes (skip rules, concurrency, pinning). The full template is the
product other repos consume, so that is where the security and correctness work
went.

---

## 1. Cheap wins on the scaffold (PR 259)

| Problem | Fix |
|---|---|
| Release-please PRs ended in `action_required`; bot PRs and drafts burned runs | Job-level `if:` skips drafts, `dependabot[bot]`, `github-actions[bot]`, `release-please--*` heads and a `skip-claude-review` label |
| Every push started a new review while the old one was still running | `concurrency: claude-review-<pr>` with `cancel-in-progress: true` |
| Action referenced by moving tag | Pinned to a commit SHA |

**Mistake, later reverted.** The first version also skipped `claude/*` head
branches, to stop the reviewer reviewing its own learning PRs. That was redundant
and harmful:
- Learning PRs are opened with `GITHUB_TOKEN`, and GitHub never starts
  `pull_request` workflows for PRs that token creates.
- They are authored by `github-actions[bot]`, which was already skipped.
- So the rule's only effect was to exclude every Claude Code session PR — the PRs
  that most need a second reader.

The skip was removed from the repo workflow before PR 259 merged. After that,
the review ran on PR 261, PR 263 and PR 265, which were themselves review-pipeline
fixes. (The installable snippet,
`github-action/claude-review-automatic.snippet.yml`, still carries the
`claude/*` skip — see Open items.)

---

## 2. Why review memory was never saved (PR 259)

**Symptom:** the review ran, but no learning note ever appeared.

**Root cause:** Claude Code treats `.claude/` as a protected directory. In a
headless (`-p`) run, a `Write` into `.claude/memory/review-learnings/` is denied
even though `Write` is in the allow-list. The prompt's "Step 7" asked Claude to
write the note, commit and push — the first action always failed, silently.

Four more defects sat behind it:

| Defect | Effect |
|---|---|
| Fixed branch name per PR | A second learning, or a re-run, collided with the first |
| Dedup checked only the PR head | Notes waiting in open learning PRs were invisible, so duplicates were possible |
| Learning step ran last in a 30-turn budget | When the review ran long, the step was never reached |
| Claude held git push rights | The model that reads untrusted PR content could push branches |

**Fix — split "decide" from "do":**
- Claude only *stages* a note at `/tmp/review-learnings/<slug>.md` (new
  Step 4b: one turn, placed before inline findings so it cannot be starved).
  Before staging it checks merged notes and open learning PRs.
- A shell step, **Open review-learning PRs**, does the writing. It validates the
  slug against a strict regex, the size, the frontmatter and the `kind`. It skips
  notes that already exist on the base branch or already have a branch. It opens
  one PR per note on `claude/review-learning/<pr>-<slug>`, at most two per run.
- Claude's allow-list lost every git write tool and `gh pr create`.

**Design note — where learnings live.** Learnings stay **per repo**, in that
repo's `.claude/memory/review-learnings/`, written through PRs. Writing across
repositories from a runner would need extra credentials. A central knowledge
store can still harvest them later (`/harvest-memory`). An early reading of
"learnings are per repo" removed that harvesting wiring; the user corrected
it, and it was restored.

**Tests:** `tests/test_review_core_template.py` parses the YAML and pins the
allow-list, step order, guards, the slug regex and the merge gate.

---

## 3. Shell injection through `pr_number` (PR 261)

**Problem:** the "Resolve PR context" step wrote `${{ inputs.pr_number }}`
straight into its `run:` script. Any caller passing user-controlled text could
inject shell code.

**Why the existing guard missed it:** the "no `${{` in `run:`" test only looked
at the learning step.

**Fix:**
- The value arrives through `env:` as `PR_NUMBER`.
- It is validated against `^[1-9][0-9]*$`, and the rejected value is never echoed,
  so it cannot inject a workflow command either.
- `${{ github.repository }}` became the runner's `$GITHUB_REPOSITORY`.
- A new `tests/test_review_core_inputs.py` checks every `run:` in every job.
  Against the old core, five of its tests fail.

The tests went into a **new file** on purpose: a parallel session was editing the
other test file, and separate files let both PRs merge cleanly.

---

## 4. Taking GitHub write access away from Claude (PR 263)

**Problem:** after PR 259, Claude still had `Bash(gh api:*)`. That is a prefix
rule, so it allowed any GitHub API call, including `-X PUT`, `--method`, implicit
POSTs via `-f`/`-F`/`--input`, and GraphQL mutations. Merge, approve, ref edits and
PR creation were all reachable from the model that reads untrusted PR text.

**Options weighed** (after checking Claude Code's permission docs, which call
argument-constraining Bash patterns "fragile"):

| Option | Verdict |
|---|---|
| (a) Allow only read-path prefixes | Rejected: a flag after the path still changes the method |
| (b) Deny rules on `-X` / `--method` / `-f` | Rejected: depends on argument order, misses `-XPOST`, `--method=…`, implicit POST and GraphQL |
| (c) Snapshot reads before Claude, stage writes for a shell step after | **Chosen**: nothing depends on matching command text |
| (d) Narrow `permissions:` / split jobs | Deferred: the publish and learning steps need write scopes in this job, and the action's own app token ignores `permissions:` anyway |

**What changed:**
- Allow-list: `Bash(gh api:*)` and `Bash(gh pr comment:*)` removed. Claude keeps
  `gh pr view`, `gh pr diff`, `git diff`, `git log`, `cat`, `Read`, `Grep`, `Glob`
  and `Write`.
- **Snapshot review state** (before Claude) fetches existing comments, review
  threads and open learning PRs into `/tmp/review-state/`.
- Claude writes its summary, review, replies and inline findings to
  `/tmp/review-outbox/`.
- **Publish review comments** (after Claude, shell) validates and posts them:
  - Markers must be on line 1.
  - A finding's `path` must be a changed file and its `line` and `side` must be valid.
  - Replies may only target trusted finding comments.
  - Duplicates are skipped and per-run caps apply.
  - It re-fetches state rather than trusting `/tmp/review-state`, because Claude
    can write there.
  - If the review cannot be posted, the step fails, so the merge gate fails closed.

**Transition risk found during review:** old comments were posted by `claude[bot]`,
and `GITHUB_TOKEN` may not be allowed to edit them. A refused edit would have
blocked publishing and therefore the merge. The publish step now posts a new
comment when an edit is refused.

**Merge gate defects found in the same pass:**

| Defect | Effect | Fix |
|---|---|---|
| Verdict read from the last marker comment by **any** author | A PR commenter could post a fake `APPROVE` and get an approving formal review | Only trusted bot logins count; publish step and gate share one `TRUSTED_JQ`, pinned equal by a test |
| `--paginate` applies `--jq` per page | On PRs with 100+ comments the gate read the oldest page's verdict | Stream matches, take `tail -n 1` |
| Verdict grepped from anywhere in the body | A quoted marker could stand in for the real one | Verdict must be on line 2 and match an exact regex; otherwise fail closed |
| Idempotency check had the same per-page bug | A duplicate formal review on every push for PRs with 2+ pages of reviews | Stream `.state`, `tail -n 1`, default `NONE` |

The downstream fork had already fixed the same pagination bug its own way, by
dropping `--jq` and piping the merged array into `jq`. The session kept the
stream-and-tail form, because the same step already used it elsewhere and two
styles in one step would be worse.

**Cost:** about 410 more lines of YAML and shell. Comments now appear as
`github-actions[bot]`.

**Tests:** `tests/test_review_publish_step.py` and `tests/test_review_merge_gate.py`
run the scripts under bash against a fake `gh` that paginates like the real one.
Mutation runs confirmed the tests catch each regression: removing the author
filter, restoring grep-anywhere, dropping the line-2 check, or letting the two
trust filters drift. 108 tests passed.

---

## 5. Moving the shell out of the YAML (PR 265)

**Problem:** the core had grown to about 1,420 lines, mostly inline bash that could
only be tested by extracting it from YAML.

**The constraint that shaped the design.** The core is consumed two ways:
1. **Installed copy:** the installer copies it into a repo's `.github/workflows/`.
2. **Cross-repo call:** the downstream fork is called by other repos with
   `uses: <org>/<repo>/.github/workflows/<file>@v1`. In that case the job's checkout
   is the *calling* repo, so script files next to the workflow are not on disk.

**Options:**

| | (A) Build-time inlining | (B) Runtime fetch |
|---|---|---|
| How | Scripts are the source; a generator inlines them into one YAML | Each step reads its script from `job.workflow_sha` with `git cat-file` |
| Installed copies | One file, unchanged | Works |
| Private cross-repo fork | One file, no credential | No documented way for the caller's `GITHUB_TOKEN` to read a private central repo — needs a PAT or app secret per consumer |
| Claude rewrites a script mid-run | Impossible: inline YAML cannot change at runtime | Depends on where the script is read from |
| Fork's drift detection | Still watches one path | One more watched path per script |

**Chosen: A.** It also neutralised a risk the split would otherwise have created:
Claude has `Write` during the review, and later steps hold a write token. A script
file that a later step executes could be rewritten by Claude in between, which
would be code execution with a write token.

**What changed:**
- Five scripts under `github-action/scripts/claude-review/`:
  `resolve-pr-context.sh`, `snapshot-state.sh`, `publish-comments.sh`,
  `open-learning-prs.sh` and `merge-gate.sh`.
- `claude-review-core.template.yml` holds the wiring and the prompt, with one
  `# @inline scripts/claude-review/<name>.sh` marker per step.
- `scripts/build_review_core.py` inlines the scripts into the generated core.
  It refuses a `${{` in a script, a missing shebang or a stray marker. `--check`
  fails CI when the committed core is stale.
- A test asserts that no `run:` in the shipped core executes or sources a file.
- The generated core was compared job by job with the previous version (ignoring
  comments) and found identical.

**Sequencing:** PR 265 was stacked on PR 263 while PR 263 was still changing the
merge gate. It was rebased onto PR 263's latest head right before generating, so
the pagination fix landed in `merge-gate.sh`.

---

## Process notes

- **Parallel sessions, stacked PRs.** PR 261, PR 263 and PR 265 each ran in their
  own session and worktree, coordinated by a parent session. Conflicts were
  avoided by design: separate test files, one owner per region of the core, and
  rebasing onto the latest upstream tip before generating.
- **Sessions disagreed, with reasons.** A session declined a suggestion from the
  parent (match the fork's `jq` style), explained why, and also refused to name
  the private fork in tracked files. Both calls were right.
- **The pipeline reviewed its own fixes.** After the `claude/*` skip was dropped,
  the review ran on every follow-up PR and reported no issues.
- **Wrong turns, corrected:**
  - The over-broad `claude/*` skip.
  - Removing the brain's harvesting wiring because of a misread instruction.
  - Blaming a missing review on a GitHub quirk, which the next run disproved.
  - Advising the installer for repos that actually consume a central fork.

---

## Open items

- **Job split.** Move Claude into a read-only job and hand its outbox as an
  artifact to a job that holds the write token. A plan was being drafted when
  this was written. The open question is whether claude-code-action needs
  `id-token: write`, which would mint an app token that can write.
- **`$GITHUB_ENV` / `$GITHUB_PATH` reachability.** Claude's `Write` may be able to
  reach the Claude step's environment files, which would let it set `BASH_ENV` or
  `PATH` for later write-token steps. This is unverified, and it applies equally to
  inline YAML.
- **Trusted login is coarse.** `github-actions[bot]` is shared by every
  `GITHUB_TOKEN` workflow in a repo, so "trusted" means "any Actions workflow".
- **Snippet still skips `claude/*`.** `github-action/claude-review-automatic.snippet.yml`
  carries the same over-broad skip that was removed from this repo's workflow.
- **Downstream re-sync.** The fork still gives Claude `Bash(gh api:*)` and has none
  of the fixes above. It also pins an old action version to avoid a Bun crash
  (Bun issue 25730, https://github.com/oven-sh/bun/issues/25730), which was fixed
  in December 2025, and newer action versions have run cleanly here. A re-sync
  can drop that pin.
