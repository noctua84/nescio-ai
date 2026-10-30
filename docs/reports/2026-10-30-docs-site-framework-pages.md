# QA Audit Report: docs site — framework/tooling pages batch

**Date:** 2026-10-30
**Auditor:** Pyrrho
**Scope:** branch `docs/site-framework-pages`, commits `bd01f74..42f1455` (merge-base
`3c3ca4e`, HEAD `42f1455344e23ad429b9977b2a7d8c641eb4d518`), audited against
`.sisyphus/plans/docs-site-framework-pages.md`. 18 files, +3454/-182.
**Severity Summary:** 0 Critical | 0 Major | 8 Minor | 6 Info

## Executive Summary

No functional defects found. Every factual claim I could reach on the four new/changed
pages (`commands.md`, `lifecycle.md`, `hooks.md`, `agents.md`'s theme section) checks out
against its source, the fence-aware parsers are correct on the real
`agents/orchestrator.md`, the MkDocs hook `sys.path` hazard is handled correctly (and
mkdocs 1.6.1's wholesale `sys.path[:] = old_sys_path` restore actually *contains* the
repo-root insert to module-exec time, which is better than the plan assumed), and the test
suites are unusually non-vacuous — three of them guard their own guards. The findings are
all documentation/comment inaccuracies, plan-alignment gaps, and latent fragilities. One
item is delivery paperwork that is genuinely outstanding: `gen_catalog.py` is **672 lines
against a 400-line tripwire** and the plan's mandated `Module-check:` verdict cannot exist
yet because there is no PR.

## Findings

### [MINOR] The module gate is not met and the mandated waiver record is absent

**Category:** Maintainability
**File(s):** `docs_site/gen_catalog.py` (672 lines), `docs_site/catalog_core.py:14-19`
**Confidence:** VERIFIED
**Status:** New

**Description:**
Plan Task 1's whole justification was the 400-line tripwire, and its acceptance criterion
was "`module_scan.py --json` shows `gen_catalog.py` materially smaller (**expect
~480-520**)". Measured: 732 at merge-base → **606** after T1 (`bd01f74`) → **672** at HEAD.
It never entered the expected band, and it is 272 lines over the gate. Three new test
modules are also over 400 (`test_gen_reference.py` 539, `test_gen_commands.py` 475,
`test_gen_lifecycle.py` 407), against Success Criterion 7's "no new file exceeds 400
lines".

**Evidence:**
`python scripts/module_scan.py --json` at HEAD, filtered to this branch's files:
```
{'path': 'docs_site/gen_catalog.py', 'lines': 672}
{'path': 'docs_site/test_gen_reference.py', 'lines': 539}
{'path': 'docs_site/test_gen_commands.py', 'lines': 475}
{'path': 'docs_site/test_gen_lifecycle.py', 'lines': 407}
tripwire 400
```
`git show origin/main:docs_site/gen_catalog.py | wc -l` → `732`;
`git show bd01f74:docs_site/gen_catalog.py | wc -l` → `606`.

`docs_site/catalog_core.py:19` states, verbatim:
> `lower breaks the cycle and brings ``gen_catalog.py`` back under the gate.`

That sentence is false — the file is 672 lines. The extraction *did* shrink it (732 → 672
net), but "back under the gate" overstates the result by 272 lines, and a future reader
will trust the docstring over the scanner.

`gh pr list --head docs/site-framework-pages --json number` → `[]` — no PR exists, so the
`Module-check:` verdict plan decision 6 and T11 require is outstanding.

**Impact:**
A stated acceptance criterion is unmet and the compensating control (a `Module-check:`
verdict naming before/after counts) does not yet exist. The 400-over test modules are
consistent with existing repo practice (`tests/test_agent_definitions.py` is 1726 lines and
tolerated), so the real residue is `gen_catalog.py` plus one false docstring sentence.

**Reproduction Steps:**
1. `python scripts/module_scan.py --json`
2. Filter `over` for `docs_site/gen_catalog.py`.
3. Expected per plan T1: ~480-520. Actual: 672.

