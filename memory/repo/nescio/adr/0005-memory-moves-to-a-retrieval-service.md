---
name: nescio-adr-0005-memory-moves-to-a-retrieval-service
description: Semantic retrieval is adopted as a separate HTTP service that becomes the system of record; notes are indexed by their human-written summary rather than chunked, and the deterministic machinery — precedence, hash dedup, watermarks, ledger — stays exact and authoritative.
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

### 3. Notes are indexed by their summary, not by chunking their bodies

Embed `name + description` — roughly 270 chars of purpose-written human summary —
as the retrieval key, store the note alongside it, and return the **whole note** as
the payload. `type` becomes a filter facet.

The default alternative, the service's current behaviour, is a 1000/200 sliding
window over the body. On this corpus that produces about 2,431 vectors averaging
5.7 per note, each a mid-argument slice of a curated note, cut at an offset rather
than a boundary — because the median note has no headings. Only 6 of 424 notes fit
a single 1000-char chunk.

Summary-indexing gives 424 vectors instead of ~2,431, 424 embedding calls instead
of ~2,431 against a service that calls the embedder serially with no batching, and
a retrieval unit that is the unit a human actually approved. Vector storage is
irrelevant either way (651 KB at 384 dimensions, fp32).

This is a different ingest contract from the one the service has today: it must
accept a structured note and store the document, not just raw text.

### 4. 384 dimensions is the model's capacity, and the schema is pinned to it

`vector(384)` matches what `qwen3-embedding:0.6b` produces; it is not a truncation
with quality left on the table. Changing it is a breaking migration requiring a
full re-embed, so a change of embedding model is a schema decision, not a config
decision.

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
| Chunk note bodies (service default) | Rejected on measurement: no heading boundaries, 5.7 fragments per curated note, 6× the embedding calls. |
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
- **Ingest is serial.** One embedder round-trip per vector, no batching, no retry.
  The largest note in the corpus is 109,009 chars; under body-chunking that is ~136
  sequential calls where one network flake fails the request. Summary-indexing
  reduces this to one call per note, which is a second reason for Decision 3.
- **The gain is real and partly new.** Two capabilities arrive that files could not
  provide: near-duplicate detection at promotion time (today's dedup is an exact
  hash, so a re-worded learning lands twice), and cross-repo recurrence over 308
  repo-scoped notes, which #10 has wanted and had no mechanism for.

**To re-verify.** Whether the summary-indexed design actually retrieves better than
body chunking on this corpus is asserted here from the corpus shape, not measured
against queries — no retrieval evaluation exists yet. Build one before the ingest
contract hardens. Also re-check the two uninstrumented ADR 0002 triggers: if the
index really has stopped scaling, that is evidence worth having rather than
inferring.
