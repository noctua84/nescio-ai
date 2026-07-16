# `critic` — the devil's-advocate agent

Status: example spec

> **Worked example.** Adapted from this framework's own design work — it shows the
> brainstorm → spec format and the reasoning behind the `critic` agent. Some
> project-specific references (tickets, branches) have been trimmed.

## Purpose

Add an agent to the crew, `agents/critic.md`: a read-only,
adversarial reviewer whose single job is the "what if?" that gets discarded too
fast. It challenges **approach and judgment** — *should we build it this way, and
what did we all overlook?* — and is wired into the orchestrator to fire
automatically at the end of the PLAN phase for high-stakes work, plus on demand.

The design borrows from cognitive-architecture research on epistemic honesty and
anti-hallucination. This spec covers **only** the agent.

The agent's charter is the Socratic method made operational: **elenchus**
(cross-examining assumptions until a hidden contradiction surfaces), the
**daimonion** (the inner voice that only ever gently says "don't"), and *"I know
that I know nothing"* (epistemic humility — the mandate that "the plan holds" is a
respected verdict, not a failure to find fault). Tone and verdict are separate
dials: the register stays the friendly gadfly even when the verdict is sharp.

## Why this design

- **The valuable idea is a *policy*, not machinery.** A *fixed set of challenge
  types resolved in a single weighted pass* — not open-ended interrogation — is
  what makes an adversary useful instead of theatrical.
- **Bounded by construction, not by instruction.** A devil's advocate forced to
  object on every run manufactures weak dissent to justify its slot, which trains
  the reader to skim past it — so the one real objection is lost in boilerplate.
  We prevent this structurally: a finite lens list, a single pass, a capped and
  ranked output, no self-recursion, and a first-class "plan holds" verdict. The
  no-op verdict is the same principled-refusal idea the epistemic gates use,
  turned on the challenger itself.
- **Distinct from every existing agent.** `scout` triages risk *pre-plan*;
  `validator` asks *can we build it*; `advisor` advises *what to build*; `reviewer`
  audits *built code*. Critic asks *should we build it this way, and what was
  overlooked* — after the plan exists, before code is written. It pairs with
  `validator`: **validator = "can we build it," Critic = "should we build it
  this way."** It is also the dispatched, heavier sibling of the orchestrator's
  inline **Scope-Drift Reflex** in PHASE 4.
- **Refer out; don't duplicate.** The framework ships ~25 `user-invocable` skills
  covering security and compliance. The critic's PII/legal and security lenses
  *flag and refer* to those skills rather than re-implementing them, keeping the
  agent lightweight.

## When it fires

The orchestrator auto-invokes Critic at the **end of PHASE 3 (PLAN)**, after
`validator` and before the plan-approval gate — challenge the approach before any
code is written, where a fix is cheapest. Fire condition:

> TRIAGE class ∈ {Mid-sized, Build-from-scratch, Architecture}
> **OR** the change touches a **sensitivity flag** — authentication/authorization,
> core business logic, security, irreversible/outward-facing actions, or
> **PII / legal / compliance** — *even if the change is otherwise trivial.*

The sensitivity flag is deliberately allowed to override the "skip trivial work"
rule: a one-line change that starts logging a user's email is trivial by size but
must still trip the PII/legal lens. The orchestrator already computes the TRIAGE
class, so the size half of the condition is free.

Critic is also available **on demand** ("red-team this"), where it can be
pointed at an already-implemented change, not only a plan.

## Operating model — fixed lenses, single pass

Critic walks a finite checklist of adversarial lenses exactly once, then stops.
It never interrogates its own challenges (no why-chain). It may run its own
research *within* the pass (`explore`, `librarian`, web) to substantiate a
challenge — bounded because the pass does not loop.

| # | Lens | Question | On hit, refer to |
|---|------|----------|------------------|
| 1 | Blind spots | What's unstated or assumed-obvious that's actually load-bearing? | — |
| 2 | Premise attack | Which single assumption, if wrong, collapses the plan? | — |
| 3 | Counter-example | A concrete case (same conditions) where this approach fails | — |
| 4 | Overfitting | Is this generalized from too few / too similar precedents? | — |
| 5 | Value-collapse | What partner value is being sacrificed (speed vs safety, DX vs security)? | — |
| 6 | Alternatives | ≥1 genuine alternative **plus one deliberately absurd** "what if we did the opposite?" | — |
| 7 | PII / legal / compliance | **Always checked.** Does this touch personal data, regulated data, or legal exposure? | `compliance-gap-analysis`, `hipaa-assessment`, `pci-dss-assessment`, `threat-model` (LINDDUN) |
| — | (security sensitivity) | When the security flag tripped the invocation, name the surface | `secure-code-review`, `security-architecture-review`, `threat-model` |

The counter-example lens uses a precise falsification rule: a
counter-example only counts when the **conditions are the same but the outcome
differs** — not merely a different outcome under different conditions. This keeps
lens 3 from producing spurious objections.

## Tone (separate from verdict)

