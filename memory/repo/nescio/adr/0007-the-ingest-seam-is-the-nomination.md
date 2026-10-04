---
name: nescio-adr-0007-the-ingest-seam-is-the-nomination
description: The memory service ingests nominations rather than committed notes, and a nomination must carry its learnings as addressable units instead of a merged note body; the chunking strategy is a consequence of that seam rather than an independent choice, and the harvest instruction to update a note in place is what has to change.
type: adr
status: proposed
---

# ADR 0007: The ingest seam is the nomination, not the note

## Status

Proposed. Supersedes nothing.

**Builds on [ADR 0005](0005-memory-moves-to-a-retrieval-service.md)**, whose
*Decision 3* was withdrawn on 2026-10-03 in favour of chunked passages. That
withdrawal settled *what retrieval returns*. It left open *what gets ingested*, and
ADR 0005 assumed throughout that the answer was the committed note. This ADR says it
is not.

**Preserves [ADR 0005](0005-memory-moves-to-a-retrieval-service.md) Decision 5** —
contradiction precedence, hash dedup, watermarks, the ledger and provenance stay
exact — and extends it: precedence moves from a destructive write-time rule to a
read-time one. See *Decision 4*.

**Does not disturb [ADR 0001](0001-no-agent-frameworks-in-nescio.md).** Nothing here
adds a runtime dependency to the framework; the service boundary established by
ADR 0005 *Decision 2* is unchanged.

