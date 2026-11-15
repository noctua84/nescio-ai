# Case study: checks that pass for the wrong reason

**Dates:** 2026-08-31 to 2026-10-02
**Sessions:** three, in the nescio-ai repository itself —
"Fix contradictory builder charter claims" (nescio-ai PR 117),
"Add per-agent scope-term match mode to boundary lint" (nescio-ai PR 113,
with its sibling nescio-ai PR 116), and
"Agent file modularization support" (nescio-ai PRs 141, 163 and 164).

The crew's charters are prompts, and the repository tests them like code:
phrase-pinning tests in `tests/test_agent_definitions.py` and lints in
`scripts/_crew_common.py` assert that each charter says what the crew depends on
it saying. These three sessions are about evaluating *those evaluators*. Every
one of them found a check that was green for the wrong reason.

---

## 1. "The only agent with write access" — in three charters at once

**The problem.** All three builder tiers said: "You are the only agent in this
crew with write access to production code." Three agents cannot each be the
only one, and in fact six could edit files. An earlier PR had fixed the README
but left the charters — so the contradiction sat inside the prompts the agents
actually read. Discovery found two more sites the brief had not named, including
a generated docs page mirroring the claim.

**The design, changed by review before any code was written.**
- A substring lint for "only agent" was rejected as brittle and inverted into a
  positive declaration: each builder must say how many agents hold write access,
  and a test checks the spelled number against the code-writer list.
- The first draft named the peer writers. `socrates` objected that a roster
  churns four files on every rename and goes red on a swap where green is
  correct: *the sentence's purpose is rarity, not census.* Final wording: "you
  are one of four agents that hold it."
- The same sentence was proposed for the QA agent, which may write only its
  report. `socrates`: "The builders need to be told they may write. qa-guard
  needs to be told it may barely write. Same sentence, opposite job." Dropped.
- `validator` confirmed all seven line references and found a task whose
  arithmetic would have failed on the first run.

**Checks that had never bitten:**
- An existing test, `test_orchestrator_names_builder_as_the_code_writer`, passed
  on both the stale and the fixed text. "It never had teeth."
- An emptied writer list would have made the new lint pass vacuously; an
  exact-equality pin closed it.
- `pyrrho` reproduced a bypass: "Write access to production code: none — the
  four other agents hold it, not you." passed the lint. Closed with an
  affirmation check and a regression test.
- The docs catalog was already stale on main, and its test failed — but CI's
  test discovery never reached that directory, so nobody had seen it.

**Numbers.** Claim sites 6 → 0. Suite 627 → 632 tests. Catalog 11 → 17 agents.
Review: `validator` OKAY WITH FIXES, `socrates` material objections,
`pyrrho` 0 Critical / 0 Major / 3 Minor.

**The incident.** One task was told to prove the lint bites by breaking a
charter, with the acceptance criterion "`git diff --name-only -- agents/` must be
empty afterwards". Agents had also been told not to commit. The only way to meet
both was a destructive revert: the agent ran `git checkout -- agents/` and wiped
three other agents' uncommitted work in the shared worktree. Its self-restore
brought back three of four files byte-exact and one half-applied and
ungrammatical. The orchestrator caught it only because another agent's check
did not reproduce, and repaired the last file by hand.

> "I told every agent not to commit… and then wrote an acceptance criterion
> that could only be met by a destructive revert." — the orchestrator

> "Had I trusted the word 'restored', we would have shipped it."

**A routing note.** The plan labelled tasks simple or standard. Every
implementer was still dispatched to the Opus `archimedes`. Tier labels in a plan
do nothing unless dispatch reads them.

## 2. A lint with a polarity hole

**The problem.** Boundary sentences ("Hard file boundary: …") were checked with
"any of these scope terms appears". That is right for inclusion-shaped
boundaries ("docs", "documentation") and wrong for exclusion-shaped ones. Widen
the QA agent's terms from `("may never edit",)` to `("may never edit", "check")`
and the inverted sentence "you may edit the files that define the checks freely"
passes on "check" alone. An earlier PR had only pinned the tuple's value — in the
user's words, "a pin around the footgun, not removal of it."

**The fix.** Each boundary declares its shape: `inclusion(...)` matches any
term, `exclusion(...)` requires all of them. Under all-of, adding a term
*tightens* the check.

| Shape | Inverted sentence accepted? | Declared sentence accepted? |
|---|---|---|
| exclusion (all-of) | no | yes |
| inclusion (any-of) | **yes — the old hole** | yes |

The pin was replaced by three checks in order: the shape, the term membership,
and a rule that every exclusion entry carries a negation marker.

**The agent corrected the user's acceptance criterion.** The brief asked to show
that widening the terms *fails*. Under the new design it deliberately does not:
"widening deliberately does not fail — that is the fix." The orchestrator said
so instead of contorting the code to meet the criterion.

**The sibling session** found that the sentence-end regex truncated a boundary
at a bracketed code span, and the lint stayed green on the truncated sentence.
Two candidate detectors were rejected on evidence: a length rule false-positived
on the planner charter, and a markup-balance rule stayed green because the
terminator's own character class ate the closing bracket.

