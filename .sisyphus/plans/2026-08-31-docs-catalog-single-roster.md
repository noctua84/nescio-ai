# Eliminate the second crew roster in docs_site/

**Status: built and shipped as PR #112.** Rewritten after the fact to describe what
was actually built. The original plan proposed the opposite design on two of its
central points; that reversal is recorded below rather than erased, because the code
looks the way it does *because* of it and a future reader will otherwise revert it.

Branch `chore/docs-catalog-single-roster`, off `origin/main`.

## The problem

`docs_site/gen_catalog.py` generates the tracked pages `docs_site/docs/agents.md` and
`skills.md` from the YAML frontmatter of `agents/*.md` and `skills/*/SKILL.md`. Its
`AGENT_GROUPS` constant hardcoded a **second, independent roster** of 11 agents while
`agents/` held 17. The six added by PR #90 fell through `_group()`'s leftover branch
into an "Other" bucket behind a warning nothing read — and the committed page did not
even show that, because nobody had rerun the generator since.

Three holes let it rot:
- `.github/workflows/docs.yml` never ran the generator.
- `gen_catalog.py` was not registered as a mkdocs hook.
- `docs_site/test_gen_catalog.py::test_committed_pages_are_up_to_date` **already
  existed and was already failing** — but `tests.yml` runs `discover -s tests`, which
  never reaches `docs_site/`. The assertion existed the whole time. Nothing asked it.

That last point is the real lesson of this plan, and it recurs below.

## What shipped

### 1. The roster comes from the filesystem, not from a second list

`AGENT_GROUPS` is a **routing table** (which bucket a name renders under), never a
roster (which agents exist). Membership comes from `agent_paths()`, the live directory
listing the count-guard already walked.

The original brief asked for the roster to be imported from
`scripts/_crew_common.py`. **Refused, and the refusal held through two reviews.**
`_crew_common` is itself a hand-maintained list; importing it would have replaced one
hardcoded roster with a dependency on another. And `expected_roster(theme)` needs a
`theme`, obtainable only via `apply_theme.detect_theme(agents_dir)` — which reads
`agents/`. The import bottoms out at the filesystem anyway, one indirection later.

Note the *stated* reason for the `docs_site`-off-`scripts` boundary is prose that
nothing enforces (`test_site_content.py` already inserts `_REPO_ROOT`). The argument
above stands without it; do not lean on the boundary.

### 2. The catalog ships functional names

`PAIRS` renames 9 agents plus 2 builder tier variants under the optional philosopher
theme. The theme is rendered locally, never committed, so the published catalog ships
**functional** names. Pinned by `TestThemedRosterIsRefused`, which asserts all 11
aliases are unrouted — routing any one of them shrinks that set and reds the test.

This is pinned deliberately rather than left emergent. It previously "worked" only
because philosopher names happened not to be listed, which a future author could have
silently deleted by routing both name sets.

### 3. Six buckets

    Coordinate         orchestrator
    Discover           scout, explore, librarian, vision
    Plan and challenge planner, validator, critic, advisor
    Build              builder, builder-standard, builder-simple, test-writer
    Verify             qa-guard, reviewer
    Document           doc-researcher, doc-writer

Ordering came from `main`, not from this branch — see "Converged with main" below.
`critic` before `advisor` is load-bearing: `test_site_content.py::CrewRosterTest`
compares this table against `brand/make_diagrams.CREW_GROUPS` **in order**.

### 4. THE REVERSAL — the generator is lenient; the guarantee is a test

The branch originally made `_group()` strict in both directions: an unrouted agent, or
a routed name with no file, raised `CatalogError` and failed the build. `gen_catalog.py
--check` went into the **required** `tests` CI job.

**The owner reversed this, and was right.** The docs site is presentation, not part of
running the framework. Gating merges on catalog drift taxes every outside contribution
with a subsystem the contributor does not care about — and forces an *editorial*
judgement (which bucket) under threat of a red build. That produces worse documentation,
not better.

So, as shipped:
- `_group()` has no `strict` parameter. An unrouted agent renders under "Other" with a
  warning. `THEME_HINT` moved to the test module, its only remaining consumer.
- The both-direction guarantee lives in
  `test_gen_catalog.py::TestAgainstTheRealRepo::test_agent_groups_routes_exactly_the_roster`,
  in the maintainer-facing suite.
- `--check` is **not** in the required `tests` job. Catalog drift is not a merge gate.

Record this reasoning, because it reads like a regression on sight: lenient-plus-visible
was never the defect. Under the original bug the page silently **omitted** six agents;
under this design they would have self-published under "Other" on a site that still
deployed. The defect was a tracked artefact nobody regenerated.

Untracking the generated pages entirely was considered — `brand/dist/` is the same kind
of thing and is gitignored — and **rejected**. They stay tracked.

