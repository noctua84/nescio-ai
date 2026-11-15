# Token consumption: where an agent crew's tokens go

**Data as of:** 2026-11-14
**Corpus:** every Claude Code transcript on one developer machine:
7,858 transcripts, made up of 879 main sessions and 6,979 subagent runs. They span
2026-04-15 to 2026-11-14; nearly all volume is from July onward. Work ran across
the public framework, its private instance and several private product repos;
none are named here.

Supporting analyses:
- a session from 2026-08-23 that built the first usage scanner (published as
  `docs/usage/`);
- a prompt-optimization study from 2026-10-18 to 2026-10-23 (see
  [case study 03](03-the-prompt-was-not-the-problem.md));
- an effort probe from 2026-10-30.

---

## 1. The headline: almost everything is re-reading

Totals over the whole corpus:

| Meter | Tokens | Share |
|---|---:|---|
| Cache reads | 70.19 B | 97.3% of all input |
| Cache writes | 1.94 B | 2.7% of input |
| Uncached input | ~0 | requests send about 2 uncached tokens each |
| Output (including thinking) | 216.6 M | 0.3% of all tokens |

The August scan of the main sessions, 3.5 weeks and 20,900 requests, priced each
meter at its relative rate:

| Weighted share of spend | |
|---|---:|
| Cache reads | 61% |
| Cache writes | 26% |
| Output | 13% |

> "Only 13% of your spend is Claude *writing things*. The rest is Claude
> *re-reading the conversation*."

Each request re-sends the whole context, so cost grows with the length of a
conversation, not with the amount of work done in it.

## 2. Context grows and never shrinks

From the August scan of main sessions (model `opus[1m]`):

- Context per request: p50 289k, p90 701k, p99 953k tokens.
- Growth: about +2.4k tokens per request, monotone.
  - A typical session opens at 84k, passes 200k around request 55 and reaches
    789k by request 275.
- Tokens above the 200k mark: 3,566M of 7,245M context tokens (**49%**). That is
  the largest single lever, worth 31–43% of weighted spend.
- Requests per session: median 78, p90 284, maximum 1,300.
- Two "marathon" sessions (1,300 and 1,198 requests) took 17% of the period's
  weighted spend.

The response was structural rather than a setting. Work that lands on its own as
a commit or PR becomes a spawned session that starts at the floor, instead of
another phase in a session that already carries 500k tokens.

> "Chips aren't a cheaper way to run subagents; they're the *mechanism* for
> 'break up marathon sessions.'"

## 3. The floor: what every agent pays before its first step

| Context | First request, before | First request, after per-agent tool lists |
|---|---:|---:|
| Main session (orchestrator) | 108.8k | — |
| A subagent with all tools | 78–82k | 7–15k |
| `archimedes` (any tier) | 80.3k | 12.5k |
| All 15 crew agents, summed | 1.19M | 168k (−85.9%) |

The floor is paid on every request for the life of the agent.

Composition of the floor:

| | Main session (108.8k) | All-tools subagent (~78k) |
|---|---|---|
| Tool definitions | ~71k (65%), about 55 tools | ~57k (73%), about 1.2k per tool |
| System prompt | 13.9k | — |
| Skill, agent and deferred-tool listings | 17.4k | ~14k |
| `CLAUDE.md` | 2.3k | ~3k |

In one product repo, always-loaded rule files added another ~28k tokens per
request. Scoping them to paths cut that by about 70%.

## 4. Per agent: how long they run and what they re-read

Medians per run over the whole corpus. Theme names are mapped to roles:
`archimedes*` = builder tiers, `pyrrho` = reviewer, `euclid` = test-writer,
`plato` = planner.

| Agent | Runs | Median requests | Median cache read | Median output |
|---|---:|---:|---:|---:|
| Main session | 879 | 58 | 9.3M | 47k |
| builder (Opus) | 860 | 49 | 5.9M | 18k |
| builder-standard (Sonnet) | 1,159 | 55 | 7.3M | 16k |
| builder-simple (Haiku) | 647 | 28 | 2.1M | 6k |
| reviewer (QA) | 365 | 39 | 5.3M | 12k |
| test-writer | 349 | 27 | 2.6M | 8k |
| planner | 142 | 28 | 3.2M | 35k |
| validator | 257 | 14 | 1.3M | 8k |
| devil's advocate | 277 | 10 | 0.8M | 11k |
| explore | 1,150 | 16 | 1.2M | 8k |
| general-purpose (not a crew role) | 1,216 | 24 | 2.2M | 9k |

