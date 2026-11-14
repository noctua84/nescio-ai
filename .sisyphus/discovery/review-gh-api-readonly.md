# Discovery Brief: remove GitHub write rights from Claude in the review core

## Codebase map
- github-action/claude-review-core.yml (956 lines) — reusable `workflow_call` review. Job `review`: steps
  "Resolve PR context" (id: pr) → "Checkout PR head" → "Run Claude Code Review" (claude-code-action,
  `claude_args --allowed-tools "..."`, long `prompt:`) → "Open review-learning PRs" (shell, `!cancelled()`,
  continue-on-error). Job `merge-gate` (needs review) reads the `<!-- claude-comprehensive-review -->` comment's
  verdict marker and submits a formal review as github-actions[bot].
- tests/test_review_core_template.py — YAML contract tests (unittest + PyYAML), `_CoreBase` helpers.
- tests/test_install_github_action.py — installer tests; must keep passing.
- github-action/README.md — "The review-learnings loop" section describes Claude's allow-list.

## `gh api` inventory in the prompt (before this change)
Reads: GET issues/N/comments (Step 0.1); GET pulls/N/comments (Step 0.2); GraphQL reviewThreads query
(Step 0.3b — `gh api graphql -f query=` is a POST and would equally accept a mutation); GET pulls?state=open
filtered to `claude/review-learning/` heads (Step 4b), each then read with `gh pr diff <n>`.
Writes: PATCH issues/comments/{id} (edit summary, Step 2; edit review, Step 4); POST pulls/N/comments/{id}/replies
(Case 0 regression, Case 1 addressed, Case 2 still-open); POST pulls/N/comments (Case 3 new inline finding).
Plus `gh pr comment N --body-file` for first-time summary / review.

## Conventions to match
- Same pattern PR 259 introduced for learnings: Claude only STAGES files under /tmp; a deterministic shell
  step validates and does the GitHub write. PR-controlled values reach shell only via `env:` — never `${{ }}`
  inside `run:`. `set -euo pipefail`; per-item failures are `::warning::` and `continue`.
- Conventional commits; never a bare `#N` or `Refs #N`.

## Constraints and hazards
- Bash allow rules are prefix matches; `gh api` flags (-X/--method/-f/-F/--input) and GraphQL mutations
  cannot be constrained by prefix. Only removing `gh api` from Claude holds.
- Comment author changes: today Claude posts with the action's token; after this change the publish step
  posts with GITHUB_TOKEN as github-actions[bot]. Publisher must recognise prior comments from both logins.
- merge-gate trusts the LAST comment containing the review marker from ANY author (pre-existing gap, out of scope).
- Out of scope: `inputs.pr_number` interpolation in Resolve PR context; repo's own .github/workflows.
- rtk hook garbles grep/pytest output: use `command grep` and `python -c "import pytest,sys; sys.exit(pytest.main([...]))"`.

## Assessment
Option (c) extended: snapshot step pre-fetches all review state to /tmp/review-state/; Claude keeps only
read-only `gh pr view` / `gh pr diff`, git diff/log, cat, Write/Read/Grep/Glob; Claude stages comments to
/tmp/review-outbox/; a publish step posts them with fixed endpoints after validation.
Rejected: (a) path-prefix allows — flags after the path still change the method; (b) deny rules on flags —
order-dependent, `-XPOST`, `--method=`, `-f` implicit POST, GraphQL mutations; (d) narrowing job permissions
alone — publisher/learning steps still need write, and the action's own token is not governed by `permissions:`.