**Recommended Fix:**
Amend `catalog_core.py:19` to say what is true ("shrinks `gen_catalog.py` by ~60 lines; it
remains over the 400-line tripwire and carries a `Module-check:` verdict"). Carry a
`Module-check:` line in the PR body naming `gen_catalog.py` 732 → 672 (and the three test
modules) with the accept-and-why rationale. No code change required.

---

### [MINOR] `build_pages`'s comment and `test_gen_theme`'s docstring both state the theme fragment is appended *after* the count-guard runs — it is appended before

**Category:** Maintainability
**File(s):** `docs_site/gen_catalog.py:524-534`, `docs_site/test_gen_theme.py:196-201`
**Confidence:** VERIFIED
**Status:** New

**Description:**
Two places state, as the safety argument for why a stray `` ### ` `` in the theme fragment
cannot corrupt the agents count-guard, that the fragment is appended after the guard runs.
The actual call order is the reverse: the fragment is concatenated into `agents_page` on
line 529, and `check_count("agents", agents_page, ...)` runs on line 534 against the
already-concatenated string.

**Evidence:**
`docs_site/gen_catalog.py:524-534`, verbatim at HEAD:
```
    # The theme fragment is appended AFTER the detail sections (and after the
    # count-guard below runs against it) so it cannot shift "## At a glance"
    # later than any "### `name`" heading, and it introduces none of its own
    # (see gen_theme's docstring), so the guard's count is unaffected either
    # way.
    agents_page = agents_page.rstrip() + "\n\n" + gen_theme.render_theme_section()
    skills_page, skill_warnings = render_skills(skills)
    commands_page, commands_warnings = gen_commands.render_commands(commands)
    lifecycle_page, lifecycle_warnings = gen_lifecycle.render_lifecycle(repo_dir)

    check_count("agents", agents_page, agent_paths(repo_dir), repo_dir)
```
`docs_site/test_gen_theme.py:200`, verbatim:
> `    detail headings. The fragment is appended after that guard runs, so a`

**Impact:**
Documentation only. The invariant still holds, and the failure mode is loud rather than
silent: if the fragment ever grew a `` ### ` `` heading, `check_count` would see `N+1`
against a live listing of `N` and raise `CatalogError`, failing the build. But the comment
misstates *why* the code is safe, which is the kind of reasoning a later editor relies on
when deciding whether reordering these five lines is safe. The real protection is
`test_gen_theme.py::HeadingShapeTest::test_fragment_has_no_item_heading`, which does exist.

**Reproduction Steps:**
1. Read `docs_site/gen_catalog.py:524-534`.
2. Observe line 529 (append) precedes line 534 (`check_count`).
3. Expected per comment: guard first. Actual: append first.

**Recommended Fix:**
Rewrite both comments to the true argument: "appended before the guard runs; the guard
therefore counts the fragment too, which is safe because the fragment carries no
`` ### ` `` heading (pinned by `test_gen_theme.py::HeadingShapeTest`) and would otherwise
fail the build loudly rather than miscount."

---

### [MINOR] `agents.md`'s banner no longer names all of the page's sources

**Category:** Maintainability
**File(s):** `docs_site/docs/agents.md:1-2`, `docs_site/gen_catalog.py:436`
**Confidence:** VERIFIED
**Status:** New

**Description:**
This batch added `catalog_core.generated_banner(source)` precisely so each generated page
names its real input, and used it for `commands.md` and `lifecycle.md`. `agents.md` keeps
the old literal `GENERATED_BANNER`, which names only agent/skill frontmatter — but the page
now also renders a table whose "why" column comes from `scripts/_crew_common.PAIR_RATIONALE`.

**Evidence:**
`docs_site/docs/agents.md:1-2`, verbatim at HEAD:
```
<!-- Generated by docs_site/gen_catalog.py from the YAML frontmatter of
     agents/*.md and skills/*/SKILL.md. Do not edit by hand. -->
```
`docs_site/gen_catalog.py:436` passes `GENERATED_BANNER` (the literal), not
`generated_banner(...)`. The deliberate rationale is in `catalog_core.py:61-71`:
> `` `GENERATED_BANNER` above is a literal, kept verbatim for ``agents.md``/ ``skills.md`` so neither page's committed banner line churns for no reason.``

**Impact:**
A contributor who wants to fix a wrong "why" cell reads the banner, looks in
`agents/*.md` frontmatter, finds nothing, and either gives up or hand-edits the generated
page. Exactly the discoverability failure the `generated_banner(source)` helper was added
to fix, left unfixed on the one page that gained a second source.

**Reproduction Steps:**
1. Read `docs_site/docs/agents.md:1-2`.
2. Read `docs_site/docs/agents.md:139-148` (the theme table).
3. Expected: banner names `scripts/_crew_common`. Actual: it names only agent/skill frontmatter.

**Recommended Fix:**
Switch `agents.md` to `generated_banner("the YAML frontmatter of agents/*.md and skills/*/SKILL.md, plus the theme table in scripts/_crew_common.py")` and regenerate. Accept the
one-time banner churn; the plan's "no banner churn" preference was written before the page
gained a second source.

---

### [MINOR] `gen_commands.py` and `gen_lifecycle.py` still assert `docs_site/` is stdlib-only with respect to `scripts/` — the docs build now hard-requires `scripts/_crew_common.py`

**Category:** Maintainability
**File(s):** `docs_site/gen_commands.py:10-11`, `docs_site/gen_lifecycle.py:29-30`
**Confidence:** VERIFIED
**Status:** New

**Description:**
Both new renderer docstrings carry a blanket claim about "the rest of `docs_site/`" that the
same batch invalidated. `catalog_core.py:21-28` gets this exactly right (scoping the claim to
itself and naming `gen_theme` as the exception); the other two modules repeat the old,
now-false generalisation.

**Evidence:**
`docs_site/gen_commands.py:10-11`, verbatim:
> `Stdlib only, same constraint as the rest of ``docs_site/``: the docs build must`
> `work with nothing from ``scripts/`` on ``PYTHONPATH``.`

`docs_site/gen_lifecycle.py:29-30`, verbatim:
> `Stdlib only, like the rest of ``docs_site/``: the docs build must work with`
> `nothing from ``scripts/`` on ``PYTHONPATH``.`

Contradicted by `docs_site/gen_theme.py:61-69`, which inserts the repo root on `sys.path`
and raises `CatalogError` if `scripts/_crew_common.py` is absent — i.e. the docs build now
*fails* on a checkout without `scripts/`.

**Impact:**
The literal statement ("nothing from `scripts/` on `PYTHONPATH`") remains true — no
`PYTHONPATH` is needed. What is now false is the implication that the docs build is
independent of `scripts/`. A reader of either of these two modules will draw the wrong
conclusion about whether a partial checkout can build the site.

**Reproduction Steps:**
1. Read `docs_site/gen_commands.py:10-11`.
2. Read `docs_site/gen_theme.py:61-69`.
3. Expected: consistent claims. Actual: contradictory.

**Recommended Fix:**
Narrow both to `catalog_core.py`'s wording: "this module is stdlib-only; note
`gen_theme.py` reads `scripts/_crew_common` through a top-level repo-root `sys.path`
insert, so the docs build does require `scripts/` to be present in the tree (but never on
`PYTHONPATH`)."

---

### [MINOR] The theme fragment hardcodes "two" builder tiers while deriving every other count, and its `and`-join degrades past two

**Category:** Bug (latent drift)
**File(s):** `docs_site/gen_theme.py:88-107`
**Confidence:** VERIFIED
**Status:** New

**Description:**
`render_theme_section` derives `renamed_total` and `len(pairs)` from the constants, exactly
as the plan demands — then writes the word "two" as a literal in the same sentence, and
joins `TIERED_AGENTS` with `" and "`.

**Evidence:**
`docs_site/gen_theme.py:90` and `:105-107`, verbatim at HEAD:
```
    tiered_names = " and ".join(f"`{name}`" for name in tiered)
```
```
        f"The two builder cost tiers ({tiered_names}) follow `builder`, so "
        f"{renamed_total} files are renamed in all: the {len(pairs)} pairs above "
        f"plus the two builder tiers.",
```
Rendered today (`docs_site/docs/agents.md:152`):
> `The two builder cost tiers (`builder-simple` and `builder-standard`) follow `builder`, so 11 files are renamed in all: the 9 pairs above plus the two builder tiers.`

**Impact:**
Add a third tier to `_crew_common.TIER_VARIANTS` and the page renders a self-contradicting
sentence: "The two builder cost tiers (`builder-simple` and `builder-standard` and
`builder-x`) follow `builder`, so 12 files are renamed in all: the 9 pairs above plus the
two builder tiers." `test_gen_theme.py::test_renamed_total_is_derived` and
`test_pairs_figure_is_derived` both still pass, because neither derives the word "two".
This is the same class of defect as the "Ten agents / 16 agents" drift the batch exists to
eliminate, surviving in the one sentence that was not derived.

