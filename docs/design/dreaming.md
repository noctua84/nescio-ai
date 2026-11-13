# Dreaming: reviewing past sessions to curate the crew's memory

> Status: design plus prototype (`scripts/dream.py`, `/dream`). This is the
> smallest useful slice, not the whole loop. Section 9 lists what is open.

Between sessions, read what the crew did, find mistakes that recur and
workflows that worked, and propose changes to memory. The idea comes from
Anthropic's "dreaming" for Claude Managed Agents. That is an API product that
Claude Code does not have, so this is a local Python version built on the
harvest pipeline that already exists here.

## 1. What Anthropic's dreaming is

Sources, checked 2026-11-12. Items marked *secondary* appear only in press
write-ups.

- **Primary:** the Dreams API docs
  (`platform.claude.com/docs/en/managed-agents/dreams`), the launch post
  (`claude.com/blog/new-in-claude-managed-agents`), and the engineering post
  "Components of agent memory" (`anthropic.com/research/components-of-agent-memory`).
- **Secondary:** SiliconANGLE (2026-05-06), InventiveHQ, and Let's Data Science.

| Aspect | What Anthropic ships | Source |
|---|---|---|
| Shape | An asynchronous job (`POST /v1/dreams`) that takes minutes to hours | primary |
| Trigger | The caller creates each dream. The API has no schedule parameter, even though the blog calls it "scheduled". | primary |
| Inputs | One memory store, plus 1–100 session transcripts, a model, and optional `instructions`. Instructions that steer synthesis work. Line-level edit directives "generally produce no change". | primary |
| Output | A **new** memory store. Duplicates are merged, stale or contradicted entries replaced, and new insights added. The input store and sessions are never modified. | primary |
| Approval | Structural. Nothing changes until you attach the output store to later sessions, and you reject it by deleting it. The blog says it can "update memory automatically, or you can review changes before they land." | primary |
| Results | Harvey reports completion rates up about 6x (vendor quote, no method given). Anthropic's own evals: a wiki-only score rising from 13% to 48% as sessions went from 2 to 128, and goal-focused instructions raising graded facts from 72% to 100%. | primary, not independent |
| Risks | Wikis can bloat (a 203 KB wiki from a 115 KB corpus), errors can compound, and injected context has to stay small. It is not eligible for ZDR or HIPAA. | primary |
| "Four phases: review, extract, reconcile, prune" | The article's own framing | *secondary only* |

Two points shape this design:

1. **Never mutate the input. Produce a separate artifact and let the caller adopt it.**
2. **Steering with a goal works, and micro-edits do not.**

The bloat warning is the main reason the output here is a short, ranked
proposal and not a rewritten wiki.

## 2. What exists here already

| Piece | Role | What dreaming takes from it |
|---|---|---|
| `hooks/record_stop.py` | The Stop hook appends one record per turn to `<config>/learning-trail/<repo_key>.jsonl`, including `transcript_path`. It deliberately records **no** verdict. | Its docstring defers deriving outcomes to a later step that can afford to read transcripts. Dreaming is that step. It reuses `repo_key`, `redact` and `config_dir`. |
| `hooks/harvest_nudge.py`, `hooks/memory_trigger_nudge.py` | SessionStart reminders: a harvest backlog, a half-finished harvest, ADR 0002 triggers | Where a "dream due" nudge would go (section 3) |
| `/harvest-memory`, plus `begin_harvest.py`, `promote_learnings.py` and `mark_harvested.py` | The **only** sanctioned writer into the version-controlled `memory/`. It validates nominations, applies `user override > empirical > agent inference`, stamps provenance and keeps a ledger. | The sink for memory proposals from dreaming. Dreaming never writes `memory/` itself. |
| `memory/` (`repo/<repo>/`, `projects/`, `concepts/`, `feedback/`, ADRs under `repo/<repo>/adr/`) | Durable, synced memory | The target of proposals, through the harvest pipeline |
| Auto-memory, `~/.claude/projects/<slug>/memory/` | Machine-local notes captured during sessions | Already an input to harvest. Dreaming adds signal that comes from transcripts. |
| Transcripts, `~/.claude/projects/<slug>/*.jsonl` | Full session logs. Worktrees get their own slug, `<slug>--claude-worktrees-<name>`. | The primary input to dreaming |
| Builder report: `<verdict>`, `<deviations>` (`Inverted pin:`, `Deferred red:`) and `<out-of-scope>` | Appears in the parent transcript as `toolUseResult.content` with `agentType` | The highest-signal "mistake" data, and structured enough to parse without a model |
| Orchestrator BLOCKED routing and tier escalation | A BLOCKED or PARTIAL from a `-simple` or `-standard` tier, followed by a re-dispatch one tier up | Shows as a sequence of `agentType`s in one session, so it can be detected without a theme |
| `scripts/session_anatomy.py` | Streams transcripts line by line and tolerates malformed lines | The parsing pattern copied here |
| `consolidate-memory` | Not in this repo. It is reachable only as the Anthropic plugin skill `anthropic-skills:consolidate-memory`, which merges duplicates and fixes stale facts in memory files. | Deliberately **not** reimplemented. See section 4c. |
| QA reports, `docs/reports/YYYY-MM-DD-*.md` | Severity-ranked audits written by the QA agent | Optional input (section 9) |

