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
| Memory note: a quirk, a convention, a correction | A nomination for `promote_learnings.py`, with source `empirical` (or `user override` for a correction the user stated) | The user approves each nomination. Auto-apply is opt-in (section 5). |
| An agent prompt, `CLAUDE.md` or tiering criterion change | A proposed diff, shown in the conversation or committed to a `dream/<date>` branch | **Always held.** It is never auto-applied. |
| A new skill | A one-paragraph sketch plus evidence, filed as a spawned task | Always held |
| A follow-up task from `<out-of-scope>` | A candidate task card | The user decides |

## 5. Approval

- **Never auto-edited:** `agents/`, `CLAUDE.md`, `skills/`, `commands/`, hooks,
  and scripts. A recurring prompt flaw found in one user's sessions is weak
  evidence for changing a prompt every consumer runs. The drift cost of a bad
  edit is high, and an eval does not exist yet (section 7).
- **Memory notes:** held by default. A later `--auto-apply-memory` (or a
  setting) could pass nominations straight to `promote_learnings.py`, under
  these limits:
  - only scopes `repo/<name>` and `feedback`, and never `concepts/` or ADRs;
  - only source `empirical`, never `agent inference`;
  - only when seen in at least 3 sessions;
  - every applied note listed in the next SessionStart nudge so that it can be
    reverted (the ledger already records it).

  This is the counterpart of Dreams' "update automatically". Here it is a
  bounded opt-in, not the default.

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
  injected text cannot write memory on its own.

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

### 7a. Effectiveness tracker (shipped)

The minimal data model has three parts, all machine-local under
`<config>/dreams/<repo_key>/`:

| Piece | Written by | Holds |
|---|---|---|
| `<UTC>.json` sidecar | `dream.py`, next to each `<UTC>.md` | The run window (`since`, `until`), `sessions_read`, `agent_dispatches`, and **every** signal seen in at least one session: `{sig_id: {key, sessions, count}}` |
| `links.json` | `dream.py --link HASH12 SIG_ID` | `{hash, sig, linked_at}`: which ledger entry was promoted because of which signal |
| `memory/learning-log.md` | `promote_learnings.py`, unchanged | The promotion date for `hash` |

- **Signal ids are stable keys, not counts.** The key is `escalation:<family>:<t>-><t'>`,
  `tool-error:<tool>:<signature>`, `corrections`, `reverts`, `inverted-pins`,
  `interrupts`, `blocked:<agent>` or `partial:<agent>`. The id is the first 8
  hex digits of its SHA-256. The proposal prints `[sig <id>]` after each
  recurring pattern, so the reviewer can copy it into `--link` after promoting.
- **The sidecar records all signals, not the top five.** A signature that
  drops out of the top five would otherwise look like it went to zero.
- **The link stays out of the ledger.** Signal keys can carry tool names and
  normalised command text. The ledger is tracked and synced, so adding a field
  there would leak them and would change the contract that three schema copies
  share. The ledger hash is enough to join on.
- **`dream.py --compare`** reads the sidecars and drops a run whose window
  overlaps an earlier kept run, which happens after `--no-stamp` reruns. For
  each link it pools the runs before the promotion date and the runs after it,
  and leaves out runs that straddle the date. Rate is the share of sessions
  that show the signal. The verdict is `too early` (fewer than `--min-after`
  sessions after, default 10), `no baseline`, `working` (the rate at least
  halved), `ineffective` (the rate did not drop) or `unclear`.
- The rate is per session, for every kind of signal. Per-dispatch rates for
  escalations would be sharper, but they wait on the background-agent
  undercount (section 9): with most reports unparsed, the denominator is wrong.

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
- User-rejected tool calls are excluded from tool errors, but rejections
  could themselves be a correction signal.
- A "dream due" SessionStart nudge, in `harvest_nudge.py`.
- Reading subagent transcripts, which hold the builder's own tool errors and
  retries, and QA reports (severity counts per audit).
- **Detecting successful workflows automatically.** Measured on one machine's
  last 60 days (870 main transcripts, aggregate counts only). The counts were taken
  from foreground `toolUseResult` reports only, before the hand-back fix above,
  so verdict coverage is a lower bound and should be measured again:

  | Proxy | Result | Verdict |
  |---|---|---|
  | First-try COMPLETE with no deviations | 68 of 229 reports with a verdict; only 229 of 1,475 parsed reports (and of about 7,500 dispatches) carry a `<verdict>` | The "no deviations" part discriminates, since 221 of 229 verdicts are COMPLETE. Coverage was about 3% of dispatches before the hand-back fix. |
  | Session with no correction or interrupt | 797 of 870 sessions | Does not discriminate. The correction regex rarely fires. |
  | Friction-free session (no correction, interrupt, revert or tool error) | 177 of 870 | Confounded by length: 106 of 285 sessions with fewer than 2 human messages, and 0 of 67 with 20 or more |

  Model-assisted pass, estimated at chars/4 as in `session_anatomy.py` (tokens
  only, never cost):

  | Input to the model | Tokens over 60 days | Per default 50-session dream |
  |---|---|---|
  | Full transcript content (text, thinking, tool input and output) | about 100M (median 54k per session) | about 5.8M |
  | Skeleton (human and assistant text, agent reports, tool calls cut to 300 chars) | about 33M (median 15k) | about 1.9M |
  | Skeleton of candidate sessions only (2 or more human messages, at least one report, no correction) | about 12M (245 sessions) | about 2.4M |
  | Clean first-try reports plus their dispatch prompts | about 100k (68 items, about 1.5k each) | well under 100k |

  The proposal the reviewer reads today is a few thousand tokens. **Recommendation:**
  do not add a transcript-level model pass. Only the last row is cheap: roughly 10 to 30 times
  today's reviewer input per dream, against hundreds to thousands of times for the others. Run
  that row inside `/dream` as part of the existing reviewer turn, with no new
  API call: give the reviewer each clean report plus its dispatch prompt, and
  ask what the brief got right. First measure verdict coverage again with the
  hand-back parser, because the 3% above came from foreground reports only. Any
  separate model call stays a decision for the user.
- `--auto-apply-memory` with the limits in section 5.
- The effectiveness tracker shipped (section 7a), and `/dream` runs it:
  `--compare` before triage, with `ineffective` notes reported as removal or
  rewrite candidates, and `--link` after each promotion. Still open: linking is
  a manual step, because `promote_learnings.py` prints no hash. If promotion
  returned the hash, `/dream` could link without reading the ledger.
- The correction regex is English-only and heuristic. Expect both false
  positives and missed corrections. Tune it on real data before trusting the
  rates.
- Porting to the brain: the files sit in framework paths (`scripts/`,
  `commands/`, `tests/`, `docs/`), so the usual sync carries them.
