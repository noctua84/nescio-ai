# Agent evaluation and optimization: case studies

These are notes and hard data on how the Nescio crew was measured, evaluated and
tuned, gathered as raw material for articles. Each file stands on its own.

| File | What it covers |
|---|---|
| [01 — A stronger builder, or a better charter?](01-a-stronger-builder-or-a-better-charter.md) | Whether to add a Fable 5.2 builder tier. Two transcript measurements, a replay eval with hidden oracles, the charter fixes it led to, and the audit of those fixes. |
| [02 — Checks that pass for the wrong reason](02-checks-that-pass-for-the-wrong-reason.md) | The lints and tests that grade charter text, and eight of them that were green for the wrong reason. |
| [03 — The prompt was not the problem](03-the-prompt-was-not-the-problem.md) | Where subagent tokens actually go, three optimizations ruled out by measurement, and the one that cut starting context by 86%. |
| [Token consumption](token-consumption.md) | Corpus-wide token data: cache reads against output, context growth, per-agent profiles, and the transcript-counting trap. |
| [Cost-effectiveness](cost-effectiveness.md) | List-price cost per agent and tier, routing over time, model migrations, levers that held and levers rejected, and what the evals cost. |

## Threads that run through all of them

1. **Measure the premise first.**
   - "We need a stronger model" predicted difficulty blocks. There were none in
     about 850 Opus runs.
   - "Slice the dispatch prompt" targeted 0.5% of the bill.
2. **Most failures were instruction failures, not model failures.**
   - A builder switched off a test that already pinned its bug.
   - A charter contained a git command that silently checked out the wrong
     commit.
   - A rule lived in charters that the agents editing the crew never read.
3. **The evaluators need evaluating.**
   - Phrase pins, lints, plan checks and the orchestrator's own scripts were all
     found green for the wrong reason at least once.
   - "Prove it bites" became a standing acceptance criterion.
4. **Cost is re-reading, not writing.**
   - About 97% of input tokens are cache reads, and output is 12–13% of spend.
   - The levers that worked shorten what is re-sent: starting context, session
     length and tier routing.
5. **The measuring instruments were wrong too.**
   - Duplicate transcript records inflate naive totals about 3×.
   - First-record counting undercounts output by about a fifth.
   - One early scan missed the subagent transcripts entirely.

## Ground rules for using this material

- **Privacy.** Product codebases and the private instance repository are not
  named; their cases are generalised. Keep it that way in derived articles, and
  run `python scripts/scrub_check.py` before publishing.
- **Prices.** All dollar figures are API list-price equivalents. The work ran on
  a flat subscription, so the figures compare choices; they are not invoices.
  [cost-effectiveness.md](cost-effectiveness.md#1-prices-used) lists the rates
  and which of them were assumed.
- **Sample sizes.** The corpus-wide figures are large, about 7,000 subagent runs.
  The evals are small:
  - 3 replay cases with one run each;
  - n=2 effort probes;
  - single-run context toggles.

  Treat them as direction, not proof, and say so where they are cited.
- **Dates.** Model names, prices and Claude Code behaviour are as of the date in
  each file.

## Related

- [What the crew caught, and what it cost the orchestrator to learn it](../orchestration-failure-modes.md)
- [Scope: purpose versus topic](../scope-purpose-versus-topic.md)
- `docs/usage/`: the usage scanner from the token-consumption work
