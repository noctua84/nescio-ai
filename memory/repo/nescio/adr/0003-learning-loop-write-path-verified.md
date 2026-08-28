---
name: nescio-adr-0003-learning-loop-write-path
description: The harvest declares its subject before reading and stamps only those trails, each at its own max_ts; corrects ADR 0002's "corpus is empty" evidence, which measured the template repo instead of the installed brain.
type: adr
status: proposed
---

# ADR 0003: Measure the live brain; scope the harvest stamp to a declared read

## Status

Proposed. **Corrects the `## Context` and the `## Consequences` risk entry of
ADR 0002, and answers its closing "to re-verify" question.** It does not
supersede ADR 0002 — that ADR's decision survives intact, on different
arithmetic. See *Reconciliation* below.

## Context

ADR 0002 deferred semantic retrieval on the grounds that "the corpus is empty"
and that "the loop has never completed a promotion." Both statements are false.
The decision they support is nonetheless still correct. Recording that split —
right conclusion, wrong evidence — is the point of this ADR, because the reason
the evidence was wrong is a trap any future session will walk into again.

### The measurement error: the template is not the brain

`~/.claude/memory` is a symlink to `PycharmProjects/ai-os/memory` — **not** to
`nescio-ai/memory`. `nescio-ai` is the **template / upstream**; `ai-os` is the
**live installed brain**. `memory/learning-log.md` is a per-instance runtime
artifact, so its absence from `nescio-ai` is correct by design: the template
ships only `.gitkeep`s and `EXAMPLE` files (`memory/repo/EXAMPLE/`), and a
ledger of promotions performed on somebody's machine has no business being
committed to it.

ADR 0002 measured the template and drew a conclusion about the instance. Its
central factual claim — that `memory/learning-log.md` "does not exist, and never
has on any branch" — is true of `nescio-ai` and irrelevant; the file it was
reasoning about is `ai-os/memory/learning-log.md`, which exists and is long.

**This is the durable, reusable lesson and the headline of this ADR: when
measuring the learning loop, measure the live brain, not the template.** Resolve
`~/.claude/memory` before counting anything. Every empirical claim about corpus
size, promotion history, or watermark state that is gathered from a `nescio-ai`
checkout is a claim about a shipping skeleton.

### What the 2026-08-20 stamp actually was

ADR 0002 closed by asking whether the 2026-08-20 stamp "came from a real harvest
that found nothing promotable, or from a partial/test run." **Neither. It was a
real, successful harvest that promoted 3 notes.** Checkable at:

- trail `…holo-mind…trusting-ardinghelli…jsonl`, session `b0da0e7b`:
  `11:30:42` session accounting → `11:34:07` "Manifest staged … for your
  confirmation" → `22:48:14` "The harvest is complete… Promoted 3 durable notes
  to `memory/repo/holo-mind/`";
- `ai-os/memory/learning-log.md` lines 227–229, dated 2026-08-20, naming exactly
  those three notes with their content hashes;
- the note files themselves exist, committed 2026-08-21 as `3593404`;
- `scripts/mark_harvested.py` was byte-identical to its 2026-07-15 scaffold
  commit that day, so it was not under development and the stamp was not a
  side effect of testing it.

So the loop had completed a promotion — 212 of them, in fact — and the sentence
in ADR 0002 that "a harvest pass stamped every trail as reviewed and promoted
nothing" inverts what happened: a harvest promoted, and *then* over-stamped.

### The corpus is not empty

| ADR 0002 states | Actual (`ai-os/memory`) |
|---|---|
| "7 files, ~150 lines, ~6KB" | **296 notes, 1.21 MB** |
| "the loop has never completed a promotion" | **212 promotions** in the ledger |

ADR 0002's own reopen triggers are ~500 notes corpus-wide and ~100 notes in any
single directory. Reality is **296** and **35** (largest: `memory/repo/soulsgate-ui`).

Stated precisely: **the decision survives, the evidence does not, and the
posture is materially closer to reopening than the document believes.** The
vector DB is still correctly deferred — but on trigger arithmetic, at roughly
59% of the corpus-wide threshold, not because there is nothing to embed. A
future session must not read ADR 0002's "nothing to embed" line as current.

What survives untouched is ADR 0002's strongest argument, which never depended
on corpus size: `CONVENTIONS.md`'s deterministic contradiction resolution
(`user override > empirical > agent inference`, ties to the newer date) and the
`concepts/` corroboration/fork mechanism are guarantees ranked retrieval
structurally cannot provide. That argument is as good at 296 notes as at 7.

