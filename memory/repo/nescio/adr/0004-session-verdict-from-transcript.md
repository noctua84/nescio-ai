---
name: nescio-adr-0004-session-verdict-from-transcript
description: A session's clean/flagged/unknown verdict is a tool-error rate over its own transcript, above a named threshold and behind a minimum-call floor; unknown is a first-class state that no missing evidence may collapse into clean.
type: adr
status: proposed
---

# ADR 0004: Derive the session verdict from the transcript — and keep `unknown` a state

## Status

Proposed. Closes the gap ADR 0002 and ADR 0003 both left open on the *read* side
of the learning loop, and retires the `INSUFFICIENT_OUTCOME` block that
`compute_readiness.py` has been emitting since #42
(`scripts/compute_readiness.py:146`). Supersedes nothing. **Corrects one
measurement in issue #70's own framing and one in the calibration that was
handed to this decision** — see *The unit was measured wrong* below.

**Calibration is stale as of 2026-10-02 — re-measure before implementing.** This
ADR was written on 2026-09-04 and committed a month later without revision. The
transcript corpus has moved materially since: distinct sessions 312 -> 564 (+81%),
subagent transcript files 57% -> 90% of all files, and — most importantly for
Decision 5's parent-only scope — the share of sessions that have a parent
transcript at all fell from 100% to about 78%. The constants
(`FLAG_ERROR_RATE`, `MIN_TOOL_CALLS`) and the scope decision therefore need
re-deriving against the current corpus before any of this is built. The method
holds; the numbers do not.

## Context

`readiness.md`'s headline section promises "a rolling view of recent harvested
sessions — how many ended clean vs. flagged." Since #42 it has instead rendered
an explicit insufficient-data block, because no verdict existed anywhere: trail
records carry no outcome field, `message_preview` is blanked wholesale to
`[redacted]` on any secret match (`hooks/record_stop.py:39`), and
`memory/learning-log.md` records only what was promoted, never what went wrong.

#66 changed the arithmetic by recording `transcript_path` on every trail record
(`hooks/record_stop.py:225`). The transcript is a real artifact containing real
tool outcomes, so a verdict can be *derived* rather than inferred from prose.

This ADR is gating: #32, the earned per-repo autonomy dial, reads this signal.
That is what makes the failure mode below non-negotiable rather than a
preference.

### The failure mode that constrains everything else

> **Defaulting a missing verdict to clean would silently raise a repo's autonomy
> cap.**

A false `flagged` costs latitude and is visible — the operator sees a repo held
back and goes looking. A false `clean` grants latitude on no evidence and looks
identical to a genuinely good record. It is ADR 0003's silent-watermark failure
in a new place: *the loop does not corrupt itself, it stops telling the truth
and leaves no trace.* Every derivation choice below is subordinate to keeping
`unknown` distinct from `clean`.

### What the corpus actually is

Measured 2026-09-04 against `~/.claude/projects/`, not against a fixture:

| | |
|---|---|
| transcript files | **3,119** |
| bytes | **1,569 MB** (median file 309 KB, largest 26.8 MB) |
| **distinct sessions** | **312** |
| files that are subagent transcripts (`agent-*.jsonl`) | **2,807** (890 MB, **57% of the corpus**) |
| full structural parse of all 3,119 files | **11.4 s** |

Issue #70's "~1,800 files / 21.7 MB" is stale by roughly two orders of
magnitude on bytes. It does not change the conclusion, because the conclusion
runs the other way: **parsing is cheap.**

**Design question 3 in the issue — caching, early-stop, parse-only-un-harvested
— is therefore largely moot, and no cache is designed here.** Eleven seconds for
the entire corpus is unremarkable at harvest time and remains unthinkable
per-turn, which is exactly the split #66 already made when it stored the pointer
instead of the verdict. A derived-verdict cache keyed on `session_id` would add
an invalidation problem, a staleness failure mode, and a second place for a
stale `clean` to survive a code change — buying back seconds that nobody is
spending. Restricting the scan to un-harvested sessions remains a legitimate
cheap win and is specified as an optimisation, not as a requirement.

### Transcript structure, verified

- Records carry `timestamp` on ~84% of lines (10,768 / 12,804 in the largest
  file). Not needed by this decision, but true.
