# The review pipeline: what it does and why

**As of:** 2026-11-14 (after PR 265)
**Companion to** [`optimizations.md`](optimizations.md), which covers how the pipeline got here.

The pipeline is a reusable GitHub Actions workflow that has Claude review every
pull request and then turns that review into a formal GitHub review that can block
the merge. It lives in `github-action/` and is installed into other repositories by
`scripts/install_github_action.py`.

---

## Design principles

1. **The model decides, shell does.** Claude reads code and writes drafts. Every
   action that changes GitHub (posting comments, submitting reviews, opening PRs)
   happens in a plain shell step that validates Claude's output first. Claude
   reads untrusted PR content, so it must not hold a tool that can write.
2. **Fail closed.** If the review is missing, malformed or can't be posted, the
   merge gate requests changes. A silent failure must never look like an approval.
3. **Incremental, not repetitive.** A second push edits the existing comments
   rather than adding new ones. It replies once when a finding is fixed and never
   re-nags about a finding a human resolved or acknowledged.
4. **Generic core, local knowledge.** The core carries no project-specific rules.
   Each repo teaches the reviewer through its own `CLAUDE.md` and
   `.claude/memory/review-learnings/` notes, and the reviewer adds to those
   notes itself, through PRs.
5. **One self-contained file.** Consumers get a single workflow file, whether they
   install a copy or call a shared fork. The shell logic is developed and tested
   as scripts, then inlined by a generator.

---

## Files

| File | Role |
|---|---|
| `github-action/claude-review-core.template.yml` | The wiring and the Claude prompt. Edit this. |
| `github-action/scripts/claude-review/*.sh` | The five shell steps, tested directly. Edit these. |
| `scripts/build_review_core.py` | Inlines the scripts into the template. `--check` fails CI when the output is stale. |
| `github-action/claude-review-core.yml` | **Generated.** The single file consumers run. |
| `github-action/claude-review-automatic.snippet.yml` | A job to paste into a repo's CI workflow so the review runs after CI is green. |
| `github-action/claude-code-review.yml` | A manual `workflow_dispatch` wrapper for re-running a review on one PR. |
| `scripts/install_github_action.py` | Copies the core and the wrapper into a target repo and seeds `.claude/memory/review-learnings/`. |

---

## How a review runs

```
caller (after CI is green)
  └─ job: review          permissions: contents/pull-requests/issues write, id-token write
       1. Resolve PR context      shell   PR number (validated) → title, author, refs, SHAs
       2. Checkout PR head
       3. Snapshot review state   shell   existing comments, threads, open learning PRs → /tmp/review-state/
       4. Run Claude Code Review  Claude  reads code + snapshot, writes drafts → /tmp/review-outbox/, /tmp/review-learnings/
       5. Publish review comments shell   validates drafts, posts/edits comments
       6. Open review-learning PRs shell  validates notes, one PR per note
  └─ job: merge-gate      needs: review, runs unless cancelled
       7. Submit formal review    shell   reads the verdict → APPROVE / REQUEST_CHANGES / COMMENT
```

### 1. Resolve PR context
Takes `pr_number` through `env:` and accepts only a positive integer. Then reads the
PR's metadata with `gh api`. Nothing from the caller is ever interpolated into
shell.

### 3. Snapshot review state
Fetches everything Claude needs to know about earlier runs: the summary and review
comments, inline finding comments and their threads (including which ones a human
resolved), and open learning PRs. Claude reads these files instead of calling the
GitHub API itself.

### 4. Claude's review
Claude runs with a short read-only tool list: `gh pr view`, `gh pr diff`,
`git diff`, `git log`, `cat`, `Read`, `Grep`, `Glob`, and `Write` for staging
drafts. The prompt walks it through:

- **Step 0 — State discovery.** Find its own earlier comments by marker and
  classify each earlier finding as fixed, still open, resolved by a human or
  acknowledged.
- **Step 1 — Understand the PR.**
- **Step 2 — PR summary.** What changed, scope, risk.
- **Step 3 — Comprehensive review:**
  - 3a, deep bug search;
  - 3b, do tests exist;
  - 3c, static coverage analysis (tests are never run, since CI already did);
  - 3d, dead code;
  - 3e, regressions;
  - 3f, logical consistency and config/contract drift, including recurrences of
    anything in the repo's review-learnings.
