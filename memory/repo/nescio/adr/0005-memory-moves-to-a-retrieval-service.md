---
name: nescio-adr-0005-memory-moves-to-a-retrieval-service
description: Semantic retrieval is adopted as a separate HTTP service that becomes the system of record; retrieval returns chunked passages rather than whole notes, and the deterministic machinery — precedence, hash dedup, watermarks, ledger — stays exact and authoritative.
type: adr
status: proposed
---

# ADR 0005: Adopt semantic retrieval as a service, and keep the deterministic layer exact

## Status

Proposed. **Supersedes [ADR 0002](0002-defer-semantic-retrieval-for-memory.md).**
That ADR's decision — defer the vector database — is withdrawn. Its *reasoning*
largely survives and is the reason this ADR is narrow: ADR 0002 was right that a
similarity score cannot express the contradiction precedence, and that guarantee
is preserved here rather than traded away.

Builds on [ADR 0003](0003-learning-loop-write-path-verified.md), which already
corrected ADR 0002's "the corpus is empty" evidence, and does not disturb
[ADR 0001](0001-no-agent-frameworks-in-nescio.md) — see *Decision 2*.

Tracked as [#160](https://github.com/noctua84/nescio-ai/issues/160).

**Decision 3 was withdrawn on 2026-10-03 and Decision 4 corrected on the same day**,
both before implementation. The rest of the ADR stands. See those sections.

## Context

`nescio-memory` exists: a separate repository at v0.3.1, explicitly a proof of
concept. PostgreSQL with `pgvector`, embeddings from `qwen3-embedding:0.6b` at 384
dimensions, three endpoints (`ingest`, `search`, `health`), API-key tenancy with
every row scoped by `client_name`. The stated intent is that it **replaces
`memory/` as the system of record** once it is stable and deployed.

ADR 0002 rejected exactly this — *"Vector DB now | Rejected — nothing to embed;
weaker matcher; first runtime dependency"* — and named four revisit triggers.
Measured against the live `ai-os` brain on 2026-10-02, two are measurable and
neither has fired:

| Trigger | Measured | Fired |
|---|---|---|
| any single `memory/` directory > ~100 notes | 65 (`repo/soulsgate-payment`) | no |
| corpus > ~500 notes | **424** | no — 85% of the way |
| a harvest cannot determine where to file a learning | not instrumented | unknowable |
| agents observed grepping past the index | not instrumented | unknowable |

> **Amendment, 2026-10-03.** Both halves of that table are now out of date, and the
> correction matters because it is the evidence this ADR said it lacked.
>
> All four triggers are instrumented, by `scripts/check_memory_triggers.py` (#168,
> landed in #170). Run it with `--memory-root <brain>/memory`. Re-measured with the
> tool rather than by hand:
>
> | Trigger | Verdict | Measured |
> |---|---|---|
> | directory > ~100 notes | clear | **80** (`repo/soulsgate-ui`) — **80%** of the trigger |
> | corpus > ~500 notes | clear | **427** — **85%** |
> | harvest cannot route a learning | **unknown** | no tally yet — absence is not zero |
> | agents grepping past the index | **unknown** | measured, but uncalibrated, so it cannot fire |
>
> Three corrections to what this ADR originally recorded:
>
> 1. **The directory figure was stale, not wrong.** Commit `4fa3aee` (2026-10-02)
>    converged `memory/repo/ui/` into `memory/repo/soulsgate-ui/` after the original
>    measurement, taking it from 49 to 80 and moving the lead off
>    `soulsgate-payment`. The count was correct when taken.
> 2. **The distribution matters more than the leader.** Three directories now sit
>    near the line — 80, 73 and 68 — so this is a corpus-wide trend rather than one
>    outlier, which is a stronger signal than the single figure above suggests.
> 3. **Two triggers are instrumented but still cannot fire**, for different reasons.
>    T3 has no tally because no harvest has declared an unrouted nomination since the
>    instrument landed, and the checker reports that as `unknown` precisely because
>    absence cannot distinguish "everything routed" from "never recorded". T4 is
>    measured — 86% of sessions searched `memory/` at all, 28% did so *after*
>    consulting an index, which is the causal reading the trigger's wording actually
>    requires — but no threshold has been chosen, so it reports and does not judge.
>    Choosing that number is a decision, not an implementation task.
>
> **What this does to the decision below.** It narrows the gap rather than closing
> it. "Deliberately ahead of its own trigger" was accurate when written and is now
> only just true: the corpus is 85% of the way, the largest directory 80%, and two
> more directories are following it up. The reasoning in *Decision 1* is unchanged
> and better supported — this is no longer inference about where the corpus is
> heading. Nothing in `## Decision` is revised by this amendment.
>
> One caution for anyone calibrating against the transcript corpus (T4, and #70):
> it grew from 3,118 files / 1,645 MB to 5,103 files / 4,116 MB inside a single day.
> Any constant derived from it goes stale almost immediately; measure at use.

Corpus growth is bursty because it advances in harvest runs rather than
continuously: 151 notes on 2026-08-01, 365 on 2026-09-01, 424 on 2026-10-02. The
500-note trigger is months away at the slow end and weeks at the fast end.

So this ADR is deliberately **ahead of its own trigger**. That is the decision, not
an oversight: a memory service with migration, an egress path and a replacement
review gate is not something that can be stood up in the window between noticing
the index has stopped scaling and needing it to work. Two of the four triggers
cannot be observed at all, which removes any possibility of waiting for a clean
signal.

The corpus itself constrains the design more than the trigger does. Measured over
424 notes, 1.86 MB:

- median note 2,306 chars, p90 5,430, max 109,009;
- **median markdown headings per note: 0** (p90 5) — most notes are flat prose with
  no structural boundary to split on;
- 406 of 424 carry both `name` (median 62 chars) and `description` (median 206,
  p90 344), authored by a human during harvest;
- `type` on all 406 — convention 94, architecture 67, context 59, regression 50,
  project 47, feedback 42.

## Decision

### 1. Semantic retrieval is adopted

The deferral in ADR 0002 is withdrawn. Retrieval by meaning becomes a supported
capability of the learning loop, and `nescio-memory` is the implementation.

### 2. It is a separate service reached over HTTP, and that is load-bearing

ADR 0001 keeps the framework's runtime install path stdlib-only and
dependency-free. An in-process embedding model would have broken that — roughly
530 MB of wheels for `sentence-transformers` and torch. A network call to a service
in another repository does not. The service boundary is what makes this ADR
compatible with ADR 0001 rather than a second reversal, and it should not be
collapsed into the framework later for convenience.

### 3. ~~Notes are indexed by their summary, not by chunking their bodies~~ — WITHDRAWN

> **Withdrawn 2026-10-03, before implementation.** Replaced by: **chunked passages
> are the retrieval contract.** A search returns the spans that bear on the query,
> each carrying enough identity to name the note it came from, and the caller
> assembles a context out of them. The note stops being the retrieval unit. The
> withdrawn text is preserved at the end of this section, because why it was wrong
> is more useful than what it said.

**This is settled by intent, not by measurement.** Decision 3's payload was the whole
note. A store that answers with whole documents over HTTP is a semantic file finder
— `memory/` with a network hop in front of it — and that is not
retrieval-augmented generation. A RAG store exists to put relevant text into a
generation context, and a 109,419-char document is not a context. Deciding this by
experiment was a category error: I went looking for evidence to settle a question
that the service's purpose already answered.

**The evaluation built to settle it could not have settled it.** The harness
(`nescio-memory` [#34](https://github.com/noctua84/nescio-memory/pull/34)) scores
*did the expected note appear in the top k*, which presupposes that the note is the
retrieval unit; it is structurally unable to score passage retrieval. Its
`mean_distinct_notes_at_k` diagnostic — which I read as evidence against chunking,
because chunking spends result slots on repeats of one note — is only a cost under
note-level retrieval. Under passage retrieval, several passages from one note is the
intended behaviour. The metric encoded its own conclusion.

**It nonetheless pointed the same way**, which is worth recording. On the 14-note
synthetic corpus at 1024 dimensions, MRR@10 by query class:

| query class | `chunk` | `summary` | `hybrid` |
|---|---|---|---|
| `topic` — restates the note's subject (n=6) | 1.000 | 1.000 | 1.000 |
| `buried` — a fact present once in the body (n=8) | 0.938 | **1.000** | 0.938 |
| `oblique` — names a symptom, not the mechanism (n=6) | **0.917** | 0.500 | 0.733 |

Summary-indexing ties where the query restates the summary, wins where a buried fact
is still reachable by topic, and collapses where the query names a symptom and not its
mechanism — one note missed entirely, another at rank 6. That is the RAG case
asserting itself through a metric built against it. Corroboration, not grounds:
fourteen hand-authored notes and four discriminating queries decide nothing. The
real-corpus run was abandoned once the question stopped being empirical.

**`hybrid` is rejected too, and that one is a measurement result.** Both unit types in
one shared cosine ranking was strictly dominated — it tied `chunk` on two classes
and lost to it on the third (0.733 against 0.917) while costing five units per note.
Neither route was dead weight (`summary` reached the note first on 14 of 20 queries,
`chunk` on 6), so the fault is the shared ranking itself: it lets the weaker unit type
take slots the stronger one would have won. "Store both and sort by distance" is not a
design.

**A per-note summary vector still has a job, and it is not retrieval.** The two
capabilities this ADR claims as genuinely new — near-duplicate detection at
promotion time, and cross-repo recurrence across the repo-scoped notes that
[#10](https://github.com/noctua84/nescio-ai/issues/10) wants — are questions about
*note identity*, and both want exactly one vector per note. That is a second index
with a different job, queried by the deterministic layer rather than by search. It
must not be ranked against passages.

#### The original rejection measured the wrong population

Chunking was rejected on *"the median note has no headings, so a window cuts
mid-argument"*. Re-measured against the live brain on 2026-10-03 — 440 markdown
files, of which 13 are generated `MEMORY.md` indexes, leaving **427 content notes**:

| | notes | share | median chars | p90 | max |
|---|---|---|---|---|---|
| promotion-owned (`<!-- promoted:begin -->` block) | 91 | 21% | **1,775** | 3,053 | **7,646** |
| hand-written / pre-pipeline | 336 | 79% | — | — | — |
| whole notes | 427 | 100% | 2,333 | 5,311 | **109,419** |

The learning loop's own output is well shaped. A promoted block is one nomination
body, bounded in practice at 7,646 chars, occupying a median 82% of the note that
holds it. The 109,419-char outlier and the missing headings belong to the 79% the
pipeline never wrote. **This ADR measured the whole corpus and attributed its shape
to the learning loop.**

#### Headings were not the only boundary, and paragraphs are the real one

Re-measured over the 423 notes excluding generated indexes and top-level documents:

- **4,438 paragraphs**, median **268** chars, p90 787, max 8,136. Only **6.1%** exceed
  1,000 chars, so a paragraph-first chunker needs a hard-split fallback for one
  paragraph in sixteen and for no others.
- A 1000/200 sliding window produces **2,198 chunks**, of which **98.2% begin or end
  mid-paragraph**. That is the concrete cost of ignoring the structure that is there.
- Headings: median 0 confirmed, but **44% of notes carry at least one**, and the notes
  above p90 — precisely the ones where chunking matters — carry a median of 9.
  The long tail is the *structured* part of the corpus, not the formless part.

So the premise was too narrow rather than wrong. Markdown headings are genuinely
absent from most notes; paragraph boundaries are not, and they are a usable semantic
boundary that the corpus supplies for free.

Two cautions on the above. Fewer, better-aligned chunks is a **boundary-quality**
result, not a retrieval result — nothing here measures whether paragraph-aligned
chunks retrieve better, and that remains unmeasured. And the measurement is of today's
corpus, 79% of which predates the pipeline; as the promoted share grows the input
shape shifts toward the tighter distribution in the table above.

#### The finding that outranks all of this

Promotion is lossy by construction, and the vector store is what can fix it.
`_compose_note` (`scripts/promote_learnings.py:324`) **replaces** the managed block
rather than appending to it — `rest[:b] + new_block + rest[e:]` — and the
overwrite path (`:621-639`) resolves a second nomination for the same target by either
overwriting the incumbent or discarding the incoming one. `_prune_target_lines`
(`:386`) then removes the superseded hash from the ledger. The displaced learning
survives only in git history.

That is not a defect in the file layer; it is forced by it. **One file can hold one
answer.** A vector store is not constrained that way: every nomination can persist as
its own row carrying `source`, `date`, `type`, `scope`, `target` and its 12-hex body
hash, with retrieval returning all of them and the deterministic precedence layer of
*Decision 5* adjudicating at **read** time instead of destroying at **write** time.
Precedence stays exact — the guarantee ADR 0002 was right about is untouched —
and the corpus stops shrinking every time two sessions learn different things about
the same target.

This is the strongest argument for the migration, and this ADR failed to make it.
Tracked for design under [#160](https://github.com/noctua84/nescio-ai/issues/160).

#### The withdrawn text, as originally accepted

> Embed `name + description` — roughly 270 chars of purpose-written human summary
> — as the retrieval key, store the note alongside it, and return the **whole
> note** as the payload. `type` becomes a filter facet.
>
> The default alternative, the service's current behaviour, is a 1000/200 sliding
> window over the body. On this corpus that produces about 2,431 vectors averaging
> 5.7 per note, each a mid-argument slice of a curated note, cut at an offset rather
> than a boundary — because the median note has no headings. Only 6 of 424 notes
> fit a single 1000-char chunk.
>
> Summary-indexing gives 424 vectors instead of ~2,431, 424 embedding calls instead
> of ~2,431 against a service that calls the embedder serially with no batching, and
> a retrieval unit that is the unit a human actually approved. Vector storage is
> irrelevant either way (651 KB at 384 dimensions, fp32).
>
> This is a different ingest contract from the one the service has today: it must
> accept a structured note and store the document, not just raw text.

### 4. The vector width is the model's native width, and the schema is pinned to it

`vector(1024)` matches what `qwen3-embedding:0.6b` produces. Changing it is a breaking
migration requiring a full re-embed, so a change of embedding model is a schema
decision, not a config decision.

> **Corrected 2026-10-03.** This decision originally read *"384 dimensions is the
> model's capacity"* and asserted that `vector(384)` was *"not a truncation with
> quality left on the table"*. Both halves were false. The model emits **1024**, so
> the service shipped a schema that could not store a single vector its own embedder
> produced — `nescio-memory` was inert by default until
> [#38](https://github.com/noctua84/nescio-memory/pull/38) set the dimension to 1024.
> I recorded the figure from a remark in conversation without making one HTTP call to
> check it, having flagged it as an open question earlier and then dropped the flag.
> The decision's *shape* survives: the width is pinned to the model, and changing it
> is a migration rather than a config edit.
>
> One correction to the reasoning rather than the number: truncation **is** available.
> `qwen3-embedding` supports Matryoshka truncation through the `dimensions` parameter
> of Ollama's `/api/embed`. The service calls the legacy `/api/embeddings` endpoint,
> which ignores it, so a narrower vector is currently *unreachable* rather than
> unavailable. If vector width ever becomes a cost question, that is the lever.

### 5. The deterministic layer is not replaced, and must not be approximated

These stay exact and authoritative. A similarity score is the wrong shape for every
one of them:

- **Contradiction precedence** is a total order in code —
  `{"user override": 3, "empirical": 2, "agent inference": 1}`
  (`scripts/_learning_common.py:36`), ties broken by the newer date, overwrite only
  on strictly higher rank or equal rank and newer. This is the specific guarantee
  ADR 0002 said ranked retrieval structurally cannot provide, and it was right.
- **Content-hash dedup** — exact 12-hex SHA-256 of the nomination body against the
  ledger.
- **Harvest watermarking** — exact max timestamp per declared trail (ADR 0003).
- **The promotion ledger** — append-only, ordered, durable; its line cap was retired
  precisely to keep full history.
- **Provenance tagging** — exactly one provenance line per note.

Vectors may *find a candidate*; the rules above decide what happens to it. Retrieval
ranks, it does not adjudicate.

### 6. Absence stays distinguishable from agreement

Mirroring ADR 0004's discipline: an unreachable service, an empty result and a
below-threshold match are three different states, and none of them may be rendered
as a confident answer. A degraded retrieval path returns "unknown", never "nothing
relevant exists".

## Options considered

| Option | Verdict |
|---|---|
| **Retrieval service as the record** (chosen) | Matches the stated intent; requires rebuilding four properties git provided free. |
| Retrieval index *beside* the files, markdown stays the record | Strong option, rejected on intent. Would have kept the review gate, distribution and egress for nothing, reducing the work to ingest plus cache invalidation. Worth revisiting if the rebuild stalls. |
| Keep deferring until a trigger fires | Rejected. Two triggers are uninstrumented, and the lead time for migration plus a replacement review gate exceeds the warning the remaining triggers would give. |
| **Chunked passages as the retrieval unit** | **Chosen 2026-10-03** — see Decision 3. Originally rejected on a measurement of the whole corpus, 79% of which the learning loop never wrote. The cost figures in that rejection stand; the rejection does not. |
| Summary-indexed whole notes | Rejected on intent — Decision 3, withdrawn. Returning whole documents is a semantic file finder, not a RAG store. Retained for note-level identity work only. |
| Both unit types in one cosine ranking (`hybrid`) | Rejected on measurement: strictly dominated by `chunk`, at five units per note. |
| In-process embedding model | Rejected — violates ADR 0001. |

## Consequences

Four properties are free while memory is files in git. None transfer, and all are
now work rather than guarantees:

1. **The review gate disappears.** `commands/harvest-memory.md` states it plainly —
   *"you review each item before it's committed."* Human-gated promotion is
   implemented *by* git review of a diff. A database has neither, so the defining
   property of the learning loop has to be rebuilt from nothing.
2. **Distribution becomes an operation.** `install.py` carries
   `LINKS = [("memory", "memory")]`; today a brain gets memory by symlink. Replacing
   that means a deployment, credentials and network reachability per instance, and
   shared tenancy makes every downstream brain depend on one service's uptime.
3. **Correction becomes impossible before it becomes easy.** There is no `UPDATE`
   statement anywhere in the service; rows are inserted or deleted, and a learning
   can only be changed by re-ingesting its whole file.
4. **There is currently no way out.** No export, no dump, no bulk read. 424 curated
   notes would go in and return five at a time through semantic search. This is the
   most serious gap and the first to close — until it does, the service is a
   one-way door.

Further costs and risks:

- **The record moves out of version control.** History, blame, diffable correction
  and offline readability are lost unless deliberately rebuilt.
- **A proof of concept becomes a dependency.** v0.3.1 has no error handling for
  embedder or database failure (both surface as 500), no retry or batching on
  ingest, no rate limiting, and no structured audit of who ingested what.
- **Ingest is serial, and chunking multiplies the cost.** One embedder round-trip per
  vector, no batching, no retry. Withdrawing Decision 3 removes the mitigation that
  decision provided, so batching and retry on the ingest path move from nice-to-have
  to required. Measured while running the evaluation: ~3,000 serial calls take roughly
  ninety minutes against a local Ollama at `NUM_PARALLEL:1`, and before a retry was
  added a single 500 in that window discarded the entire run.
- **The gain is real and partly new.** Two capabilities arrive that files could not
  provide: near-duplicate detection at promotion time (today's dedup is an exact
  hash, so a re-worded learning lands twice), and cross-repo recurrence over 308
  repo-scoped notes, which #10 has wanted and had no mechanism for.

**To re-verify.** The retrieval evaluation this section called for was built
(`nescio-memory` [#34](https://github.com/noctua84/nescio-memory/pull/34)) and is what
withdrew Decision 3 — but its metric scores note-level retrieval and must be
replaced with passage-level relevance before it can evaluate the design that replaced
it. The thirty hand-labelled queries over the live brain survive that change; the
scoring does not. Two things are still unmeasured and neither should be guessed at:
whether paragraph-aligned chunks actually *retrieve* better than offset-aligned ones,
and how much recall the production path loses to HNSW approximation plus the
`client_name` post-filter, which the in-memory exact-scan harness cannot see. Nothing
should harden the ingest contract until the first of those lands.

The four ADR 0002 triggers are now instrumented — see the amendment above. T4
reports without judging, because no threshold has been chosen; that remains a decision
rather than an implementation task.