## 3. Trigger

Options, in order of preference:

1. **SessionStart nudge (recommended default).** Extend `harvest_nudge.py` to
   print one line when the last dream is older than N days *and* at least M
   sessions have ended since then. This costs nothing until the user acts, and
   it follows the pattern the hooks already use.
2. **On demand:** `/dream`, which the prototype ships.
3. **Scheduled:** a cloud routine (`/schedule`) or a local `/loop`. A cloud
   routine cannot see machine-local transcripts. That rules it out unless the
   transcripts move, and moving them is a privacy cost (section 6). `/loop`
   keeps a session open. Treat both as opt-ins for later.

`<config>/dreams/<repo_key>/last-dream.json` holds the watermark, kept apart
from the harvest watermark. A dream does not claim to have harvested anything,
so it must never move the pruner's watermark.

## 4. The pipeline

The work is split in two stages. A deterministic **extractor** costs no tokens
and has no model in it. A **reviewer** pass is Claude running inside `/dream`.

### 4a. Inputs (extractor)

- Transcripts newer than the watermark from every slug of the repo, worktrees
  included, up to `--max-sessions`, newest first.
- From each one: agent results (`toolUseResult` with `agentType`), user
  messages, `tool_use` and `tool_result` pairs, and Bash commands.
- Not yet read: subagent transcripts under `<session>/subagents/`, QA report
  files, the learning trail, and auto-memory. Section 9 covers these.

### 4b. Signals (extractor)

A signal is **recurring** only if it shows up in at least `--min-sessions`
distinct sessions (default 2). One bad afternoon is not a pattern.

| Signal | Detection | What it usually means |
|---|---|---|
| Tier escalation `F: t→t'` | A BLOCKED or PARTIAL verdict from family F at tier t, then a dispatch of F at a higher tier in the same session | The plan's tiering criteria under-classify this kind of task |
| Verdict mix per agent | A tally of `<verdict>` values | An agent that is often PARTIAL or BLOCKED needs a prompt or brief fix |
| Inverted pin / deferred red | Labelled lines in `<deviations>` | Briefs that tell builders to change tests. Worth confirming. |
| Out-of-scope findings | `<out-of-scope>` lines, deduplicated | A backlog that would otherwise die with the session |
| User corrections and interrupts | A user message that starts with "no", "don't", "instead", "actually", "revert" and similar, or an interrupt marker | The crew's defaults differ from what this user wants. This is the strongest `user override` candidate. |
| Repeated tool errors | `is_error` tool results, grouped by a normalised first line | Environment quirks, such as a Windows shell trap or a missing tool, that a memory note would prevent |
| Reverts | Bash `git revert`, `reset --hard`, `checkout --` or `restore` | Work that was done and then undone |

Workflows that worked are the inverse signals: a COMPLETE with no deviations
on the first dispatch, or a session with no corrections. The extractor reports
the counts and the reviewer pass names the workflow. Detecting success
patterns automatically is left open, because doing it well needs a model.

### 4c. Stale or duplicate memory

