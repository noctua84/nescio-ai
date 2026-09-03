# Philosopher theme + tests for the six new crew members

Revision 2 — incorporates validator (OKAY) and socrates (Material objections).

## Problem

PR #90 added six agents (`builder-simple`, `builder-standard`, `test-writer`,
`qa-guard`, `doc-researcher`, `doc-writer`). Neither `scripts/apply_theme.py`
nor `tests/test_agent_definitions.py` knows about them. 8 tests are red.

1. **The theme corrupts the builder tiers.** `_transform` rewrites on
   `\bbuilder\b`, which matches inside `builder-simple`, but `file_renames`
   only knows `builder.md`. Applying the theme yields `builder-simple.md`
   containing `name: archimedes-simple` — so the agent stops loading. The
   round-trip test misses it because the corruption is symmetric.
2. `THEME_INVARIANT_ROSTER` omits all six, so roster tests fail both directions.
3. `test_builder_is_the_only_editor` fails for five agents.
4. `test_orchestrator_dispatches_builder_not_general_purpose` greps a literal
   `subagent_type: "builder"` the tiered dispatch line no longer contains.

## Corrections carried in from review

- **The original rationale was wrong.** Adding tier variants to `PAIRS` does
  NOT double-map — `_transform` applies rules sequentially, so the extra rule
  is a dead no-op. The real reason to keep them separate is **coupling**:
  `PAIRS` is consumed as a rename dict at `tests/test_apply_theme.py:49`,
  `tests/test_agent_definitions.py:57`, `:70`, `:82`. It must stay the
  word-pair source; file-only renames live apart.
- **`_themed("builder-simple")` would KeyError** — `dict(PAIRS)` has no such
  key but `CODE_WRITERS` contains it. The roster helper must resolve
  `TIER_VARIANTS` too. This is the sharpest edge in the work.
- **Path-scoped tool permissions are not supported** in agent frontmatter
  (confirmed against the Claude Code docs). `tools`/`disallowedTools` take
  tool names only. A "hard file boundary" therefore cannot be enforced by
  configuration — the check below is a **doc-lint** and must be named as one.
- `test_builder_is_the_only_editor` did not "expire" — it was **violated**, by
  PR #90. Making it green is not bookkeeping.
- Python floor is fine: `requires-python = ">=3.13"`, CI pins 3.13, no matrix.
  `Path.read_text(newline=)` (3.13+) is within contract. The local pytest
  wrapper runs an out-of-contract interpreter; verify with `python -m unittest`.

## Decisions (locked by the user)

- Constants live in a new `scripts/_crew_common.py`, matching the existing
  `_adopt_common` / `_hygiene_common` / `_learning_common` / `_wiki_common`
  convention. Crew write policy must not depend on an opt-in cosmetic feature.
- **Two commits.** A (`fix:`) makes everything green with zero naming
  decisions. B (`feat:`) adds the four philosopher names and is independently
  revertible.
- The writer set stays falsifiable via a pinned count with an explanatory
  message.
- Names for commit B: `test-writer` to `euclid`, `qa-guard` to `cato`,
  `doc-researcher` to `callimachus`, `doc-writer` to `cicero`.
  Builder tiers keep suffixes: `archimedes-simple` / `archimedes-standard`.

---

# COMMIT A — `fix:` (no naming decisions)

### Task A1 — `scripts/_crew_common.py` [complex]

New module holding, with a docstring explaining why it is not in
`apply_theme.py` (write policy must outlive the cosmetic theme):

- `PAIRS` — the 5 existing word-level rename pairs, unchanged for now.
- `TIER_VARIANTS = ("simple", "standard")` on `builder`. Drives **file
  renames only**; the `\bbuilder\b` text rule already handles the prose.
- `THEME_INVARIANT_ROSTER` — the existing 6 **plus** `test-writer`,
  `qa-guard`, `doc-researcher`, `doc-writer` (theme-invariant in commit A).
- `CODE_WRITERS = {builder, builder-standard, builder-simple, qa-guard}`
- `BOUNDED_WRITERS = {test-writer, doc-writer}`
- `BOUNDARY_PHRASE = "Hard file boundary:"` — a named constant. The two
  current descriptions already differ in wording after this prefix, so a bare
  inline literal is one reword away from silent failure.
- `expected_roster(theme)` and a themed-name helper that resolves **both**
  `PAIRS` and `TIER_VARIANTS` (see the KeyError note above).

### Task A2 — refactor `scripts/apply_theme.py` [standard]