**Reproduction Steps:**
1. Add `"turbo"` to `scripts/_crew_common.TIER_VARIANTS`.
2. `python -c "import sys;sys.path.insert(0,'docs_site');import gen_theme;print(gen_theme.render_theme_section())"`
3. Expected: a consistent sentence. Actual: "two" appears twice while the derived figures say three tiers / 12 files. `python -m unittest discover -s docs_site -p "test_gen_theme.py"` stays green.
4. Revert.

**Recommended Fix:**
Derive the count word (`len(tiered)`, or a tiny `_count_word` helper) and use an Oxford-safe
join (`", ".join(...[:-1]) + " and " + ...[-1]` for n>2). Add a `test_gen_theme` case that
patches `TIERED_AGENTS` to three entries and asserts no literal "two" survives.

---

### [MINOR] The theme fragment is the only page content using ASCII `--`, which renders literally (no smartypants extension is enabled)

**Category:** Maintainability (presentation)
**File(s):** `docs_site/gen_theme.py:96`, `:109`; `docs_site/docs/agents.md:141`, `:154`; `docs_site/mkdocs.yml:109-116`
**Confidence:** VERIFIED
**Status:** New

**Description:**
Every other generated page uses the em dash `—`. The theme fragment uses `--`, and
`mkdocs.yml`'s `markdown_extensions` list contains no `smarty` / `pymdownx.smartsymbols`,
so `--` is published verbatim as two hyphens.

**Evidence:**
`docs_site/mkdocs.yml` `markdown_extensions`, verbatim at HEAD:
```
markdown_extensions:
  - abbr
  - admonition
  - attr_list
  - md_in_html
  - toc:
      permalink: true
  - pymdownx.details
  - pymdownx.superfences
```
Dash census across the committed pages (`grep -c -- " -- "`): `index.md:0`,
`skills.md:0`, `lifecycle.md:0`, `hooks.md:0`, `commands.md:0`, `agents.md:2` — both
`agents.md` hits are the theme fragment:
`docs_site/docs/agents.md:141` → `...after Graeco-Roman philosophers -- the same renaming...`
`docs_site/docs/agents.md:154` → `The remaining agents -- `explore`, ... -- keep their functional names under both themes.`