**Numbers.** Suite 628 → 629 (and 628 → 630 for the sibling). One Opus builder
each, no review agents. Main session plus builder: about 4.0M cache-read tokens
and 43K output tokens for the main fix.

## 3. A rule that never fired

**The problem.** The crew had no guidance at all on splitting oversized files. A
search of every charter, skill, `CLAUDE.md` and the README found none.

**What shipped (PR 141).** No new agent ("a decomposer agent would have to be
invoked by someone who already noticed the problem"). Instead: a 400-line
*tripwire* that prompts a cohesion test, two of whose three questions are
vetoes against cargo-cult splitting — "line count prompts the question; cohesion
answers it." A scanner, `scripts/module_scan.py`, found 45 of 241 tracked files
over the tripwire. 16 commits, +2,598 lines, 15 files.

**The review that mattered.** Five task-level reviews passed. Then a
whole-branch review on Opus found one Critical: the doctrine "installs the
obligation to *act* but never the obligation to *notice*." The scanner appeared
in zero charters and the number 400 in none, so the prevention arm was a no-op.

**Vacuous checks inside the session's own verification:**
- The plan's check used `grep -E '\b(a|b|c)\b'`, which never matches in that
  grep build. A Haiku implementer reported "clean" on that basis. The
  orchestrator caught it only because `sed` output disagreed.
- The scanner printed "no files over" for `--top 0` while 45 were over.
- The orchestrator's own checkers were wrong four more times: a naive fence
  split, an index overrun ("wrong, twice, in the same way"), reading stdout when
  the test runner writes to stderr, and `$?` capturing `tail`'s exit code.
- It ran the suite without `PYTHONPATH=scripts` "all session", which hid 36
  tests, and briefly reported main as red.

> "Three verification defects were in my own plan… All three passed *as
> written*."

**The rule never fired in practice.** After merge, `agents/orchestrator.md` grew
from 669 to 876 lines, about +207 lines from two commits — and nothing stopped
it. The rule lived in the builder and planner charters, and the agents that
edit the crew are not those. The fix was a CI gate (PR 164) that "blocks on the
silence, not the size": a PR that grows an over-tripwire file must carry a
one-line `Module-check:` acknowledgement in its body. Splitting the orchestrator
was analysed and declined: "a charter isn't a module, it's an agent's working
memory."

**Model routing, done explicitly.** This session dispatched 25 generic
subagents with per-task model overrides: 6 Haiku for transcription-grade tasks
("complete code in the brief → transcription plus testing, so cheapest tier"),
15 Sonnet for task reviews and two tasks, 4 Opus for the whole-branch review and
the orchestrator analyses. The Opus review caught what five Sonnet reviews
missed. A Haiku fixer dropped a required commit-message bracket; the orchestrator
amended it.

**Also refused:** merging a hello-world CI stub that would have turned a red,
non-required check green — "turns the check green by making it assert nothing."

## Patterns across the three

| Check | Why it was green | How it was found |
|---|---|---|
| Orchestrator names-the-writer test | Matched both stale and fixed text | An implementer tested it against the stale text |
| Write-access lint | Accepted a sentence revoking access | `pyrrho` wrote the counterexample |
| Writer-list lint | An empty list passes vacuously | An implementer noticed the domain could empty |
| Docs catalog test | Outside CI's discovery path | `validator` ran it directly |
| Boundary lint | Any-of on an exclusion | User brief, then a polarity table |
| Boundary sentence end | Truncation still contained a term | Sibling session's counterexample |
| Plan grep | Pattern never matches in that grep | Disagreement with `sed` |
| Module tripwire | Lived in charters that never edit the crew | Post-merge growth of the orchestrator |

- **"Prove it bites" was the acceptance criterion in all three sessions.** A lint
  nobody has seen fail is not evidence of anything.
- **Write the proof so it cannot destroy work.** In a shared worktree, "break it,
  then make the diff empty" plus "do not commit" has exactly one solution, and
  it is a destructive revert.
- **Adversarial plan review paid before code existed.** `socrates` and
  `validator` changed the design of the first session twice and caught a task
  that would have failed on its first run.
- **The orchestrator's own checks fail as often as the agents' work.** Every
  session found the controller's verification wrong at least once.
- **A rule only works where the editing agent reads it.** Placement is part of
  the rule.

## Token footprint

Summed over unique assistant messages per transcript (input / cache write /
cache read / output):

| Session | Main session | Subagents |
|---|---|---|
| Builder charter claims | Opus 5: 0.76M / 13.0M / 113K | 7 Opus builders: 0.34M / 7.1M / 68K; `pyrrho` 2.9M read; `validator` 1.4M; `socrates` 0.26M; `explore` (Haiku) 0.42M |
| Boundary lint | Opus 5: 0.13M / 1.6M / 19K | 1 Opus builder: 0.06M / 2.5M / 24K |
| Modularization | Opus 5: 1.5M / 55.3M / 212K | 4 Opus: 9.8M read; 15 Sonnet: 63.5M read; 6 Haiku: 4.9M read |

These sums take the first copy of each message's usage, which undercounts output
(see [token consumption](token-consumption.md#7-the-transcript-counting-trap)).
Cache figures are unaffected.
