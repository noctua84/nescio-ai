---
name: fix-security-vulnerabilities
description: Use when working on dependency vulnerabilities, security advisories, Dependabot or Snyk PRs, GitHub security alerts, or Azure DevOps vulnerability work items — to triage, prioritize, and prepare fixes. Triggers on "fix vulnerabilities", "dependabot", "snyk", "security alerts", "CVE remediation", "dependency update plan", "audit fix".
user-invocable: true
---

# Fix Security Vulnerabilities

## Overview

Full-lifecycle skill for dependency and security vulnerability management. Aggregates findings from multiple sources, de-duplicates, discovers stale PRs, prioritizes by severity and complexity, and **prepares** fixes — then produces an **Update Plan** where merging is always a human action.

This operationalizes the "Package updates and security vulnerabilities" policy in `CLAUDE.md`. It complements — it does not replace — the report-oriented `vuln-assessment` and `sbom` skills: those *assess and score*; this one *triages and fixes*.

## Context

Before starting, read the repo's `CLAUDE.md` / `CLAUDE.local.md` and any relevant notes under `memory/` (e.g. `memory/repo/<repo>/`, `memory/feedback/`). These record which sources apply to this repo, the PR/CI conventions, and any ADO project tag.

## THE IRON LAWS

These apply without exception:

1. **Query every source that applies to this repo.** Never act on a single Dependabot PR alone. If a source is unavailable, follow the Source Failure Handling protocol — never skip silently.
2. **Never create or modify a fix PR without rewriting its body to the repo's PR template.**
3. **Never merge automatically.** All merges are explicit user steps in the Update Plan. (This mirrors the universal PR rule in `CLAUDE.md`: only the human merges.)

## Package-Update Discipline (from `CLAUDE.md`)

When a fix bumps a package version, apply the same rigor as any package update:

| Bump | Action |
|---|---|
| **Patch** | Fine to apply. |
| **Minor** | Check the package changelog for breaking changes; apply only if none. |
| **Major** | Read the changelog for **every** major version crossed, review the codebase for breakage, and note the risk explicitly in the Update Plan. Do not silently roll a major bump into a "no code change" tier. |

A security fix that *requires* a major bump is never "Tier 1 — merge immediately"; it moves to the code-change tier with a breaking-change note.

## Prerequisites

```bash
# Required
for cmd in gh jq; do
  command -v "$cmd" >/dev/null 2>&1 && echo "OK: $cmd" || echo "MISSING: $cmd (required)"
done
# Optional (Azure DevOps CLI fallback — the ADO MCP tools are preferred when available)
command -v az >/dev/null 2>&1 && echo "OK: az" || echo "MISSING: az (ADO CLI fallback unavailable)"
```

**Detect the package manager** — use the detected one for every audit/update/commit command:

```bash
if [ -f "yarn.lock" ]; then echo "PKG: yarn"
elif [ -f "pnpm-lock.yaml" ]; then echo "PKG: pnpm"
elif [ -f "package-lock.json" ]; then echo "PKG: npm"; fi
[ -f "Gemfile.lock" ] && echo "PKG: bundler"
[ -f "go.mod" ] && echo "PKG: go (use govulncheck / go get -u)"
[ -f "uv.lock" ] || [ -f "poetry.lock" ] && echo "PKG: python (pip-audit / uv)"
```

If a required tool is missing, stop and inform the user before proceeding.

## Four-Phase Workflow

### Phase 0 — Discovery: Stale & Superseded PR Audit

Before triage, take stock of open bot PRs so you don't work a dead-end.

```bash
gh pr list --search "is:open author:app/dependabot author:app/snyk-bot" \
  --json number,title,url,body,createdAt,updatedAt,statusCheckRollup,headRefName,mergeable | jq .
```

Classify each PR:

- **Ready** — CI green, no conflicts, not superseded
- **Stale** — no activity for >30 days (compare `updatedAt` to today); close and let the bot re-open fresh
- **Superseded** — a newer PR exists for the same package (duplicate name in `title`); close the older
- **Blocked** — CI red or merge conflict; record the blocker

> Only **Ready** PRs flow into Phase 2. Close Stale/Superseded PRs before proceeding.
> Per `CLAUDE.md`: ignore Gatekeeper (needs a manual comment) and SonarQube (unreliable) checks in `statusCheckRollup` when judging "CI green" on employer repos. React only to real CI failures.

### Phase 1 — Aggregate & De-duplicate (run every applicable source)

Reuse the Phase 0 bot-PR data — do not re-query it.

