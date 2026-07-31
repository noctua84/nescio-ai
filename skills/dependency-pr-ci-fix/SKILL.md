---
name: dependency-pr-ci-fix
description: Use when a dependency-bump PR's CI is failing (Dependabot, Renovate, or a manual bump) and you need to green it with the smallest safe fix. Reads the failing CI log, applies a minimal mechanical fix, and refuses to weaken/skip tests, downgrade the bump, or edit CI. Triggers on "fix the failing CI on this bump PR", "dependabot PR CI failing", "renovate PR red", "green this dependency PR".
user-invocable: true
---

# Fix a dependency-bump PR's failing CI

Given a dependency-bump PR whose CI is red, produce the **smallest mechanical fix**
with a high probability of turning CI green — or, if the only path is a forbidden
change, stop and hand it to a human. Bot-agnostic: the bump is detected from the
**diff**, so this serves Dependabot, Renovate, and manual bumps identically.

## Guardrails — refuse even if it would make CI green

Never, even when it is the only way to green the build:

- Delete or skip tests (`describe.skip`, `it.skip`, `xit`, `test.skip`,
  `pytest.mark.skip`, `t.Skip()`, …).
- Weaken assertions (relax `toEqual`→`toBeTruthy`, drop expected fields, swap
  strict equality for a substring match), or remove `expect` / `assert` /
  `should`.
- Downgrade the bumped dependency toward its old version.
- Edit CI workflow files (`.github/workflows/*`).
- Edit outside conventional source dirs (`src/`, `test/`, `tests/`, `__tests__/`,
  `lib/`, `cmd/`, `pkg/`, `internal/`).
- Hand-edit lockfiles — let the package manager regenerate them.

If the only route to green requires one of these, **make no change and report**
what a human must decide. A red CI handed back with a precise diagnosis is a
valid, honest outcome — the same principled-refusal stance the rest of the crew
takes.

## Process

### 1. Understand the bump

`gh pr diff <pr>` (or `git log -p BASE..HEAD`). Identify each bumped package, its
old → new version, and the semver delta — the change is almost always in
`package.json` / `pnpm-lock.yaml` / `yarn.lock`, `go.mod` / `go.sum`,
`requirements.txt` / `Pipfile.lock`, `Gemfile.lock`, or a Dockerfile base image.
**Major** bumps are the likeliest to need a fix. If several packages moved, work
the failures one at a time but commit them together.

### 2. Read the failing CI log — before reading code

Get the failing job(s): `gh pr checks <pr>`, then `gh run view <run-id>
--log-failed`. For each failing job, find the **first** error — later errors are
usually downstream noise. Watch for:

- `TypeError` / `ReferenceError` / `ImportError` / `ModuleNotFoundError`
- `is not a function` / `is not exported` / `has no attribute`
- `deprecated` / `has been removed` / `is no longer`
- type-checker errors (`tsc`, `mypy`) — read the first line, not the cascade
- snapshot mismatches (Jest, Vitest)

Quote the exact failing line — it becomes the commit's audit trail. Read logs
before code: the log says what failed; the code only says what is.

### 3. (Optional) Read the package changelog

If the error suggests a breaking API change, `WebFetch` the package's
changelog / migration guide and read only the entries **between** the old and new
version. Don't over-read. Trust the changelog over guessing a new API from a name.

### 4. Propose the minimal fix

Allowed modifications:

- Update imports for renamed/moved exports.
- Update call sites for renamed methods.
- Update mock signatures to match new interfaces.
- Adjust type annotations to match new types.
- Update snapshots **only if** the rendered output is provably equivalent
  (whitespace, ordering of equivalent attributes).
- Add/remove call arguments when a parameter was added/removed.
- Replace a deprecated name with its documented 1:1 replacement.

Anything beyond these — or anything on the guardrail list — is out of bounds.

### 5. Verify locally if cheap

If running just the failing test file is under ~60 s, run it (`npx jest <file>
--bail`, `go test ./<pkg> -run <test>`, `pytest <file> -x`). If it's expensive
(full install/build), skip and let CI catch it. If verify fails, retry once with
a different approach; if it still fails, proceed but mark the commit
`Verification: FAILED — needs human`. A fix that only works in CI is fine —
committing and letting CI judge is valid.

### 6. Commit — one commit, audited

Conventional subject (`fix(ci):` or `fix(deps):`). Multi-paragraph body so a
reviewer can audit the reasoning without expanding the diff:

- one-paragraph root cause with a **verbatim quote** of the failing log line;
- a "forbidden changes considered and rejected: …" line (or "none");
- a `Verification: PASSED locally | FAILED locally — needs human | SKIPPED (too
  expensive)` line.

One commit per fix — stage all the small fixes and commit once. Never add
`[skip ci]`: CI re-running is the signal.

## Boundary

Complements — does not replace — [`fix-security-vulnerabilities`](../fix-security-vulnerabilities/SKILL.md),
which triages and prioritizes vulnerabilities across sources and produces an
Update Plan; that skill may hand a specific failing bump here for the tactical
"green its CI" step. This skill does **not** aggregate advisories, score
severity, or decide *which* bumps to take.

## Out of scope

- Choosing or bumping dependencies (the bot's / a human's job).
- Posting PR comments or driving a headless workflow — an optional GitHub Action
  wrapper is tracked separately; this skill runs interactively on the checkout or
  a PR you point it at.
- Non-GitHub forges.