### 5. The deploy self-heals

`docs.yml` runs `python docs_site/gen_catalog.py` (a real regeneration, in the ephemeral
runner checkout) **before** `mkdocs build`. Ordering matters: it makes the check-only
mkdocs hook pass. The published site is therefore correct regardless of whether the
committed copy is current, so a contributor's un-regenerated page is untidy, never
site-breaking.

### 6. The mkdocs hook is check-only, and advisory

`on_pre_build` calls `generate(check_only=True)`. A **writing** hook was measured
rewriting the tracked source page mid-build (11 -> 17 sections, exit 0) — mutating a
developer's working tree during a test run and laundering the drift it should report.
Both write paths sit inside the `else:` of `if check_only:`; calling `on_pre_build(None)`
leaves every file byte- and mtime-identical.

The refusal applies to the **writing** hook specifically, not to hooks in general. That
distinction was itself a reversal — the check-only variant was initially rejected along
with the writing one, wrongly.

### 7. `docs-tests` is a maintainer drift detector, on the `roadmap` trigger

A second, non-required job runs the `docs_site/` unittest root — a separate discovery
root that `discover -s tests` cannot reach.

It runs on **push-to-main, schedule and workflow_dispatch, never `pull_request`**,
using the same job-level `if:` as the `roadmap` job. Reason, the same one `roadmap`
gives: docs drift is produced by a merge, not by the PR under review. A PR run would
red honest contributions for a subsystem this branch deliberately stopped gating on,
while catching nothing a post-merge run would miss.

Consequence worth stating plainly: **"make `docs-tests` required" is now structurally
impossible, not merely discouraged.** A job that does not run on pull requests cannot
be a merge gate. That is the intended end state, not an omission.

Install tolerance: `pip install mkdocs-material` carries `continue-on-error` with
retries, because a PyPI blip must not red a job nobody re-runs cheaply. The suite is
split by dependency so an outage costs as little as possible — only `BuiltSiteTest`
needs mkdocs, and it self-skips. Everything else, including the roster-equality test
and `CrewRosterTest`, runs regardless.

## Converged with main

While this branch was in flight, `main` independently solved overlapping parts. Where
it got there first or better, this branch took its work:

- **Crew diagram**: main redrew the full 17-agent roster and made the caption count
  *derived* (`sum(len(agents) for _, agents in CREW_GROUPS)`). This branch had only
  de-counted the caption — a symptom fix. Main's is the root fix. Ours was discarded.
- **`AGENT_GROUPS` ordering and its rationale comments**, including `critic` before
  `advisor`.
- **The `--check` step's comment**, when both branches added the identical step.

## Verification

    PYTHONPATH=scripts py -3.13 -m unittest discover -s tests     # 651 OK
    py -3.13 -m unittest discover -s docs_site                    # 80 OK
    py -3.13 docs_site/gen_catalog.py --check                     # exit 0
    py -3.13 scripts/scrub_check.py docs_site/docs/agents.md      # publish-surface gate

Python 3.13 via `py -3.13`; the default `python` here is 3.14 and cannot run discovery.
**Never pytest** — the local wrapper uses an out-of-contract interpreter and reports a
spurious `Path.read_text() ... newline` TypeError.

`scrub_check` on the catalog is listed because this PR put six agent descriptions on the
public web for the first time, and that gate otherwise runs only post-merge in `docs.yml`.

## Not done, deliberately

- **Untracking the generated pages.** Considered, rejected; they stay in git.
- **`docs/design/docs-site-mockup.html`** still carries stale "nine specialists" copy
  and a hardcoded 10-agent nav. A frozen design artefact.
  `docs/plans/2026-08-19-docs-site.md:63` calls it "untracked scratch" although it is
  tracked — its tracked status may itself be unintended.
- **Making `docs-tests` required.** Now incoherent by construction; dropped, not deferred.

## Open, worth a follow-up

- Nothing asserts the two `-p` patterns in `docs-tests` cover `docs_site/` between them.
  A third `test_*.py` added there would run in **neither** step, silently. Same defect
  class as the one this plan removed, one layer down in CI config. `MaterialPinTest`
  already establishes that stdlib-regex parsing of workflow files is acceptable here.
- `SKILL_GROUPS` is lenient in both directions, so a deleted skill degrades to a warning
  nothing reads. Asymmetric with the roster-equality test now covering agents.
- 11 prose citations of `mkdocs-material` 9.7.7 across 6 files are undetected on a bump;
  `MaterialPinTest` covers only the two workflow files.
- `memory/repo/nescio/adr/0001-no-agent-frameworks-in-nescio.md:55` cites `tests.yml:31`
  for a line this branch displaced. Already stale beforehand; widened here. The durable
  fix is citing the job name, per `_crew_common.py:51` ("cited by symbol, not by line").