| Source | Tool | How |
|---|---|---|
| Open bot PRs | `gh` | Reuse Phase 0 results |
| GitHub Dependabot alerts | `gh api` | `gh api repos/{owner}/{repo}/security/dependabot/alerts?state=open&per_page=100 --paginate` |
| Azure DevOps (employer repos) | **ADO MCP** preferred | `mcp__ado__advsec_get_alerts` for Advanced Security alerts; `mcp__ado__wit_query_by_wiql` / `mcp__ado__search_workitem` for `Vulnerability` work items. Fallback: `az boards query --wiql "SELECT [Id],[Title],[State],[Severity],[Tags] FROM WorkItems WHERE [System.WorkItemType]='Vulnerability' AND [State] NOT IN ('Closed','Done','Resolved')"`. Look up the project/tag in `CLAUDE.local.md`. **Skip entirely for personal/non-employer repos.** |
| Package audit | detected PM | npm: `npm audit --json` · yarn: `yarn audit --json` · pnpm: `pnpm audit --json` · go: `govulncheck ./...` · python: `pip-audit` |

Build one unified table keyed on **package + CVE ID + GHSA ID** (match on any shared identifier). Items in multiple sources merge into one entry listing all references. An item with only a GHSA (no CVE) or vice versa is still valid.

> **Monorepos/workspaces:** run the audit from the workspace root; verify your PM version supports workspace-level `audit`; note workspace-specific findings separately.

#### Source Failure Handling

Attempt every applicable source. If one fails (not installed, auth error, 403/404, no manifest for that ecosystem):

1. **Log** the source, the command attempted, and the error.
2. **Warn** the user which source was unavailable and why.
3. **Note the gap** in the Update Plan's "Data Gaps" section.
4. **Proceed** with the available sources — never block the whole workflow.

Never skip silently. Even "nothing found" is a result that must be reported.

### Severity Normalization

Normalize to one scale before prioritizing:

| Unified | npm | Dependabot | ADO | Snyk | CVSS |
|---|---|---|---|---|---|
| Critical | `critical` | `critical` | `1 - Critical` | `critical` | 9.0–10.0 |
| High | `high` | `high` | `2 - High` | `high` | 7.0–8.9 |
| Medium | `moderate` | `medium` | `3 - Medium` | `medium` | 4.0–6.9 |
| Low | `low` | `low` | `4 - Low` | `low` | 0.1–3.9 |

Note: npm's `moderate` == everyone else's `medium`. When textual severity is missing/ambiguous, fall back to the CVSS band.

### Phase 2 — Prioritize by Severity × Complexity

Work top-to-bottom:

| Order | Severity | Complexity | Description |
|---|---|---|---|
| 1–4 | Critical→Low | No code change | Existing **Ready** bot PR — needs template rewrite + user merge |
| 5–8 | Critical→Low | Code change required | No bot PR — create branch, update package, open PR |

**Complexity:**
- **No code change** — a bot PR exists and is **Ready** (CI green, no conflicts, not a major bump)
- **Code change required** — no bot PR, or the PR is Blocked/Stale/Superseded, or the fix needs a major bump (see Package-Update Discipline)

### Phase 3 — Prepare Fixes & Produce the Update Plan

Work in priority order. **Prepare** each fix, then add it to the plan. Do not merge.

**For a Ready bot PR:**
1. Detect and fill the repo's PR template (order below).
2. Rewrite the body with a single-quoted HEREDOC:
   ```bash
   gh pr edit <number> --body "$(cat <<'EOF'
   <filled template content>
   EOF
   )"
   ```
3. Add to the plan as a **merge step for the user**.

**For a code-change fix:**
1. Branch `fix/<package>-<CVE-or-GHSA>` (e.g. `fix/axios-CVE-2025-62718`). No advisory ID → `fix/<package>-<short-desc>`.
2. Run the update for the detected PM (see Quick Reference).
3. Commit, open a PR with the template filled in. Include `AB#<id>` in the title when it maps to an ADO work item. Link the issue with a closing keyword (`Fixes #N`) per `CLAUDE.md`.
4. Add to the plan as a **merge step for the user** (after CI passes).

#### Transitive (indirect) dependencies

`npm/yarn/pnpm update <pkg>` only touches **direct** deps. For a transitive vuln:

1. First: `npm audit fix` / `yarn audit fix` / `pnpm audit --fix`.
2. If that fails: add `overrides` (npm/pnpm) or `resolutions` (yarn) forcing the patched version.
3. If the parent hasn't published a fix: mark **"blocked upstream"** in the plan with parent + vulnerable child; the user decides wait/fork/replace.

**Update Plan format:**

