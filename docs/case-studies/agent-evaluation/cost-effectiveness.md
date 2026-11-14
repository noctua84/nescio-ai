# Cost-effectiveness: what each agent costs, and what that buys

**Data as of:** 2026-11-14
**Corpus:** the same one as [token consumption](token-consumption.md). It holds
879 main sessions and 6,979 subagent runs, from July to November 2026.

**All dollar figures are API list-price equivalents.** The work ran on a flat
subscription, so these numbers measure relative cost and how much quota each
choice burns. They are not an invoice.

---

## 1. Prices used

Prices are list prices per million tokens.

| Model | Input | Output | Cache read | Source |
|---|---:|---:|---:|---|
| Opus 5.5 | $4 | $20 | $0.20 | model docs |
| Opus 5 / Opus 4.8 | $5 | $25 | $0.50* | model docs ("half of Fable 5.1"; the 4.8 → 5 bump was price-neutral) |
| Sonnet 5.5 / Sonnet 5 | $2 | $10 | $0.20 | model docs |
| Haiku 5.5 | $0.10 | $0.50 | $0.01* | model docs, prompts ≤ 100K tokens (above that $0.50 / $2.50) |
| Haiku 4.5 | $1 | $5 | $0.10* | model docs |
| Fable 5.2 | $8 | $40 | $0.20 | release notes, 2026-11-09 |

How the other rates were set:
- **Cache writes:** 1.25× input for 5-minute entries and 2× for 1-hour entries,
  taken per request from the transcript's own split.
- **Starred cache reads:** set to 0.1× input. The model docs consulted did not
  quote them.

## 2. The bill, by agent

Whole corpus, list-price equivalent: **$42,145**. Main sessions account for
$22,298 (53%) and subagents for $19,846 (47%).

| Agent | Runs | Total | Median / run | p90 / run | Main model(s) |
|---|---:|---:|---:|---:|---|
| Main session | 879 | $22,298 | $6.73 | $55.82 | Opus 5.5, Opus 5 |
| builder (Opus) | 860 | $6,564 | $4.48 | $17.44 | Opus 5 |
| builder-standard | 1,159 | $3,831 | $2.03 | $7.14 | Sonnet 5 → 5.5 |
| general-purpose | 1,216 | $3,273 | $1.66 | $6.25 | mixed |
| reviewer (QA) | 365 | $1,820 | $4.11 | $9.25 | Opus 5 |
| test-writer | 349 | $1,237 | $2.34 | $6.87 | Opus 5 |
| planner | 142 | $944 | $4.58 | $14.06 | Opus 5 |
| validator | 257 | $478 | $1.55 | $3.29 | Opus 5 |
| devil's advocate | 277 | $413 | $1.27 | $2.63 | Opus 5 |
| explore | 1,150 | $367 | $0.29 | $0.50 | Haiku 4.5 |
| builder-simple | 647 | $263 | $0.31 | $0.89 | Haiku 4.5 → 5.5 |
| advisor | 111 | $247 | $1.86 | $4.11 | Opus 5 |