- **Step 4 — Comprehensive review comment**, with the verdict on line 2.
- **Step 4b — Learning capture.** Rare and high-bar: at most two notes, only for a
  regression, security or architecture lesson that isn't already recorded.
- **Step 5 — Inline findings.** New findings get an inline comment; fixed ones get
  a one-time "addressed" reply; still-open ones get at most one nudge.
- **Step 6 — Signal the verdict.**

Comments are tied together by invisible HTML markers:

| Marker | Meaning |
|---|---|
| `<!-- claude-pr-summary -->` | the summary comment |
| `<!-- claude-comprehensive-review -->` | the review comment |
| `<!-- claude-verdict: APPROVE\|CHANGES_REQUESTED\|COMMENT -->` | the verdict, line 2 of the review |
| `<!-- claude-finding: FINGERPRINT -->` | one inline finding |
| `<!-- claude-stillopen: FINGERPRINT -->` | the single "still open" nudge |
| `<!-- claude-ack -->` | a human accepted or won't-fix a finding |

### 5. Publish review comments
A shell step posts what Claude staged, after checking it:
- **Summary and review:** the marker must be on line 1, and the review's line 2 must
  be a valid verdict. The step edits the newest earlier comment by a trusted bot,
  or posts a new one if there is none or the edit is refused.
- **Findings:** the file must be part of the PR, the line and side must be valid,
  and duplicates are skipped.
- **Replies:** they may only answer a trusted finding comment.
- **Limits:** sizes and per-run counts are capped, and symlinks are rejected.
- **Fresh state:** everything is re-fetched rather than read from the snapshot,
  because Claude could have written to it.
- **Failure:** if the review comment can't be posted, the step fails.

### 6. Open review-learning PRs
For each staged note, it validates the slug, size, frontmatter and kind. It skips
notes already on the base branch or already on a branch, then opens a PR on
`claude/review-learning/<pr>-<slug>`. A failure here warns but never blocks the
review. The repo must allow GitHub Actions to create pull requests, and PRs
opened with `GITHUB_TOKEN` get no CI run of their own.

### 7. Merge gate
A separate job reads the newest review comment written by a trusted bot, across all
pages. It takes the verdict from line 2 only:

| Verdict | Formal review |
|---|---|
| `APPROVE` | `APPROVE` |
| `CHANGES_REQUESTED` | `REQUEST_CHANGES` |
| `COMMENT` | `COMMENT` (minor suggestions, not blocking) |
| missing, malformed, or from anyone else | `REQUEST_CHANGES` (fail closed) |

It doesn't submit the same state twice, so repeated pushes don't stack duplicate
reviews.

---

## How a repo uses it

- **Install:** run `python scripts/install_github_action.py <repo>`, adding
  `--force` to overwrite an older copy. Then paste the snippet job into the repo's
  CI workflow, with `needs:` set to the CI jobs. GitHub holds a `needs:` job
  without a runner, so waiting for CI costs nothing. Add `ready_for_review` to the
  CI triggers, because drafts are skipped.
- **Skipped PRs:** drafts, Dependabot and `github-actions[bot]` PRs, release-please
  PRs, and PRs labelled `skip-claude-review`.
- **Teaching the reviewer:** write or merge notes in
  `.claude/memory/review-learnings/`. The reviewer reads them in check 3f, and its
  own learning PRs add to them.
- **Shared fork:** an organisation can keep one copy and have its repos call it
  with `uses: <org>/<repo>/.github/workflows/<file>@v1`. Because the core is a
  single generated file, re-syncing a fork means copying one file and keeping the
  fork's own deliberate changes.

---

## Why this shape

| Choice | Alternative | Reason |
|---|---|---|
| Claude stages, shell posts | Give Claude `gh` with deny rules | Command-pattern rules are fragile; a model with no write tool can't misuse one |
| Snapshot before Claude | Let Claude call `gh api` for reads | `gh api` can't be limited to reads by pattern |
| Merge gate in its own job | Let Claude submit the formal review | The gate is small, deterministic and fails closed; it trusts only the bot's own comment |
| Learnings via PRs in the same repo | Write to a central store | Cross-repo writes from a runner need credentials; PRs give a human a review step |
| Build-time inlining | Ship scripts beside the YAML | Cross-repo callers don't have the scripts on disk, and an executed file could be rewritten by Claude mid-run |
| Static coverage analysis | Run tests in the review | CI already ran them on the same commit; the review reasons about gaps |
