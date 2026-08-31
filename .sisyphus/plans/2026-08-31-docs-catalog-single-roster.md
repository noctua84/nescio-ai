# Eliminate the second crew roster in docs_site/

Branch: `chore/docs-catalog-single-roster` off `origin/main` (714ea43, merge of #109).
Reviewed by `validator` (REJECT, narrow — both blockers resolved below) and `socrates`
(Material objections — all adopted). Revisions from that review are marked **[rev]**.

## Verified starting state

| Fact | Evidence |
|---|---|
| `AGENT_GROUPS` hardcodes 11 of 17 agents | `docs_site/gen_catalog.py:75` |
| The 6 PR-#90 agents fall to Other with a **non-fatal** warning | `_group()` leftover branch; `generate()` prints to stderr and continues |
| `docs_site/docs/agents.md` is stale | `gen_catalog.py --check` exits **1** (`:588`) |
| `docs.yml` never runs the generator | no such step |
| **A drift test already exists and already fails** | `docs_site/test_gen_catalog.py:268` -> `generate(repo, check_only=True)` |
| It has never run in CI | `tests.yml` runs `discover -s tests`; docs_site is a separate root |
| `main` required checks are exactly `["tests"]` | live: `gh api .../branches/main/protection` |
| Registering the writing hook **rewrites the tracked source page** | measured: md5 `054e77fe`->`f7067e38`, 11->17 sections, build exits 0 |
| `_crew_common.expected_roster()` is CI-verified against `agents/*.md` | `tests/test_agent_definitions.py:185` |
| The docs_site-off-scripts boundary is **prose, unenforced** | `test_site_content.py:136` already does `sys.path.insert(0, _REPO_ROOT)` |

Baseline: `tests/` 627 pass. `docs_site/` 60 run, 1 **error** (the drift test), 1 skip (mkdocs
absent locally); with mkdocs installed, 68 run, same single error, **zero** skips.

## Decision 1 — grouping stays local; membership comes from the filesystem

`gen_catalog.py` does **not** import `_crew_common`.

**[rev]** The load-bearing reason is not the isolation boundary (which nothing enforces).
It is that `expected_roster(theme)` needs a `theme`, obtainable only via
`apply_theme.detect_theme(agents_dir)` — which reads `agents/`. Importing it means pulling two
modules from `scripts/` to reach the directory `gen_catalog` already walks in `agent_paths()`.
That is not a more authoritative view of the roster; it is the same fact, one indirection later.
`CODE_WRITERS` and friends are assertions *about* frontmatter that `_agent_meta()` already
renders directly — publishing them would be publishing the test.

## Decision 2 — the catalog ships functional names, pinned not accidental

**[rev]** `_group()` becomes fatal in **both** directions for agents, so `AGENT_GROUPS` is
pinned to equal `agents/*.md` as a set. Previously only filesystem->table was checked, leaving
the theme refusal emergent: a future author routing philosopher aliases would silently publish
`plato` to the public site. Both-way pinning makes a themed tree fail deterministically and
self-explainingly, with no `PAIRS` import.

## Decision 3 — six buckets

    Coordinate         orchestrator
    Discover           scout, explore, librarian, vision
    Plan and challenge planner, validator, advisor, critic
    Build              builder, builder-standard, builder-simple, test-writer
    Document           doc-researcher, doc-writer          [rev] new
    Verify             reviewer, qa-guard

The `doc-writer` charter says it does not write code; filing it under Build was the only fit
among five and a poor one. The new bucket keeps the research->write pair adjacent.

## Task 1 — AGENT_GROUPS becomes a routing table

`docs_site/gen_catalog.py`
- Add the `Document` bucket and route all 17 agents per Decision 3.
- `_group(items, groups, *, strict=False)`. Agents pass `strict=True`; skills stay lenient
  (33 curated entries, different churn profile). Under strict, **both** an unrouted definition
  and a table entry with no definition on disk raise `CatalogError`.
- Error text lists the offending names, says to update `AGENT_GROUPS`, and adds: if the
  philosopher theme is applied, run `scripts/apply_theme.py functional` before regenerating,
  because the published catalog ships functional names.
- Update the grouping comment (`:66-72`): its promise that anything unlisted still renders
  under Other is no longer true for agents.

**[rev] Task 1a — four committed tests break under strict; fix them in the same commit.**
Measured: `Ran 25 tests ... FAILED (errors=4)`.
- `test_gen_catalog.py:156 test_unmapped_name_still_renders` — directly contradicts strict.
  **Rewrite**, do not delete: assert `CatalogError` for the agent path, and keep the lenient
  Other assertion by exercising `SKILL_GROUPS` instead.
- `test_gen_catalog.py:233 test_name_location_mismatch_warns_but_renders` — its `name: scoutt`
  fixture is unrouted. Route the fixture name, or assert the new behaviour.
- `test_gen_catalog.py:193 test_addition_does_not_fire_the_guard` — fixture agent `newcomer`
  is unrouted. Same fix.
- `test_gen_catalog.py:175 test_fires_when_a_definition_never_reaches_the_page` — monkeypatches
  `_group(items, groups)`; the new `strict=` kwarg raises `TypeError`. Update the stub signature.

**[rev] Task 1b — pin the refusal.** Add a test asserting a themed roster is refused, so
Decision 2 cannot be silently deleted by a future author.

Acceptance: `docs_site` suite green except the known drift error; removing any agent from
`AGENT_GROUPS` exits non-zero; adding an unrouted `agents/*.md` exits non-zero.

## Task 2 — regenerate and commit

`python docs_site/gen_catalog.py`; commit `docs_site/docs/agents.md`.
Acceptance: 17 item sections, count line reads 17, no Other heading, `--check` exits 0.

## Task 3 — close the drift loop **inside the required gate** [rev]

The original plan put this in a new job. Both reviewers rejected that: `main` requires only
`["tests"]`, so a new job is red-but-mergeable — moving the drift test from *never runs* to
*runs and is ignorable*. The cited FRAMEWORK_PATHS rationale was a category error: that rule
forbids `tests/` **importing** `docs_site/`; a `run:` step is a separate process with a separate
`sys.path`, and `.github/` never reaches a derived instance at all.

- **In the existing required `tests` job**, append a step running
  `python docs_site/gen_catalog.py --check`. Stdlib-only, no new dependency, inside the gate
  that actually blocks merges.
- **New non-required `docs-tests` job**: install `mkdocs-material==9.7.7`, then
  `python -m unittest discover -s docs_site`. Covers the other 67 tests including the 13
  `BuiltSiteTest` cases (confirmed passing) and `test_committed_copies_match_the_generator`.
  Kept out of the required job deliberately: a network install in the blocking check means a
  PyPI blip reds every PR.
- **Backstop**: the same `--check` invocation in `docs.yml` before `mkdocs build`.
- **Manual follow-up, cannot be done by a commit**: adding `docs-tests` to branch protection.
  Named here as an owner-action, not left implicit.

**[rev] Ordering constraint**: the strict generator (Task 1) and the required-job step must
land in the same commit. Strict generator plus non-blocking check is worse than either
alternative: an unrouted agent would pass every required check, merge, and break the Pages
deploy on `main`.

**[rev] Hook — check-only, registered.** Reversed from the original refusal. `on_pre_build`
calling `generate(check_only=True)` writes nothing, launders nothing, and makes a *local*
`mkdocs build` refuse on drift — which a CI-only guard never does. The refusal applies to the
**writing** hook specifically (measured above: it mutates tracked files during a test run),
not to hooks in general. Record that distinction so it is not re-litigated.

Acceptance: revert `agents.md` -> the `tests` job step fails; restore -> green.

## Task 4 — register the obligation where the next author reads it

`CONTRIBUTING.md`, new "Adding an agent" section: create `agents/<name>.md`; update
`_crew_common` (`PAIRS` or `THEME_INVARIANT_ROSTER`, plus the write-policy sets); route it in
`gen_catalog.AGENT_GROUPS`; run the generator and commit its output; run **both** suites,
noting the docs_site one is not discovered by the `tests/` command.

## Task 5 — de-caption the crew diagram [rev, user-approved]

Not scope creep: this PR is what falsifies it. `agents.md` will say 17 while the homepage
inlines the claim of one orchestrator and nine specialists. Correcting that number to sixteen
over artwork that draws nine would be worse, so **remove the count** rather than assert a new
one the artwork cannot support.
- `brand/make_diagrams.py:279` -> keep only the second clause: delegation goes down, every
  result comes back through the gate.
- Re-run `python brand/make_diagrams.py`, copy the tokenised source over
  `docs_site/docs/assets/diagrams/diagram-crew.svg`.
- Enforced by `test_site_content.py:130 test_committed_copies_match_the_generator`, which
  imports `make_diagrams` in-process and will run in CI via Task 3.

Full redraw (7 missing agents) -> **spawned task**, created at delivery, not a recommendation.

## Verification

    PYTHONPATH=scripts py -3.13 -m unittest discover -s tests
    py -3.13 -m unittest discover -s docs_site
    py -3.13 docs_site/gen_catalog.py --check
    py -3.13 scripts/scrub_check.py docs_site/docs/agents.md

The last is a publish-surface gate: this PR puts six agent descriptions on the public web for
the first time, and `scrub_check` otherwise runs only post-merge in `docs.yml`.

Python 3.13 via `py -3.13`; default `python` here is 3.14 and cannot run discovery. Never pytest.
