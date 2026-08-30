# Case study: what the crew caught, and what it cost the orchestrator to learn it

**Date:** 2026-08-29
**Shape of the work:** one orchestrator, ~15 dispatched `archimedes` agents, a
cross-repo payment-flow rework in a private codebase. 18 commits, 65 files,
+13,407/−310. All verification gates green at the end.

The codebase is not named here and the findings are generalised. Nothing in this
document depends on the client; the evidence is about the *setup*, not the
subject.

---

## Why this is written as a list of failures

The obvious way to argue for an agent crew is to show what it produced. That
argument is weak, because a single competent model produces plausible output
too, and plausible output is exactly the failure mode nobody catches.

The stronger argument is the one this session actually supports:

> **The crew's value showed up as refusals and corrections — most of them
> directed at the orchestrator, not at the code.**

Five times an agent declined to do what it was told, and was right. Once the
orchestrator was wrong in a way that *three agents independently confirmed*, and
the confirmation was worthless. That last one is the most useful thing in this
document.

---

## 1. An agent refused to fabricate a passing test, and disproved the premise

**The instruction.** A config flag had to default off. The orchestrator briefed a
regression test and demanded proof it bites: reintroduce the bug, show the test
failing, revert, show it passing.

**What came back.** The mutation did not fail — and the agent said so, pasted the
green run, and explained why: the schema's own default meant the two forms were
provably equivalent. The trap the orchestrator had written a warning comment
about *did not exist as described*.

It then ran two substitute mutations that did represent the real danger, showed
those failing, and reported the discrepancy.

**Why it matters.** The easy path was one line of theatre — tweak the assertion
until the mutation appeared to bite, paste both runs, collect the green tick.
Nothing downstream would have caught it. Instead the orchestrator learned that a
comment it had already committed was *factually wrong*, and the fix became
structural: make the idiom safe under both conditions rather than document a
hazard that only half-existed.

> An overstated warning is worse than no warning. A reader checks it, finds it
> false in thirty seconds, distrusts the surrounding reasoning, and does the
> dangerous thing anyway — which is precisely what the comment existed to prevent.

---

## 2. An agent caught the orchestrator's own briefing error, and refused to write unverifiable facts

**The instruction.** Record a cross-repo invariant in a permanent code comment.
The orchestrator supplied a table of values from both sides.

**What came back.** The agent opened the file and found the orchestrator's figure
for *this* repo wrong by a factor of 24. It made no value change — that was
outside its scope — but it drew the correct inference:

> If the number I was given for the side I *can* check is wrong, I should not
> hard-code the numbers for the side I *cannot* check.

It wrote the invariant naming both variables and the **direction of danger**, and
omitted every figure.

**Why it matters.** The orchestrator later verified the other repo directly and
found that number wrong too. A comment stating both would have been stale on the
day it landed — in a place whose entire purpose is to be the only enforcement
mechanism for a constraint with no shared config source.

The agent could not have known the second number was wrong. It reasoned from
*calibration*: the brief had just demonstrated its own unreliability on a
checkable claim.

---

## 3. An agent reversed an instruction on evidence

**The instruction.** A row count was unfiltered; filter it, or explain why not.

**What came back.** It declined, with a reason the orchestrator had not
considered: the figure renders in an account-deletion confirmation under *"the
following data has been permanently deleted."* It counts **rows destroyed**, not
live rows. Filtering would have *understated* an erasure in a
compliance-facing message — wrong direction, and worse than the inconsistency it
would have fixed.

It made the intent explicit in a comment instead.

**Why it matters.** The orchestrator had classified this as a trivial cleanup and
briefed it as one. The correct answer required reading a template three
directories away and knowing which regulatory promise the number serves. The
orchestrator verified the claim and accepted the reversal.

---

## 4. An agent found a test that passed for the wrong reason

After a control-flow change, one test still passed. The agent flagged it anyway:
it was named for one branch but now reached its assertion through a *different*
one, because a stub defaulted in a way that routed around the named path.

It reported this as more serious than the test that had failed loudly.

**Why it matters.** It is right, and this is the finding least likely to come
from a single pass over a diff. A red test gets fixed. A green test that never
exercises the path it names reports coverage that does not exist, and nobody
looks at it again. The fix split it into two tests — one per branch — and proved
each bites.

---

## 5. An agent hit a defect in another agent's work and refused to widen its scope

Mid-task, an agent discovered that a repository method committed earlier could
not work inside a caller-supplied transaction — which was the entire reason the
method's optional parameter existed. The blast radius was real: the broken path
was taken by *any user who had previously cancelled*.

The method was outside its permitted scope. So it:

1. wrote a **failing-when-fixed test asserting the broken behaviour**,
2. skipped the two dependent cases with pointers to that pin,
3. reported `PARTIAL`, and
4. did not touch the file.

**Why it matters.** Three worse options were available and all are common: fix it
quietly and blow the scope; work around it locally and leave the defect; or leave
two red tests to be explained away at merge. Instead the defect stayed *loudly
visible* while the suite stayed *honest*, and the orchestrator dispatched a
dedicated fix with the reproduction already written.

