# Epistemic gates — principled refusal + routing quality gate

Status: example spec

> **Worked example.** Adapted from this framework's own design work — it shows the
> spec format and the reasoning behind the epistemic gates. Some project-specific
> references have been trimmed.

## Purpose

Add two small, additive epistemic policies to the agent crew, both grounded in
cognitive-architecture research on epistemic honesty:

1. **Principled refusal** — make *"I don't know / no competent path"* a
   first-class, respected output for the orchestrator and the six advisory /
   research agents, instead of forcing a best-of-a-bad-set answer.
2. **Routing quality gate** — the orchestrator refuses to relay or act on a
   subagent result it trusts less than its own read (the "telephone-game" /
   *Stille Post* failure).

It is a pure agent-prompt change — no memory code, no new agents, no scripts.
Both policies are small additive clauses; no agent is restructured.

## Scope boundary (what this is NOT)

This covers **only** the two agent-prompt policies. Memory-side epistemic gates —
confidence-decay on stale memory, diversity-weighted promotion — are deliberately
out of scope here; they belong with the memory/learning subsystem, not the agent
charters. Whether specialist agents should emit an explicit "Confidence & gaps"
signal to feed the routing gate is left open, to decide from real use.

## Why this design

- **Hallucination is a structural absence, not a data problem.** The
  central claim: a system with no first-class way to say "I have nothing for this"
  is *forced* to emit the nearest neighbour. The fix is structural and cheap — 
  legitimize refusal as an output. That is the flagship idea here.
- **Refusal is a form of driving forward, not stalling.** The orchestrator's
  TURN TERMINATION rule mandates never ending passive. Refusal does not violate
  it: a refusal *surfaces the blocker and hands the user a concrete decision*,
  which is forward motion. The design frames it that way explicitly so the two
  rules don't appear to contradict.
- **The gate stays qualitative on purpose.** A naive version compares numeric
  uncertainties; doing that literally would require every subagent to emit a
  confidence number, which invites fabricated-confidence theatre. The orchestrator
  already judges answer quality in "Synthesis Over Relay" — we add a *decision*
  (withhold / re-dispatch / surface) rather than a *metric*. Whether an explicit
  per-agent signal earns its keep is left to decide from real use.
- **Refuse where fabrication is most likely.** The advisory/research agents
  produce answers and reports that can be confidently wrong; they are the primary
  targets. `scout` and `validator` already have refuse-like behaviour (asking
  questions; blocking a plan), so they get lighter, register-appropriate touches.

## Policy 1 — Principled refusal

### Orchestrator (`agents/orchestrator.md`)

- **PHASE 0 TRIAGE** — add a branch: if there is no competent path (no agent,
  tool, or available knowledge fits the request), or the request is
  under-specified beyond what a DISCOVER phase could resolve, say so and ask —
  do not force the lifecycle forward to manufacture motion.
- **TURN TERMINATION** — add refusal as an allowed terminator, alongside the
  existing ones: *"No competent path — here's what's missing, and here's the
  decision I need from you."* Framed explicitly as surfacing-the-blocker (forward
  motion), not passive stalling.

### Advisory / research agents

Each gets one short clause, in its own register, legitimizing honest non-answers
as the expected output when the basis is absent — better than a confident guess.
This mirrors `critic`'s respected "Plan holds" verdict.

- `agents/advisor.md` — "insufficient basis to advise → say so and name what's
  missing" (extends its pragmatic-minimalism stance).
- `agents/reviewer.md` — "if you cannot confirm an issue, say 'unverified' + what
  would resolve it" (it already has a "Needs Investigation" status — make the
  refusal explicit).
- `agents/explore.md` — "if you didn't find it, return *not found* + where you
  looked; never fabricate a plausible path."
- `agents/librarian.md` — "if the docs/sources don't answer it, say so; don't
  synthesize a confident answer from thin sources."
- `agents/scout.md` — *light touch*: "if intent is too ambiguous to classify,
  say so and ask, rather than guessing a class" (it already asks questions and
  reports classification confidence).
- `agents/validator.md` — *light touch*: "if there's insufficient basis to judge
  executability, say so rather than rubber-stamping" (it is already an
  approve-biased blocker gate).

## Policy 2 — Routing quality gate

Edit `agents/orchestrator.md` **"Synthesis Over Relay"**. Add a gate applied
before relaying or acting on any subagent result:

> Judge whether you trust the result more than your own read. If it is hedged,
> thin, internally inconsistent, or you would be *less* sure of it than if you
> had done the work yourself, do not relay it. Instead: re-dispatch with a
> tighter prompt, cross-check with another agent, or surface the uncertainty to
> the user. Never launder a low-trust answer into a confident summary.

Qualitative only — no confidence scores. This is a routing quality gate ("reject
a routed answer more uncertain than your own composite") expressed at the prompt
layer.

## Testing (behavioral)

Agents are prompts; verification is behavioral (as with `critic`), run via the
Task tool by having fresh agents adopt the edited charters. Golden scenarios:

1. **No competent path** — orchestrator handed an impossible or badly
   under-specified task (e.g. "make the app faster" with no app, metric, or
   access) → expect refusal + a specific question, **not** a fabricated
   plan/lifecycle.
2. **Low-trust relay** — orchestrator handed a subagent result that is visibly
   hedged / internally inconsistent / likely wrong → expect withhold + re-dispatch
   or surface-uncertainty, **not** a confident relay.
3. **Honest specialist non-answer** — an `explore`-style agent asked for
   something that isn't in the codebase → expect *not found + where I looked*,
   not a plausible-but-invented path.

Behavioral, not CI-asserted; the limitation is stated openly (consistent with the
`critic` spec).

## Deliverables

- `agents/orchestrator.md` — TRIAGE branch, TURN TERMINATION refusal terminator,
  Synthesis-Over-Relay quality gate.
- `agents/advisor.md`, `agents/reviewer.md`, `agents/explore.md`,
  `agents/librarian.md` — refusal clause (primary targets).
- `agents/scout.md`, `agents/validator.md` — light refusal clause.
- This spec.
- No README change (behaviour refinement, not new agents).

## Open risks / notes

- **Over-refusal.** A poorly-worded clause could make agents bail instead of
  attempting. Mitigation: each clause is scoped to *absence of basis* (no path /
  no evidence / not found), not difficulty; the wording emphasises "honest
  non-answer when the basis is absent," not "give up when it's hard." Verified by
  scenario 3 (the agent should still search hard before saying not-found).
- **Gate subjectivity.** The routing gate relies on the orchestrator's judgment
  of "trust." That is acceptable — it already synthesises and resolves
  contradictions; this adds a withhold decision. If it proves insufficient, an
  explicit per-agent signal is the escalation path.
- **Executors excluded deliberately.** `general-purpose` execution agents keep a
  "just do the task" mode; refusal there would risk bailing on implementable work.
