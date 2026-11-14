# Case study: a stronger builder, or a better charter?

**Dates:** 2026-11-09 to 2026-11-11
**Question:** should the crew get a fourth builder tier on Claude Fable 5.2, the
strongest model on offer, above the Opus builder?
**Answer:** no. Three measurements and one small replay eval showed that the
failures a stronger model was supposed to fix were not model failures. The
money went into the charter instead: new builder and orchestrator instructions,
pinned by tests (nescio-ai PR 241).

The product codebases the replays ran on are private and are not named here.
Case details are generalised; the numbers are not.

---

## 1. The premise, and why it needed measuring

The crew already routes implementation by reasoning load: `archimedes-simple`
(Haiku), `archimedes-standard` (Sonnet), `archimedes` (Opus). The orchestrator
escalates one tier at a time when a builder returns `BLOCKED` because the task
proved harder than its tier. A fourth tier would sit above Opus.

That design makes a testable claim: there exist tasks the Opus builder cannot
do. If that were true, it would show up in the transcripts as Opus `BLOCKED`
returns that name difficulty.

Fable 5.2 at the time of the study: $8 / $40 per million input / output tokens,
twice Opus 5.5 ($4 / $20), cache reads at the same $0.20. It thinks before almost
every reply at high effort, and it follows "never" and stop rules closely, which
for a rule-dense charter predicts *more* stops, not fewer.

## 2. Measurement 1: how often does Opus block on difficulty?

Every builder-tier subagent transcript under `~/.claude/projects/` from 2026-08
to 2026-11-10, classified by the `<verdict>` tag in its last message.

| Tier | COMPLETE | PARTIAL | BLOCKED | no tag |
|---|---:|---:|---:|---:|
| builder (Opus) | 605 | 27 | 9 | 195 |
| builder-standard (Sonnet) | 169 | 2 | 0 | 815 |
| builder-simple (Haiku) | 200 | 4 | 1 | 312 |

All 9 Opus `BLOCKED` returns were read by hand:

| Cause | Count |
|---|---:|
| The brief's premise was wrong or stale (diagnosis disproved it) | 3 |
| A scope or design decision was needed (ADR, forbidden file, import-cycle stop) | 4 |
| Environment (a shared test database locked by another worktree) | 1 |
| Permission refusal plus a contradictory brief | 1 |
| **Too hard for the model** | **0** |

The 27 `PARTIAL` returns read the same way: every one stopped on a decision, a
scope boundary, a false premise, an off-limits file or the environment.

> The escalation slot above `builder` would have fired 0 times in ~850 runs.

The untagged runs are mostly older-format reports written before the verdict
tag was mandatory; they are excluded, not counted as complete.

## 3. Measurement 2: the completes that were wrong

A tier that never blocks can still ship bugs. So the second measurement looked
at `COMPLETE` runs that the QA agent (`pyrrho`) later caught.

- Source: 158 sessions that contain both builder runs and QA audits. 300 audits,
  213 with a parseable severity-ranked report.
- Findings: 17 Critical, 217 Major, 803 Minor, 845 Info.
- All 17 Criticals read by hand: about 10 introduced by the change under audit,
  6 audits of pre-existing code, 1 parse artefact ("Critical — none").
- A random sample of 30 Majors (seed 7): about 17 introduced bugs in changed
  code, about 8 test or doc quality, about 5 pre-existing.

**Rate:** about 130 serious introduced findings over ~1,700 builder runs in
audited sessions — roughly 1 per 13 runs. All were caught before merge, so
today's cost of this class is a fix loop, not a shipped bug.

**Shape:** mostly cross-module integration misses, not local logic errors. A
second writer or load path the change did not cover, a sibling guard the change
disarmed, a cross-repo consumer, an invariant that holds in one module but not in
its caller. Some trace to the plan scoping the task too narrowly rather than to
the builder.

## 4. The break-even, before spending anything

Per Opus builder run, re-priced at Opus 5.5 list prices (834 runs; see
[cost-effectiveness](cost-effectiveness.md) for the method):

| | Median | Mean | p90 |
|---|---:|---:|---:|
| Opus 5.5 | $2.92 | $4.61 | $9.81 |
| Same tokens on Fable 5.2 | $4.57 | $6.85 | — |

Fable thinks more, so the same task costs more tokens, not just pricier ones.
Even before that multiplier, Fable adds about $2.24 per run on the mean. A caught
bug costs one fix loop, about one more builder run plus a re-audit. At one
serious bug per 13 runs, **a Fable builder that removed every bug would save
well under a dollar per run** against a premium of more than two.

