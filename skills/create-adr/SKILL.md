---
name: create-adr
description: Use when recording an architecture decision, proposing an architectural change, or checking whether a proposed change conflicts with an existing decision. Writes an ADR in this brain's lightweight format and reconciles it against every existing ADR. Triggers on "create ADR", "architecture decision record", "document this decision", "does this conflict with an existing ADR".
user-invocable: true
---

# Create ADR

## Overview

ADRs capture significant architectural decisions with enough context for a future session to understand the *why*, the alternatives, and the consequences. The value this skill adds over free-hand note-taking is the **conflict gate**: every new ADR is reviewed against all existing ADRs for the same repo, and **no decision may silently contradict an accepted one** — it must either supersede it or justify coexistence.

This brain already has an ADR convention — see the `adr/` subdirectory of any `memory/repo/<dir>/` that has one. Match it — do **not** invent a heavier template.

## Context

Before starting, read the repo's `CLAUDE.md` / `CLAUDE.local.md` and the relevant `memory/repo/<repo>/` notes for prior decisions and constraints.

## Step 1 — Locate the ADR directory

Decide where the ADR lives:

- **Target project has its own `docs/adr/`** (or `docs/decisions/`) → write there, in that project's format.
- **Otherwise (default for this brain)** → `memory/repo/<repo>/adr/`, using this brain's format below. `<repo>` is the short repo name already used under `memory/repo/`.

```bash
ls docs/adr docs/decisions 2>/dev/null            # target-project convention?
ls memory/repo/<repo>/adr 2>/dev/null             # brain convention (default)
```

## Step 2 — Review existing ADRs before writing (MANDATORY)

Read **every** ADR already in the chosen directory. Do not skip this — it's the whole point of the skill.

```bash
ls memory/repo/<repo>/adr/ | sort
```

For each existing ADR, read its `## Decision` and `## Status`, then group them by the domain they touch (transport, persistence, error handling, identity, config, observability, …). Build the domain grouping **dynamically from what you read** — there is no fixed domain map, because it differs per repo.

### Conflict checklist

The new decision must NOT, without explicit resolution:

- [ ] Contradict an ADR whose status is `accepted` / `as-built` without superseding it
- [ ] Re-standardize a concern an existing ADR already standardized (a different library/pattern for the same job)
- [ ] Change a taxonomy (error codes, ID typing, naming) an existing ADR fixed
- [ ] Reintroduce something an existing ADR explicitly rejected in its Consequences

**If any box is checked:** the new ADR must address the conflict in its `## Context` — either supersede the old ADR (Step 5) or justify why both can coexist. A silent contradiction is the one failure mode this skill exists to prevent.

## Step 3 — Number and name the file

- Next number = highest existing + 1, 4-digit zero-padded.
- Filename: `NNNN-kebab-case-title.md` (e.g. `0005-retry-budget-per-request.md`).

## Step 4 — Write the ADR (brain format)

Match the existing files exactly. Frontmatter + core sections:

```markdown
---
name: <repo>-adr-NNNN-<slug>
description: <one-sentence statement of the decision — this is what recall reads>
type: adr
status: proposed        # proposed | accepted | as-built | superseded
---

# ADR NNNN: <Title as an imperative or a claim>

## Status

Proposed.   <!-- or: Accepted. / As-built (documents current code, not a weighed decision). -->

## Context

[Forces at play: constraints, requirements, what prompted this. Cite code with
file:line where the decision is grounded. **List related ADRs here** and state
whether this conflicts with any — resolved per Step 2.]

## Decision

[The decision in active voice: "We will …" / "X is typed as …". Include the
rationale: why this option won, against which drivers and constraints.
Subsections and code snippets where they clarify. For as-built ADRs, describe
what the code does.]

## Options considered

**Required for `proposed` and `accepted` ADRs; exempt for `as-built`** (which
document existing code, not a weighed choice). List each alternative you
actually weighed, with its pros/cons and **why it was not chosen**. Always
include "do nothing / status quo" as one option. Don't invent straw men or pad
a genuinely straightforward decision.

## Consequences

[What follows — including the costs. State at least one **negative** consequence
or risk; an ADR with only upsides is under-examined. Note anything a future
session should re-verify.]
```

**Note on frontmatter:** `adr-template.md` uses the *published* form frontmatter (`title`/`status`/`source_repo`), as transformed by `scripts/_adr_transform.py`. Brain ADRs use the form shown above (`name`/`description`/`type`/`status`). Match whichever applies to your ADR's location.

## Step 5 — Supersession (only if replacing an existing ADR)

When the new ADR replaces an old one:

1. New ADR frontmatter/context: note `Supersedes ADR-NNNN`.
2. Open the old ADR, set `status: superseded` in frontmatter and `## Status` → `Superseded by ADR-MMMM.`
3. Cross-link both directions in their `## Context`.
4. **Never rewrite the body of a superseded ADR** — only update its status and add the pointer. The old reasoning stays as history.

## Common mistakes

| Mistake | Fix |
|---|---|
| Skipping Step 2 | Read every existing ADR first — conflict detection is the point. |
| Silent contradiction of an accepted ADR | Supersede it, or justify coexistence in Context. |
| Only positive consequences | Add at least one negative/risk. |
| Importing a heavy multi-section corporate template | Use the sections in Step 4 and nothing else — Status, Context, Decision, Options considered (exempt for `as-built`), Consequences; match the existing files. |
| `proposed` or `accepted` with no Options considered | Add the alternatives you actually weighed and why each was rejected. Exempt only `as-built` ADRs. |
| No rationale in Decision | State why the chosen option won against which drivers/constraints. |
| Author self-marks `accepted` | Default `proposed`; promote to `accepted` only when the decision is actually adopted. |
| Rewriting a superseded ADR's body | Update status + add a pointer; leave the reasoning intact. |