- A tool call is a `{"type": "tool_use", "id", "name", "input"}` block inside
  `message.content`.
- A tool outcome is a sibling block
  `{"type": "tool_result", "tool_use_id", "content", "is_error"}`. `tool_use_id`
  links it back to the call.
- **`is_error` is present-and-`false` far more often than it is absent or true.**
  Across the 40 largest transcripts: 10,276 blocks with `is_error: false`, 4,649
  with the key absent, **368 with `is_error: true`**. The predicate must be
  `block.get("is_error") is True`. Truthiness testing, or treating absence as
  failure, inflates the error count by an order of magnitude.
- **Do not build on `hook_non_blocking_error` attachment records.** Those are the
  operator's *own* hooks failing — a different, far noisier signal.

### The unit was measured wrong — one file is a session, but a session is many files

The issue's design question 2 asks whether to count sessions or turns. Both
answers in circulation were built on a wrong premise, so it is recorded here
rather than settled quietly.

**One transcript file does carry exactly one `sessionId`** — verified across a
41-file sample including the largest file: zero files with more than one. So the
issue's worry that "one transcript can span several sessions" is unfounded.

**But the converse is false, and it is where the real hazard lives.** Of 3,119
files only 312 are top-level session transcripts; the other 2,807 are subagent
transcripts, and **every one of them carries its parent's `sessionId`** (0 of
2,807 orphaned). One session's files: median 4, **max 241**.

The consequence for calibration is direct. A distribution computed *per file* —
n≈1,560 at a 30-call floor — is not a distribution over sessions. There are only
312 sessions on this machine. **The `n=1560` figure this decision was handed is
a per-file measurement wearing a session label**, and the threshold derived from
it does not transfer:

| unit (floor: 30 tool calls) | n | p50 | p95 | p99 | max | flagged at 10% |
|---|---|---|---|---|---|---|
| per **file** (the stale calibration) | 1,561 | 0.029 | 0.103 | 0.161 | 0.226 | 81 (**5.2%**) |
| per **session**, parent transcript only | 249 | 0.028 | 0.073 | 0.118 | 0.143 | 4 (**1.6%**) |
| per **session**, parent + all subagents | 268 | 0.031 | 0.071 | 0.095 | 0.100 | 0 (**0.0%**) |

A 10% threshold flags 5% of *files* and between 1.6% and **zero** sessions. It
was not a bad choice; it was a choice made at the wrong altitude. Aggregation
pulls rates toward the mean, and the more work a session aggregates the harder
it becomes to exceed any fixed rate — the parent+subagents column has a maximum
of 0.100 across 268 sessions, so a 10% rule is not merely strict there, it is
unreachable.

### Scope: whose tool calls count

**72% of all tool calls and 75% of all tool errors occur inside subagent
transcripts** (133,133 calls total; 37,239 in parent transcripts). A subagent's
internal failures do **not** surface in the parent: the delegation tool is
`Agent` (1,495 calls in the sample), and it reported `is_error: true` only 4
times — it errors when the invocation fails, not when the agent's own `Bash`
call does.

So the choice is real, and both halves have a cost:

- **Parent transcript only** sees 28% of the tool calls, and a session that
  delegates everything looks clean because it *was* clean at its own altitude.
- **Parent + subagents** sees everything, but requires discovering sibling
  `agent-*.jsonl` files by filename convention in the same directory, and
  smooths the rate so far toward the mean that the metric loses its ability to
  discriminate at all.

### Why "any error" is unusable

70% of sessions contain at least one tool error. The top erroring tools are
`Bash` (225), `Edit` (29), `PowerShell` (27), `Read` (16). A failed `grep`, a
`Read` on a path that turned out not to exist, a test that legitimately fails —
that is normal work. "Any error" flags competence.

### Why "unrecovered error" was rejected — the metric moved under measurement

This is the strongest candidate the issue names, and the reason it is rejected
is empirical rather than aesthetic. Matching a retry by its actual *target* (the
command string, `file_path`, or `pattern`) rather than by tool name:

| outcome after an errored call | share |
|---|---|
| retried with the **same target** and succeeded | 27% |
| only a later success on the same **tool** | **58%** — ambiguous |
| no later success on that tool at all | 13% |