Readings:
- **The reviewer re-reads like a builder.** It runs 39 requests and reads 5.3M
  cached tokens per audit, against 49 requests and 5.9M for the Opus builder.
  Auditing a diff means loading most of what was built.
- **The planner writes the most per run.** Its 35k median output is twice the
  builder's: it writes the plan.
- **The cheap roles are cheap because they are short**, not because their
  context is small. Validator and devil's advocate finish in 10–14 requests.

## 5. Subagents versus the main session

Three figures have been published for this. They disagree, and the reason they
disagree is a lesson in itself.

| Source | Subagent share | Why |
|---|---|---|
| August scan | "≈ 1% of spend" | **Wrong.** It read only top-level transcripts and missed the `subagents/` folders, 320 of them for that window. |
| Two multi-agent product runs (telemetry) | 84% and 63% of cost | Large waves of builders and reviewers |
| Whole corpus at list prices (this study) | 47% of cost | A mix of solo sessions and orchestrated runs |

In sessions that dispatch few builders, the coordinating thread dominates. It
held 61–97% of tokens in four of the optimization sessions studied, and 49% in
one that ran 22 subagent runs.

## 6. Effort is a token knob, and only where it applies

Probe on Claude Code 2.1.312, Haiku 5.5, n=2 per arm, so the figures are
directional:

- Frontmatter `effort:` is honoured for subagents. Output was about 11k and 15k
  tokens at `low`, against about 18k and 24k at `high` (~60% more).
- It has **no effect** on an agent run as the main session. There, the session's
  own effort setting decides: `--effort low/high` moved output from 283 to 507
  tokens.

The crew's builder tiers all run at the same effort on purpose. Effort changes
reasoning depth, and the tiers are meant to differ only in model.

## 7. The transcript-counting trap

Claude Code writes each assistant message to the transcript several times while
it streams. Each record repeats the message id; only the last one carries the
final counts. Three ways to sum them give three different answers:

| Method | Result |
|---|---|
| Sum every record | Inflates totals about 3× (August scan) |
| Take the first record per message id | Undercounts output. Builder runs showed a median of 4.3k output tokens instead of 17.8k; mean cost per Opus builder run read $3.65 instead of $4.61 (−21%). |
| Take the maximum of each field per message id | Correct for input and cache. Output is still a lower bound for some subagent runs: one wrote ~500 changed lines but logged 653 output tokens. |

The first-record method was used for the break-even that framed the
[builder-tier decision](01-a-stronger-builder-or-a-better-charter.md). The
correction made the conclusion stronger, not weaker, but the number in the plan
was wrong.

**Other measurement pitfalls hit along the way:**
- Subagent transcripts live in `<session>/subagents/agent-*.jsonl`, with the
  agent type in a sibling `.meta.json`. Both are undocumented harness internals.
  A scan that misses them reports subagents as negligible.
- A running session caches agent definitions. Before/after probes of a charter
  change must run in a fresh session.
- Characters read are not tokens re-sent. A large file read once early costs
  more than a larger one read at the end.
- A scan once picked up its own session's in-flight text and reported
  "41.9M subagent tokens". None of the 1,842 agent results it parsed carried a
  token count. The dashboard was corrected; the published `data.json` still
  holds that field.

## 8. Volume over time

| Month | Main sessions | Subagent runs |
|---|---:|---:|
| 2026-07 | 53 | 201 |
| 2026-08 | 216 | 1,889 |
| 2026-09 | 178 | 1,704 |
| 2026-10 | 303 | 2,378 |
| 2026-11 (to the 14th) | 121 | 807 |

Subagent runs per main session went from about 4 in July to between 7 and 10
from August on, with the orchestrator as the default agent.

## Method

- **Scope:** every `*.jsonl` under `~/.claude/projects/`. Main sessions are the
  top-level files; subagent runs are `subagents/agent-*.jsonl`.
- **Agent type:** the sibling `.meta.json`.
- **Counting:** usage was taken per unique `message.id`, with the maximum of each
  field across its records.
- **Exclusions:** messages with model `<synthetic>` are excluded.
- **Theme mapping:** `archimedes*` is mapped to the builder tiers; the other
  theme names are mapped to their functional roles.
- **Scripts:** kept outside the repository, because the transcripts contain
  private code.
