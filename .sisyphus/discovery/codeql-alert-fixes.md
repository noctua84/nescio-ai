# Discovery Brief: CodeQL alert fixes

## Codebase map
- scripts/scrub_check.py — pre-publish scanner. SECRET_PATTERNS / custom terms (FAIL) and PATH_PATTERNS (WARN). Lines ~152-171 collect `line.strip()[:120]` snippets and print them. Run in CI by .github/workflows/scrub.yml on every push/PR.
- tests/test_scrub_check.py — existing tests; none assert on snippet text.
- .github/workflows/tests.yml — jobs at lines 21 (tests), 80 (lint), 258 (docs-tests), 370 (lockfile), plus a roadmap job (~line 422) that already declares job-level `permissions: contents: read, issues: read`.
- .github/workflows/module-gate.yml, scrub.yml — no `permissions:` block.
- .github/workflows/docs.yml, release-please.yml — precedent: top-level `permissions:` after `on:`.
- scripts/install_github_action.py — prints secret *names* only; CodeQL alerts #3-#6 are false positives (dismissed, no code change).

## Conventions to match
Python 3.13, stdlib only, pytest. Workflow comments explain *why*. Conventional commits.

## Constraints and hazards
- Repo is public; CI logs are public. The scanner must never echo the matched secret text.
- Job-level `permissions:` overrides workflow-level — roadmap job stays as is.
- Repo default GITHUB_TOKEN is already `read`; the permissions change is defence in depth.

## External research
Skipped — no external surface.

## Assessment
Redact matched spans in printed snippets (FAIL and WARN); add top-level `permissions: contents: read` to the three workflows.

## Open questions
None.