"Unrecovered" therefore lands anywhere between **13% and 73%** depending purely
on how retry-matching is implemented. A first, looser pass over the same corpus
reported 86% recovery and was wrong. **That instability is the argument, not an
anecdote about a bad afternoon:** a definition whose value swings by 60
percentage points under a refactor of its own matching heuristic cannot be
allowed to move an autonomy cap, because the cap would move with the refactor
and nothing would report that it had.

Related ADRs: **ADR 0001** — everything decided here is stdlib (`json`,
`pathlib`, `statistics` not required); no dependency is added, the install path
is untouched. **ADR 0003** — this consumes `session_id`, which
`_trail_scope`/`compute_readiness` already bucket per repo; the harvest stamp,
the manifest, and the watermark are not touched. No conflict-checklist box is
checked.

## Decision

**A session's verdict is one of `clean` / `flagged` / `unknown`, derived from
that session's own transcript by tool-error rate, and `unknown` is a state — not
a missing value, not a zero, and never a synonym for `clean`.**

1. **Three states, named constants, one arithmetic.**

   ```
   MIN_TOOL_CALLS   = 30     # below this the rate is noise
   FLAG_ERROR_RATE  = 0.07   # strictly-greater-than flags
   ```

   `calls` = `tool_use` blocks. `errors` = `tool_result` blocks with
   `is_error is True`. Then:

   - `calls < MIN_TOOL_CALLS` → **`unknown`** (`reason: below-floor`)
   - `errors / calls > FLAG_ERROR_RATE` → **`flagged`**
   - otherwise → **`clean`**

   The comparison is strictly-greater-than so a rate exactly at the threshold is
   clean; the constant is the first flagged value's exclusive lower bound.

2. **`FLAG_ERROR_RATE = 0.07`, calibrated on the session distribution, not the
   file distribution.** At a 30-call floor it sits immediately below p95
   (0.073) and flags **16 of 249 sessions (6.4%)**. The full trade-off, so the
   constant can be moved by reading a table rather than re-deriving it:

   | threshold | flagged (floor 30, n=249) | min errors needed to flag a 30-call session |
   |---|---|---|
   | 0.05 | 37 (14.9%) | 2 |
   | 0.06 | 26 (10.4%) | 2 |
   | **0.07** | **16 (6.4%)** | **3** |
   | 0.08 | 9 (3.6%) | 3 |
   | 0.10 | 4 (1.6%) | 4 |
   | 0.15 | 0 (0.0%) | 5 |

   It leans deliberately to the low side of p95. A threshold set too high
   produces false `clean` verdicts, which is the failure mode this whole ADR is
   organised around; a threshold set too low produces false `flagged` verdicts,
   which cost latitude visibly and get corrected. **When in doubt, flag.**

3. **`MIN_TOOL_CALLS = 30`, and its job is to make a single error unable to
   flag.** A 3-call session with 1 error is 33% and means nothing. The floor is
   chosen against the threshold, not independently: at 0.07 a 30-call session
   needs **3** errors to cross, and 1/30 = 0.033 is comfortably under the line.
   Below the floor the verdict is `unknown` — 63 of 312 sessions (20%) on this
   machine. That fifth of the corpus reporting "not enough evidence" is the
   floor working, not the floor failing.

4. **The counting unit is the session, keyed on `session_id`.** Trail records
   are per-turn and several turns share a `session_id`; `readiness.md` counts
   sessions; `compute_readiness.collect_activity` already accumulates
   `bucket["sessions"]` as a set of `session_id`
   (`scripts/compute_readiness.py:246`). The verdict layer therefore consumes
   that set and needs no new grouping concept. A turn-level verdict is rejected:
   the trail's own `sessions` count is what the file reports, and publishing a
   rate whose denominator differs from the denominator one line above it in the
   same generated block is how a consumer misreads the number.