This is not part of the extractor. Merging duplicates is what
`consolidate-memory` does, and what Dreams does to its store. Here it already
belongs to `promote_learnings.py` (dedupe through the content-hash ledger, and
contradiction precedence) and to ADR 0002's revisit triggers. `/dream` tells
the reviewer to check each proposed note against existing `memory/` before
nominating it, rather than building a second deduplicator.

### 4d. Outputs

The extractor writes a Markdown proposal to
`<config>/dreams/<repo_key>/<UTC>.md`. It is machine-local and never touches the
repo. The `/dream` reviewer pass then sorts each recurring pattern into one of
four outputs:

| Output | Where it goes | Approval |
|---|---|---|
| Memory note: a quirk, a convention, a correction | A nomination for `promote_learnings.py`, with source `empirical` (or `user override` for a correction the user stated) | The user approves each nomination. Never auto-applied (section 5b). |
| An agent prompt, `CLAUDE.md` or tiering criterion change | A proposed diff, shown in the conversation or committed to a `dream/<date>` branch | **Always held.** It is never auto-applied. |
| A new skill | A one-paragraph sketch plus evidence, filed as a spawned task | Always held |
| A follow-up task from `<out-of-scope>` | A candidate task card | The user decides |

## 5. Approval

- **Never auto-edited:** `agents/`, `CLAUDE.md`, `skills/`, `commands/`, hooks,
  and scripts. A recurring prompt flaw found in one user's sessions is weak
  evidence for changing a prompt every consumer runs. The drift cost of a bad
  edit is high, and an eval does not exist yet (section 7).
- **Memory notes:** held by default. Each nomination is shown to the user and
  goes through `/harvest-memory` only on approval.

An earlier draft of this section sketched an opt-in `--auto-apply-memory`:
nominations passed straight to `promote_learnings.py` when they targeted
`repo/<name>` or `feedback`, carried source `empirical`, had been seen in at
least 3 sessions, and were listed in the next SessionStart nudge for revert.
Section 5a checks that sketch against the code. Section 5b records the
decision.

### 5a. Can the sketched auto-apply be built safely?

No, not as an unattended write into `memory/`. The findings, checked against
the code on 2026-11-13:

1. **A model has to write the note.** The extractor emits a signal kind, a
   redacted excerpt of at most 160 characters, and a session count. It does not
   emit a note. Turning a signal into a note body needs a model, either a
   headless run or the interactive `/dream`. So "auto" can only mean that a
   setting approves the model's draft in advance. The limits can check the
   envelope (scope, target, source label, session count). They cannot check the
   body, which is the part that is loaded into later sessions. The `source`
   label has the same problem: the drafting model asserts it. It is not
   measured. A gate has to derive the source from the signal kind instead of
   trusting the label.
2. **The recurrence threshold does not contain prompt injection.** Excerpts come
   from tool output, error text and fetched pages. `record_stop.redact` blanks
   secret shapes, not instructions, and 160 characters is enough room for an
   instruction. The threshold of 3 sessions filters noise, not attacks. A
   planted string in a repo file, a dependency's error message, or a page the
   crew fetches often shows up in every session, so a persistent source is
   exactly what clears the threshold. Memory is read by every later session as
   trusted guidance. An injected note would therefore outlive the transcript it
   came from and act as a persistent injection. Holding proposals for approval
   (section 6) is the only control in this design that addresses this risk, and
   auto-apply removes it.
3. **The brain guard warns when nobody is reading.** `guard_brain` refuses only
   on `mismatch` and `broken`. On `unknown` and `override` it prints a warning
   and proceeds. That is fine in an interactive harvest, where someone sees the
   warning. In an automatic path nobody does, so that path must require the
   verdict `brain` exactly.
4. **Contradiction precedence protects only `user override`.** In
   `promote_learnings.py`, a `body` nomination whose source equals the existing
   note's source overwrites it without a date comparison (same-source
   refinement). An automatic `empirical` note could therefore replace a reviewed
   `empirical` note entirely. An automatic path must be create-only and refuse
   any existing target. The `units` shape is not a way around this: the
   promote docstring says it stays unexercised until #180 stage 2, and its
   `supersedes` deletes text.
