# Claude PR-review action

A GitHub Actions **pipeline** that runs Claude as an automated PR reviewer in
a target repo, gates merges on the verdict, and — with a high bar — opens a
`chore: record review learning` PR recording durable learnings (regression /
security / architecture) into that repo's `.claude/memory/review-learnings/`,
so future reviews watch for them.

## Files

- `claude-review-core.yml` — **generated; do not edit by hand** (see
  [Editing the review core](#editing-the-review-core)). The reusable
  `workflow_call` **core**: the
  review engine (PR summary + six-point comprehensive review, incremental
  comment updates), split into three jobs (`review`, `publish`,
  `merge-gate`; see [What Claude can and cannot do](#what-claude-can-and-cannot-do)),
  with the merge gate turning the verdict into
  `APPROVE` / `REQUEST_CHANGES`. Carries no repo-specific knowledge — it
  reads `.claude/memory/review-learnings/` and `CLAUDE.md` from the target
  repo at review time (check 3f). Never triggered directly; always invoked
  by one of the two callers below.
- `claude-code-review.yml` — a thin `workflow_dispatch` **manual wrapper**.
  Polls the target's CI run for the PR's head SHA (default workflow name
  `CI`, up to ~20 min) and, once it's green, calls the core. Use it for
  manual re-runs: branches an automatic path skips by design, resuming a
  review after removing a "skip review" label (label removal doesn't
  retrigger CI), or recovering from a review that died mid-run.
- `claude-review-automatic.snippet.yml` — a single job you **paste into
  your own CI workflow** (the one named `CI`), with `needs:` set to your CI
  job IDs (e.g. `[lint, typecheck, test, build]`). GitHub holds a `needs:`
  job without a runner until those succeed, so the review starts the
  instant CI is green with no idle-poll cost, and red CI skips the review
  entirely instead of failing it after a long poll.

- `claude-review-core.template.yml` — the **source** of the core's wiring
  (inputs, jobs, steps). Each shell step's `run: |` holds a single
  `# @inline scripts/claude-review/<name>.sh` marker instead of the script.
- `scripts/claude-review/*.sh` (next to this README) — the shell steps themselves
  (`resolve-pr-context`, `restore-trusted-config`, `snapshot-state`,
  `scrub-staged`, `publish-comments`, `open-learning-prs`, `merge-gate`),
  each tested directly by `tests/`.
- `scripts/build_review_core.py` (repo root `scripts/`) — the generator that
  inlines the scripts into the template and writes `claude-review-core.yml`.

The manual wrapper and the automatic snippet both call the same core, so a
manual re-run and the automatic path behave identically — they only differ
in how they decide CI is green.

## Install into a target repo

    python scripts/install_github_action.py <path-to-target-repo> \
        --auth oauth|apikey --repo <owner/name> [--ci-workflow-name CI]

This copies the core + manual wrapper into the target's
`.github/workflows/` (substituting the chosen auth secret name), seeds
`.claude/memory/review-learnings/` with a `README.md` + `.gitkeep`, sets the
auth secret on the target repo via `gh secret set` (unless `--skip-secret`),
and prints a pointer to `claude-review-automatic.snippet.yml`. It never
commits or pushes — review and PR the changes in the target repo yourself.

The installer copies only the generated `claude-review-core.yml` — one
self-contained file, no script files. To upgrade an existing install, re-run
the installer with `--force`; it overwrites a core that differs.

**Upgrading from a core that used `id-token: write`.** Re-run the installer
with `--force`. The core no longer mints a Claude GitHub App token, so the
Claude GitHub App no longer needs to be installed on the target repo, and
`id-token: write` in your callers is no longer needed. It is safe to remove
it from the manual wrapper and from the pasted snippet, and harmless to leave
it. The wrapper and snippet in this directory already omit it. Keep
`contents`, `pull-requests` and `issues` at `write` in the caller: the core's
`publish` job uses them, while the job that runs Claude asks only for read.
If you trim the caller's `permissions:` further, remember that permissions
must nest: every job in the core has to ask for a subset of what the caller
grants, otherwise GitHub refuses to start the run and no `merge-gate` runs at
all. Make the merge-gate check a **required status check** on the protected
branch (it is named after the caller's job, for example
`claude-review / merge-gate` for the pasted snippet), so a run that does
not start blocks merging instead of passing silently.

Pass `--ci-workflow-name` if the target's CI workflow isn't named `CI`; the
installer rewrites the manual wrapper's polling `select(.name == "CI")`
match accordingly. (The automatic snippet doesn't need this — it runs as a
job inside that same CI workflow, so `needs:` handles the ordering instead
of polling.)

## Editing the review core

Never edit `claude-review-core.yml` directly. Change the wiring in
`claude-review-core.template.yml` or the logic in
`scripts/claude-review/*.sh`, then regenerate and commit both together:

    python scripts/build_review_core.py

`python scripts/build_review_core.py --check` exits 1 when the committed core
is stale; use it in CI or a pre-commit hook (`tests/test_build_review_core.py`
enforces the same).

The scripts are inlined rather than shipped as files for two reasons. Claude
has a `Write` tool during the review, and the `review` job checks out the PR
head, so a script file in the workspace is something Claude could rewrite
before a later step in that job runs it; inline YAML is fixed when the core
is built and can't be changed at runtime, so every step runs exactly the code
that was reviewed and committed. (Steps that hold a write token run in the
separate `publish` and `merge-gate` jobs, which never see the review job's
workspace; see [What Claude can and cannot do](#what-claude-can-and-cannot-do).)
And a fork consuming the workflow cross-repo can't read script files from a
private central repo without an extra credential, so the core stays a single
YAML file.

## Wire up the automatic path

Installing only ships the core + manual wrapper. To get review-on-green-CI
without polling, paste the job in `claude-review-automatic.snippet.yml` into
your existing CI workflow file and set its `needs:` to your actual CI job
IDs:

```yaml
claude-review:
  needs: [lint, typecheck, test, build]   # <- your CI job ids
  uses: ./.github/workflows/claude-review-core.yml
  with:
    pr_number: ${{ github.event.pull_request.number }}
  secrets:
    CLAUDE_CODE_OAUTH_TOKEN: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}
```

Without this step the pipeline only runs on manual `workflow_dispatch` via
`claude-code-review.yml`.

## Auth: OAuth vs API key

Two mutually-exclusive auth modes, chosen at install time with `--auth`:

| Mode | Secret | `uses:` input | When |
|---|---|---|---|
| `oauth` (default) | `CLAUDE_CODE_OAUTH_TOKEN` | `claude_code_oauth_token` | Personal use — a subscription-backed OAuth token. |
| `apikey` | `ANTHROPIC_API_KEY` | `anthropic_api_key` | Enterprise / org use — pay-as-you-go API billing, easier to rotate and scope per-repo. |

The installer substitutes the secret name and input key throughout the
copied workflows, so pick the mode at install time rather than editing the
YAML by hand afterward. If you paste the automatic snippet yourself, swap
its `secrets:` line the same way (the snippet's header comment shows the
`apikey` variant).

## What Claude can and cannot do

Claude has **no GitHub write tool**. Its allow-list in
`claude-review-core.yml` is exactly:

    Bash(gh pr view:*),Bash(gh pr diff:*),Bash(git diff:*),Bash(git log:*),Bash(cat:*),Write,Read,Grep,Glob

There is no `gh api` and no `gh pr comment`, and no git write command. The
reason: Bash allow rules are prefix matches, so `Bash(gh api:*)` cannot
constrain the HTTP method, the `-f` / `-F` / `--input` flags or a GraphQL
mutation, and Claude reads untrusted PR content. Only removing the tool
holds. On top of that, the job Claude runs in holds no write token at all.

The workflow is split into three jobs. Claude only ever runs in the first.

1. **`review` (read-only; runs Claude).** Its permissions are exactly
   `contents: read`, `pull-requests: read` and `issues: read`, and it has no
   `id-token`. The read-only `GITHUB_TOKEN` is passed to the Claude step
   explicitly, so the action does not exchange an OIDC token for a Claude
   GitHub App token and the App is not used. The checkout does not persist
   credentials. The review always runs with the base branch's Claude
   configuration, on every event, including manual dispatch: a step before
   Claude replaces the PR head's `.claude`, `.mcp.json`, `CLAUDE.md` and
   related configuration files with the base branch's version, and the job
   fails (and the merge gate with it) if the base branch cannot be found in
   the checkout.

   The job proceeds in stages:
   - **Snapshot.** A `Snapshot review state` shell step reads the PR's issue
     comments, inline review comments, review threads (resolved /
     acknowledged state) and the open learning PRs into `/tmp/review-state/`.
     Claude only reads those files. If the snapshot fails, Claude does not
     run and the merge gate fails closed.
   - **Stage.** Claude writes what it wants to say under
     `/tmp/review-outbox/`: `summary.md`, `review.md`,
     `findings/<slug>.md` (one new inline finding each, with `path` / `line`
     / `side` frontmatter) and `replies/<slug>.md` (a reply, with an
     `in_reply_to` frontmatter key), plus candidate learning notes under
     `/tmp/review-learnings/`.
   - **Prune and upload.** A `Prune staged files before upload` step keeps
     only the files the publish job can use: regular `.md` files in the
     expected places (`summary.md` and `review.md`, one level of
     `findings/` and `replies/`, and top-level learning notes). It removes
     everything else, including links, special files, nested paths and any
     file containing a credential-shaped string. The staged files are then
     uploaded as one artifact, `review-staged`, kept for one day. Artifacts
     of a public repository are downloadable by signed-in users while they
     are retained, which is why the pruning exists.

   Steps that run after Claude in this job cannot be fully protected from
   Claude. The pruning is therefore hygiene for the accidental case, not a
   security boundary, and the artifact's content is treated as untrusted by
   everything downstream.

2. **`publish` (write token; never runs Claude).** This job boundary is the
   security boundary. It downloads the artifact and treats it as untrusted
   input: it re-validates every file itself (a regular file, within the size
   limit, with the expected markers and frontmatter) and refuses any file
   containing a credential-shaped string. That filter is best-effort: it
   recognises the plain shape of GitHub and Anthropic credentials only. The
   `Publish review comments` step then posts each validated file to a fixed
   endpoint: it edits the existing summary and review comments in place (or
   creates them), replies only to finding comments this workflow wrote on
   this PR, and posts a finding only for a file that is part of the PR. It
   runs even if Claude hit its turn limit. A summary, finding or reply that
   cannot be published is a warning; a staged review that cannot be
   published (including one rejected by the credential filter) fails the
   step. The job reports whether this run's review was published as its
   output `review_published`. The learning-PR step also runs here (see
   below).

3. **`merge-gate`.** It needs both `review` and `publish`, and **fails
   closed**: unless this run's review was published, it submits
   `REQUEST_CHANGES` instead of reading a verdict from an earlier run's
   comment. When the review was published, it submits the formal review
   from the verdict on line 2 of the review comment. It only trusts the
   review comment authored by the workflow's own logins
   (`github-actions[bot]`, and `claude[bot]` for earlier versions), so a
   comment from anyone else, or a marker quoted elsewhere in the review,
   cannot change the outcome. A run that is truncated, fails, or is
   rejected at publish time therefore blocks the PR until it is re-run or
   the `skip-claude-review` label is applied.

Comments are now authored by `github-actions[bot]`. One-time transition:
summaries and reviews posted earlier by `claude[bot]` are still recognised
and edited in place, so an open PR keeps one summary and one review rather
than getting a second pair.

Because the permissions of a reusable workflow must nest, the caller has to
grant every permission any core job asks for (`contents`, `pull-requests`
and `issues` at `write`, for `publish`). See the upgrade note under
[Install into a target repo](#install-into-a-target-repo).

## The review-learnings loop

The reviewer's Step 4b (in `claude-review-core.yml`) is a high bar: only
when a finding is a DURABLE, likely-to-recur regression, security, or
architecture issue — and no equivalent note exists, either in
`.claude/memory/review-learnings/` or in an open learning PR — does Claude
stage a candidate note at `/tmp/review-learnings/<slug>.md` (at most two
per run). Claude never touches git: it has no `fetch`, `checkout`, `add`,
`commit`, `push` or `gh pr create` in its allow-list (see above), and it
could not write into `.claude/` itself, which Claude Code treats as a
protected directory in headless runs.

A plain shell step in the `publish` job (`Open review-learning PRs`) does the
git work, on a checkout of the base branch. The branch push is authenticated
with the publish job's `GITHUB_TOKEN`. For each staged file it checks the
slug (lowercase kebab-case, at most 50 characters) and the frontmatter,
skips notes that already exist
on the base branch or already have a branch, then branches off the base
ref as `claude/review-learning/<pr-number>-<slug>`, copies the file to
`.claude/memory/review-learnings/<slug>.md`, commits as
`github-actions[bot]`, pushes, and opens a `chore: record review learning
(<slug>)` PR against the base branch. The branch name carries the slug so
a review that runs on every push can record several learnings per PR and a
re-run is a no-op. The step treats the staged notes as untrusted input like
the rest of the artifact: it re-checks each one and skips any that contains a
credential-shaped string. It runs even if Claude hit its turn limit, and a
failure in it only produces a warning — it never fails the `publish` job or
the merge gate.

Each note is self-contained:

    ---
    kind: regression | security | architecture
    origin: PR <number>
    date: YYYY-MM-DD
    ---
    **What it is:** ... **Signal to watch:** ... **Where:** ...

Requirements in the target repo:

- Enable *Settings → Actions → General → Allow GitHub Actions to create and
  approve pull requests*. Without it `gh pr create` fails and the step only
  warns.
- PRs opened with `GITHUB_TOKEN`, and branches pushed with it, do not
  trigger other workflows, so a learning PR gets no CI run. If the base branch requires status checks,
  push a commit to the learning branch or merge as an admin.

Every subsequent review (check 3f) reads all notes under
`.claude/memory/review-learnings/` before reviewing, so the bar the target
repo has already crossed once doesn't get crossed again silently.

The reviewer stores learnings in the target repo itself, through these
PRs, because writing to another repository from an Actions runner would
need cross-repo credentials. The brain can still harvest them into its own
memory store later: `/harvest-memory` reads the current project's
`.claude/memory/review-learnings/` as a source, and the `adopt-config` skill
(tier-2) covers pulling them from a target repo.
