---
name: nescio-adr-0002-defer-semantic-retrieval
description: The learning loop keeps curated-index retrieval; no vector database or graph framework, because the corpus is empty and the binding constraint is the write path, not retrieval.
type: adr
status: proposed
---

# ADR 0002: Defer semantic retrieval for the learning loop

## Status

Proposed.

## Context

The question raised was whether the learning loop — `/harvest-memory` →
`scripts/promote_learnings.py` → `memory/` — would benefit from LangGraph or a
vector database. Investigating it surfaced a finding that reframes the question.

### The corpus is empty

`memory/` holds 7 files, ~150 lines, ~6KB. `context/`, `feedback/`, `people/`
and `projects/` are empty but for `.gitkeep`. `concepts/` and `repo/` contain
only `EXAMPLE` templates. Across every ref in the repo, the complete set of
files ever added under `memory/` is: `CONVENTIONS.md`, `glossary.md`, four
`.gitkeep`s, and five `EXAMPLE` files.

### The loop has never completed a promotion

`memory/learning-log.md` — the dedup ledger `promote_learnings.py` appends to on
every successful promotion — **does not exist, and never has on any branch.**
Meanwhile the machine-local trail holds **3,002 records across 121 repos**, and
105 `.watermark` files are all stamped to the same instant,
`2026-08-20T11:30:14Z`.

So a harvest pass stamped every trail as reviewed and promoted nothing. The
retention rule in `hooks/record_stop.py:293` drops a record only when it is both
older than `RETENTION_DAYS = 14` *and* at or below the watermark — logic that is
careful and correct in isolation, but whose safety property ("everything at or
below the watermark has been distilled into `memory/`") is currently false.

### The retrieval model is already semantic

`scripts/wiki_index.py` regenerates each folder's `MEMORY.md` from note
frontmatter as `- [name](file.md) — description`, recomputed from disk after
every promotion so it cannot drift. Agents (`agents/explore.md`,
`agents/reviewer.md`) read `memory/repo/<repo>/` on demand; memory is
deliberately *not* preloaded into the always-on prompt.

The matching is therefore done by a frontier model reading curated one-line
descriptions, rather than by cosine similarity over embedded chunks. A vector
store would not *add* semantic retrieval — it would substitute a weaker matcher
for a stronger one, and charge an embedding pipeline, a cache-staleness problem,
and this repo's first runtime dependency for it.

Related ADRs: **ADR 0001** (no agent frameworks; dependency-free install path).
This ADR is consistent with it and narrows it to the memory subsystem — it does
not contradict or supersede it. A vector database would violate 0001's
dependency rule, so adopting one later requires amending both.

## Decision

**The learning loop keeps curated-index retrieval. No vector database, no graph
framework.**

1. **LangGraph is rejected.** Note the argument is *not* that the loop is
   stateless — per ADR 0001, the `.watermark` cursor is genuine durable
   checkpointing, and `harvest_nudge.py` is a genuine resume signal. The
   argument is that this state spans Claude Code sessions, machines, and git
   history, while a LangGraph checkpointer attaches to one long-lived Python
   process that does not exist here. The loop itself (capture → harvest →
   promote) is additionally linear, with no branching to express as a graph.
2. **A vector database is deferred, not refused on principle.** It is the wrong
   tool *at this scale*, and the precondition for evaluating it honestly — a
   corpus produced by a loop that actually runs — does not yet exist.
3. **If retrieval later becomes the real bottleneck, the first escalation is
   full-text search, not embeddings.** `sqlite3` ships in the stdlib with FTS5
   compiled in (verified against SQLite 3.50.4), so a `search_memory.py` over
   note bodies costs zero dependencies and preserves ADR 0001.
4. **Named revisit triggers.** Reopen this ADR when *any* holds:
   - any single `memory/` directory exceeds ~100 notes, or the corpus exceeds
     ~500, such that a `MEMORY.md` index no longer fits comfortably in context;
   - a harvest pass reports it cannot determine where to file a learning;
   - agents are observed grepping past the index because description-routing
     stopped resolving.

## Options considered

| Option | Verdict |
|---|---|
| **Curated `MEMORY.md` index** (chosen) | Recomputed from disk, zero deps, LLM does the matching. |
| Vector DB now | Rejected — nothing to embed; weaker matcher; first runtime dependency. |
| LangGraph for the loop | Rejected — state spans process boundaries a checkpointer cannot. |
| SQLite FTS5 | Held in reserve as the zero-dependency escalation (Decision 3). |

**Do nothing at all** (status quo including the write-path gap) is rejected
separately: the corpus emptiness is itself the finding, and is tracked as work
rather than accepted as a decision.

A property worth preserving explicitly: `CONVENTIONS.md`'s `concepts/` mechanism
lifts a learning recurring in ≥2 repos into a shared invariant with
`corroboration: <N>`, and forks rather than merges on contradiction
(`> [!contradiction]`). A similarity search structurally **cannot** do this — it
returns both chunks and leaves the model to reconcile them. Deterministic
contradiction resolution (`user override > empirical > agent inference`, ties to
the newer date) is a stronger guarantee than ranked retrieval, and is the thing a
vector store would quietly erode.

## Consequences

- Retrieval stays inspectable and diff-able in git. There is no opaque index to
  rebuild, no embedding model version to pin, no cache to invalidate.
- The decision is falsifiable: three concrete triggers are recorded above rather
  than leaving "when it feels slow" to judgement.
- **Cost:** curated-index routing depends on `description` frontmatter being
  written well. A lazily-described note becomes effectively unfindable, and
  nothing detects that — the index will happily list a useless one-liner.
- **Cost:** deferring means that when the corpus *does* grow past the triggers,
  the migration happens under pressure rather than ahead of need.
- **Risk — the finding this ADR is downstream of:** step 9 of the harvest
  (`mark_harvested.py`, global by design) can advance the watermark for all 121
  trails without step 8 (`promote_learnings.py`) having promoted anything. There
  is no invariant tying the stamp to a successful promotion. Until that is
  closed, harvested-but-undistilled records age out at 14 days. **This, not
  retrieval, is the binding constraint on the learning loop, and it must be
  addressed before any retrieval work is considered.**
- **To re-verify:** whether the 2026-08-20 stamp came from a real harvest that
  found nothing promotable, or from a partial/test run. That distinction decides
  whether the gap is a usability problem or a correctness bug.

[Source: empirical — 2026-08-26]