**Impact:**
Two visible `--` on the published Agents page where the rest of the site shows `—`.
Cosmetic, user-visible, and the only typographic inconsistency on the site.

**Reproduction Steps:**
1. `grep -n -- " -- " docs_site/docs/*.md` → only `agents.md`, lines 141 and 154.
2. Confirm no smarty extension in `docs_site/mkdocs.yml`.

**Recommended Fix:**
Replace the two `--` in `gen_theme.py` with `—` to match sibling renderers, and regenerate.

---

### [MINOR] Plan-specified test assertions are missing: `hooks.md` not in `build_pages()` output, and a `--check` hand-edit case for `commands.md`

**Category:** Maintainability (test coverage)
**File(s):** `docs_site/test_gen_reference.py:177-190`, `docs_site/test_gen_commands.py:430-471`
**Confidence:** VERIFIED
**Status:** New

**Description:**
Two assertions the plan enumerates were not written.

Plan T10: *"Assert `hooks.md` is **not** in `gen_catalog.build_pages()`'s output — it is
hand-written and must stay so."* `test_gen_reference.py` never imports or calls
`build_pages`; the nearest thing is a banner-absence check.

Plan T7: *"`--check` detects a hand-edit of `commands.md`; the **committed**
`docs/commands.md` matches a fresh render."* `test_gen_commands.py::TestAgainstTheRealRepo`
checks only that each live command reaches a *freshly rendered* page; it never reads
`docs_site/docs/commands.md`.

**Evidence:**
`docs_site/test_gen_reference.py:178-186`, verbatim — the closest substitute:
```
    def test_page_is_present_and_not_generated(self):
        self.assertTrue(_PAGE.is_file(), f"missing {_PAGE}")
        text = _page()
        self.assertNotIn(
            "Generated by",
            text,
            "hooks.md is hand-written; a generated banner means the contract "
            "of this test file changed",
        )
```
`docs_site/test_gen_commands.py` contains no occurrence of `docs/commands.md` or
`build_pages` (whole file read at HEAD).

**Impact:**
Mostly covered in practice, which is why this is MINOR rather than MAJOR:
- The committed-page guarantee for **all four** pages is held by
  `docs_site/test_gen_catalog.py:705-706`, verbatim:
  ```
      def test_committed_pages_are_up_to_date(self) -> None:
          gen_catalog.generate(self.repo, check_only=True)
  ```
  `generate(..., check_only=True)` compares every entry of `build_pages`, so a hand-edited
  `commands.md` does fail — in `test_gen_catalog.py`, not in the commands suite, with a
  message that does not point at the commands generator.
- The hooks-page assertion is partially covered: every generated page carries a banner, so
  a future wiring commit that generated `hooks.md` would trip the banner check. It would
  *not* be caught if someone added `hooks.md` to `build_pages` without a banner.

Note this repo deliberately does **not** gate merges on `gen_catalog.py --check`
(`.github/workflows/tests.yml:136-150`), so these tests in the non-required `docs-tests`
job are the only guard.

**Recommended Fix:**
Add the two assertions as specified: `self.assertNotIn("hooks.md", gen_catalog.build_pages(REPO_DIR)[0])` in `test_gen_reference.py`, and a committed-page equality case in
`test_gen_commands.py::TestAgainstTheRealRepo` so the failure names the right generator.

---

### [MINOR] `build_pages`' docstring claims every page honours `repo_dir`; the theme fragment does not

**Category:** Maintainability
**File(s):** `docs_site/gen_catalog.py:512-517`, `docs_site/gen_theme.py:72-82`
**Confidence:** VERIFIED
**Status:** New

**Description:**
Commit `8d6f7e2` fixed a `REPO_DIR` leak so commands and lifecycle render from
`build_pages`' `repo_dir`. `gen_theme.render_theme_section()` takes no `repo_dir` and reads
the module-level `scripts._crew_common` imported from the real `REPO_DIR` — so a
fixture-repo `build_pages(tmp)` still embeds the *live* crew's theme table in the fixture's
`agents.md`.

**Evidence:**
`docs_site/gen_catalog.py:512-517`, verbatim:
```
    """Render all four pages in memory. Returns ({filename: text}, warnings).

    Every page honours ``repo_dir`` -- that parameter exists so
    ``test_gen_catalog.py`` can point this function at a small synthetic
    fixture tree instead of the real repo, and the real CLI and the MkDocs
    hook run it against ``REPO_DIR`` by default.
    """
```
`docs_site/gen_theme.py:72` — the signature, verbatim: `def render_theme_section() -> str:`
(no parameter), reading `_crew_common` imported at `gen_theme.py:63` after
`sys.path.insert(0, str(REPO_DIR))` at `:61`.