```
## Dependency Update Plan

Merge in order. Verify CI is green before each merge. After merging each PR,
re-check later PRs for conflicts (PRs touching the same lockfile often conflict).

### Tier 1 — No code changes (merge when CI green)
- [ ] PR #101 — Critical — lodash (CVE-2023-XXXX) — `gh pr merge 101 --squash` — then close ADO #4421

### Tier 2 — Code changes prepared (merge after CI)
- [ ] PR #201 — Critical — manual fix: my-package (no bot PR existed) — `gh pr merge 201 --squash`

### Breaking-change review required (major bump)
- pkg-x 3.x → 4.x — changelog reviewed: <summary>; codebase impact: <notes>

### Blocked upstream (no fix available)
- vulnerable-child via parent-pkg — waiting on parent-pkg >= 3.0.0

### Stale PRs closed (no action needed)
- PR #55 — superseded by #102 · PR #61 — stale (45d), closed

### Data Gaps
- ADO source skipped: personal repo (not applicable)
```

> **Merging is always a user action** — Claude never runs `gh pr merge`.
> **ADO closure is always a user action** — advise it in the plan; do not run `wit_update_work_item` / `az boards work-item update` without explicit confirmation.

## PR Template Detection

Detection order (first match wins):

```bash
for f in ".github/PULL_REQUEST_TEMPLATE.md" ".github/pull_request_template.md" \
         "PULL_REQUEST_TEMPLATE.md" "docs/PULL_REQUEST_TEMPLATE.md" \
         ".github/PULL_REQUEST_TEMPLATE/default.md"; do
  [ -f "$f" ] && echo "TEMPLATE: $f" && break
done
```

Fill it for a security fix: mark the correct changelog section (`[internal] Fixed security vulnerability in <package> (<CVE/GHSA>)`); in "How to test" describe version verification (`npm list <pkg>`, `go list -m <mod>`, etc.); check the performance box only for major bumps.

## Commands Quick Reference

| Operation | Command |
|---|---|
| List bot PRs | `gh pr list --search "is:open author:app/dependabot author:app/snyk-bot" --json number,title,url,body,createdAt,updatedAt,statusCheckRollup,headRefName,mergeable` |
| GitHub alerts | `gh api repos/{owner}/{repo}/security/dependabot/alerts?state=open&per_page=100 --paginate` |
| npm / yarn / pnpm audit | `npm audit --json` · `yarn audit --json` · `pnpm audit --json` |
| go / python audit | `govulncheck ./...` · `pip-audit` |
| Close stale/superseded | `gh pr close <n> --comment "Superseded by #<newer>"` |
| Rewrite PR body | `gh pr edit <n> --body "$(cat <<'EOF' ... EOF)"` |
| npm fix | `npm update <pkg> && git add package.json package-lock.json && git commit -m "fix: update <pkg> to fix <CVE>"` |
| yarn fix | `yarn upgrade <pkg> && git add package.json yarn.lock && git commit -m "fix: update <pkg> to fix <CVE>"` |
| pnpm fix | `pnpm update <pkg> && git add package.json pnpm-lock.yaml && git commit -m "fix: update <pkg> to fix <CVE>"` |
| Transitive fix | `npm audit fix` / `yarn audit fix` / `pnpm audit --fix` |

## Red Flags — Stop and Correct

| Thought | Reality |
|---|---|
| "I was given a Dependabot PR, so I'll just merge it" | Query every applicable source first. Run Phase 0. And Claude never merges. |
| "I'll skip the stale-PR check" | Stale PRs pollute the plan. Classify all PRs in Phase 0. |
| "The bot already wrote a PR body" | The bot body is not a changelog entry. Rewrite to the template. |
| "It's just a minor/major bump, no code change" | Minor → check changelog. Major → full review + breaking-change note. Never auto-tier a major bump as "no code change". |
| "No CVE ID, so skip it" | It may have a GHSA ID. Include it. |
| "The ADO query returned nothing, skip it" | Report the result; don't skip the source (unless it doesn't apply to this repo). |
| "This source failed, skip it silently" | Log, warn, note the gap, proceed. |
| "Just a transitive dep, `npm update` fixes it" | `npm update` only fixes direct deps. Use `audit fix`, overrides/resolutions, or flag blocked upstream. |
| "I'll close the ADO item now" | Closure is a user action, after the fix merges. |

## Out of Scope

- Running Snyk CLI / `bundle-audit` from scratch — this skill consumes existing reports/PRs/alerts.
- Automatic rollback if a bump breaks tests — human decision.
- Managing Dependabot/Snyk configuration.
- Executing merges or ADO work-item closure — always user actions.