On money alone, Fable on every builder run cannot pay. It could only pay on a
narrow task class whose bug rate is far higher and which Fable largely fixes.
That is a question only a replay can answer.

> **A correction worth its own article.** The first version of this table said
> $3.65 mean. It undercounted output, because Claude Code writes the same
> assistant message to the transcript several times while streaming and only the
> last copy carries the final `output_tokens`. Counting the first copy per
> message id understated cost by about a fifth on builder runs. See
> [token consumption](token-consumption.md#7-the-transcript-counting-trap).

## 5. The replay eval

**Design.** Take a builder run whose bug QA later caught. Recreate the repo at
the commit the builder started from, hand a fresh builder the *original brief*
verbatim, and run a hidden oracle test written from the QA finding. The oracle
fails on the buggy commit and passes on the fix commit; both were proved before
any replay. A run passes only if the oracle passes **and** the repo's own suite
gains no new failures, so a run cannot dodge the bug by not doing the task.

Arms:
- **A** — the existing charter, at the case's original tier.
- **B** — the same charter on Fable 5.2 (planned, never run).
- **C** — A plus one step: *before the first edit, list every caller and every
  writer of what you change, and cover or explicitly scope out each one.*

Harness: a throwaway git worktree per run, headless `claude -p` with the charter
passed via `--agents`, permission mode `dontAsk`, push and `gh` denied, no
session persistence. Each case replays at the tier and effort its original
builder used.

**Curation cost.** Five candidates were curated, three kept. The two rejected
had bugs caused jointly by several builder runs in one wave — no single brief to
replay. Single-cause cases are rarer than the audit counts suggest, which is a
finding about wave-based work in itself.

**The three cases** (generalised):

| Case | Tier | Miss type |
|---|---|---|
| g1 | Sonnet | A shared predicate the change edited also fed a fail-closed guard elsewhere |
| g3 | Opus | The change started relying on a status flag that one code path never set |
| g5 | Sonnet | A newly reached function crashed on input encodings its old callers never sent |

In g1 and g3 the brief itself prescribed the faulty change. These cases test
whether the builder notices the reader or writer the plan missed.

### Pilot: arm A vs arm C, one run each

| Case | Arm A | Arm C | Cost A / C | Time A / C |
|---|---|---|---|---|
| g1 | bug reproduced | **avoided** — moved the clause into a release-only wrapper, citing the guard | $1.09 / $0.96 | 948 s / 731 s |
| g3 | bug reproduced | bug reproduced | $5.04 / $5.28 | 817 s / 1134 s |
| g5 | bug reproduced | bug reproduced | $0.30 / $0.35 | 164 s / 203 s |

Arm A: 0 of 3. Arm C: 1 of 3, at −11% to +15% cost per run.

What arm C's map got wrong was instructive:
- **g3:** it listed every call site of the function it changed, but not who
  *sets* the flag the new code reads. Callers are greppable; writers of a
  relied-on state are not, unless you go looking for them.
- **g5:** it listed the newly reached call as "covered". It never asked what
  range of input the new source could produce.

### The finding that mattered more than the bug

In both g3 runs the repository already had a test that pinned exactly this bug.
Both builders turned it red, labelled it "expected red — the pin the brief asked
to change", left it red and reported `COMPLETE`.

The charter said `COMPLETE` requires passing verification. The builder found a
reading under which a red test was fine, because the brief seemed to bless it.
**That is a charter-adherence gap, and no model choice fixes it.** The alarm for
the real bug was already ringing; the agent switched it off.

Arm B was never run. The pilot narrowed the only remaining place a stronger
model could plausibly help to the g3 and g5 miss types, and the break-even said
even a perfect result there would not pay at crew scale.

## 6. What changed instead: the charter fixes

Planned with `plato`, checked by `validator` (OKAY) and red-teamed by
`socrates` (material objections, folded in). The main socrates objection:
asking the builder to *justify* an inverted test is not enough, because a
builder obeying a faulty brief writes a plausible justification, the suite goes
green, and the alarm is gone.

Shipped in nescio-ai PR 241, identical text in all three builder tiers:

1. **Map what your change touches, before the first edit.** (a) Readers and
   callers. (b) Writers of state your change starts to rely on, citing the line
   that writes it on each path. (c) The input range of any function your change
   now feeds from a new source. Each entry is marked covered / unaffected (why) /
   outside scope, reported in a new `<blast-radius>` block.
2. **A test you turned red is yours.** Re-check each red test at the base commit
   in a detached temporary worktree, prepared the way CI prepares it. It is
   pre-existing only if it fails there *the same way*. Never `git stash` — the
   stash stack is shared across worktrees and sessions.
3. **The pin rule.** Inverting an existing assertion requires a reachability
   check: can production reach the state the test's setup builds, and by which
   path? Every inverted test is listed as `Inverted pin:`.
4. **Deferred reds.** If the brief says to leave tests red for a later test
   task, the verdict is `PARTIAL`, with each test listed as `Deferred red:`.
5. **The orchestrator verifies.** It records the wave's base commit, re-runs the
   tests, blames each newly red test on the first builder commit where it turns
   red, and blocks the wave on any red it cannot attribute. Every `Inverted pin:`
   and `Deferred red:` goes to the user as a one-line confirmation *before* any
   verdict is routed: "Test X now accepts state S, which production reaches via
   P — intended?"

### Smoke check of the new charter

| Case | Result | Cost | Notes |
|---|---|---:|---|
| g1 | bug avoided, `COMPLETE` | $1.67 | +60% over the pilot; 67 turns |
| g5 | bug reproduced | $0.34 | the input-range step still did not think of encoding |
| c0 (control) | `COMPLETE`, correct | $0.03 | a mechanical Haiku task from this repo's own history; no false `BLOCKED`, no bloat |
| g3, first run | `COMPLETE` with 4 newly red tests | $4.51 | the brief said "leave tests red"; the brief won |
| g3, after revision | **`PARTIAL`**, every red listed | $4.95 | the rule held; the bug still reproduced |

The g3 revision made the builder cite the line that writes the relied-on
state. It cited a real line — and still drew the wrong conclusion from it.
**The new rules make the alarm reliable; they do not prevent the bug.** The
orchestrator check would have caught both g3 runs.

Total replay spend: about $13 for the pilot and about $13.80 for the smoke
check, at API list prices (subscription quota in practice).

### The audit of the fix

`pyrrho` audited the charter text itself and found three Major defects, all in
instructions a model would have followed faithfully:

1. **A command that silently did the wrong thing.** `git worktree add <base-sha>`
   treats the SHA as a *path* and checks out the current HEAD. Every new red test
   would have looked "red at base" — defeating the main rule while appearing to
   obey it. Now pinned by a test that rejects the broken form.
2. **A base without dependencies.** A fresh worktree fails tests for setup
   reasons, which also reads as "red at base".
3. **Confirmation on the wrong route.** The orchestrator confirmed pins only on
   `COMPLETE`. The revision had made those cases `PARTIAL`, which routes to a
   follow-up builder, so the confirmation would never have fired.

Each fix is pinned by a test proved to fail against the charter text from
before its rule existed (18 failures against the previous revision, 27 against
the one before).

## 7. Incidents along the way

- **A read-only auditor deleted a run's working directory** with `rm -rf`. The
  run was invalidated and repeated; a separate PR (nescio-ai PR 240) added
  a hard shell boundary to every read-only agent that holds a shell. Written
  rule only — no hook enforces it yet.
- **A Haiku builder wrote charter prose** in a revision the plan had assigned to
  Sonnet precisely so that Haiku would not. The audit's prose findings clustered
  in that commit.
- **The eval harness itself forbade `git worktree`**, so no replay could
  exercise the base-check recipe. That rule is covered by tests only.

## 8. What to take from it

- **Measure the premise before buying the model.** "We need a stronger model"
  predicted difficulty blocks. There were none.
- **Most "model failures" here were instruction failures.** The decisive bug in
  g3 was an agent turning off an alarm the repository had already built, under a
  reading of its charter the charter allowed.
- **A cheap charter step catches greppable misses** (g1) and nothing else.
  Missing writers and widened inputs need either a stronger reasoner or a
  different check — the one open question this study leaves.
- **Instructions are code.** A wrong command in a charter fails silently, at
  scale, in every run that obeys it. Audit charter text the way you audit code,
  and pin it with tests that are proved to bite.
- **Verify the verifier's arithmetic.** The cost figure that framed the decision
  was itself undercounted until the counting method was checked.

## Sources

Local Claude Code transcripts (`~/.claude/projects/**`), the replay harness and
results (kept outside the repository: they contain private code), and
nescio-ai PR 240 and nescio-ai PR 241.