**Impact:**
Benign today — the plan specifies this signature, the theme table is a repo-invariant, and
it introduces no `` ### ` `` heading. But it is the one page component the `8d6f7e2` fix did
not reach, and the docstring asserts otherwise. The concrete consequence is that any future
fixture-based assertion about `agents.md`'s *absent* content is silently contaminated by
live `_crew_common` data.

**Recommended Fix:**
Amend the docstring: "Every *generated page body* honours `repo_dir`; the appended theme
fragment is deliberately repo-invariant and reads `scripts/_crew_common` from `REPO_DIR` —
see `gen_theme.render_theme_section`." No signature change needed.

---

### [INFO] `_find_anchor` dispatches on anchor kind inside an unparenthesised conditional expression

**Category:** Maintainability
**File(s):** `docs_site/orchestrator_spine.py:84-91`
**Confidence:** VERIFIED

**Description:**
The line parses correctly (`==` binds tighter than the conditional expression, so it means
`(line.rstrip() == literal) if kind == "heading" else line.startswith(literal)`) and the
behaviour is right, but it reads as if the `if` statement's condition were
`line.rstrip() == literal`.

**Evidence:**
`docs_site/orchestrator_spine.py:89`, verbatim at HEAD:
```
        if line.rstrip() == literal if kind == "heading" else line.startswith(literal):
```

**Impact:** Pure readability. One misread and someone "fixes" it into a behaviour change
that silently moves which section `section_text` hashes — and the digest pin would then
fire with a message pointing at `agents/orchestrator.md` rather than at the parser.

**Recommended Fix:** Parenthesise, or hoist to
`matched = line.rstrip() == literal if kind == "heading" else line.startswith(literal)`.

---

### [INFO] Fence masking has two latent blind spots, neither of which fires on the real file

**Category:** Bug (latent)
**File(s):** `docs_site/orchestrator_spine.py:35`, `:76`, `:79`
**Confidence:** VERIFIED

**Description:**
(a) `_FENCE_RE` only matches a fence at ≤3 leading spaces, so a code fence indented 4+
spaces (a fenced block inside a nested list item) is not masked and its `## PHASE` /
`|` table lines would be read as structure. (b) `open_fence = match.group(1)[:3]`
truncates the opening run to three characters, so a ```` ``` ```` line *inside* a
```` ```` ````-fenced block closes the outer fence early.

**Evidence:**
`docs_site/orchestrator_spine.py:35`, `:76`, `:79`, verbatim:
```
_FENCE_RE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
```
```
                open_fence = match.group(1)[:3]
```
```
            if match and match.group(1).startswith(open_fence):
```
Measured against the real source — all 52 fence lines in `agents/orchestrator.md` are plain
三-backtick fences at indent 0 (50) or 3 (2), with no tilde fences, no 4+-run fences, and the
mask closes cleanly at EOF (`unclosed at EOF: None`). Independently corroborated by
`test_gen_lifecycle.py::RealRepoFactsTest::test_fixture_scan_agrees_with_the_generators_parser`,
which cross-checks the parser against a second, independently written fence scanner.

**Impact:** None today. If it ever fires, the failure is loud: `parse_phases` raises below
two phases, `_table_after` raises below three table lines, and `section_text` raises on a
missing anchor. The realistic bad outcome is an *extra* phase or a wrong table, which
`test_page_carries_no_phase_other_than_the_declared_ones` catches only because the test's
own scanner shares blind spot (a).

**Recommended Fix:** Optional. If hardened, keep the full opening run (`match.group(1)`)
and require the closer to be at least as long, which is CommonMark's rule; drop the indent
cap to `\s*` only if indented fences appear.

---

### [INFO] A command whose lead prose contains a fenced `` ### `name` `` line would red the docs build

**Category:** Bug (latent)
**File(s):** `docs_site/gen_commands.py:95-103`, `docs_site/gen_catalog.py:536-538`
**Confidence:** INFERRED

**Description:**
`_lead_prose` deliberately *includes* fenced blocks in the lead (proved by
`test_gen_commands.py::test_a_fenced_block_containing_headings_does_not_end_the_lead`). The
lead is then emitted verbatim into `commands.md`, which is counted by
`ITEM_HEADING_RE = ^### \``. A command whose lead — i.e. before its first real heading —
contained a fenced example line of the shape `` ### `x` `` would inflate the rendered count
and make `check_count("commands", ...)` raise.

**Evidence:**
`docs_site/gen_commands.py:97-99`, verbatim:
```
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            continue
```
`docs_site/gen_commands.py:231` emits `item.meta.get("lead", "")` into the page body, and
`docs_site/gen_catalog.py:536-538` runs the guard over that page.
Not reachable today: both live leads are a single link-free paragraph with no fence
(`docs_site/docs/commands.md:23-26`, `:34-36`, byte-identical to
`commands/assess-repo.md:9-12` and `commands/harvest-memory.md:9-11`).

**Impact:** A documentation author writing a fenced markdown example in a command's opening
paragraph takes down `mkdocs build --strict` with a `count-guard:` error naming "commands",
which points at the wrong thing entirely. Loud, not silent — hence INFO.

