# Case study: the prompt was not the problem

**Dates:** 2026-10-18 to 2026-10-23
**Question:** should the orchestrator write a sliced, per-agent task prompt
instead of handing every subagent the whole plan, to cut subagent token use?
**Answer:** no. The premise was false and the dispatch prompt was 0.5% of what
subagents processed. Measuring where the tokens actually went found a different
lever: what every agent loads *before its first step*. Restricting each agent's
tool list cut that starting context by 86% (nescio-ai PR 190).

The two production runs measured here were on a private product codebase; they
are described by shape only.

---

## 1. Two real runs, priced

Cost per agent came from OpenTelemetry `invoke_agent` spans; token detail from
local subagent transcripts.

| | Run A (a GitHub-issue session) | Run B (a timezone-drift fix) |
|---|---:|---:|
| Subagents | 161 | 48 |
| Subagent input tokens | 2,748M | 544M |
| API-equivalent cost, total | ≈ $1,675 | ≈ $572 |
| … of which subagents | ≈ $1,403 (84%) | ≈ $361 (63%) |
| Largest single line | Opus builder, $862 | orchestrator, $212 |
| Cache write vs cache read | 35M vs 2,713M | 14M vs 530M |

About 98% of input was already served from cache, so caching was not a lever.
The runs were on a flat subscription, so the later work measured tokens rather
than dollars.

## 2. Where subagent input goes

Every request re-sends the agent's whole context. So the question is not "how
big is the prompt" but "what is re-sent, how often".

| Component | Run A | Run B |
|---|---:|---:|
| Dispatch prompt (avg 600–1,100 tokens; 85–100% carried the discovery-brief digest) | **0.4%** | **0.5%** |
| Starting context × number of requests (first request already 62–114k tokens) | 38% | 54% |
| Growth while working (context reaches 200–320k by the last request) | 62% | 46% |

The proposal under study would have optimised the 0.5% line.

**A correction mid-study.** The first analysis said growth was "dominated by
code reading". That compared characters read, not the cost of re-sending them.
Re-measured by re-sent cost:

| Growth component | Run A | Run B |
|---|---:|---:|
| Tool results | 22.4% | 14.7% |
| Thinking | 7.6% | 5.9% |
| Assistant text and tool-call input | 7.5% | 5.4% |
| Unexplained (mostly the 4-chars-per-token estimate; code is nearer 3–3.5) | 24.1% | 20.0% |

## 3. Three alternatives, ruled out by measurement

The six most-read files in each run were studied line by line.

- Agents already read only **4–9%** of the lines in large files. Exact duplicate
  reads within one agent: 0–2%.
- Only 20–28% of the lines read were provably needed — but a perfect fix would
  save just **1.6–2.8%** of session input.

| Alternative | Effect on hot-file read cost |
|---|---|
| Symbol-level reads, as specified | **+21% / +35% (worse)** |
| Orchestrator pastes the snippets into the dispatch | **2.6–3.8× worse**, counting the orchestrator carrying them |
| Hybrid: outline + small symbols whole + ±20-line windows | −51% / −47%, on a 2.5–5.2% slice |

> "Snippets aren't free… a snippet saves tokens only if it is much more precise
> than what the agent would otherwise read."

The orchestrator keeps each dispatch prompt in context for a median of about
100 further requests; a subagent lives about 50. Anything pasted into a dispatch
is paid for by the orchestrator twice over.

One outlier worth naming: one agent re-read an 834-line file in full 34 times
around 66 edits — 63% of its reading cost.

## 4. The real lever: the starting context

Probe agents were asked to reply "OK" and nothing else. Their first request
shows what every dispatch pays before doing any work.

| Probe | Tools loaded | First request |
|---|---:|---:|
| general-purpose | 50 | 78.6k tokens |
| `archimedes` | 50 | 80.3k |
| built-in Explore | 46 | 61.9k |
| claude-code-guide | 5 (own ~23k prompt) | 43.5k |
| vision | Read only | 7.0k |

For an all-tools agent: tool definitions about 57k tokens (≈73%, ~1.2k per tool),
the listing of skills, agents and deferred tools about 14k, `CLAUDE.md` about 3k.
Implementers inherited 42 tools, 20 of them browser tools they never use.

> "Tool definitions are most of every agent's starting context."

**The fix.** A per-agent `tools:` allowlist on 14 agents, `omitClaudeMd` on three
read-only agents, and an explicit `Agent(explore, librarian)` grant for the
planner.

**Measured effect** (fresh-session probes):

| Agent | Before | After |
|---|---:|---:|
| `archimedes` tiers | 80.3k | 12.5k (−84%) |
| `librarian` | 78.7k | 8.2k (−90%) |
| `pyrrho` | 82.0k | 14.9k (−82%) |
| All 15 agents, summed | 1.19M | 168k (**−85.9%**) |

Because the starting context is re-sent on every request, the projected effect
on real runs is roughly a third to under half less subagent input. That
projection has not yet been measured on a production run.

In the product repo a second lever showed up: `CLAUDE.md` plus always-loaded
rule files were about 110k characters (~28k tokens) per request. Scoping the
rule files with `paths:` cut the always-loaded text to about 31k characters —
with the tool lists trimmed, those rules had been about 70% of an agent's
starting load there.

## 5. The orchestrator's own starting context

The main session opened at 108.8k tokens before the user's first word:

| Component | Tokens |
|---|---:|
| Loaded tool definitions (~55 tools) | ~71k (65%) |
| System prompt (orchestrator charter ~8.7k of it) | 13.9k |
| Skill listing (116 skills) | 8.6k |
| Deferred tool names (502, ~13.5 tokens each) | 6.8k |
| MCP server instructions | 2.4k |
| `CLAUDE.md` | 2.3k |
| Agent listing | 2.0k |

Single-run toggle tests (±1.5k noise): turning the in-app browser pane off saved
9.4k tokens (−8.7%), the largest single setting; all switchable settings together
about 19k (~18%). Ten skills with non-English descriptions cost 2.75k tokens —
more than the other 55 listed skills combined.

That session grew from 108.8k to 461k context over 187 requests; at that point
the starting load accounted for 37% of everything it had processed.

## 6. Mistakes that would have produced wrong numbers

- **Characters are not cost.** The first growth analysis ranked components by
  characters read, not by how often they were re-sent.
- **Stale agent definitions.** A running session caches agent definitions, so the
  first "after" probes still showed 78–82k. They were discarded and re-run in a
  fresh session.
- **A documentation summary was wrong.** It said `Agent` is stripped from
  dispatched subagents; probes showed the planner does load it. The PR
  description was corrected; the commit message is still wrong in history.

## 7. What to take from it

- **Measure before optimising the visible part.** The prompt the orchestrator
  writes is the part everyone looks at, and the smallest part of the bill.
- **Re-sent context is the unit of cost.** Anything loaded at the start is paid
  once per request, for the whole life of the agent.
- **Omission risk is asymmetric.** "Extra context costs tokens. Missing context
  costs correctness." The cuts that held were tools an agent provably never
  calls, not information it might need.