What the table shows:
- **The main session is the biggest single line.** The main-session p90 of $56
  is the marathon sessions described in
  [token consumption](token-consumption.md#2-context-grows-and-never-shrinks).
- **Review is not cheap.** A QA audit costs about as much as an Opus build
  ($4.11 against $4.48 median), and it runs once per wave.
- **Unrouted work is a real line item.** $3,273 went to generic subagents that
  are not crew roles. Those runs get no tier routing and no charter.

## 3. Where an Opus builder run's money goes

The table splits the cost of 834 Opus builder runs, re-priced at Opus 5.5 rates
with 1-hour cache writes.

| Meter | Share of cost |
|---|---:|
| Cache reads | 52% |
| Cache writes | 36% |
| Output | 12% |
| Uncached input | ~0% |

Output is the only meter a "smarter, more concise" model changes directly. The
other 88% depends on how long the run lasts and how much context it carries.

## 4. Tier routing: the single biggest cost lever

The crew routes implementation by reasoning load across three tiers. These are
runs per month for each builder tier:

| Month | Opus | Sonnet | Haiku | Opus share |
|---|---:|---:|---:|---:|
| 2026-08 | 347 | 0 | 0 | 100% |
| 2026-09 | 332 | 256 | 158 | 45% |
| 2026-10 | 153 | 654 | 318 | 14% |
| 2026-11 (to the 14th) | 28 | 249 | 171 | 6% |

These are median costs per builder run:

| Tier and model | Runs | Median | Mean | Median requests |
|---|---:|---:|---:|---:|
| builder, Opus 5 | 802 | $4.63 | $7.90 | 49 |
| builder, Opus 5.5 | 32 | $3.82 | $5.41 | 44 |
| builder-standard, Sonnet 5 | 927 | $2.52 | $3.90 | 65 |
| builder-standard, Sonnet 5.5 | 228 | $0.58 | $0.89 | 20 |
| builder-simple, Haiku 4.5 | 474 | $0.42 | $0.52 | 32 |
| builder-simple, Haiku 5.5 | 166 | **$0.03** | $0.04 | 18 |

A Haiku 5.5 builder run costs about 1/150 of an Opus 5 run. The Sonnet 5.5 and
Haiku 5.5 runs are also much shorter, with 20 and 18 median requests against 65
and 32. **That is not a like-for-like model comparison.** Task mix and charter
changes moved at the same time; read it as what the tiers cost in practice.

**Routing has to be enforced, not just planned.** On 2026-09-01 the plan for one
session labelled its tasks simple or standard, and every implementer still went
to the Opus builder. Tier labels in a plan do nothing unless dispatch reads them.
Since then the orchestrator charter has said so in as many words: the expensive
tier is not the safe default, and over-tiering buys the same behaviour at a
higher price.

## 5. Model migrations, and what each one bought

| Change | Date | Price effect | What actually changed |
|---|---|---|---|
| Opus 4.8 → Opus 5 | 2026-08-22 | None ($5 / $25 both) | Adaptive thinking on by default: "the thinking default is the real win" |
| Opus 5 → 5.5 | 2026-10-30 | −20% per token | Default effort dropped to `medium`; pinned explicitly to keep behaviour |
| Sonnet 5 → 5.5 | 2026-10-30 | None | Effort levels recalibrated |
| Haiku 4.5 → 5.5 | 2026-10-30 | ~−90% per token | 1M context instead of 200K; "the biggest single win" |

The October migration had to make effort explicit, because moving to the 5.5
models would otherwise have lowered effort silently. The first plan tiered
builder effort (high/medium/low). The devil's-advocate agent rejected that, on
the grounds that the tiers must differ only in model ("effort is not a price
knob — it is a reasoning-depth knob"). All three builder tiers run at `high`.
The Sonnet support roles run at `medium` and explore runs at `low`.

## 6. When a stronger model does not pay

From [case study 01](01-a-stronger-builder-or-a-better-charter.md). These are
Opus builder runs re-priced at current rates:

| | Median | Mean | p90 |
|---|---:|---:|---:|
| Opus 5.5 | $2.92 | $4.61 | $9.81 |
| Same tokens on Fable 5.2 | $4.57 | $6.85 | — |

The case against a stronger builder:
- **Premium:** Fable 5.2 would cost about $2.24 more per run on the mean. That
  is before Fable's heavier thinking, which adds tokens on top.
- **Saving:** QA catches about one serious introduced bug per 13 builder runs,
  and each one costs a fix loop of one builder run plus a re-audit. A Fable
  builder that removed every one of those bugs would save well under $1 per run.
- **Measured difficulty:** across about 850 Opus builder runs, the number of
  blocks caused by difficulty was zero.

The same money bought a charter change instead. A one-step "map what you touch"
instruction avoided one of three replayed bugs at −11% to +15% per-run cost.

## 7. Cheap levers that held up

| Lever | Measured effect | Source |
|---|---|---|
| Per-agent tool allowlists | Starting context −85.9% (1.19M → 168k summed over 15 agents) | [case study 03](03-the-prompt-was-not-the-problem.md) |
| Path-scoped rule files in a product repo | ~−28k tokens per agent request | case study 03 |
| Browser pane off for the main session | −9.4k tokens (−8.7%) per request | case study 03 |
| Spawning delivery-sized work as fresh sessions | Avoids paying for 200k+ of carried context; above 200k sat 49% of context tokens | [token consumption](token-consumption.md) |
| Haiku 5.5 for mechanical builds | $0.03 median per run, no false `BLOCKED` in the replay control | case study 01 |

## 8. Levers that were measured and rejected

| Proposal | Why not |
|---|---|
| Slicing the dispatch prompt per agent | The prompt is 0.4–0.5% of subagent input |
| Orchestrator pastes code snippets into dispatches | 2.6–3.8× worse once the orchestrator's carry is counted |
| Symbol-level reads | 21–35% worse than what agents already read |
| More caching | About 97–98% of input is already cache reads |
| Lower effort on cheaper builder tiers | It changes reasoning depth, not just price |
| A fourth builder tier on Fable 5.2 | See section 6 |

## 9. Cost of the evaluation itself

| Eval | Spend |
|---|---|
| Replay pilot: 3 cases × 2 arms, plus smoke runs | ≈ $13 |
| Charter smoke check: 4 runs, 1 invalid run, 1 retry | ≈ $13.80 |
| Planned cross-model "I don't know" eval: 30 cases, 4 vendors, 2 judges | ≈ $20–25 estimated, $4 smoke run, hard cap $40 |
| Full Fable replay, as first scoped: 108 runs | ≈ $600, up to ~$1,000. Not run. |

The pilot was enough to make the decision. Scoping the full eval first, with a
break-even calculation in the plan, kept about $600 from being spent on a
question the measurements had already answered.

## 10. A CI review that ran out of budget

A headless review workflow ran with a default of 30 turns. Each inline finding
used 2 turns, and saving the review's learning took about 7 more at the end. Any
review with six or more findings therefore ran out of turns before it saved what
it learned.

The fix moved that write into a single turn before the comments are posted, and
handed the rest to a plain shell step. The same session also cut spend on runs
that are not worth reviewing:
- skip drafts, bot authors and release PRs;
- let a newer push cancel the older review;
- optionally, review only after CI is green.

## Method

Per-run cost comes from each transcript's own usage meters:
- **Counting:** each unique message is counted once, with the maximum of each
  field across its records.
- **Pricing:** each message is priced at its own model's rates, with cache writes
  split by TTL as the transcript records them.
- **Output:** output counts are a lower bound for some subagent runs (see
  [token consumption](token-consumption.md#7-the-transcript-counting-trap)).
- **Telemetry figures:** the two product-run figures in case study 03 come from
  OpenTelemetry spans instead and are labelled as such.