### There was a real bug — a different one — and it is now closed

ADR 0002's Risk section named the right area and the wrong mechanism. It framed
the hazard as "no invariant tying the stamp to a successful promotion." The
actual defect was a **scope mismatch inside the command**: step 1 of
`commands/harvest-memory.md` read sources *"for the current project"* while
step 8 / `scripts/mark_harvested.py` stamped **globally**.

Consequence on this machine: the 2026-08-20 harvest of **one** repo wrote **105
watermarks**, marking **2,438 records it never read** as reviewed across **96
unrelated trails**. The promotion was real; the blast radius was not.

**This also corrects ADR 0002's stated harm.** The pruner was never the imminent
threat: `hooks/record_stop.py::_maybe_prune` (`hooks/record_stop.py:334`)
returns early unless a trail exceeds `PRUNE_SIZE_THRESHOLD = 1_000_000` bytes
(`hooks/record_stop.py:46`), and the largest trail on this machine is 212 KB —
so nothing was aging out, and "harvested-but-undistilled records age out at 14
days" did not happen.

The real, present harm was silence. `hooks/harvest_nudge.py` counts records
*newer than* the watermark (`count_unharvested`, `hooks/harvest_nudge.py:87`)
and fires at `NUDGE_THRESHOLD = 20`; a spurious watermark zeroes every count.
**33 repos' harvest reminders had been silently dead since 2026-08-20.** The
loop did not corrupt itself — it stopped asking to be fed, which is the failure
mode that leaves no trace.

### Reconciliation with existing ADRs

- **ADR 0001** (no agent frameworks; dependency-free install path) — untouched
  and unthreatened. Everything decided here is stdlib only: `json`, `pathlib`,
  `argparse`, `datetime`. This branch adds no dependency.
- **ADR 0002** (defer semantic retrieval) — **not superseded.** Its `## Decision`
  stands unmodified. This ADR corrects two of its Context subsections
  ("The corpus is empty", "The loop has never completed a promotion"), replaces
  the mechanism in its Risk consequence, and answers its "to re-verify" item.
  Per the skill's supersession rule the old reasoning stays as history, and
  because ADRs 0001 and 0002 live on another, unmerged branch
  (`claude/pydantic-langgraph-ai-agents-7c9eb9`, not on `main`), **neither file
  is edited here.** The correction is carried forward-only, by this document.
- No conflict-checklist box is checked: nothing accepted is contradicted, no
  concern is re-standardized, no taxonomy is changed, and nothing an existing
  ADR rejected is reintroduced.

## Decision

**The harvest declares its subject up front; the stamp obeys the declaration.**

1. **Declare before reading.** `scripts/begin_harvest.py` (new) runs at step 1
   and writes a `read.json` manifest naming every trail opened and each one's
   `max_ts`, clamped to the read-time (`scripts/begin_harvest.py:28`,
   `scan_trail`/`collect` at `:71`/`:151`). Nothing written after the read can
   be inside the read.
2. **Stamp only what was declared, never backward.** `scripts/mark_harvested.py`
   stamps exactly the manifest's trails, each at its own `max_ts`.
   `mark_all_harvested()` was **deleted, not deprecated** — its absence is
   asserted by a test (`tests/test_mark_harvested.py:197`), so it cannot creep
   back as a convenience.
3. **Scoping is an equality test on normalised repo roots.** `_trail_scope.py`
   attributes a trail by comparing normalised posix roots
   (`belongs_to_repo`, `scripts/_trail_scope.py:258`) rather than by prefix, so
   a worktree under a repo resolves to the repo and an unrelated repo never
   matches. On this machine that narrows 123 candidate trails to 9.
4. **Refusing to stamp is not failing.** An invalid or missing manifest writes
   no watermark, drops a per-repo `.harvest-pending-<repo_key>` marker, and
   returns **0** (`_refuse`, `scripts/mark_harvested.py:305`). The unstamped
   records stay protected from pruning and the next session start reminds the
   operator.
5. **The promotion receipt is advisory, not a gate.** `promote_learnings.py`
   drops a `receipt.json` beside the manifest; `mark_harvested.check_receipt`
   (`scripts/mark_harvested.py:242`) warns on a missing, unreadable,
   version-mismatched, or zero-promotion receipt and **stamps anyway**.
