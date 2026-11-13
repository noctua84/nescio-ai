# Claude PR-review action

A GitHub Actions **pipeline** that runs Claude as an automated PR reviewer in
a target repo, gates merges on the verdict, and — with a high bar — opens a
`chore: record review learning` PR recording durable learnings (regression /
security / architecture) into that repo's `.claude/memory/review-learnings/`,
so future reviews watch for them.

## Files

- `claude-review-core.yml` — the reusable `workflow_call` **core**: the
  review engine (PR summary + six-point comprehensive review, incremental
  comment updates) and the merge-gate job that turns the verdict into
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

Pass `--ci-workflow-name` if the target's CI workflow isn't named `CI`; the
installer rewrites the manual wrapper's polling `select(.name == "CI")`
match accordingly. (The automatic snippet doesn't need this — it runs as a
job inside that same CI workflow, so `needs:` handles the ordering instead
of polling.)

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

## The review-learnings loop

The reviewer's Step 4b (in `claude-review-core.yml`) is a high bar: only
when a finding is a DURABLE, likely-to-recur regression, security, or
architecture issue — and no equivalent note exists, either in
`.claude/memory/review-learnings/` or in an open learning PR — does Claude
stage a candidate note at `/tmp/review-learnings/<slug>.md` (at most two
per run). Claude never touches git: it has no `fetch`, `checkout`, `add`,
`commit`, `push` or `gh pr create` in its allow-list, and it could not
write into `.claude/` itself, which Claude Code treats as a protected
directory in headless runs.

A plain shell step after the review (`Open review-learning PRs`) does the
git work. For each staged file it checks the slug (lowercase kebab-case,
at most 50 characters) and the frontmatter, skips notes that already exist
on the base branch or already have a branch, then branches off the base
ref as `claude/review-learning/<pr-number>-<slug>`, copies the file to
`.claude/memory/review-learnings/<slug>.md`, commits as
`github-actions[bot]`, pushes, and opens a `chore: record review learning
(<slug>)` PR against the base branch. The branch name carries the slug so
a review that runs on every push can record several learnings per PR and a
re-run is a no-op. The step runs even if Claude hit its turn limit, and a
failure in it only produces a warning — it never fails the review job or
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
- PRs opened with `GITHUB_TOKEN` do not trigger other workflows, so a
  learning PR gets no CI run. If the base branch requires status checks,
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
