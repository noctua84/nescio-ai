---
name: nescio-adr-0001-no-agent-frameworks
description: Nescio's runtime install path stays dependency-free and framework-free; agent frameworks and harness experimentation live in a separate repo, not here.
type: adr
status: proposed
---

# ADR 0001: Keep agent frameworks out of Nescio

## Status

Proposed. Revised after an adversarial review that upheld the decision and
rejected two of its original supporting arguments; both are corrected below.

## Context

Nescio is routinely mistaken — including by its own maintainers reading general
agent-engineering advice — for an *agent system*. It is a **configuration
distribution for Claude Code**: agents are markdown with YAML frontmatter
(`agents/*.md`), skills are `SKILL.md` files, and dispatch is Claude Code's
native agent/skill system. No code here makes an LLM API call or owns an agent
loop.

The prompting question was whether Nescio would benefit from Pydantic and
LangGraph. The advice is sound for its intended audience — people building an
agent loop in Python — and misapplied here. The axis is not the system's
*domain* (software engineering vs. general purpose) but whether you **build the
agent loop or configure someone else's**. This aligns with Anthropic's
[Building Effective Agents](https://www.anthropic.com/research/building-effective-agents),
which advises starting with LLM APIs directly and warns that frameworks add
abstraction layers that obscure prompts and invite complexity.

### What this repo's state actually looks like

Two claims an earlier draft of this ADR made, which do not survive inspection —
recorded here because a future reader will otherwise re-derive them:

**Nescio is not "stateless CLI tooling."** It maintains durable state across
process boundaries, deliberately, in roughly 150 lines:

- a **durable cursor** — `hooks/record_stop.py` keeps a `.watermark` per trail;
  `prune_lines()` protects un-harvested records from the retention window, and
  `scripts/mark_harvested.py` advances the cursor using the harvest *read-time*
  so records written mid-harvest are not marked done and aged out;
- a **human-approval gate spanning processes and days** —
  `scripts/repo_hygiene_scan.py` writes a manifest, a human reviews it, and
  `scripts/repo_hygiene_apply.py` consumes it *later, in a separate process*,
  re-verifying every precondition rather than trusting the scan;
- a **hash-keyed resume ledger** — `_adopt_common.py:61` `is_done(sha, ledger)`
  against the git-tracked `memory/adoption-log.md`;
- a **threshold-triggered resume signal** — `hooks/harvest_nudge.py`.

**"Zero dependencies" is a property of the install path, not of the repo.**
Nescio already depends on third-party software outside `pyproject.toml`:
`.github/workflows/docs.yml:42` pins `mkdocs-material==9.7.7`, `tests.yml:31`
installs `uv`, several scripts shell out to `git` and `gh`, and
`install.py:457` bakes `sys.executable` into `~/.claude/settings.json` — so an
installed Nescio carries a hard dependency on one specific interpreter.

Related ADRs: **ADR 0002** (defers semantic retrieval for the memory subsystem)
is downstream of and consistent with this one. No conflicts.

## Decision

**Nescio's runtime install path remains dependency-free, and the repo remains
framework-free.**

1. We will not add LangGraph, Pydantic AI, or any agent-orchestration framework.
   The reason is *not* that there is no durable state — there is, per above. It
   is that **the durable state spans Claude Code sessions, machines, git
   history, and human decisions taken over days.** LangGraph's checkpointer
   attaches to a long-lived Python process, and there is no such process here
   for it to attach to. A framework cannot span the boundaries this state
   actually crosses; the ~150 hand-written lines can.
2. `[project] dependencies` stays empty. The property being protected is
   precise: **clone, run `install.py`, working system — with no virtualenv and
   no dependency resolution.** Because hooks execute under the interpreter
   captured at install time, a runtime dependency would resolve for a
   venv-based install and fail for a system-Python one.
3. Harness experimentation — building or wrapping an agent loop, model routing,
   durable execution, programmatic evals — lives in a **separate repo**
   (currently the `ai-exploration` scratch project).

## Options considered

| Option | Verdict |
|---|---|
| **Status quo — no runtime deps** (chosen) | Preserves clone-and-install with no environment setup. |
| LangGraph for the learning loop | Rejected — checkpointing already exists at a granularity LangGraph cannot span, for ~150 lines. |
| Pydantic as a **runtime** dependency | Rejected — breaks Decision 2 for one script's error messages. |
| Pydantic as a **dev-only** dependency group | Rejected, but narrowly — see below. |
| Vendored single-file validator under `scripts/_vendor/` | Rejected — upstream-drift maintenance for a small win. |
| stdlib `dataclass` + `__post_init__` | **Preferred if validation ergonomics become a real problem.** |
| Harness experiments inside Nescio | Rejected — couples a config tree to a runtime lifecycle. |

**The dev-only dependency group deserves its real rejection reason.** A PEP 735
`[dependency-groups] dev = ["pydantic"]` leaves `[project] dependencies = []`
untouched; `install.py` never resolves it and symlink-install is unaffected. It
genuinely does not threaten Decision 2. It is rejected because it adds a
toolchain step for contributors and a lockfile for CI to police, in a repo whose
local path (`conftest.py`, pytest) and CI path (`python -m unittest`) already
disagree about tooling — one more split is the wrong direction. This is a close
call and a legitimate future reversal.

**Pydantic is also aimed at the wrong seam.** The fragile part is not
validation, it is *parsing*: `split_frontmatter()` in `scripts/_wiki_common.py`
is a hand-rolled YAML subset parser (flat scalars, `- ` lists,
`raw.partition(":")`) with no handling for quoted values, block scalars,
comments, or escapes — and it fails **silently**, returning `({}, text)` so a
malformed note is indistinguishable from a frontmatter-free one. Pydantic cannot
fix this; it is not a YAML parser, and would be handed `{}` after parsing has
already failed. The dependency that would address it is **PyYAML**, rejected for
the same Decision 2 reason. The stdlib fix is strictly better here: constrain
frontmatter to the flat subset by convention and add a `wiki_lint` rule
*rejecting* YAML features the parser cannot represent, converting silent
degradation into an authoring-time error.

## Consequences

- The install story stays trivial: clone, run `install.py`, no virtualenv, no
  resolution, no lockfile drift across machines.
- Blog-post drift is pre-empted. The Pydantic/LangGraph question is answered
  once rather than relitigated whenever good general advice is encountered.
- **Cost:** validation in `promote_learnings.py` stays verbose and its failure
  messages are worse than a schema library's. Real ergonomics traded for
  portability, deliberately.
- **Cost / tracked work:** the frontmatter parser is duplicated three times —
  `_wiki_common.split_frontmatter`, `_split_raw_frontmatter` in
  `promote_learnings.py`, and again in `compute_readiness.py`. That divergence
  risk is created by this decision and no dependency choice fixes it;
  consolidation is owed.
- **Risk to re-verify:** if `ai-exploration` matures into a harness that Nescio
  configurations target, the config/runtime split assumed here weakens and the
  boundary needs an explicit interface — probably its own ADR.
- **Risk, adjacent:** `promote_learnings.py` is the gate through which
  session-derived content enters a **public** repo, and its
  `VALID_SCOPE_BUCKETS` includes `people` and `feedback`. Mitigations exist
  (secret redaction that blanks the whole preview on a hit, machine-local
  gitignored trails, `scrub_check.py` in CI, `memory/` absent from the mkdocs
  nav). But `scrub-terms.local` is gitignored, so CI scrubs with baseline
  patterns only — the strongest filter is the one absent from the machine that
  gates publishing. Out of scope here; needs its own assessment.
- The separate-repo rule depends on discipline; nothing mechanically prevents a
  dependency being added here.

[Source: user override — 2026-08-26]