6. **A bad stamp is revertible.** `scripts/unmark_harvested.py` (new) deletes
   watermarks matching a given bad stamp, **dry-run by default**, requiring an
   explicit apply pair to delete — the same arming convention as every other
   destructive tool here.

### Why the receipt is not a gate

This is the sub-decision most likely to be re-litigated, so the reasoning is
recorded rather than left implicit.

- **A receipt proves ordering, not diligence.** It is produced and consumed
  inside a single flow, by the same agent, in the same run. It can attest that
  promote ran before mark — nothing more. It cannot attest that the trails were
  actually read.
- **`promoted >= 1` is satisfied by exactly the pass it should catch.** A run
  that reads 500 records and promotes one trivially clears the bar.
- **And it punishes the honest case.** An honest re-run whose nominations all
  dedup against the ledger legitimately reports `promoted: 0` — and a gate would
  refuse to stamp precisely the pass that did the most careful work.

## Options considered

| Option | Verdict |
|---|---|
| **Declared-scope manifest + per-trail `max_ts`** (chosen) | The stamp can only cover what the harvest said it would read; scope is auditable on disk. |
| Status quo — global stamp | Rejected. It is the defect: 105 watermarks, 2,438 unread records, 33 repos' nudges dead. |
| Receipt as a hard gate (`promoted >= 1` or no stamp) | Rejected — self-destructs on an honest dedup-only re-run, and is trivially satisfied by a one-note pass. |
| Gate, plus an `--allow-empty` escape hatch | Rejected — a bypass decided by the same agent that tripped the gate is not a safeguard, it is a longer path to the same stamp. |
| Refuse with a hard `rc 1` | Rejected — by step 8 the notes, the ledger and the readiness updates are already on disk; exiting non-zero strands the operator mid-transaction with no marker and no instructions. Refusal returns 0 and leaves a `.harvest-pending-<repo_key>` breadcrumb instead. |
| Deprecate `mark_all_harvested()` with a warning | Rejected — deleted outright and pinned by a test; a deprecated global stamp is a global stamp. |

## Consequences

- The stamp's blast radius is now bounded by a file the operator can read before
  it is used. The scope narrowed from 123 trails to 9 on this machine.
- The nudge loop is audible again. `harvest_nudge.py` counts against a watermark
  that only advances over declared trails, so a repo that has not been harvested
  keeps asking.
- Refusal is safe and recoverable in both directions: an unstamped harvest
  leaves a marker and re-runs cleanly; an over-wide stamp is reversible with
  `unmark_harvested.py`.
- **Cost — the manifest is a declaration, not proof.** `begin_harvest` lists
  every trail *in scope*; `mark_harvested` stamps them whether or not the agent
  opened each one. The enforced invariant is **"only trails scoped to this
  repo"**, not "only trails actually read". The residual gap between those two
  is real and is accepted here, not solved. Closing it would require the reader
  to emit per-trail read evidence, which reintroduces the self-attestation
  problem the receipt already fails at.
- **Cost — one more file and one more failure mode in the flow.** The harvest
  now has a step that can be forgotten, a manifest that can be stale, and a
  staging directory to keep track of. The refusal path exists because that will
  happen.
- **Open risk — unresolved retention question.** A trail with **no** watermark
  is retained **indefinitely**: `record_stop._is_unharvested`
  (`hooks/record_stop.py:275`) treats `watermark is None` as "everything is
  un-harvested" and protects every parseable record from pruning. Trail records
  carry up to `PREVIEW_MAX = 500` characters of assistant output
  (`hooks/record_stop.py:39`), absolute paths, and branch names, and `redact()`
  (`hooks/record_stop.py:187`) matches only credential *shapes* — it does not
  catch names, email addresses, or customer identifiers. This bites twice:
  - the remediation itself deletes 96 watermarks, converting those trails to
    indefinite retention;
  - **orphaned trails** whose repo was renamed or deleted can never be declared
    under equality-based scoping, so they can never be stamped, so they are
    never pruned.

  Recorded as an accepted, **named** cost — not as a solved problem. The
  recommended follow-up is a `threat-model` / LINDDUN pass over
  `~/.claude/learning-trail`, which is out of scope for this ADR.
- **To re-verify:** the corpus counts above are a 2026-08-26 snapshot of one
  machine's `ai-os` brain, and the corpus is ~59% of ADR 0002's own reopen
  threshold. Re-count before assuming ADR 0002's deferral still has headroom —
  and re-count against `~/.claude/memory`, not against a `nescio-ai` checkout.

[Source: empirical — 2026-08-26]
