---
name: gh-milestones-projects
description: Use when creating a GitHub milestone or a GitHub Project (Projects v2 board) from the terminal, or adding issues/PRs to a project. Covers the two gh operations that have non-obvious invocations. Triggers on "create milestone", "gh milestone", "create a project board", "GitHub Projects", "add issue to project".
user-invocable: true
---

# GitHub Milestones & Projects (gh)

## Overview

Two GitHub planning operations whose `gh` invocation is easy to get wrong:

- **Milestones** — `gh` has **no** `milestone` subcommand; you must go through the REST API.
- **Projects (v2)** — `gh project …` exists, but it needs the `project` token scope, which the default login does not grant.

For plain issue/PR creation and PR-template detection, use the `handle-pr-comments` skill and standard `gh issue create` / `gh pr create`; this skill is only the milestone + project pieces.

## Context

Before starting, read the repo's `CLAUDE.md` / `CLAUDE.local.md` for repo/owner conventions. Derive the repo identity — never hardcode it:

```bash
REPO=$(gh repo view --json owner,name -q '.owner.login+"/"+.name')   # e.g. Cognigy/ui
OWNER=${REPO%%/*}
```

## Milestones

`gh milestone create` **does not exist**. Use the API.

```bash
# Create
gh api --method POST "/repos/$REPO/milestones" \
  --field title="v1.0" \
  --field description="First stable release" \
  --field due_on="2026-09-30T00:00:00Z"     # ISO 8601; always T00:00:00Z. Omit the field for no due date.

# List existing (titles)
gh api "/repos/$REPO/milestones" --jq '.[].title'
```

Attaching a milestone to an issue/PR:
- `gh issue create --milestone "v1.0"` / `gh pr create --milestone "v1.0"` — these take the milestone **title**.
- `gh api` payloads take the numeric milestone **id**, not the title.

## Projects (v2 boards)

**Prerequisite — the `project` scope.** The default `gh` token lacks it; `gh project` commands fail with a scope error until you add it (a one-time, interactive user action):

```bash
gh auth status                 # check current scopes
gh auth refresh -s project     # add the 'project' scope (interactive — user runs this)
```

If the scope is missing, stop and tell the user to run `gh auth refresh -s project` — don't try to work around it.

```bash
# Create a project (owner: a user login, an org, or @me for yourself)
gh project create --owner @me --title "Q3 Roadmap"
gh project create --owner "$OWNER" --title "Q3 Roadmap"      # org-owned

# List projects for an owner (get the project number)
gh project list --owner "$OWNER"

# Add an existing issue/PR to a project (by number + URL)
gh project item-add <project-number> --owner "$OWNER" \
  --url https://github.com/$REPO/issues/23

# Add a brand-new draft item (not backed by an issue yet)
gh project item-create <project-number> --owner "$OWNER" \
  --title "Spike: evaluate X" --body "Details…"

# Link a project to this repo (so it shows under the repo's Projects tab)
gh project link <project-number> --owner "$OWNER" --repo "$REPO"
```

`--format json -q <jq>` is available on the read/create commands when you need to capture the new project's number/id for scripting.

## Common mistakes

| Mistake | Fix |
|---|---|
| `gh milestone create` | Doesn't exist — `gh api --method POST /repos/$REPO/milestones`. |
| Hardcoding `owner/repo` | Derive with `gh repo view --json owner,name -q '.owner.login+"/"+.name'`. |
| `gh project` fails with a scope error | Missing `project` scope — user runs `gh auth refresh -s project`. |
| `--milestone` with a numeric id on `gh issue create` | That flag takes the milestone **title**; only `gh api` payloads use the id. |
| `due_on` without the time component | Must be full ISO 8601 ending `T00:00:00Z`, or omit the field. |
| `item-add` without `--url` | It needs the issue/PR **URL**; use `item-create` for a draft item with no URL. |
