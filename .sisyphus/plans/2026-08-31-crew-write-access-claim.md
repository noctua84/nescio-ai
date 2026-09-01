# Correct the "only agent that writes production code" claim in the crew charters

Branch: `claude/hungry-bose-77f645`, based on `origin/main` @ 714ea43 (PR #109 merged).
Baseline: `PYTHONPATH=scripts python -m unittest discover -s tests` → 627 tests, OK.

Revision 3 — incorporates the devil's-advocate and validator passes. See
**Rejected designs** at the foot for what changed and why; do not re-propose
those without reading it.

## Problem

Six charter locations assert an exclusivity that `_crew_common.CODE_WRITERS`
contradicts. All verified on the merged main:

| # | Location | Text |
|---|---|---|
| 1 | `agents/builder.md:3` (`description:`) | "The only crew member with write access to production code." |
| 2 | `agents/builder.md:12` | "You are the only agent in this crew with write access to production code." |
| 3 | `agents/builder-simple.md:12` | identical |
| 4 | `agents/builder-standard.md:12` | identical |
| 5 | `agents/orchestrator.md:333` | "`builder` is the only agent that actually reads and edits the code" |
| 6 | `docs_site/docs/agents.md:88` | generated mirror of (1) |

Plus `agents/orchestrator.md:25` — "Write production code (delegate to `builder`)"
— which predates the cost tiers that the same file's dispatch table routes to.

`CODE_WRITERS = {"builder", "builder-standard", "builder-simple", "qa-guard"}`.
Three agents cannot each be the only one, and qa-guard makes four.
(`test-writer` and `doc-writer` also hold Edit, but bounded to tests and docs —
they are `BOUNDED_WRITERS`, not production-code writers, and sit outside this
claim's scope. The count this plan pins is therefore four, not six.)

`README.md` was corrected by #109 and needs nothing.

**Deliberately out of scope:** `docs/plans/2026-08-22-implementer-agent.md` and
`docs/specs/2026-08-22-implementer-agent-and-delivery-boundaries-design.md` also
carry the sentence. They are dated historical records of what was decided in
August; rewriting them would falsify the archive. Left alone on purpose — this
note exists so a reviewer does not file it as a miss.

### The same root cause, three times

PR #90 added six agents and three downstream registries never caught up: the
write-policy tests (fixed by #109), these charters (this plan), and the docs
catalog (T0 below). The catalog's staleness was invisible because CI's
`discover -s tests` never reaches `docs_site/` — see Findings.

## Constraints

- Charters are operating instructions: surgical edits, preserve voice, no silent
  scope change. Preserve the *purpose* of the original sentence — impressing on
  the agent that write access is rare and carries responsibility.
- `description:` is routing metadata the orchestrator reads to *choose* an agent.
  Only put a **discriminator** there. Provenance facts shared by all three tiers
  discriminate nothing and belong in the body.
- `scripts/apply_theme.py` rewrites `\bbuilder\b` → `archimedes` across charter
  text. Every new sentence must read correctly under BOTH themes.
- An existing test pins orchestrator prose:
  `test_orchestrator_names_builder_as_the_code_writer` asserts the literal
  substring `` delegate to `builder` ``. Do not break it. (Verified: T4's
  replacement preserves it in both themes.)
- Python floor 3.13. Tests via `PYTHONPATH=scripts python -m unittest discover -s tests`
  (NOT pytest — the local wrapper reports a spurious `Path.read_text() ... newline`
  TypeError).
- `agents/qa-guard.md` must not be modified. See T1's comment for why.

## Tasks

### T0 — `docs_site/gen_catalog.py`: place the six ungrouped agents  [simple]

`AGENT_GROUPS` (~line 75) still reads `("Build", ["builder"]), ("Verify", ["reviewer"])`.
Six agents fall through to "Other" and `--check` exits 1 **on the current
baseline, before any of this plan's changes**. T3 forces a regeneration, so this
must be fixed first or the regeneration ships a warning-emitting catalog.

Target table, preserving the existing lifecycle order and adding one group:

```python
AGENT_GROUPS: list[tuple[str, list[str]]] = [
    ("Coordinate", ["orchestrator"]),
    ("Discover", ["scout", "explore", "librarian", "vision"]),
    ("Plan and challenge", ["planner", "validator", "advisor", "critic"]),
    ("Build", ["builder", "builder-standard", "builder-simple", "test-writer"]),
    ("Verify", ["qa-guard", "reviewer"]),
    ("Document", ["doc-researcher", "doc-writer"]),
]
```

`Document` is a new group: `doc-researcher` runs as a parallel track during
EXECUTE and `doc-writer` fires at DELIVER, after VERIFY — so it belongs at the
end of the lifecycle order, not folded into Build. Do not reorder the existing
four groups or rename them.

Verify with `python docs_site/gen_catalog.py --check`: the "not in any grouping
table" warning must disappear. It will still exit 1 until T6 regenerates.

### T1 — `_crew_common.py`: the anchor and its domain  [standard]

Add two things next to `BOUNDARY_PHRASE`, in the module's established voice.

```python
WRITE_ACCESS_PHRASE = "Write access to production code:"

WRITE_ACCESS_DECLARERS = {"builder", "builder-standard", "builder-simple"}
```

The comment on `WRITE_ACCESS_DECLARERS` must state **why it is not `CODE_WRITERS`**,
because the difference is a deliberate asymmetry and not an oversight:

> `qa-guard` is a `CODE_WRITER` and is deliberately absent. The declaration
> sentence is a *licensing* sentence — it tells an implementer that it may write
> and that few others may. `qa-guard`'s charter does the opposite job: it opens
> "You have one job: make the CI-equivalent checks pass" and spends a hundred
> lines narrowing that to the mechanical, returning `BLOCKED` at the first
> judgment call. Inserting a licensing sentence there would widen the only
> control that charter has — agent frontmatter takes tool names only, so the
> prose *is* the control surface (see
> `test_bounded_writers_declare_their_boundary`). A partial domain with a stated
> reason beats a total one bought by editing a charter to fit a test.

Do not change `CODE_WRITERS` or any other constant. This module is pure data.

### T2 — the three builder charters  [standard]

In each of `agents/builder.md`, `agents/builder-simple.md`,
`agents/builder-standard.md`, replace the `## CRITICAL IDENTITY` paragraph. The
payload is a **count, not a roster** (see Rejected designs). Full text for each
file, written out so the copy-paste error that caused this bug cannot recur:

`agents/builder.md`:
```
## CRITICAL IDENTITY

Write access to production code: you are one of four agents that hold it. Most
of this crew reads, judges, and advises; you build. That inversion is your
purpose — and the reason your constraints are tighter than theirs, not looser.

You are the `complex` tier: design judgment, or work beyond the standard tier's
line budget.
```

`agents/builder-standard.md` — identical first paragraph, then:
```
You are the `standard` tier: moderate complexity, 50–200 lines, one or two
design decisions. The `complex` tier carries this same contract at higher cost.
```

`agents/builder-simple.md` — identical first paragraph, then:
```
You are the `simple` tier: mechanical work, no design judgment, under 50 lines.
The `standard` and `complex` tiers carry this same contract at higher cost.
```

The first paragraph names no agent, so `apply_theme.py` does not touch it and it
reads identically under both themes. The tier sentences name no agent either.
This is a property worth keeping — do not reintroduce an agent name here.

### T3 — `agents/builder.md` `description:`  [simple]

Replace "The only crew member with write access to production code." with the
complexity band, **and nothing else**:

> Complex tier — design judgment, or work beyond the standard tier's 200-line band.

`builder.md` is the only tier whose description lacks a band; both siblings have
one. That missing band is the real defect in this line. Do not restate the
write-access fact here: it is identical across all three tiers, so it cannot help
the router choose, and it would rot in the generated catalog (T6) that nobody
hand-edits.

Leave `builder-simple.md` and `builder-standard.md` descriptions alone.

### T4 — `agents/orchestrator.md`  [simple]

Line 25: `- Write production code (delegate to `builder`)` →
`- Write production code (delegate to `builder` or its `-simple` / `-standard` tiers)`.
The substring `` delegate to `builder` `` must remain intact — a test pins it.

Line 333: `` `builder` is the only agent that actually reads and edits the code ``
→ `` `builder` and its tiers actually read and edit the code ``, adjusting the
following clause's agreement ("so their incidental findings are…").

### T5 — the doc-lint  [standard]

Add to `tests/test_agent_definitions.py`, modelled on
`test_bounded_writers_declare_their_boundary`:

- `_write_access_sentence(body)`, symmetric with `_boundary_sentence`: from
  `WRITE_ACCESS_PHRASE` to the first sentence-final punctuation, hard-stopping at
  the paragraph break. Reuse `BOUNDARY_SENTENCE_END_RE`.
- A spelled-number map, `NUMBER_WORDS = {1: "one", 2: "two", …}`, covering at
  least the current roster size. A `len(CODE_WRITERS)` with no entry must raise,
  not silently skip.
- `test_code_writers_declare_how_many_hold_write_access`: for each name in
  `WRITE_ACCESS_DECLARERS`, read `agents/<themed>.md`, strip frontmatter, extract
  the sentence, assert it is present, and assert it contains
  `NUMBER_WORDS[len(CODE_WRITERS)]` as a **whole word** — `\bfour\b`, so "four"
  does not match inside "fourteen".
- Assert `len(CODE_WRITERS) > 1`, so the lint cannot pass vacuously on a future
  single-writer crew — and so that if the crew ever does shrink to one, the
  exclusivity claim must be re-argued rather than silently re-enabled.
- Assert `WRITE_ACCESS_DECLARERS <= CODE_WRITERS`, so the domain cannot drift to
  include an agent that may not write at all.
- **Pin the set itself by exact equality**, in the existing
  `test_the_writer_partition_is_pinned` alongside its siblings:
  `assertEqual(WRITE_ACCESS_DECLARERS, {"builder", "builder-standard", "builder-simple"})`.
  Without this the lint is vacuously green if the set is ever emptied — a zero-iteration
  loop, and `<= CODE_WRITERS` holds for the empty set. This is precisely the failure that
  test's own docstring already names for `BOUNDED_WRITERS`: "quietly dropping one stops the
  check rather than failing it." Extend that docstring to cover the new set; do not write a
  separate pin test.

**Also tighten `test_orchestrator_names_builder_as_the_code_writer` (:473).** It
asserts only that `` delegate to `builder` `` appears — a substring present in both
the stale text and T4's corrected text, so it would have stayed green on the very
line it was meant to pin. Add an assertion that the line also names the tiers, so
T4's fix is load-bearing and cannot silently revert. Resolve the tier names through
`_themed`, not as literals, so the assertion holds under both themes. Extend the
test's docstring to say what the extra assertion is for.

**What this lint does and does not claim.** It is aimed at an author who edits
`CODE_WRITERS` in `_crew_common.py` and forgets `agents/` — exactly how this bug
arose, when PR #90 added the tiers and qa-guard. It does not stop an author
writing the anchored sentence correctly and contradicting it two paragraphs
later. Claim that scope in the docstring and no more.

### T6 — regenerate the docs catalog  [simple]

`python docs_site/gen_catalog.py`, after T0 and T3 have both landed. Commit the
regenerated `docs_site/docs/agents.md`. Do not hand-edit it.

Expect a large diff: the catalog is stale on the baseline independently of this
work (agent count 11 → 17, six new sections, the new grouping rows). That is
expected and is the point of T0.

## Execution order

- Wave 1 (parallel, disjoint files): T0, T1, T4
- Wave 2: T2 + T3 — same files; one agent. Needs T1's exact phrase.
- Wave 3: T5 (needs T1 + T2), then T6 (needs T0 + T3)

## Acceptance

1. `grep -rn "only agent\|only crew member" agents/ docs_site/docs/` returns
   nothing. (Verified on the baseline to return exactly the six locations and no
   false positives.)
2. `PYTHONPATH=scripts python -m unittest discover -s tests` → OK, count ≥ 628.
3. `python docs_site/gen_catalog.py --check` exits **0**, with no "not in any
   grouping table" warning.
4. `tests/test_apply_theme.py` still passes, and
   `python scripts/apply_theme.py philosophers --dry-run` shows the three
   charters' new `CRITICAL IDENTITY` paragraphs unchanged — they contain no agent
   names, so the theme must be a no-op over them.
5. `python -m unittest discover -s docs_site -p 'test_gen_catalog.py'` → OK.
   (Currently red on the baseline: `Ran 25 tests, FAILED (errors=1)`.)
6. T5 fails if `CODE_WRITERS` changes size and the charters are not updated.
   Demonstrate with an **existing** agent name — a fictional one makes T5 raise
   `FileNotFoundError` at `AGENTS_DIR / f"{_themed(name)}.md"` rather than fail an
   assertion. Expect three reds, not one: `test_the_writer_set_is_pinned` (:283)
   and `test_the_writer_partition_is_pinned` (:325) also fire. Paste the output,
   then revert.
7. `git diff --name-only` must not list `agents/qa-guard.md`.

## Findings to surface at DELIVER

- **CI never runs `docs_site/`'s tests.** `tests.yml` runs `discover -s tests`
  only; `docs.yml` runs `mkdocs build --strict`, whose hooks never import
  `gen_catalog`. `docs_site/test_gen_catalog.py::test_committed_pages_are_up_to_date`
  has therefore been red and unnoticed. T0 + T6 fix today's staleness but nothing
  stops it recurring. Approved as a **separate spawned task**: add `docs_site` to
  CI discovery or a `gen_catalog.py --check` step.

## Rejected designs

**A roster payload ("you, `builder-simple`, `builder-standard` and `qa-guard`").**
Rejected. It puts four proper nouns at the highest-attention position of three
system prompts to encode a fact none of them acts on, and it goes red on a
*rename* — churn in four files for no semantic change — and on a *swap*, where
green would have been correct, because the sentence's purpose is rarity, not
census. A count catches the one failure that matters (the write set changing
size) and no others. Revisit only if a builder is ever given a decision that
depends on *which* peers can write.

**Extending the declaration to `agents/qa-guard.md`** to make the invariant total
over `CODE_WRITERS`. Rejected: see the T1 comment. Reshaping a charter to satisfy
a test's domain is the tail wagging the dog, and this repo has already declared
that charter prose is a control surface, not decoration.

**"you, plus three named peers", with the test asserting set equality against
`CODE_WRITERS`.** Rejected as arithmetically broken — the sentence names three
roster names, the assertion expected four, and it would have failed on all three
files on the first run. The obvious patch (union the self-name back in) makes the
self-name unverifiable by construction, so `builder-standard.md` could name itself
in the third person and still pass — the exact copy-paste class of error that
caused this bug.

**A negative grep for "only agent" / "sole" / "exclusive".** Rejected as
unboundedly brittle in both directions, per the original brief.
