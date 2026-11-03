---
name: the 2026-10-28 harvest produced nothing, and why
description: the over-tooling failure mode of /harvest-memory, recorded by the session that committed it
type: feedback
---
<!-- promoted:begin -->
A harvest ran on 2026-10-28, executed the full ten-step apparatus — staging manifest, read declaration, watermark, receipt, PR gate — and **promoted nothing**. Branch left at `origin/main`, working tree empty, no ledger written, watermark unmoved at 2026-10-23. The records it read stayed un-harvested, which is the one thing the step ordering is designed to guarantee, so nothing was lost.

The diagnosis, from the session that made the mistake: it ran the machinery first and then asked a three-option question about repository topology. That ordering is the error. The question was answerable from the repo (`memory/repo/<name>/` is repo-scoped by its own convention, settled in ADR 0005's reasoning), and it should have been settled during the read, not raised after the pipeline had been built.

What to take from it:

- **The deliverable of a harvest is a small set of curated notes, not a completed pipeline.** The scripts are bookkeeping around a judgement call. If the judgement has not been made, running the scripts produces an audit trail of nothing.
- **Settle the destination while reading the sources**, from the repo's existing filing convention. Do not reach the manifest step still unsure where a note belongs — and if you genuinely are unsure, declare the nomination `unrouted` rather than stalling the whole pass or guessing a target.
- The ordering guardrail held: because the watermark is stamped **last**, a failed harvest is re-runnable rather than lossy. Trust that and stop; do not stamp to "tidy up".

Evidence this was never written down: before 2026-11-02 the repo had no `memory/learning-log.md` at all, so no harvest had ever promoted a note into it.
[Source: empirical — 2026-11-01]
<!-- promoted:end -->