The defect had survived because the parameter it broke had **zero integration
coverage** — the original agent's tests were thorough on the path it happened to
exercise and silent on the one that mattered. Which is an argument for adversarial
review by a *different* agent, not for more tests by the same one.

---

## 6. The orchestrator's failure: three agents agreed, and all three were wrong

This is the one worth the price of admission.

Three separate agents reported the integration harness as broken. They gave
**three different root causes**, each with a plausible mechanism:

| Agent | Diagnosis | Evidence offered |
|---|---|---|
| A | container reuse + unconditional teardown | connection-terminated errors mid-run |
| B | deadlock in the shared truncate | untouched control file failing identically |
| C | a config option defaulting to parallel | untouched file 12/25 red, 25/25 with an override |

C's was the strongest evidence in the session: a file nobody had touched,
failing, then passing under a one-line change. It was labelled the highest-value
finding available and the fix was one line in shared test config.

**The orchestrator ran that same untouched file on a quiet machine. It passed
25/25 without the override. Then the full suite passed 208/208.**

The harness was never broken. All three reports were artifacts of the
orchestrator's own parallelism — up to two dozen processes contending for one
container. Three agents had independently observed a real phenomenon and
correctly reported it; the *cause* was the thing dispatching them.

Had the best-evidenced diagnosis been accepted, the result would have been a
committed one-line change to shared test infrastructure that fixed nothing,
justified by a reproduction that does not reproduce.

> **Convergence is not corroboration when the reports share a hidden common
> cause.** Three independent confirmations of a symptom say nothing about the
> cause if the thing they have in common is the observer.

The orchestrator then reproduced the same mistake **three more times** while
trying to close the gate — cleanup racing a run's own startup, then two
overlapping runs, then a third. Each produced the identical "broken harness"
signature. Cleaning up, confirming zero processes, and running *once* passed in
279 seconds.

### The mechanism, named plainly: impatience

It is worth being specific about *how* the orchestrator kept doing this, because
"be careful with shared state" is too vague to act on and did not stop it happening
four times.

The pattern was identical each time. The orchestrator dispatched an agent to do a
piece of work, the work included a five-minute verification run — and rather than
wait, the orchestrator ran **the same verification itself, in parallel**, to find out
sooner. Its own run swept the agent's database container mid-flight. The fourth
occurrence destroyed a run belonging to an agent that had, moments earlier, correctly
diagnosed exactly this hazard and declined to re-run in case the interfering process
was still live. It was: it was the orchestrator.

There is an irony worth keeping. An orchestrator exists to delegate, and this one
could not tolerate the latency of its own delegation. It re-did the work it had just
handed out, and in doing so destroyed the result. The agents were more patient than
the thing coordinating them.

The general form is not really about containers:

> **An orchestrator that duplicates a dispatched agent's work while waiting for it
> is not saving time. It is racing itself for a shared resource — and it holds the
> one view of the system in which that race is invisible.**

The fix is procedural, not technical: before touching any shared resource, establish
what else is currently using it — and treat *waiting for a dispatched agent* as the
default, not as dead time to fill.

---

## What this says about the setup

**Delegation is not the mechanism. Independent verification is.** Every catch
above came from an agent applying its own judgement against a brief it had reason
to doubt — not from parallelism, and not from volume.

**The orchestrator is the least-checked component.** Five of the six incidents
were the orchestrator being wrong: a false premise, a value wrong by 24×, a
misclassified task, and a self-inflicted diagnosis it confirmed three times over.
The agents caught four of them. Nothing caught the fifth except running the
experiment properly.

**"I don't know" has to be a permitted outcome, or it becomes a fabricated
one.** The agent in §1 could have manufactured a passing mutation. The agent in
§2 could have copied the numbers it was handed. The agent in §5 could have
claimed a clean run. Each declined, and each said plainly what it could not
verify. That only survives if `PARTIAL` and "this criterion cannot be met as
written" are treated as *results* rather than as failures to be retried away.

**Concurrency has a cost that looks like a bug.** Parallel agents in one
workspace produced: a shared-container collision misread as a harness defect,
one agent's in-flight edit failing another's test run, and an orchestrator
instruction (`git checkout -- src/`) that destroyed a peer's uncommitted work.
Fan out for independent judgement; serialise anything touching shared state.

---

## The one that nearly cost real work

The orchestrator wrote an acceptance criterion instructing an agent to revert a
mutation with `git checkout -- src/`. The production fix under test was
**uncommitted**. The command destroyed it.

The agent had captured the method before mutating, reconstructed it, verified it
against that capture — and then labelled its own recovery honestly:

> *"This is strong evidence, not proof."*

That sentence is why it was recoverable. It sent the orchestrator to verify by
**behaviour** rather than by bytes: the full integration suite, including the
eight tests written specifically to catch a broken version of that exact control
flow. All passed. The work was then committed immediately.

Mutate-and-revert is only safe against committed code. The lesson generalises:
**an instruction that touches shared state is the orchestrator's responsibility
to make safe, not the agent's to survive.**