5. **Scope is the session's own transcript. Subagent transcripts are excluded,
   and the exclusion is named, measured, and given a reopen trigger.** This is
   the closest call in the ADR and it is recorded as such:

   - `transcript_path` is a value the Stop-hook payload *hands us* — a contract.
     `agent-*.jsonl` in the sibling directory is an undocumented internal naming
     convention. Building a cap-moving metric on it means the metric changes
     when Claude Code renames a file, silently, in the safe-looking direction
     (fewer files found → fewer errors → more `clean`). That is precisely the
     "value moves with an implementation detail" objection that killed
     unrecovered-error counting in Decision-adjacent reasoning above; applying
     it there and not here would be inconsistent.
   - Including subagents also destroys discrimination: max session rate falls
     from 0.143 to 0.100, and *no* threshold at or above 0.10 flags a single
     session out of 268.
   - **Accepted cost, stated plainly: the verdict is blind to 72% of tool calls
     and 75% of tool errors.** A session that delegates all its work reads
     `clean` on 28% of the evidence. It is a false-clean risk — the exact class
     this ADR exists to prevent — and it is accepted here rather than solved,
     because the available fix trades a stable contract for an unstable one.
   - **Reopen trigger:** if the parent-transcript share of tool calls falls below
     ~20%, or if a flagged-session review finds sessions whose failures lived
     entirely in subagents, revisit — the escalation is to include `agent-*.jsonl`
     files matched by `sessionId` and *raise* the threshold to compensate for
     smoothing, not to keep 0.07.

6. **Every failure path returns `unknown`, and that is enforced structurally
   rather than intended.** The derivation lives in one new module,
   `scripts/_session_verdict.py`, and:

   - the literal `"clean"` is produced at **exactly one** return site, reachable
     only after both the floor and the threshold have been evaluated on a
     successfully parsed file. A test asserts that count is 1 — the same pinning
     technique ADR 0003 used to keep `mark_all_harvested()` from creeping back
     (`tests/test_mark_harvested.py:197`);
   - `unknown` carries a machine-readable `reason`: `below-floor`,
     `no-transcript`, `unreadable`, `unparseable`, `no-tool-calls`;
   - there is **no default argument, no `or "clean"`, and no bare `except` that
     falls through to a verdict.** `OSError`, `PermissionError`, a missing path,
     and a zero-call transcript each return `unknown` explicitly;
   - the reader streams the file handle line by line and never calls
     `read_text()` — a 26.8 MB transcript must not be materialised, and a
     `MemoryError` must not be the thing standing between a bad session and a
     `clean` verdict.

7. **Dangling `transcript_path` degrades to `unknown`, and the pointer is not
   the only way to find the transcript.** A path that no longer resolves is
   `unknown/no-transcript`. Currently 372 of 372 recorded pointers resolve
   (100%), so this is a latent rather than active problem — but it is a
   retention race with Claude Code, not something this repo controls.

8. **Backfill by `session_id`, and it is worth far more than it sounds.**
   Measured on the live trail: 3,534 records, of which only **372 (11%)** carry
   a `transcript_path` at all — everything before #66 has none. But **190 of the
   192 distinct trail `session_id`s (99%) have a transcript on disk at
   `~/.claude/projects/*/<session_id>.jsonl`.** Resolution order is therefore:

   1. `transcript_path` from the record, if it resolves;
   2. otherwise glob `<config>/projects/*/<session_id>.jsonl` — 312 candidate
      files, one `is_file()` check per session;
   3. otherwise `unknown/no-transcript`.

   Step 2 turns an 11% coverage into a 99% one. The alternative the issue
   offers — "accept that outcome history starts at #66" — would cold-start the
   dial on a tenth of the evidence that exists.

9. **What #32 reads: three counts that must sum, never a ratio.**
   `compute_readiness.py --json` gains, per repo:

   ```json
   "outcome": {
     "available": true,
     "clean": 12, "flagged": 2, "unknown": 5,
     "sessions": 19,
     "threshold": 0.07,
     "min_tool_calls": 30,
     "unknown_reasons": {"below-floor": 3, "no-transcript": 1, "unreadable": 1}
   }
   ```

   `clean + flagged + unknown == sessions` is an invariant asserted in code and
   in a test. **No `clean_rate` field is emitted**, because `clean / sessions`
   and `clean / (clean + flagged)` differ exactly when `unknown` is large, and a
   consumer that computes one of them has re-introduced the failure mode this
   ADR forbids — by arithmetic rather than by a bug. #32 must read the three
   counts and decide for itself how to treat `unknown`; it is handed the
   distinction, not a number that has already dissolved it.

