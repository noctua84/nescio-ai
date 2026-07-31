# `dependency-pr-ci-fix` — green a dependency-bump PR's CI with the smallest safe fix

Status: draft — awaiting review

> Adapted (idea only, written fresh) from a generic Renovate-PR-fix pattern.
> Bot-agnostic. Skill only; the optional headless GitHub Action is a deferred
> follow-up issue.

## Purpose

A user-invocable skill that, given a **dependency-bump PR whose CI is failing**
(Dependabot, Renovate, or a manual bump), reads the failing CI log, applies the
**smallest mechanical fix** that has a high probability of turning CI green, and
commits it with an audited message — under hard guardrails that refuse to cheat
CI green (never weaken/skip tests, downgrade the bump, edit CI, or touch
non-source dirs).

## Why this design

- **Real gap, no overlap.** `fix-security-vulnerabilities` is a vuln-triage
  *lifecycle* (aggregate findings across sources → prioritize by severity ×
  complexity → produce an Update Plan). This skill is tactical: *this one bump
  PR's CI is red — make it green minimally, or refuse.* They compose — the triage
  skill can hand a specific failing bump to this skill.
- **The guardrails are the value.** The whole point is a fix that does not lie:
  the failure modes to prevent are "agent skips the test," "agent relaxes the
  assertion," "agent downgrades the dependency back." Those are enumerated as
  hard refusals. This is nescio's principled-refusal ethos in a mechanical task.
- **Bot-agnostic by construction.** The bump is detected from the **diff**
  (`package.json`/lockfiles, `go.mod`/`go.sum`, `requirements.txt`/`Pipfile.lock`,
  `Gemfile.lock`, Dockerfile base image), not from the PR author. So it serves
  Dependabot, Renovate, and hand-rolled bumps identically. (Adapting "the Renovate
  one to Dependabot" generalizes rather than swaps.)
- **Skill, not infra.** The source coupled this to a headless reusable workflow
  (bot-author precondition, bypass token, attempt-count labels, PR status
  comments). Those are deployment concerns, not the fix logic. nescio ships the
  skill (all the guardrail value, works interactively on the checkout / a named
  PR); the headless automation is an opt-in follow-up (see Deliverables).

## The skill — `skills/dependency-pr-ci-fix/SKILL.md`

`user-invocable: true`. Triggers: "fix the failing CI on this bump PR",
"dependency bump CI failing", "renovate/dependabot PR CI red".

Process (each step is a short instruction, not code):

1. **Understand the bump.** `gh pr diff <pr>` (or `git log -p BASE..HEAD`).
   Identify each bumped package, old → new version, and the semver delta. Major
   bumps are the likeliest to need a fix. If several packages moved, fix the
   failures but commit together.
2. **Read the failing CI log — before reading code.** Get the failing job(s)
   (`gh pr checks <pr>`, `gh run view --log-failed`). For each, find the **first**
   error (downstream errors are usually noise). Watch for: `TypeError` /
   `ImportError` / `ModuleNotFoundError` / `is not a function` / `is not exported`
   / `has no attribute`; `deprecated` / `removed` / `no longer`; type-checker
   errors (read the first line, not the cascade); snapshot mismatches. Quote the
   exact failing line — it becomes the commit's audit trail.
3. **Optional — read the package changelog.** If the error suggests a breaking API
   change, `WebFetch` the changelog / migration guide for entries *between* the
   old and new version. Don't over-read; trust the changelog over guessing a new
   API from a name.
4. **Propose the minimal fix.** Allowed: update imports for renamed/moved exports;
   update call sites for renamed methods; update mock signatures to new
   interfaces; adjust type annotations; update snapshots *only if* provably
   equivalent; add/remove call arguments for changed signatures; replace a
   deprecated name with its documented 1:1 replacement.
5. **Verify locally if cheap.** If running just the failing test file is
   <~60 s, run it. If it's expensive (full install/build), skip and let CI
   catch it. If verify fails, retry once with a different approach; if still
   failing, proceed but mark the commit `Verification: FAILED — needs human`.
6. **Commit — one commit, audited.** Conventional `fix(ci):` / `fix(deps):`
   subject; body: a one-paragraph root cause with a **verbatim quote** of the
   failing log; a "forbidden changes considered and rejected" line; a
   `Verification:` line. Never add `[skip ci]` — CI re-running is the signal.

### Guardrails — refuse even if it would make CI green

- Deleting or skipping tests (`.skip`, `xit`, `pytest.mark.skip`, `t.Skip()`, …).
- Weakening assertions (relaxing `toEqual`→`toBeTruthy`, dropping expected fields,
  strict→substring), or removing `expect`/`assert`/`should`.
- Downgrading the bumped dependency back toward its old version.
- Editing CI workflow files (`.github/workflows/*`).
- Editing outside conventional source dirs (`src/`, `test(s)/`, `__tests__/`,
  `lib/`, `cmd/`, `pkg/`, `internal/`).
- Hand-editing lockfiles (let the package manager regenerate).

If the only path to green requires a forbidden change, **stop, make no change,
and report** what a human needs to decide. A red CI handed back with a clear
diagnosis is a valid, honest outcome — the same principled-refusal stance the
rest of the crew takes.

### Boundary / cross-reference

- Points to `fix-security-vulnerabilities` for cross-source vuln triage &
  prioritization; that skill may delegate the "green this bump" step here.
- Does **not** aggregate advisories, score severity, or decide *which* bumps to
  take — only fixes the failing CI of a bump already opened.

## Testing

Prompt/markdown — no `pytest` surface. Layers:

- **Mechanical:** `SKILL.md` has `user-invocable: true`, the full guardrail
  refusal list, and the numbered process (read-log-before-code, minimal-fix,
  audited-commit).
- **Behavioral (golden scenarios via `prompt-testing-plan` + `agent-evaluation`):**
  1. Renamed/moved export breaks the build → the fix is a minimal import update;
     CI-greenable; commit quotes the failing log.
  2. The only way to green is to skip a failing test → the skill **refuses**,
     makes no change, and reports for a human.
  3. A major bump with a documented breaking change → fetches the changelog and
     applies the documented 1:1 replacement (no guessed API).
  4. The skill never downgrades the bumped dependency and never edits CI YAML.

  Behavioral, verified via the Task tool at VERIFY; not CI-asserted.

## Deliverables

- `skills/dependency-pr-ci-fix/SKILL.md` — the skill.
- README `## Skills` line — add the skill to the listed set.
- A **follow-up issue** (self-contained) for the optional headless GitHub Action
  that runs this skill on a Dependabot/Renovate PR CI failure — mirrors #20/#21.
- This spec; behavioral scenarios verified at VERIFY.

## Out of scope

- The headless reusable workflow / any write-capable-token, branch-protection, or
  attempt-count-label machinery (follow-up issue).
- Vulnerability aggregation, severity scoring, or update-plan production
  (`fix-security-vulnerabilities` owns that).
- Bumping or choosing dependencies (the bot's / a human's job).

## Open risks / notes

- **Guardrails are behavioral.** Nothing mechanically blocks a forbidden edit; the
  prompt makes refusal the default and golden scenario 2 checks it. Same
  limitation as every prompt-level agent/skill in nescio.
- **"Fix only works in CI" is acceptable.** If a change can't be verified locally
  but is well-grounded in the log/changelog, committing and letting CI judge is a
  valid outcome — stated in the skill so the agent doesn't over-block on local
  verify.