**Recommended Fix:** Either indent/escape fenced lead content when rendering, or make
`check_count` count only headings the renderer emitted (e.g. count `` ### `/ `` for
commands). Cheapest: a comment at `gen_commands.py:231` naming the hazard.

---

### [INFO] `hooks.md` does not mention the nudge count's known worktree undercount

**Category:** Maintainability (accuracy)
**File(s):** `docs_site/docs/hooks.md:70-73`, `hooks/harvest_nudge.py:165-173`
**Confidence:** VERIFIED

**Description:**
The page describes the un-harvested-record nudge as firing on "the number of trail records
newer than the repo's watermark". The hook's own comment documents that this reads only the
repo's canonical trail, not its worktree trails, so the number is a lower bound — and the
message it prints says `(N+)` for exactly that reason.

**Evidence:**
`docs_site/docs/hooks.md:70-73`, verbatim:
> `- **Un-harvested records.** If the number of trail records newer than the`
> `  repo's watermark reaches `CLAUDE_HARVEST_NUDGE_THRESHOLD` (default `20`),`
> `  the hook prints a one-line reminder to run `/harvest-memory`. Set the`
> `  environment variable to change the threshold.`

`hooks/harvest_nudge.py:165-173`, verbatim:
> `    # KNOWN UNDERCOUNT: this reads only the repo's *canonical* trail, not the`
> `    # aggregate across its worktree trails, so the count is a lower bound and a`
> `    # repo whose recent work all happened in worktrees can stay below the`
> `    # threshold.`

**Impact:** An omission, not a false claim, and not privacy-relevant (it under-promises
rather than over-promises). A worktree-heavy user may wonder why the nudge never fires.