Tracked under [#160](https://github.com/noctua84/nescio-ai/issues/160). *Decision 2*,
the largest piece of work here, is ordered as
[#180](https://github.com/noctua84/nescio-ai/issues/180).

## Context

ADR 0005 decided that `nescio-memory` becomes the system of record, and its every
cost estimate, corpus measurement and ingest sketch took the **committed note** as
the thing to be stored. Re-measuring the pipeline shows that choice was never
examined, and that the note is the worst of the three available seams.

### What the pipeline actually produces

Measured against the live brain on 2026-10-03 — 440 markdown files, less 13
generated `MEMORY.md` indexes, giving **427 content notes**:

| | notes | share |
|---|---|---|
| promotion-owned (carry a `<!-- promoted:begin -->` block) | 91 | **21%** |
| hand-written or pre-pipeline | 336 | **79%** |

The committed corpus is four-fifths material the learning loop never wrote. Any
property measured across all 427 notes and attributed to the pipeline is a statement
about hand-authored files — which is the error ADR 0005 made when it rejected
chunking on *"the median note has no headings"*.

Where the pipeline *did* write, its output is tight:

| promoted block | median | p90 | max |
|---|---|---|---|
| characters | 1,775 | 3,053 | **7,646** |
| paragraphs | **6** | 12 | 22 |

and in 86 of those 91 notes the block is the *entire* note — median hand-written
content outside the markers is **0 characters**, with only 5 notes carrying more
than 500.

### The nomination is note-shaped, not learning-shaped

This is the finding that decides the ADR, and it contradicts what the field names
suggest. `commands/harvest-memory.md` defines `body` as **"The note body
(markdown)"**, and step 3 instructs the harvesting agent to *"Update an existing note
in place rather than creating a near-duplicate."* A nomination is therefore one
*note*, not one *learning*, and when a session learns something about a target that
already has a note, the agent is told to read that note and submit a merged
replacement.

The measurement agrees: **not one of the 91 promoted blocks is a single paragraph.**
Sixty-seven of them have five or more.

So the learning-event boundary is destroyed at **authoring** time, by instruction,
before promotion runs. The promotion code is merely consistent with it:
`_compose_note` (`scripts/promote_learnings.py:324`) replaces the managed block
wholesale — `rest[:b] + new_block + rest[e:]` — the overwrite path (`:621-639`)
resolves two nominations for one target by discarding one of them, and
`_prune_target_lines` (`:386`) deletes the superseded hash from the ledger. Every one
of those is the correct behaviour **for a file**, because one file can hold one
answer.

### What a nomination already carries

Every nomination is validated for eight fields before anything is written:
`scope`, `target`, `name`, `description`, `type`, `body`, `source`, `date`. That is
an unusually well-labelled ingest unit: `type` is a ready-made filter facet (97
convention, 67 architecture, 60 context, 50 regression, 47 project, 42 feedback, 27
adr, and a thin tail), `scope` and `target` give repo and project partitioning,
`source` is a three-level priority class, `date` is recency, and
`content_hash12(nom["body"])` is a stable identity key. Corpora rarely arrive
pre-labelled like this.

The nomination is also **the unit a human reviews.** ADR 0005's first consequence
states it plainly: human-gated promotion is implemented *by* git review of a diff.
Whatever the service ingests, the review gate sits here.

## Decision

### 1. The service ingests nominations, not committed notes

The ingest contract takes a nomination — its eight validated fields — and not a
markdown file read off disk. The committed note stops being the unit of storage and
becomes a rendered view of what was ingested.

Three seams were available and the note is the worst of them. The **learning-trail
and auto-memory records** upstream of harvest are the most atomic, but ingesting
there bypasses the human review gate, which is the defining property of the learning
loop and the thing ADR 0005 already identified as hardest to rebuild. The **committed
note** is the most convenient and carries the least: 79% of it never came through the
pipeline, and its metadata has been flattened into frontmatter by the time it lands.
The **nomination** is the only seam that is both reviewed and structured.

### 2. A nomination carries learnings as addressable units, not a merged note body

This is a change to the harvest contract, not only to the service. `body` becomes a
sequence of learning units, each with its own text and its own `source`/`date`, and
the note body becomes something *rendered from* them rather than something authored
over them.

**Step 3 of `commands/harvest-memory.md` is what has to change.** "Update an existing
note in place" is right for a file store and wrong for this one: the agent should
*add a learning to a target* and never rewrite a target's accumulated prose. Until
that instruction changes, every nomination will keep arriving as a six-paragraph
merged body with no recoverable seams, and no amount of work on the service will
recover them.

The work order is [#180](https://github.com/noctua84/nescio-ai/issues/180), which
carries the open design questions this decision deliberately does not settle —
whether the file keeps one managed block per unit or one rendered from all of them,
how the existing 91 blocks migrate without a lossy guess at their internal
boundaries, and what `content_hash12` hashes once a nomination holds more than one
body.

Per-unit identity must survive into storage. Today `content_hash12` is written only
to `memory/learning-log.md` and never into the note, so a retrieved passage cannot be
joined back to the learning event that produced it. For a store whose answers feed a
generation context, that provenance is not optional.

### 3. The chunking strategy is a consequence of this seam, not an independent choice

ADR 0005 treated "summary or chunks" as a question to be settled on its own, and got
it wrong partly because it was the wrong question in the wrong order. Once the seam is
fixed, chunking follows:

- **New content needs no chunker.** A learning unit submitted under *Decision 2* is
  already a retrieval unit. The harvest boundary is the semantic boundary.
- **The 336 legacy notes need one, and paragraphs are it.** Across 423 notes there
  are 4,438 paragraphs, median 268 characters, p90 787, and only **6.1%** exceed
  1,000 characters — so a paragraph-first chunker needs a hard-split fallback for one
  paragraph in sixteen. A 1000/200 sliding window over the same corpus produces 2,198
  chunks of which **98.2% begin or end mid-paragraph.**
- **Headings help where they exist.** Median 0 as ADR 0005 recorded, but 44% of notes
  carry at least one, and the notes above p90 — precisely where chunking matters —
  carry a median of 9. The long tail is the structured part of this corpus.

The two populations get different treatment and are labelled as such, because a
backfilled hand-written note is not evidence of the same kind as a reviewed
nomination.

### 4. Every nomination persists, and precedence adjudicates at read time

Contradiction precedence stays exactly as ADR 0005 *Decision 5* requires — the total
order in `scripts/_learning_common.py:36`, ties broken by the newer date — but it
stops being a reason to delete. A second nomination for a target is stored next to the
first, with its own `source`, `date` and hash; retrieval returns both; the
deterministic layer decides which to present and may say that the two disagree.

This is a capability the file layer cannot have rather than a preference. It also
removes a current, silent loss: today the losing nomination survives only in git
history, and `_prune_target_lines` removes even its ledger trace.

### 5. Unrouted nominations become ordinary rows

An unrouted nomination — [#170](https://github.com/noctua84/nescio-ai/pull/170)'s
outcome, declared when a session cannot determine where a learning belongs — exists
only because a file needs a path. Similarity retrieval does not. Under this seam an
unrouted learning is stored with a null `target` and retrieves normally, and
`check_memory_triggers.py`'s trigger 3 stops measuring a structural limitation of the
storage format.

## Options considered

| Option | Verdict |
|---|---|
| **Ingest nominations** (chosen) | The only seam that is both human-reviewed and structured. Requires changing the harvest contract, not just the service. |
| Ingest committed notes | Rejected. ADR 0005's implicit assumption. 79% of the corpus never came through the pipeline, metadata is flattened by then, and the merged body has no recoverable seams. |
| Ingest learning-trail / auto-memory records | Rejected on the review gate, not on shape — they are the most atomic units available. Worth revisiting *only* if a replacement review gate is built at that layer first. |
| Keep nominations note-shaped and chunk them on arrival | Rejected. Works, and is strictly worse: it spends a chunker recovering boundaries the harvesting agent had and was instructed to discard. |
| Store a per-note summary vector as the retrieval key | Rejected — ADR 0005 Decision 3, withdrawn. Retained for note-level identity work (near-duplicate detection, cross-repo recurrence) and never ranked against passages. |

## Consequences

**Positive:** the review gate keeps its current shape. Because the ingested unit is
the nomination, the human still reviews exactly what gets stored, and ADR 0005's most
serious consequence — *"the defining property of the learning loop has to be rebuilt
from nothing"* — is reduced to transporting an existing gate rather than inventing
one.

**Positive:** the corpus stops shrinking. *Decision 4* ends a loss that is happening
now and is invisible, because the displaced learning leaves no trace outside git
history.

**Positive:** chunking is decided by construction for all new content, and the
chunker is needed only for a bounded one-time backfill of 336 notes.

**Negative:** this changes `commands/harvest-memory.md` and the nomination schema,
which means `promote_learnings.py`, `mark_harvested.py` and the receipt contract move
with it. *Decision 2* is the largest piece of work in this ADR and it lands in the
framework, not the service.

**Negative:** two populations means two confidence levels, and every consumer of
retrieval has to know which it is holding. A backfilled paragraph from a 2025
hand-written note and a reviewed learning unit from 2026 are not the same kind of
evidence, and nothing currently distinguishes them.

**Negative:** `status: proposed`, and *Decision 2* is a contract change proposed on
the strength of 91 notes. That is the right population but a small one, and the
7,646-character practical bound should not harden into a schema constraint on that
evidence.

**Negative:** rendering a note from stored units is new machinery with no present
equivalent, and it is on the path to every human reading `memory/` as files. If it is
late or wrong, the readable corpus degrades while the retrievable one improves.

**To re-verify:** every count here is a measurement of a corpus that moved twice
during the session that produced it — the largest directory went from 65 to 80 notes
inside a day, and the transcript corpus from 1,645 MB to 4,116 MB. Re-measure before
relying on any figure. Specifically: the promoted share (91/427) rises with every
harvest and changes the balance between *Decision 3*'s two populations; and the claim
that paragraph-aligned chunks **retrieve** better than offset-aligned ones is
**not measured anywhere** — *Decision 3* rests on boundary quality and chunk count
only. The harness in `nescio-memory`
[#34](https://github.com/noctua84/nescio-memory/pull/34) cannot answer it until its
metric moves from note-level to passage-level relevance.
