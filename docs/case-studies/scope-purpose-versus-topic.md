# Case study: three scope decisions, all correct, none the same rule

**Date:** 2026-08-30
**Companion to** `orchestration-failure-modes.md` — same session, opposite claim.

That document argues the crew's value shows up as **refusals**. This one is about the
harder case: when an agent should do *more* than it was told, and how that is
distinguishable from the scope creep everyone rightly fears.

The codebase is not named and the findings are generalised.

---

## The observation

An agent was told to retire a false premise from shipped code. The brief listed the
sites: a justification comment, a method built on the premise, the types it flowed
through, and the contract document.

It fixed all of them, and then reported two more it had found on its own — a
"rules that must not be softened" preamble, and an enum's doc-comment — with the
reasoning that leaving either would let a reader **re-derive the false model** the task
existed to destroy.

That is the difference between executing a checklist and understanding what it is for.
Nobody could have enumerated those two sites without reading the code; the brief's author
(the orchestrator) had not.

## Why this is not simply "good initiative"

Scope expansion is normally a **vice** in an agent. It produces unreviewable diffs, it
touches files other agents are holding, and it is the most common way a small change
becomes a big one. Most of the time the correct behaviour is the opposite — and the same
session shows agents doing exactly that.

**Three scope decisions, from three agents, all correct, and all different:**

| | Situation | Decision | Why it was right |
|---|---|---|---|
| **1** | Hit a real defect in a file the brief put off-limits | **Did not fix it.** Wrote a failing-when-fixed test pinning the broken behaviour, skipped the two dependent cases with pointers to the pin, reported `PARTIAL` | The defect was outside the brief's *purpose*. Fixing it would have hidden a serious bug inside an unrelated diff. The pin made it loud without widening the change |
| **2** | A change to a union broke an off-limits file's exhaustive `never` guard | **Edited it anyway**, one line, and said so plainly | Omission was *impossible*: the file would not compile. The `never` guard converted a silent gap into a build failure, which is what it exists for |
| **3** | Brief listed the sites restating a false premise | **Found two more and fixed them** | The brief's purpose was "a reader must not be able to re-derive this model." Leaving either site would have defeated it while satisfying the letter of the list |

No single rule produces all three. "Stay in scope" gets #3 wrong. "Fix what you find"
gets #1 wrong. "Follow the brief exactly" gets #2 stuck.

## The discriminator

The question that separates them is not *how far from the brief* the work is. It is:

> **Does this serve the brief's purpose, or merely its topic?**

- #1's defect shared the *topic* (the same feature) but not the purpose. Out.
- #3's two extra sites were not on the list, but the list was only ever a proxy for the
  purpose. In.
- #2 was not a choice at all — the compiler made it — and the right response was to do
  it and **declare it**, which is what turns an unavoidable breach into a reviewable one.

This is why briefs should state **why**, not only **what**. All three agents were given
the reasoning behind their task, not just its file list. #3's agent could only recognise
the two extra sites because it knew what the fix was *for*; given a bare checklist it
would have completed the checklist.

## The failure mode this avoids

The document being corrected had already produced one real defect earlier in the same
session: a comment that was *confidently wrong*. A reader had checked its claim, found it
false, and — correctly, on the evidence — concluded the surrounding reasoning was
unreliable.

**A confidently wrong comment is worse than no comment**, because it is load-bearing for
someone else's decision. That is precisely why a half-corrected premise is not half a
fix: the two surviving sites would have been the ones a future reader found, and they
would have reconstructed the retired model in full.

Getting that right is not diligence. It is knowing what the artifact is for.

## What it implies for how work is dispatched

- **Put the purpose in the brief, above the file list.** The list is a proxy; agents that
  only receive the proxy can only satisfy the proxy.
- **Say what is off-limits and why.** #1's agent respected a boundary *and* made the
  defect impossible to miss — it could only do both because it knew the boundary's reason.
- **Expect the boundary to be wrong sometimes.** In #2 it was, and the agent's job was to
  say so, not to route around it silently.
- **Ask for the extras to be reported, not just done.** In all three cases the value came
  as much from the *report* as from the change. An agent that had quietly fixed #3's two
  extra sites would have been right and unreviewable.
