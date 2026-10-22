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

> **Correction, 2026-10-21.** **The table above is backwards, and the sentence after it
> is wrong.** It counts notes carrying a `<!-- promoted:begin -->` block — that is
> *current marker ownership*, not authorship. `PROMOTED_BEGIN` was only introduced on
> 2026-08-10 (`git log -S PROMOTED_BEGIN -- scripts/promote_learnings.py`), so every
> promotion before that date is marker-less while still carrying the
> `[Source: ... — date]` line that **only** `promote_learnings.render_block` writes.
>
> Re-measured against the live brain on 2026-10-21:
>
> | | notes | share |
> |---|---|---|
> | carry a marker block | 175 | 34.9% |
> | marker-less but provenance-bearing (pipeline-authored, pre-marker) | 236 | 47.0% |
> | **pipeline-authored, total** | **411** | **81.9%** |
> | **no pipeline trace** | **91** | **18.1%** |
>
> over 502 content notes (515 `.md` less 13 generated `MEMORY.md`). The ledger settles
> it independently: of 405 distinct targets, **404 still exist on disk — 174 carrying
> a marker, 229 marker-less but provenance-bearing.**
>
> So the corpus is four-fifths material the learning loop **did** write, not the
> reverse. A pre-marker promoted note later hand-rewritten is indistinguishable from
> outside, so treat ~91 as a **floor** on hand-written and ~411 as a **ceiling** on
> pipeline-authored; separating them needs git archaeology inside the private brain.
>
> **What this does to the decisions, in three directions:**
>
> 1. ***Decision 2 gets stronger.*** The authoring-time boundary loss affects ~82% of
>    the corpus rather than 21%. That is the decision this ADR most wanted supported,
>    and the corrected figure supports it far better than the one it cited.
> 2. ***Decision 3 gets much cheaper.*** The one-time chunker backfill population is
>    ~91 notes, not 336.
> 3. ***Decision 1's stated reason partly collapses.*** "79% of it never came through
>    the pipeline" is not true of authorship. The committed note is still the worse
>    seam — metadata is flattened into frontmatter by then, and 229 notes carry a
>    single provenance line for an entire merged body — but that is the reason, and
>    not the one given below.
>
> The *method* error this ADR accused ADR 0005 of — measuring a population and
> attributing its shape to the pipeline — is one this ADR then made itself, in the
> opposite direction. Recorded rather than quietly fixed, because the shape of the
> mistake repeated, and that is worth more than the number.

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
note** is the most convenient and carries the least: its metadata has been flattened
into frontmatter by the time it lands, and 229 notes carry a single provenance line
covering an entire merged body. (This originally read "79% of it never came through
the pipeline" — backwards, as the Context correction above records.)
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
how the existing blocks migrate without a lossy guess at their internal
boundaries, and what `content_hash12` hashes once a nomination holds more than one
body.

> **Amendment, 2026-10-22.** **Decision 2's reasoning above is largely wrong, its
> mechanism is unsafe, and the decision itself survives in a narrower form.** Third
> correction to this ADR in three days; the record being right matters more than the
> record being tidy.
>
> **The boundary-loss argument does not hold at the scale claimed.** It rests on
> nominations arriving as merged bodies. Measured over the 175 marker-carrying notes
> by counting commits that touched each one (`git log --follow`, counts only):
>
> | commits per promoted note | notes | share |
> |---|---|---|
> | 1 | 139 | **79.4%** |
> | 2 | 29 | 16.6% |
> | 3 | 4 | 2.3% |
> | 4 | 3 | 1.7% |
>
> median 1, mean 1.3, **max 4**. So **79.4% of promoted notes were written by a single
> promotion and never touched again** — there was no merge to recover boundaries from.
> The figure is a ceiling, not a floor: `--follow` counts the `repo/ui` to
> `repo/soulsgate-ui` directory convergence as a touch, so true re-promotion is rarer
> still.
>
> The *"six-paragraph merged body"* above measures **prose style, not accumulation**.
> A single harvest natively writes several paragraphs. Boundary destruction is real for
> at most 20.6% of promoted notes and seriously only for the seven touched three or
> more times. The ledger could not have told us this, because `_prune_target_lines`
> drops a target's superseded lines on overwrite — it destroyed the evidence, which is
> a second reason to delete it.
>
> **The mechanism was unsafe, and this is the more serious half.** The work order's
> design answers proposed union-merge by unit hash. But retraction already exists:
> `commands/harvest-memory.md:106` instructs the agent to *"drop anything already
> captured or since proven wrong"*, implemented by re-authoring the body without the
> disproven learning, which `_compose_note:339-345` then commits — and the human sees
> the removal in the git diff, which **is** the review gate.
>
> Under union-merge, omitting a unit removes nothing, so **retraction becomes
> inexpressible**. `memory/CONVENTIONS.md:48` makes `promote_learnings.py` the only
> sanctioned writer and contains no deletion or correction procedure, so there is no
> second route. Unbounded accumulation was the symptom; **a learning proven wrong
> becoming permanent** is the disease. `VALID_SCOPE_BUCKETS` includes `people` and
> `feedback`, so this also removes the only erasure path for notes about identifiable
> individuals.
>
> **What Decision 2 now decides.** A nomination carries learning units, for two reasons
> that survive measurement and one that does not:
>
> 1. **Per-unit identity** so a retrieved passage joins back to its learning event
>    — unchanged, and independent of whether any merging happened.
> 2. **Per-unit `source`/`date`** so precedence can be read rather than destroyed
>    — also unchanged.
> 3. ~~Recovering boundaries from a merged body~~ — withdrawn as a *justification*.
>    It describes a fifth of the corpus at most.
>
> And the mechanism is **supersession, not union-merge**: a unit may carry
> `supersedes: [<hash12>, ...]`. The superseded unit stays in the ledger and in the
> store, so *Decision 4*'s "nothing is lost" holds, while the renderer omits its text.
> Append-only in the data, curatable in the view, one reviewable diff. For the `people`
> and `feedback` buckets, supersession must actually remove text from the rendered
> block rather than demote it.
>
> **Retraction is hereby on the must-not-break list**, alongside the review gate,
> dedup, watermarks and the ledger. It was absent, which is how a design that deletes
> it got as far as being written down.
>
> *Step 3 of `commands/harvest-memory.md` still has to change* — but to "add a
> learning, or supersede one", not merely "add".

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
- **The legacy notes need one, and paragraphs are it.** (~91 of them, not the 336
  stated when this was written — see the correction above.) Across 423 notes
  there
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
| Ingest committed notes | Rejected. ADR 0005's implicit assumption. Metadata is flattened by then, a single provenance line covers an entire merged body, and that body has no recoverable seams. (The "79% never came through the pipeline" first given here was wrong — see the Context correction.) |
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
chunker is needed only for a bounded one-time backfill of ~91 notes.

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
relying on any figure — and this ADR's own Context figures were wrong on first
measurement, so re-measure rather than cite. Note also that **ADR 0002's trigger T2
has since fired**: `check_memory_triggers.py` reports `FIRED t2-corpus-size — 502
notes`, with T1 at 90 of ~100, so ADR 0005's claim to be "deliberately ahead of its
own trigger" no longer holds. Specifically: the pipeline-authored share (411/502)
rises with every
harvest and changes the balance between *Decision 3*'s two populations; and the claim
that paragraph-aligned chunks **retrieve** better than offset-aligned ones is
**not measured anywhere** — *Decision 3* rests on boundary quality and chunk count
only. The harness in `nescio-memory`
[#34](https://github.com/noctua84/nescio-memory/pull/34) cannot answer it until its
metric moves from note-level to passage-level relevance.