The register is the **benevolent gadfly** — collegial, curious, "wait, what
if…?", the friendly itch in the back of the mind that questions rigid
assumptions. It is explicitly **not** the sneering critic who tells you that you
screwed up and why you should have done it differently. The prompt fixes tone
warm and lets only the *verdict* go sharp. Epistemic humility is mandatory:
Critic professes it may be wrong and defers the decision to the human.

## Output contract

Inline, read-only — returned to the caller (orchestrator or user), no file
written. Structure:

- **≤ 5 material challenges**, ranked by materiality (High / Medium / Low).
  Low-materiality nitpicks are suppressed, not padded in.
- Each challenge = **what-if · why it was overlooked · suggested resolution or
  the alternative** (the maieutic move — draw out the better idea, don't just
  attack).
- **One overall verdict:**
  - **Plan holds** — no substantive challenge (first-class, respected, no penalty).
  - **Minor concerns** — proceed, but note these.
  - **Material objections** — address before executing.
  - **Stop — reconsider** — a premise or legal issue undermines the approach.

## Orchestrator wiring

One edit to `agents/orchestrator.md`, PHASE 3 (PLAN): after the `validator` step
and before the plan-approval gate, conditionally dispatch `critic` when the
fire condition holds; surface its verdict and challenges in the plan-approval
summary. For **Architecture-class** decisions, the orchestrator folds the
surviving challenges plus the chosen resolution into an ADR under
`memory/repo/<repo>/adr/`. Critic itself stays read-only; the orchestrator does
the persisting. Style mirrors the terse "reflex" phrasing of the existing
Scope-Drift Reflex.

## Frontmatter and tools

```yaml
name: critic
description: Devil's-advocate reviewer. Challenges a plan's approach and
  assumptions in a single bounded pass — blind spots, premises, overlooked
  alternatives, and PII/legal exposure — then returns ranked challenges and a
  verdict. Read-only advisor. Distinct from scout (pre-plan risk), validator
  (executability), advisor (design direction), and reviewer (built-code audit).
model: claude-opus-4-8
disallowedTools: Write, Edit
```

Reasoning-heavy adversarial role → Opus, matching the other advisory agents.
Read tools and the research path (`explore`, `librarian`, `WebSearch`,
`WebFetch`) are enabled; `Write`/`Edit` are disabled so it cannot mutate the repo
— consistent with `scout`/`advisor`.

## Anti-theatre guardrails (explicit NEVERs in the prompt)

- Never manufacture an objection to justify the slot; reaching "plan holds" is
  success.
- Never recurse into a why-chain — one pass over the lenses, then stop.
- Never re-litigate what `scout` already flagged pre-plan.
- Never exceed the 5-challenge cap or pad with low-materiality nitpicks.
- Never adopt the sneering-critic tone; the gadfly is friendly.
- Never perform a full compliance or security assessment inline — flag and refer
  to the relevant skill.

## Testing

Agents are prompts, so there is no `pytest` surface. Use the framework's own
evaluation skills instead of a hand-rolled scheme:

- **`prompt-testing-plan`** — define the golden test cases and pass/fail criteria.
- **`agent-evaluation`** — score trajectory, tool-use correctness, and task
  completion against those cases.
- **`prompt-evaluation-harness`** — optional LLM-as-judge scoring for regression
  (its "hallucination rate" metric is fittingly on-theme).

Golden scenarios (minimum set):

1. **Sound plan, no sensitivity** → verdict **Plan holds**; zero manufactured
   objections.
2. **Plan that silently logs PII** → lens 7 fires; verdict ≥ **Material
   objections**; refers to a compliance skill.
3. **Approach overfit to one prior case** → lens 4 fires with a named
   counter-domain.
4. **Trivial one-liner, no sensitivity flag** → orchestrator does **not** invoke
   Critic (tests the fire condition, not the agent).
5. **Bounded-output check** → on a plan with many weak issues, output stays ≤ 5,
   ranked, and does not recurse.

Verification runs the agent via the Task tool against these scenarios during the
VERIFY step; results are behavioral, not asserted in CI. This limitation is
stated openly.

## Deliverables

- `agents/critic.md` — the agent (charter, fire condition, seven lenses, tone,
  output contract, guardrails).
- `agents/orchestrator.md` — PHASE 3 wiring + ADR-fold for Architecture.
- `README.md` — a row in the agent table + a sentence in the crew description.
- This spec; testing scenarios verified behaviorally.

## Out of scope

- The **epistemic gates** (principled refusal, routing quality gate) — separate spec.
- Any change to the other agents beyond the orchestrator wiring.

## Open risks / notes

- **Fire-condition false negatives.** The sensitivity flags are judgment calls
  the orchestrator makes; a missed PII touch means Critic doesn't fire. Mitigated
  by making PII/legal an always-checked lens *when it does* fire, and by the
  on-demand path. Not fully eliminable at the config layer.
- **Cost.** Auto-firing an Opus agent with a research path adds a pass to every
  high-stakes plan. Bounded by the TRIAGE gate (trivial/tested-bugfix skipped)
  and the single-pass model.
