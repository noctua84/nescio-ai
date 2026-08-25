# Agent design principles

> A reference for anyone designing a new agent for this crew — contributor,
> maintainer, or the orchestrator running a design review. The principles here
> are not rules invented from theory; they are patterns extracted from the
> existing agents and the failures that shaped them.
>
> Read alongside the existing agent files in `agents/`. The principles are
> most useful when you are writing a new agent and asking "does this feel right?"
> — this document is the shared vocabulary for that conversation.

---

## 1. Trust model capability

Write the agent to use the model's reasoning. Specify the problem, the
constraints, and the outcomes. Do not specify the steps.

Over-specified prompts — "first do X, then check Y, then write Z" — produce
agents that follow the steps even when the situation calls for something
different. The model already knows how to reason sequentially; it does not need
the sequence written out. What it needs is clarity about what success looks like
and what is out of scope.

Compare `validator`'s core definition: *"Can a capable developer execute this
plan without getting stuck?"* One question, no procedure. The agent reasons its
way to the answer. That is more reliable than a 12-point checklist that a
different input might need in a different order.

The same principle applies to output format. Request the structure; don't
narrate every field. `<result>`, `<verdict>`, `<changed>` are output contracts
(see Principle 5) — they specify shape, not filling.

---

## 2. Lead with positive identity

Define what the agent does before what it avoids.

An agent whose opening statement is a list of prohibitions has no clear identity.
It will follow the rules without understanding why, and when a situation isn't
covered by a rule, it will guess — usually in the direction of being "helpful"
in ways that aren't helpful.

`builder`'s opening is: *"You write code that works, and you tell the truth about
what you did."* That sentence establishes identity. The constraint sections
come after, and they earn their place: each one exists because a real failure was
observed. An agent prompt is not a compliance document; it is an identity
statement with supporting constraints.

Corollary: before adding a new constraint section, ask what failure it prevents.
If you have not seen the failure, you are speculating — and speculative constraints
add length without adding safety (see Principle 6). The constraint sections in
the existing agents are evidence, not caution.

---

## 3. Scope the tools, scope the role

The tool list is part of the agent's identity, not a capability cap applied on
top of it.

An agent with `Write` is a different agent from one without it. The model does
not just avoid using the tool; it routes its reasoning differently because the
tool is present. `advisor`, `critic`, `scout`, `validator`, and `explore` all
carry `disallowedTools: Write, Edit`. They are read-only *by design*, not by
restriction — and that design makes them sharper at reading, because there is no
path in their reasoning that terminates in writing.

Assign only the tools the agent needs for its role. Additional tools expand what
the model considers doing, not just what it's allowed to do. A research agent
that has `Write` will occasionally try to write, even if its prompt says not to.
Remove the tool and the consideration disappears.

The practical test: if you are writing `disallowedTools` for a tool that is
clearly outside the role, ask whether it should be in `tools` at all.
`disallowedTools` exists for tools that come in by default and are not wanted,
not for tools you would never assign in the first place.

---

## 4. First-class outcomes

Every outcome the agent can honestly produce must be named and respected.

The crew's agents have explicit outcome vocabularies: `COMPLETE`, `PARTIAL`,
`BLOCKED` for `builder`; "all checks pass" or `BLOCKED` for `qa-guard`; ranked
findings or "no findings worth reporting" for `reviewer`. These are not just
formatting conventions — they are the mechanism that prevents an agent from
rationalising its way into an outcome it cannot honestly claim.

An agent that can only succeed in one way will reframe partial or blocked
situations as successes. This is the most common failure mode in practice: the
agent completes the nominal task and omits a `BLOCKED` that was the most
important thing to say.

The epistemic refusal — "I cannot determine this" or "no competent path exists"
— must be a named outcome, not an implicit fallback. `validator` approves by
default, but its prompt names disapproval explicitly and defines exactly when it
applies. `advisor`'s `interrogate` mode is a named outcome for the situation
where giving an answer before asking questions would be dishonest.

When you design a new agent, list every honest outcome before writing the rest
of the prompt. If the list has only one entry, the agent is over-constrained.

---

## 5. Output contracts over prose conventions

Use structured output blocks for anything the orchestrator, another agent, or a
human needs to parse reliably.

Prose conventions — "end your response with a summary of changes" — drift under
context pressure. When a session is long or a task is complex, the model
compresses the prose or reorganises it. Structured blocks do not drift: `<result>`
is `<result>`, regardless of what precedes it.

The blocks used across the crew follow the same pattern: a status or verdict
line, a content section, and a reference section (file paths, commit SHAs, test
output). These three slots cover almost everything a consuming agent needs to
route on or a human needs to audit.

New agents should define their output contract explicitly and up front. If the
output is consumed only by humans and does not need machine parsing, prose is
fine — but the decision to use prose should be made deliberately, not by default.

---

## 6. Minimal prompt length

A well-focused 200-word prompt outperforms an exhaustive 800-word one.

Long prompts bury the agent's identity in qualification and edge-case handling.
The model reads the full prompt at inference time, but the most recent and most
prominent text has more weight. A prompt that front-loads a 400-word preamble of
background and caveats makes the actual identity statement arrive late and
de-emphasised.

The practical discipline: write the core in 100–200 words. Every additional
section must justify its length by pointing to a real failure it prevents. If you
cannot name the failure, the section is speculative; speculative sections add
noise without adding safety.

`validator` is 180 words of actual instruction. `explore` is 250. The longer
agents — `reviewer`, `builder`, `critic` — are longer because those roles have
more observed failure modes, not because the role is more important.

The test: cover the prompt and ask what the agent would do given only its name
and its tool list. If the answer is roughly right, the prompt is in good shape.
If the name tells you nothing without the prompt, the identity is not clear enough
and more words will not fix it — a sharper name and a shorter, more direct first
sentence will.

---

## 7. Role separation with explicit non-overlap

Each agent should briefly state what it is not.

This is not redundant with the positive identity statement — it serves a
different function. When the orchestrator dispatches an agent for an ambiguous
task, the agent's "you are not X" clause is what keeps it from expanding into an
adjacent role. Without it, the model's helpfulness instinct fills the gap.

`builder`'s prompt states: "Distinct from planner (decides what to build),
advisor (decides how it should be shaped), and reviewer (audits it after the
fact)." `reviewer`'s states it is distinct from `validator` and `advisor`.
`critic`'s names four adjacent roles it is not.

The non-overlap clause should be one sentence per role that might be confused.
More than that is a sign the role boundary itself is unclear — fix the boundary,
not the disclaimer.

The secondary benefit: explicit non-overlap makes the crew's role map
self-documenting. A contributor adding a new agent can read the existing
non-overlap clauses and understand the existing role boundaries without needing
to read every agent's full prompt.

---

## Applying these principles

When reviewing a proposed new agent, the following questions operationalise
the principles above:

1. Can you state what the agent does in one sentence that a non-technical person
   would understand? *(Principle 2)*
2. Does every tool in the list have a specific use case in the prompt? *(Principle 3)*
3. Is there a path through the agent's task where it should honestly say "I
   cannot complete this"? Is that path named? *(Principle 4)*
4. If the prompt were cut to 150 words, what would be lost? *(Principles 2, 6)*
5. Could another agent in the crew do this task? If yes, is the boundary stated
   explicitly? *(Principle 7)*

These are not a required checklist — they are the five places where agent design
most commonly goes wrong, and the questions that surface the problem before the
agent is deployed.