5. **Revert has no tool, and merge is already the gate.** `promote_learnings.py`
   does no git work. `/harvest-memory` step 9 requires delivering through a
   branch and a PR, never a commit on `main`. Every `memory/` change therefore
   already passes a human at merge, and auto-applying to `main` would break the
   repo's own rule. `scripts/unmark_harvested.py` does not revert notes. It
   deletes harvest watermarks left by a bad global stamp, which is a different
   problem. A `body` note can only be reverted with git: close the PR, or
   `git revert` after merge. Closing the PR also drops the ledger line, so the
   next dream proposes the same note again. An automatic path needs a
   machine-local rejection list keyed by signal signature, or rejected notes
   come back on every run.
6. **The `feedback` scope does not fit.** Most feedback notes come from user
   corrections, and those are `user override`, which the limits exclude. The
   promote docstring also treats `feedback` and `people` as observations about
   identifiable individuals, which is the worst place to write without review.
   Only `repo/<name>` fits.

### 5b. Decision: no auto-apply (2026-11-13)

Auto-apply is dropped. Every memory nomination from `/dream` is held, shown to
the user and promoted through `/harvest-memory` only on approval. There is no
`--auto-apply-memory` flag or setting.

An alternative was considered and rejected: "auto-staging", where nominations
that pass a deterministic gate would skip the per-item question and land
together as one `dream/<date>` PR. The gate would have required a new note
under `repo/` only, a signal of kind `tool-error`, `escalation` or `revert`
seen in at least 3 sessions, no entry in a rejection list, and a brain-guard
verdict of exactly `brain`. It kept a human gate at merge, so it was safe. It
was dropped because the gain is small (one PR review in place of one
confirmation per note), while it needs three new parts: a machine-readable
sidecar from `dream.py`, a gate module, and a rejection list.

Revisit this decision if the per-item review becomes a bottleneck, for example
if dreams routinely produce more nominations than a user will confirm one by
one. Start from auto-staging, not from auto-apply. The findings in 5a still
apply to any version.

## 6. Privacy

- Transcripts hold private code, paths, customer names and secrets. The
  extractor:
  - keeps only short excerpts (at most 160 characters) and passes each one
    through `record_stop.redact`, which blanks it on any secret shape;
  - replaces the home directory with `~`;
  - writes only under `<config>/dreams/`, which is machine-local and not synced.
- **Output scope follows the input scope:**
  - Per-project learnings go to the machine-local store or the brain's
    `memory/repo/<repo>/`.
  - Only a **generic** lesson goes to public nescio-ai, as a prompt tweak to
    this framework. A generic lesson is a pattern stated without names, paths
    or quoted user text, and that pattern has to hold across repos.
  - `/dream` requires `scripts/scrub_check.py` to pass before anything bound for
    the public repo is committed.
- A cloud-scheduled dream would need transcripts uploaded. That is out of scope
  until the user explicitly chooses it. Anthropic's Dreams are not
  ZDR-eligible, for the same reason.
- Prompt-injection surface: transcripts contain web pages and tool output. The
  reviewer treats every excerpt as data. Proposals are held for approval, so
  injected text cannot write memory on its own. That hold is the control.
  Redaction, truncation and the recurrence threshold do not stop an
  instruction (section 5a).

## 7. Cost controls, and how to know whether it helps

Cost:

- The extractor makes no model calls and streams line by line. Its cost is disk
  reads, bounded by `--max-sessions` (50 by default) and the watermark.
- The reviewer pass reads one proposal of a few KB, not the transcripts. That
  is the main saving over Dreams, whose cost grows linearly with the number of
  transcript tokens.
- The `--min-sessions` threshold keeps the proposal short. This is the remedy
  for the bloat Anthropic reports.

Measurement. The extractor's own counts serve as the metrics, so measuring needs
no new instrumentation:

- **Leading:** the share of proposals accepted, and nominations per dream that
  survive review.
- **Outcome:** compare the per-week rates of the recurring signals before and
  after a learning lands, using the same extractor on the two windows:
  - escalations per 10 builder dispatches;
  - user corrections per session;
  - repeated tool-error signatures;
  - BLOCKED rate.

  A lesson works if its signature stops recurring. Its decay is the test.
- **Guard:** if a note lands and its signal does not drop within N sessions,
  the next dream flags the note as ineffective. That makes it a candidate for
  removal, which keeps memory from only ever growing.
- This is not a controlled experiment. Usage mix changes week to week, so read
  trends across several dreams, not a single delta.

