# Discovery Brief: move the review core's shell steps into shipped scripts

## Codebase map
- github-action/claude-review-core.yml (~1,380 lines) — reusable `workflow_call`. Job `review`:
  "Resolve PR context" (id pr, inline, runs before any checkout) → "Checkout PR head" (head_sha,
  fetch-depth 0) → "Snapshot review state" (id state, ~40 lines bash) → "Run Claude Code Review"
  (claude-code-action; prompt ~560 lines — stays in YAML) → "Publish review comments" (~280 lines
  bash, `!cancelled()`) → "Open review-learning PRs" (~130 lines bash, `!cancelled()`,
  continue-on-error). Job `merge-gate` (needs review, `!cancelled()`, no checkout today) → one
  ~100-line bash step.
- scripts/install_github_action.py — copies core + wrapper into `<target>/.github/workflows/`,
  `_subst` rewrites auth names (core) and `select(.name == "CI")` (wrapper only), `_write_guarded`
  is the per-file `--force` clobber guard. Seeds `.claude/memory/review-learnings/`.
- tests/test_review_core_template.py, tests/test_review_core_inputs.py — YAML contract tests
  (PyYAML, unittest, `_CoreBase`). tests/test_review_publish_step.py — extracts the publish step's
  `run:` and executes it with bash against a fake `gh` + real `jq` (skips without bash/jq).
- tests/test_install_github_action.py — installer tests.
- github-action/README.md — "Files", "Install into a target repo", "What Claude can and cannot do".

## Conventions to match
- Bash steps: `set -euo pipefail`; inputs only via `env:`; never `${{ }}` inside `run:`; per-item
  failures are `::warning::` + `continue`.
- Tests: unittest classes, PyYAML, `_CoreBase` helpers; skip when bash/jq absent; LF newlines
  when writing scripts on Windows.
- Commits: conventional + `[impl]`/`[test]`/`[docs]`/`[chore]`; no bare `#N`, no `Refs #N`.

## Constraints and hazards
- Claude has `Write` (works outside the workspace: it writes /tmp/review-outbox). Anything in the
  workspace or $RUNNER_TEMP can be rewritten by Claude between steps. `.git/` is a protected path.
- Post-Claude steps hold GITHUB_TOKEN with contents/pull-requests/issues write.
- PR 263 (base branch) is still changing the merge-gate. Move step code only after rebasing on the
  latest tip of origin/claude/review-gh-api-readonly-d28410 (or origin/main once merged).
- Behaviour must not change. Moving code is the whole change.
- rtk hook garbles grep/pytest output: use `command grep` and
  `python -c "import pytest,sys; sys.exit(pytest.main([...]))"`.

## Decision (chosen by the user): build-time inlining
- Source of truth: `github-action/scripts/claude-review/*.sh` (tested directly) plus a wiring template
  `github-action/claude-review-core.template.yml` whose `run: |` blocks hold one include marker line.
- `scripts/build_review_core.py` inlines each script into its step and writes
  `github-action/claude-review-core.yml` (GENERATED header). `--check` exits 1 when the committed core
  is stale; a test runs the same comparison.
- The installer stays a single-file copy. The Souls-Gate fork (private, cross-repo `uses:`) keeps
  consuming ONE file, and its drift tripwire keeps watching only that path; its deltas (action pin,
  max_turns 100, `model` input, `contents: read`, no learning step) are unaffected.
- Security: the shipped YAML stays fully inline, so nothing Claude can Write is ever executed by a
  later step. A test asserts no `run:` in the generated core executes or sources a file.
- Rejected: runtime fetch from `job.workflow_sha` — works for installed copies, but a private central
  repo is not documented to be readable with the consumer's GITHUB_TOKEN (needs a PAT/App secret).

## Open questions
- Pre-existing, out of scope: Claude's Write may reach the step's $GITHUB_ENV / $GITHUB_PATH file
  (BASH_ENV, PATH for later steps). Affects inline YAML equally. Report as a finding.