10. **`## Recurring flags` is populated from tool names and counts only — never
    from error text.** A pattern is a `(tool_name)` pair appearing in **≥ 2
    distinct flagged sessions**, rendered as e.g. `Bash — 9 errors across 3
    sessions`. `tool_result.content` is unredacted model-visible output that can
    contain credentials, customer identifiers, and absolute paths;
    `record_stop.redact()` (`hooks/record_stop.py:187`) matches credential
    *shapes* only and is not applied to transcripts at all. `memory/` is a
    committed, published tree. **Error content never leaves the transcript.**

## Options considered

| Option | Verdict |
|---|---|
| **Tool-error rate > threshold, behind a call floor, three states** (chosen) | Deterministic, cheap, one constant to tune, and the only candidate whose value does not move under reimplementation. |
| Any tool error → flagged | Rejected — 70% of sessions have one; flags competent work. |
| Unrecovered errors (no later success) | Rejected — the metric ranges 13%–73% depending on how retries are matched. Unfit for an autonomy cap. |
| Permission denials / explicit stop-reason | Rejected as the *primary* signal — a denial is the guardrail working, not the session failing. Viable later as a second, separate axis. |
| Verdict per **turn** instead of per session | Rejected — `readiness.md` counts sessions; two denominators in one block invites misreading. |
| Include subagent (`agent-*.jsonl`) transcripts | Rejected, **narrowly and reluctantly** — see Decision 5. Costs a stable contract; destroys threshold headroom. Has a named reopen trigger. |
| `FLAG_ERROR_RATE = 0.10` (the handed-down number) | Rejected — calibrated per *file*; flags 1.6% of sessions, and 0% once subagents are included. Right method, wrong altitude. |
| Cache derived verdicts keyed on `session_id` | Rejected — 11.4 s for the entire corpus. Buys nothing and adds an invalidation path in which a stale `clean` can outlive the code that produced it. |
| Missing transcript → `clean` | Rejected on principle. It is the failure mode; it is why `unknown` exists. |
| Missing transcript → omit the session entirely | Rejected — silently shrinks the denominator, which *is* defaulting to clean with extra steps. |
| Keep emitting `INSUFFICIENT_OUTCOME` | Rejected — #42's honest placeholder has served its purpose; #32 stays blocked while it stands. |

## Consequences

- `readiness.md`'s headline section answers its own question for the first time.
  #32 is unblocked with a signal that distinguishes "went well", "went badly",
  and "we do not know" — and cannot be read as the first when it means the third.
- The whole subsystem is one constant away from recalibration. Moving
  `FLAG_ERROR_RATE` is a one-line change against a published table, and the
  table is in this document rather than in someone's terminal history.
- Derivation stays where #66 put it: harvest/compute time. The Stop hook's hot
  path is untouched, still a single O_APPEND write, still never opens a
  transcript.
- **Cost — the blind spot is large and named.** 72% of tool calls are invisible
  to this verdict (Decision 5). This is the single most likely reason a future
  session will reopen this ADR, and it should.
- **Cost — the thresholds are calibrated on one machine's 312 sessions, by one
  operator, in one working style.** They are not a population statistic. A repo
  whose work is 90% `Bash` in a flaky container will look worse than one that is
  90% `Read`; the verdict measures tool friction, and tool friction is not
  uniformly distributed across kinds of work.
- **Cost — a fifth of sessions report `unknown`.** With 63 of 312 below the
  floor, an early-days repo may show more `unknown` than `clean`. That is
  correct and it will still look like a bug in a bug report.
- **Risk — retention is not ours.** The verdict is derived from an artifact
  Claude Code owns and prunes on its own schedule. A repo's history can thin out
  underneath the dial. It degrades to `unknown` rather than to `clean`, which is
  the safe direction, but "safe" here means the dial loses confidence over time
  rather than gaining it falsely.
- **Risk — `is_error` is an undocumented field on an undocumented file format.**
  If its semantics change, the rate moves and nothing errors. A canary is owed:
  a corpus-wide error rate that drops to zero, or a `clean` share that jumps,
  should be treated as a format change until proven otherwise.
- **To re-verify:** every number in this document is a 2026-09-04 snapshot of one
  machine's `~/.claude/projects`. Per ADR 0003's rule, it measures the live
  brain, not a `nescio-ai` checkout — but it is still one machine. Re-measure
  the session-level distribution before moving either constant, and re-measure
  the parent-vs-subagent call split before accepting Decision 5's cost a second
  time.

[Source: empirical — 2026-09-04]