## 8. Prototype (shipped in this change)

- `scripts/dream.py` (aggregate, render, CLI) and `scripts/_dream_parse.py`
  (transcript parsing) are the deterministic extractor described in sections
  4a and 4b. It writes the proposal and stamps the watermark (`--no-stamp` to
  skip).
- `commands/dream.md` holds the `/dream` reviewer steps: run the extractor,
  triage each pattern into memory nomination, held prompt diff, or drop, and
  apply the privacy gate.
- `tests/test_dream.py` covers the extractor on synthetic JSONL fixtures. No
  real transcripts are used.

## 9. Open

- **Background agents: fixed, with gaps left.** A background dispatch
  returns only an `agentId`. Its report arrives later as a hand-back message
  (`<agent-message from="<agentId>">` with `[Subagent hand-back]`), or in older
  transcripts inside `<task-notification>`. The parser now links `agentId` to
  `agentType` through the dispatch and counts these reports. On real data the
  parsed reports went from 69 to 153 in a 50-session window. Dispatches still
  outnumber reports (272 against 153), and some builder hand-backs carry no
  verdict. Escalations came out at 0. All three need a closer look.
- The follow-ups section reached 335 lines on real data, so it needs a cap or a
  ranking before `/dream` is pleasant to review.
- User-rejected tool calls are excluded from tool errors. A rejection that
  carries a reason now counts as a correction; a bare rejection does not.
- A "dream due" SessionStart nudge, in `harvest_nudge.py`.
- Reading subagent transcripts, which hold the builder's own tool errors and
  retries, and QA reports (severity counts per audit).
- Detecting successful workflows automatically: needs a model call, which means
  a cost decision.
- The effectiveness tracker: link a ledger entry to the signal signature that
  prompted it.
- **User corrections are a lower bound, not a rate.** Measured on one
  machine's real transcripts (871 sessions, 5,669 human messages; labels by
  one reviewer, counts only):
  - The first regex matched 72 messages; about 37% of a 60-message sample were
    real corrections. Most false positives were a "no" answering the agent's
    question with "nothing else", "stop here", "actually ..." redirects, and a
    repeated session-opening prompt.
  - The current rule matches 29 messages, about 83% of them corrections. It
    ignores the session's first message, drops "actually" and "stop", requires
    word boundaries, ignores "I mean," elaborations, and counts a bare "no"
    only when the agent's last text did not end in a question. A rejected tool
    call that carries a reason also counts (4 on that machine). The precision
    is in-sample: the rule was tuned on the messages it was scored on.
  - Recall did not improve. In a random sample of 200 human messages, 9 were
    corrections and both rules caught 2. Most corrections are plain statements
    of fact (for example, naming the right file), which no start-of-message cue can
    tell apart from ordinary talk.
  - Messages right after an interrupt are not counted: about 3 of the 17
    measured were corrections. Interrupts stay a separate count.
  - The cues are English-only. Corrections in other languages are not seen.
    Closing the recall gap needs a model call, which is a cost decision.
- **The transcript format is internal and unstable by Anthropic's own
  statement.** Only the location is documented
  (`~/.claude/projects/<project>/<session-id>.jsonl`, in
  [Manage sessions](https://code.claude.com/docs/en/sessions.md), "Where
  transcripts are stored"). The same page says the entry format is internal to
  Claude Code and changes between versions, so direct parsers can break on any
  release, and points to `/export` and the SDK instead. No official page defines
  `toolUseResult`, `isMeta`, `agentType` or the entry `type` values, and the
  SDK's `getSessionMessages()` types the payload as `unknown`
  ([Agent SDK sessions](https://code.claude.com/docs/en/agent-sdk/sessions.md)).
  The extractor therefore runs a format self-check: it tallies the shapes it
  relies on (user/assistant entries, `message.content`, `tool_use` blocks,
  `toolUseResult` dicts, Agent/Task dispatches, agent reports once
  dispatches exist) and adds a "Format check"
  section to the proposal when one goes missing, or when an unknown top-level
  key appears on most entries. On the 871 sessions above it raised no warning.
- Porting to the brain: the files sit in framework paths (`scripts/`,
  `commands/`, `tests/`, `docs/`), so the usual sync carries them.