Import from `_crew_common`; declare no roster facts of its own. Add
`TIER_VARIANTS` to the file-rename list so `builder-simple.md` becomes
`archimedes-simple.md`. Update the module docstring (it claims only five
agents are renamed; after this it is seven files).

Constraints: preserve `newline=""` on both read and write (the CRLF
regression at `:90`/`:97`); keep `detect_theme` working; keep the round trip
byte-identical and the operation idempotent.

### Task A3 — `tests/test_agent_definitions.py` [standard]

- Delete the local `THEME_INVARIANT_ROSTER`; import from `_crew_common`.
  Both test modules already put `scripts/` on the path — no new plumbing.
- Replace `test_builder_is_the_only_editor` with:
  - `test_only_declared_writers_can_edit` — `CODE_WRITERS` and
    `BOUNDED_WRITERS` can edit; every other agent in the roster cannot.
  - A pinned count:
    `assertEqual(len(CODE_WRITERS | BOUNDED_WRITERS), 6, "adding a writer is
    an architectural decision — say why in the commit message")`.
    The docstring must say a red here means *justify the new writer*, not
    *add it to the set*.
  - `test_bounded_writers_declare_their_boundary` — asserts `BOUNDARY_PHRASE`
    appears in the **charter body** (where
    `docs/specs/2026-08-24-team-workflow-patterns.md:66` says enforcement
    lives), not only in `description:`. The docstring must state plainly:
    this is a doc-lint, not enforcement; path-scoped permissions are
    unavailable; `Write`-boundary agents (`planner`, `reviewer`) are
    deliberately out of scope.
- Fix `test_orchestrator_dispatches_builder_not_general_purpose` to assert all
  three tier names appear in the dispatch section.

### Task A4 — `tests/test_apply_theme.py`: the tests the round trip cannot see [standard]

Task A3's roster assertions derive from the same constants as the code, so
these carry the **independent oracles**. Do not drop them as redundant.

- `test_theme_never_desyncs_name_from_filename` — apply the theme to a temp
  copy of the real `agents/`, then assert for **every** file that frontmatter
  `name:` equals the filename stem, in both directions. This is the exact
  property the symmetric round-trip test is blind to, and the regression test
  for defect 1.
- `test_no_mapping_replacement_is_another_mappings_search_term` — in both
  directions. Guards the hazard class the docstring's "Socratic" warning
  describes but never tested, and survives the next name added.
- A casing scan: no search term appears in `agents/` in a casing the
  `.capitalize()`-based mappings do not cover (today `Qa-guard` would match
  but `QA-guard` would not).

### Task A5 — `README.md` [simple]

- Crew table (rows 103-113): add the six new agents.
- Line 107: `builder` is no longer "the only agent that writes production
  code" — correct it.
- Theme section (~140-151): note that the builder tier variants are renamed
  too (7 files in commit A).

---

# COMMIT B — `feat:` (the naming)

### Task B1 — the four philosopher names [simple]

Move `test-writer`, `qa-guard`, `doc-researcher`, `doc-writer` out of
`THEME_INVARIANT_ROSTER` and into `PAIRS` as `euclid`, `cato`, `callimachus`,
`cicero`. Update the `apply_theme.py` docstring and the README theme section
(now 11 renamed files).

Note: the repo ships **functional** names — the theme is rendered locally, not
committed — so this commit renames no `agents/*.md` files.

Verified clean by socrates: zero occurrences of the four new names (or
`Euclidean` / `Ciceronian`) anywhere in the tree; all 33 occurrences of the six
functional names are lowercase-hyphenated; no chaining between mappings.

---

## Out of scope — findings to surface at DELIVER

- `docs_site/gen_catalog.py:75` hardcodes a **second** roster in
  `AGENT_GROUPS`; its committed output `docs_site/docs/agents.md` is already
  stale (predates this work, caused by PR #90). Nothing runs it in CI and
  there is no test for it.
- `agents/builder.md`, `builder-simple.md`, `builder-standard.md` each claim
  "You are the only agent in this crew with write access to production code" —
  three agents cannot all be the only one.
- `agents/orchestrator.md`: "fold Critic**'** surviving challenges".
- `docs_site/docs/assets/diagrams/diagram-crew.svg` and
  `brand/make_diagrams.py` depict the old crew.

## Verification

`python -m unittest tests.test_agent_definitions tests.test_apply_theme` green
after commit A. `python scripts/apply_theme.py --dry-run philosophers` reports
**7** renames after commit A and **11** after commit B.