**Recommended Fix:** Add half a sentence ("counted against the repo's canonical trail only,
so worktree-heavy work undercounts — the message says `N+`"). Optional.

---

### [INFO] mkdocs 1.6.1 restores `sys.path` wholesale after hook exec, which contains the repo-root insert better than the plan assumed

**Category:** Security / integration (positive finding)
**File(s):** `docs_site/gen_theme.py:57-69`, `mkdocs/config/config_options.py::Hooks._load_hook`
**Confidence:** VERIFIED

**Description:**
Discovery hazard 7 asked whether `docs_site/`'s new top-level
`sys.path.insert(0, str(REPO_DIR))` can shadow modules or break other importers. It cannot,
for a reason stronger than the plan's: mkdocs does not merely remove the directory it
added, it replaces the whole list with a pre-exec copy, discarding `gen_theme`'s insert too.
The repo root is therefore on `sys.path` only for the duration of hook module exec; the rest
of the build runs with an unmodified path. `scripts._crew_common` is already in
`sys.modules` by then, so `on_pre_build` works.

**Evidence:**
`mkdocs.config.config_options.Hooks._load_hook` at the installed mkdocs 1.6.1, verbatim:
```
        old_sys_path = sys.path.copy()
        sys.path.insert(0, os.path.dirname(path))
        try:
            spec.loader.exec_module(module)
        finally:
            sys.path[:] = old_sys_path
```
Shadowing surface at the repo root: only `conftest.py` and `install.py` are top-level `.py`
files (`ls *.py`), and the importable directory names are `agents commands docs docs_site
github-action hooks memory scripts skills tests brand` — none shadow a stdlib or
site-packages module used by a docs build. `hooks/` is a real package
(`hooks/__init__.py` exists), but mkdocs registers its own hook modules under their config
path strings (`sys.modules[name]`, `name` = e.g. `"hooks/assets.py"`), not as submodules of
a `hooks` package, so there is no collision.

**Impact:** None. Hazard 7 is closed. The "must stay a top-level import" discipline in
`catalog_core.py`, `gen_commands.py`, `gen_lifecycle.py`, `gen_theme.py` and
`orchestrator_spine.py` is not merely correct, it is load-bearing — a function-level
`sys.path.insert` in `gen_theme` would have failed inside the build.

---

### [INFO] `test_gen_catalog.py`'s hand-maintained `THEMED_NAMES` literal could now be derived, and its amended comment half-admits it

**Category:** Maintainability
**File(s):** `docs_site/test_gen_catalog.py:447-462`
**Confidence:** VERIFIED

**Description:**
The plan's T3 required amending the "`docs_site/` must not import from `scripts/`" comment,
and that was done correctly (comment prose only; `git diff` shows no assertion or fixture
value changed). The amended text argues the literal is unavoidable because the test builds
synthetic repos. That is true of the *fixtures* but not of the list itself — now that
`docs_site/` can import `_crew_common`, the expected themed names could be derived from
`PAIRS`/`TIERED_AGENTS` while the fixtures stay synthetic.

**Evidence:** The amended comment, verbatim at HEAD (`docs_site/test_gen_catalog.py:447-462`):
> `#: \`archimedes-*\` tier variants). Kept as a literal on purpose: this test`
> `#: builds *synthetic* fixture repos (see \`_make_repo\` below) rather than`
> `#: reading the real crew, so there is no live roster here to import`
> `#: \`_crew_common\` against -- a hand-maintained copy is the only shape that`
> `#: fits.`

**Impact:** One remaining hand-maintained roster copy whose comment says maintaining it by
hand is the only option. Out of plan scope; worth a follow-up.

---

### [INFO] `orchestrator_spine.py` is an unplanned module, and the plan's file-ownership table does not cover it

**Category:** Maintainability (plan alignment)
**File(s):** `docs_site/orchestrator_spine.py` (185 lines, new in `c75a872`)
**Confidence:** VERIFIED

**Description:**
The plan's T5 and ownership table name only `docs_site/gen_lifecycle.py`. The branch split
the parser into a second module, with `gen_lifecycle` re-exporting its names (`__all__`
added in a follow-up chore commit `42f1455` to satisfy ruff F401).

**Evidence:** `git log --oneline origin/main...HEAD` shows `c75a872 refactor: [impl] split
orchestrator parser out of gen_lifecycle` and `42f1455 chore(docs): [chore] declare
gen_lifecycle's spine re-exports in __all__`. `docs_site/gen_lifecycle.py:61-74` documents
the re-export and names `test_gen_lifecycle.py::ReexportTest` as the pin.

**Impact:** Positive on balance — it is why both modules land under 400 lines
(`gen_lifecycle.py` 390, `orchestrator_spine.py` 185; combined they would be ~550). The
deviation is well documented, the re-export is pinned by a test, and the separation
(structure parser vs. hand-written prose) is a defensible boundary. Recorded for plan
traceability only.

## Regression Check Results

| Feature/Contract | Status | Notes |
|-------------------|--------|-------|
| `gen_catalog` re-exports keep `test_gen_catalog` / `test_site_content` / `brand` importing unchanged | Pass | `gen_catalog.py:82-100` re-exports all 15 moved names with `# noqa: F401`; no assertion edited (`git diff` of `test_gen_catalog.py` is +92/-7, all fixture additions and comment prose) |
| `on_pre_build` is check-only, never writes | Pass | `gen_catalog.py:607-632` still calls `generate(check_only=True)`; `generate`'s write branch (`:596-599`) is unreachable from the hook |
| `generate()` return shape `{"agents": n, "skills": m}` | Pass | `gen_catalog.py:601-604` unchanged by exact equality; the commands count is read separately in `main()` at `:662` and documented at `:568-575` |
| `ITEM_HEADING_RE` count guards survive the new page content | Pass | Theme fragment emits no `` ### ` `` (pinned by `test_gen_theme.py:204-206`); lifecycle page uses `### PHASE n:`; commands page's `` ### `/name` `` is intentionally counted. Note the guard now runs *over* the theme fragment — see finding 2 |
| `grep -c '^### ' docs_site/docs/agents.md` unchanged by the theme section | Pass | `test_gen_theme.py:208-214` asserts page count == pre-fragment count |
| Fence-aware parsing of `agents/orchestrator.md` | Pass | All 52 fences are plain 3-backtick at indent 0/3, balanced; two independent scanners agree (`test_gen_lifecycle.py:172-180`). Latent blind spots recorded as INFO |
| Committed pages match a fresh render (all four) | Pass | `test_gen_catalog.py:705-706` runs `generate(repo, check_only=True)` over every `build_pages` entry; `test_gen_lifecycle.py:240-251` and `test_gen_theme.py:223-228` add page-specific checks. `commands.md` has no page-specific check — see finding 7 |
| `commands.md` lead prose is verbatim from source | Pass | `docs_site/docs/commands.md:23-26` ≡ `commands/assess-repo.md:9-12`; `:34-36` ≡ `commands/harvest-memory.md:9-11`. Nothing swallowed, nothing added |
| `hooks.md` privacy claims vs. `hooks/record_stop.py` | Pass | 11 `SECRET_PATTERNS` → the page names all 10 vendor categories; whole-preview blanking, redaction-before-truncation, unknown-shape survival, transcript-never-opened, retention-as-a-floor, malformed-line drop, absolute record ceiling — every one verified in source and pinned by `test_gen_reference.py` with one side derived from the module |
| `hooks.md` claims vs. `hooks/harvest_nudge.py` | Pass | Default 20 *and* the unparseable→20 fallback (`harvest_nudge.py:52-55` try/except) are both accurate; pending-marker precedence (`:159-163`), `lines[:2]` cap (`:283`, `:328`), near-threshold-only-when-none-fired (`:287-290`), degrade-to-silence (`:339`), `startup`/`resume` only (`:56`), async Stop (`install.py:756`) — all confirmed |
| Theme roster vs. live `agents/*.md` (the "Ten agents / 16" class) | Pass | 17 files = 9 `PAIRS` + 2 `TIERED_AGENTS` + 6 `THEME_INVARIANT_ROSTER`, and `tests/test_agent_definitions.py:424-429` pins `{agents/*.md stems} == expected_roster(theme)` in the **required** root suite — an 18th agent reds CI. The gap I went looking for is closed transitively |
| `mkdocs.yml` nav and anchor validation | Pass | Six flat entries in plan order; `validation.links.anchors: warn` resolves (`load_config` yields `30` = `logging.WARNING`), so `--strict` fails on `agents.md#the-philosopher-theme`, `commands.md#harvest-memory`, `index.md#the-learning-loop` — all three targets exist |
| `test_ci_coverage.py::ScannerTest` still green after one `tests.yml` pattern change | Pass | `test_ci_coverage.py` is untouched on this branch (byte-identical to merge-base); the single edit is `-p "test_gen_catalog.py"` → `-p "test_gen_*.py"` at `tests.yml:345` plus comments |
| Module gate | **Warning** | `gen_catalog.py` 672 (tripwire 400); three new test modules 407-539. `Module-check:` verdict outstanding — see finding 1 |
| No README / styling / nav-structure changes beyond the four entries | Pass | Merge-base diff touches no README and no CSS; `mkdocs.yml` gains only three nav lines and the `validation` block |

## Recommendations

Priority order. Nothing here blocks a merge on correctness grounds.

1. **Before opening the PR:** add the `Module-check:` verdict for `gen_catalog.py`
   (732 → 672 against a 400 tripwire) and the three >400 test modules. Plan decision 6 and
   T11 require it, and no PR exists yet.
2. **Fix the two false comments** (finding 2) — `gen_catalog.py:524-528` and
   `test_gen_theme.py:200`. These are the ones most likely to mislead a future editor into a
   real defect. Same pass: correct `catalog_core.py:19`'s "back under the gate".
3. **Derive the word "two"** in `gen_theme.py:105-107` and fix the `and`-join (finding 5).
   It is the one undierived figure in a batch whose entire premise is that figures must be
   derived.
4. **Normalise the two `--` to `—`** in `gen_theme.py` and regenerate (finding 6) — the only
   user-visible defect on the published site.
5. **Add the two plan-specified assertions** (finding 7): `hooks.md` absent from
   `build_pages()` output, and a committed-page check in `test_gen_commands.py` so a stale
   `commands.md` fails in the commands suite rather than only in `test_gen_catalog.py`.
6. **Narrow the stdlib-only claims** in `gen_commands.py:10-11` and `gen_lifecycle.py:29-30`
   to `catalog_core.py`'s accurate wording (finding 4), and amend `build_pages`' "every page
   honours `repo_dir`" (finding 8).
7. **Optional / follow-up:** `agents.md`'s banner (finding 3), `_find_anchor`'s ternary
   (INFO), fence-masking hardening (INFO), the worktree-undercount sentence in `hooks.md`
   (INFO), deriving `test_gen_catalog.py`'s `THEMED_NAMES` (INFO).

## Files Reviewed

All reads pinned to HEAD `42f1455344e23ad429b9977b2a7d8c641eb4d518` or merge-base `3c3ca4e`.

Branch diff (18 files, read in full):
- `docs_site/catalog_core.py`, `docs_site/gen_catalog.py`, `docs_site/gen_commands.py`,
  `docs_site/gen_lifecycle.py`, `docs_site/gen_theme.py`, `docs_site/orchestrator_spine.py`
- `docs_site/docs/agents.md` (theme section), `docs_site/docs/commands.md`,
  `docs_site/docs/hooks.md`, `docs_site/docs/lifecycle.md`
- `docs_site/mkdocs.yml`, `.github/workflows/tests.yml`, `scripts/_crew_common.py`
- `docs_site/test_gen_commands.py`, `docs_site/test_gen_lifecycle.py`,
  `docs_site/test_gen_reference.py`, `docs_site/test_gen_theme.py`,
  `docs_site/test_gen_catalog.py` (diff + the committed-pages test)

Sources the pages are checked against:
- `agents/orchestrator.md` (headings, triage table L35-41, `### Per-Task Dispatch` L358-372,
  competence check L43-50, fence census)
- `commands/assess-repo.md`, `commands/harvest-memory.md`
- `hooks/record_stop.py`, `hooks/harvest_nudge.py`, `install.py` (hook wiring)
- `scripts/mark_harvested.py`, `scripts/module_scan.py`
- `tests/test_agent_definitions.py` (the roster pin), `tests/test_apply_theme.py` (consumers
  of `PAIRS`)
- `docs_site/docs/index.md` (anchor target), `docs_site/test_site_content.py` (scope check
  only — untouched by this branch), `docs_site/test_ci_coverage.py` (untouched)
- `.github/workflows/docs.yml`, `CLAUDE.md` (declared architecture: none; default 400-line
  tripwire)
- `mkdocs.config.config_options.Hooks._load_hook` at the installed mkdocs 1.6.1

Commands run (read-only): `git diff/log/show` against the pinned refs,
`python scripts/module_scan.py --json`, `gh pr list`, a `mkdocs.config.load_config` probe of
`docs_site/mkdocs.yml`, and a fence-balance script over `agents/orchestrator.md`. I did not
re-run the suites the CI agent already reported green.
