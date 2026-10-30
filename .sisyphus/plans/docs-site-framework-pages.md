# Docs site — first batch of framework/tooling pages

## TL;DR
> Add four things to docs.nescio-ai.org, **three of them generated**: a Commands
> catalogue from `commands/*.md` (frontmatter *and* each command's lead prose), a
> philosopher-theme mapping table appended to the Agents page (names *and*
> rationale sourced from `scripts/_crew_common`), and an Orchestrator lifecycle
> page whose factual spine — phase list and triage table — is parsed out of
> `agents/orchestrator.md`, with a sha256 staleness pin on the sections its prose
> summarises. The fourth, a Hooks reference, is hand-written and its every number
> is pinned to the hook modules' constants. Because the generator is already 732
> lines against a 400-line tripwire and three new renderers must import its
> primitives, one preceding task extracts `docs_site/catalog_core.py`, and one
> dedicated task owns **all** `gen_catalog.py` wiring so no two parallel tasks
> ever touch the same file.

---

## DECISIONS (approved, with the six revisions applied)

1. **Base: `origin/main`.** Branch `docs/site-framework-pages` cut from
   `origin/main`, in a **new worktree at
   `.claude/worktrees/docs-framework-pages`**
   (the coordinator creates it). Not stacked on #219/#220. **Verified against
   `origin/main`:** `docs_site/` contains `gen_catalog.py`, `mkdocs.yml`,
   `test_ci_coverage.py`, `test_gen_catalog.py`, `test_site_content.py` (933
   lines) — there is **no `site_under_test.py` and no `test_site_*.py` glob**;
   `.github/workflows/tests.yml` runs exactly three docs_site steps, with
   patterns `test_ci_coverage.py` (L334), `test_gen_catalog.py` (L345) and
   `test_site_content.py` (L368). `docs_site/` and `tests.yml` are byte-identical
   between `origin/main` and this worktree's HEAD, so everything quoted from the
   current tree below is also true of `main`.
2. **Every new test module is named `test_gen_*.py`**, so Task 7's single
   `tests.yml` edit (`-p "test_gen_catalog.py"` → `-p "test_gen_*.py"`) is the
   only workflow change the whole batch needs, and
   `test_ci_coverage.py::ScannerTest` stays green. **`test_site_content.py` is not
   touched** (933 lines, and widening its pattern is not needed).
3. **README unchanged this batch.** The site becomes canonical for commands /
   hooks / lifecycle; trimming README is a separate change. The one README-adjacent
   edit is expanding its ditto marks when the rationale text moves into
   `scripts/_crew_common.py` (Task 3) — the README file itself still stays as it is.
4. **Theme table** lives at the end of the generated `agents.md`, not on its own
   nav page. Nav stays flat: `Home / Agents / Skills / Commands / Hooks / Lifecycle`.
5. **One owner for `gen_catalog.py`.** Tasks 2, 3 and 5 ship renderer modules and
   touch nothing else; **Task 6 alone** edits `gen_catalog.py`, `mkdocs.yml` and
   the generated pages. This resolves the validator's blocker more completely than
   serialising into Wave 1b would: with wiring extracted, the three renderers are
   genuinely file-disjoint and run in parallel, and the wiring lands as one
   reviewable commit.
6. **Module gate.** `catalog_core.py` is extracted rather than growing
   `gen_catalog.py` past 1,000 lines behind a waiver. Any >400-line file that
   nonetheless grows needs a **`Module-check:` verdict in the PR body** — called
   out in Task 11.

### Noted consequence of revision 5 (surfacing, not blocking)

Sourcing the theme rationale from `scripts/_crew_common.py` **reverses a
documented stance**. `docs_site/test_gen_catalog.py` L372-377 says, verbatim:
"Kept as a literal on purpose -- `docs_site/` must not import from `scripts/`,
because the docs build has to work with nothing from `scripts/` on PYTHONPATH."
The approved design makes `docs_site/gen_theme.py` import `scripts._crew_common`.

This is defensible — the stated reason is *PYTHONPATH setup*, and a top-level
`sys.path.insert(0, str(REPO_DIR))` plus `from scripts import _crew_common`
needs no environment at all (verified working; `scripts/__init__.py` exists, so
only the repo root goes on the path) — and the dependency direction is the safe
one, since `scripts/` is on FRAMEWORK_PATHS and ships everywhere `docs_site/`
does not. But the comment must be **amended, not ignored** (Task 3). If you would
rather keep `docs_site/` hermetic, the fallback is a `THEME_RATIONALE` dict inside
`gen_theme.py` with a key-coverage test — say so and Task 3 changes shape only.

---

## Context

**Declared architecture:** the project's `CLAUDE.md` `## Architecture` section
declares **no shape** and **no tripwire override** — the crew follows the
structure already in the tree, and the module tripwire is the default **400
lines** (`python scripts/module_scan.py --json`).

Discovery brief: `.sisyphus/discovery/docs-site-framework-pages.md`. Read it; do
not re-derive it. Facts below were verified during planning — inherit them.

### The site and its generator
- MkDocs Material in `docs_site/`; nav Home/Agents/Skills; `mkdocs build
  --strict`; material pinned 9.7.7 in `.github/workflows/docs.yml`, which runs
  `python docs_site/gen_catalog.py` (writing) *before* the build.
- `docs_site/gen_catalog.py` — **732 lines**, generator + CLI + MkDocs hook.
  `--check` verifies without writing; `on_pre_build` calls
  `generate(check_only=True)` and **never writes** (a writing hook was measured
  laundering drift mid-build, taking a committed page from 11 to 17 sections and
  exiting 0 — do not change that).
- **Verified:** MkDocs loads `hooks:` entries via
  `importlib.util.spec_from_file_location`, inserting the hook file's dirname
  into `sys.path` **only around module exec** and restoring it after
  (`mkdocs.config.config_options.Hooks._load_hook`, mkdocs 1.6.1). Consequence,
  load-bearing for Tasks 1/3/5: **sibling and repo-root imports in
  `docs_site/*.py` must be at module top level.** A function-level
  `import catalog_core` would work from the CLI and fail inside a build.
- **Verified:** `mkdocs` 1.6.1 is installed locally; **`mkdocs-material` is not**,
  so a local `mkdocs build --strict` fails on the theme until the pin is
  installed. `--strict` also fails on broken internal links — relevant to any
  prose extracted from repo files (Tasks 2, 5).
- **Verified:** `docs_site/test_ci_coverage.py::ScannerTest` enforces that every
  test module under `docs_site/` is reached by some `-p` pattern in a workflow
  step, and proves its own detector against fixtures
  (`test_a_pattern_that_misses_a_sibling_module_is_reported`). A module outside
  the covered patterns fails CI.

### Sources the new pages read
- `commands/` — `assess-repo.md`, `harvest-memory.md`; frontmatter `name`,
  `description`, `user-invocable: true`. **Verified** lead-prose shape: `# /name`
  then one paragraph (assess-repo 292 chars, harvest-memory 213), each ending at
  the first following `##`; **no markdown links in either lead today**.
- **Verified:** `scripts/__init__.py` exists; `scripts/_crew_common.py` is **325
  lines** (room to grow under the tripwire), stdlib-only pure data: `PAIRS` (9
  functional↔philosopher word pairs, order significant),
  `TIERED_AGENTS = ("builder-simple", "builder-standard")`,
  `THEME_INVARIANT_ROSTER = {explore, librarian, orchestrator, scout, validator,
  vision}`, `THEMES`, `_FUNCTIONAL_TO_PHILOSOPHER`, `themed_name`,
  `renamed_agents`. Consumers of `PAIRS`: `scripts/apply_theme.py` L54/L90
  (word-pair rename dictionary), `_crew_common` itself L273/L278/L322,
  `tests/test_apply_theme.py` (726 lines, incl. `ThemeNamePinTest` — the
  deliberate outside oracle). **A new sibling dict breaks none of them**; `PAIRS`
  must keep its exact `list[tuple[str, str]]` shape.
- `agents/orchestrator.md` — **878 lines**. H2s: `CRITICAL IDENTITY`,
  `PHASE 0: TRIAGE (Every Request)` (L31), `PHASE 1: DISCOVER` (L65),
  `PHASE 2: ANALYZE (When Needed)` (L153), `PHASE 3: PLAN` (L205),
  `PHASE 4: EXECUTE` (L310), `PHASE 5: VERIFY` (L542), `PHASE 6: DELIVER` (L659),
  `ORCHESTRATION PRINCIPLES` (L727), `TURN TERMINATION` (L866). Note the
  **trailing parentheticals** on phases 0 and 2. Triage table at **L35-41**
  (6 rows), competence check at L43-50, `### Delivery Boundary Check` L274,
  `### Scope-Drift Reflex` ~L349, `### Per-Task Dispatch` + tier table L368-372 +
  escalation paragraphs following, `### Work Placement: Inline, Subagent, or
  Spawned Task` L729, **Routing quality gate** L842.
  The file also contains `## `-prefixed lines *inside fenced blocks* (template
  skeletons at L100-129, L163-187, L213-288) — a naive `^## ` scan hits them.
- `hooks/record_stop.py` (394 lines) — **verified constants and semantics:**
  `RETENTION_DAYS = 14`, `PRUNE_SIZE_THRESHOLD = 1_000_000` bytes,
  `ABSOLUTE_MAX_RECORDS = 10_000`, `SECRET_PATTERNS` (11 patterns), trail at
  `<$CLAUDE_CONFIG_DIR or ~/.claude>/learning-trail/<repo_key>.jsonl`, watermark
  at `<repo_key>.watermark`. `redact()` **blanks the entire preview** on any
  pattern hit ("cheaper and safer than partial redaction"). `build_record()`
  fields: `ts`, `session_id`, `git_root`, `repo_root`, `git_branch`, `prompt_id`,
  `transcript_path` (**stored verbatim, never opened**), `message_preview` (a
  one-line, redacted, `PREVIEW_MAX`-truncated preview of the **last assistant
  message** — *not* the user's prompt). `prune_lines()`: a record is dropped only
  when it is **both** older than `RETENTION_DAYS` **and** at/below the harvest
  watermark; un-harvested records are kept **regardless of age**, bounded only by
  `ABSOLUTE_MAX_RECORDS`. So **14 days is a floor, not a cap** — confirmed, and
  Task 6's wording may state it.
- `hooks/harvest_nudge.py` (411 lines) — `NUDGE_THRESHOLD =
  int(os.environ.get("CLAUDE_HARVEST_NUDGE_THRESHOLD", "20"))`,
  `NEAR_THRESHOLD_FRACTION = 0.9`, `PENDING_PREFIX = ".harvest-pending-"`; checks
  ADR 0002 triggers via a `scripts/check_memory_triggers.py` subprocess.
- `install.py` wires both hooks into `~/.claude/settings.json` (~L756-780).

**The hazard that shapes every task:** drift. The site shipped "Ten agents" while
there were 16. Generated content first; hand-written prose summarises and links
to its source; every specific number or name in prose is pinned by a test that
reads the source side itself.

## Work Objectives

1. `docs/commands.md` — generated from `commands/*.md`: frontmatter **plus** each
   command's lead prose.
2. A generated `## The philosopher theme` table at the end of `docs/agents.md`,
   names and rationale both from `scripts/_crew_common`.
3. `docs/hooks.md` — hand-written: what the hooks record, what may land in the
   trail, how redaction and retention actually behave, how to tune, delete and
   disable.
4. `docs/lifecycle.md` — **generated**: phase list and triage table parsed from
   `agents/orchestrator.md`, prose owned by the generator, staleness-pinned.
5. The generator stays within the module gate; all new tests run in CI.

**Out of scope:** README edits, any further page, styling, nav restructuring
beyond the four entries, changes to agents/skills rendering beyond the appended
theme section, touching `test_site_content.py`.

## Verification Strategy

| What | How |
|---|---|
| Generated pages match their sources | `python docs_site/gen_catalog.py --check` exits 0; regenerating leaves a clean tree |
| No page can silently drop an item | count-guard per generated page (`check_count`) |
| Theme table cannot rot on a roster change | rendered rows derived from `PAIRS`; `PAIR_RATIONALE` keys == `PAIRS` functional names |
| Lifecycle facts cannot rot | phase list and triage table parsed, never typed; no phase count anywhere |
| Lifecycle *prose* cannot silently rot | sha256 digests of the five orchestrator sections the prose summarises, stored in `test_gen_lifecycle.py` |
| Hooks page cannot rot | `test_gen_reference.py` reads each constant from the hook module and asserts the page states it |
| Site still builds | `mkdocs build --strict` (conditional on material 9.7.7 installing) |
| Nothing fell out of CI | `test_ci_coverage.py` green after the one `tests.yml` pattern change |
| Module gate | `module_scan.py --json`: `gen_catalog.py` smaller; no new file over 400; `Module-check:` verdict in the PR body for any >400 file that grew |

Self-check commands, from the repo root of the new worktree:

```bash
python -m unittest discover -s docs_site -p "test_gen_*.py" -v
python -m unittest discover -s docs_site -p "test_site_content.py" -v
python -m unittest discover -s docs_site -p "test_ci_coverage.py" -v
PYTHONPATH=scripts python -m unittest discover -s tests -v
python docs_site/gen_catalog.py --check
python scripts/module_scan.py --json
```

## Execution Strategy

Worktree: `.claude/worktrees/docs-framework-pages`.
Branch: `docs/site-framework-pages` off `origin/main`. Suggested delivery: three
commits — `refactor: extract catalog_core from gen_catalog` (T1),
`feat(docs): generate commands, theme and lifecycle pages` (T2-T6),
`test: pin the new docs pages against their sources` (T7-T10).

```
Wave 0  (1 agent,  blocks all):   T1  catalog_core extraction
Wave 1  (4 agents, parallel):     T2  gen_commands      T3  theme rationale + gen_theme
                                  T4  docs/hooks.md     T5  gen_lifecycle
Wave 2  (1 agent,  sole owner):   T6  wire build_pages + nav + regenerate & commit pages
Wave 3  (4 agents, parallel):     T7  test_gen_commands + tests.yml   T8  test_gen_theme
                                  T9  test_gen_lifecycle              T10 test_gen_reference
Wave 4  (1 agent):                T11 verification + delivery
```

File ownership, so no two parallel agents collide:

| File | Owned by |
|---|---|
| `docs_site/catalog_core.py` | T1 |
| `docs_site/gen_catalog.py` | T1 (extraction), then **T6 only** |
| `docs_site/gen_commands.py` | T2 |
| `scripts/_crew_common.py`, `docs_site/gen_theme.py` | T3 |
| `docs_site/docs/hooks.md` | T4 |
| `docs_site/gen_lifecycle.py` | T5 |
| `docs_site/mkdocs.yml`, `docs_site/docs/{agents,commands,lifecycle}.md` | T6 |
| `.github/workflows/tests.yml` | T7 |
| `docs_site/test_gen_{commands,theme,lifecycle,reference}.py` | T7 / T8 / T9 / T10 |

## TODOs

- [ ] 1. Extract `docs_site/catalog_core.py` — the primitives the new renderers need
  **Complexity**: standard
  **Depends on**: nothing (Wave 0)
  **Why this exists**: `gen_catalog.py` is 732 lines against a 400-line tripwire,
  and three new renderer modules need `split_frontmatter`/`Item`/`CatalogError`
  while `gen_catalog.build_pages` must call *them* — importing both ways is a
  cycle. A third, lower module breaks the cycle and shrinks the file the gate is
  complaining about.
  **What to do**:
  - Create `docs_site/catalog_core.py` and **move, verbatim with their comments**,
    from `gen_catalog.py`: `SITE_DIR`, `REPO_DIR`, `DEFAULT_OUT_DIR`,
    `REPO_BLOB_BASE`, `CatalogError`, `GENERATED_BANNER`, `split_frontmatter`,
    `_scalar`, `_unquote`, `Item`, `Catalog`, `_parse_item`, `_source_link`,
    `ITEM_HEADING_RE`, `check_count`. Nothing else. No renames, no signature
    changes, no behaviour changes.
  - Leave in `gen_catalog.py`: `AGENT_GROUPS`, `SKILL_GROUPS`, `UNGROUPED_TITLE`,
    `_group`, `_at_a_glance`, `_split_tool_list`, `_agent_meta`, agent/skill
    discovery and rendering, `build_pages`, `generate`, `on_pre_build`, `main`.
  - In `gen_catalog.py`, add a **top-level** `from catalog_core import (...)`
    re-exporting every moved name, so `test_gen_catalog.py`,
    `test_site_content.py` and `brand/` keep importing them from `gen_catalog`
    unchanged. **Do not edit any test file in this task.**
  - Comment at that import the verified MkDocs fact: the hook loader puts the
    hook's directory on `sys.path` only around module exec and restores it, so
    sibling imports must be top-level — a function-level one works from the CLI
    and fails inside `mkdocs build`. Cite
    `mkdocs.config.config_options.Hooks._load_hook`.
  - House-style module docstring on `catalog_core.py`: what it owns, why it is not
    in `gen_catalog.py` (the cycle and the gate), stdlib-only, and the rule that
    it must **never** import `gen_catalog`.
  **Files**: `docs_site/catalog_core.py` (new), `docs_site/gen_catalog.py`
  **Acceptance criteria**:
  - `python -m unittest discover -s docs_site -p "test_gen_catalog.py" -v` passes
    with **zero edits** to that file; `-p "test_site_content.py"` passes too.
  - `python docs_site/gen_catalog.py --check` exits 0 and
    `git status --porcelain docs_site/docs/` is empty — the extraction changes no
    rendered byte.
  - `module_scan.py --json` shows `gen_catalog.py` materially smaller (expect
    ~480-520) and `catalog_core.py` under 400.
  - `grep -c "import gen_catalog" docs_site/catalog_core.py` → 0.
  **QA Scenarios**:
  - `python -c "import sys; sys.path.insert(0,'docs_site'); import gen_catalog;
    print(gen_catalog.CatalogError, gen_catalog.GENERATED_BANNER[:20])"`.
  - If material is installed: `cd docs_site && mkdocs build --strict` succeeds,
    proving the hook imports its sibling. If it is not, say so — do not claim it.

- [ ] 2. `gen_commands.py` — render the Commands catalogue (module only)
  **Complexity**: standard
  **Depends on**: T1
  **What to do**:
  - New `docs_site/gen_commands.py`, top-level `from catalog_core import ...`.
    Public contract T6 will call — keep these names exactly:
    `command_paths(repo_dir) -> list[Path]` (sorted `commands/*.md`),
    `discover_commands(repo_dir) -> Catalog`, `render_commands(catalog) ->
    tuple[str, list[str]]` (page text, warnings) mirroring `render_agents`.
  - Frontmatter: `name`, `description`, `user-invocable`. A `name` that disagrees
    with the filename raises `CatalogError`; a missing `description` raises; a
    missing `user-invocable` defaults to false **and warns** (metadata, not a lie).
  - **Lead prose (revision 4).** Extract the text after the body's `# /name`
    heading up to the next heading of any level, and render it under the command's
    section *in addition to* `description`. Hazards to handle, both cheap:
    (a) **skip fenced code blocks** when looking for the terminating heading — a
    ```` ``` ````-fenced block in a command body can contain `## ` lines
    (`harvest-memory.md` is 25 KB of exactly that shape); (b) **rewrite relative
    markdown links** in the extracted prose to absolute `REPO_BLOB_BASE` URLs —
    `mkdocs build --strict` fails on broken internal links, and repo-relative
    links do not resolve inside the site. Verified: both current leads are a
    single paragraph with **no links**, so (b) is defensive; implement it anyway
    and test it with a fixture.
  - Page shape, matching the existing pages: `GENERATED_BANNER`, H1, a one-sentence
    lead, an at-a-glance table (`| command | what it does |`, command as
    `` `/name` `` in mono), then one ``### `/name` `` section per command carrying
    description, lead prose, a `user-invocable: yes/no` meta line in the
    `_agent_meta` idiom, and a `_source_link`.
  - **No hardcoded command count anywhere** (`test_gen_catalog.py` already forbids
    hardcoded counts in the generator — stay compatible).
  - **Do not touch `gen_catalog.py` or `mkdocs.yml`.** T6 wires this up.
  **Files**: `docs_site/gen_commands.py` (new)
  **Acceptance criteria**:
  - `python -c` driving `render_commands(discover_commands(REPO_DIR))` prints a
    page with `GENERATED_BANNER`, exactly two ``### `` sections today
    (`/assess-repo`, `/harvest-memory`), each command's real frontmatter
    description, and each command's real lead paragraph.
  - A temp fixture whose command body has `## Heading` inside a fence does **not**
    truncate the lead there.
  - A `name:`/filename mismatch raises `CatalogError`.
  - Under 400 lines; no `import gen_catalog`.
  **QA Scenarios**:
  - Diff your extracted lead for `assess-repo` against `sed -n '8,12p'
    commands/assess-repo.md` — same text, nothing swallowed, nothing added.
  - Fixture with a relative link `[x](../README.md)` in the lead → rendered as a
    `REPO_BLOB_BASE` URL.

- [ ] 3. Theme rationale into `_crew_common`, plus `gen_theme.py` (module only)
  **Complexity**: standard
  **Depends on**: T1
  **Read first**: the "Noted consequence of revision 5" section above — you are
  implementing a deliberate, approved reversal of a documented stance, and part of
  the task is amending the comment that states it.
  **What to do**:
  - In `scripts/_crew_common.py`, add **`PAIR_RATIONALE: dict[str, str]`**
    immediately after `PAIRS`, keyed by **functional** name. Do **not** change
    `PAIRS`'s shape: it is consumed as a word-pair rename dictionary by
    `apply_theme._mappings` (L90), by `_FUNCTIONAL_TO_PHILOSOPHER` (L273) and by
    `tests/test_apply_theme.py`; a restructure would break all three. A sibling
    dict breaks nothing.
  - **Expand README's ditto marks** (revision 5). README L164-172 gives
    `aristotle` and `socrates` a `"` pointing at `plato`'s "the Socrates → Plato →
    Aristotle lineage". Write all nine explicitly, e.g. `plato` "named for the
    Socrates → Plato → Aristotle lineage — the planner at its centre",
    `aristotle` "the same lineage's systematiser, which suits the advisor",
    `socrates` "the same lineage's questioner, which suits the critic", and the
    seven remaining lines as README already words them (`pyrrho` the skeptic;
    `archimedes` the engineer and craftsman, deliberately outside that lineage,
    which suits the agent that builds rather than reasons; `euclid` proofs laid out
    step by step; `cato` the censor, who checked what others shipped;
    `callimachus` catalogued the library of Alexandria; `cicero` the prose
    stylist). **README.md itself stays unchanged.**
  - Comment above `PAIR_RATIONALE`: its keys are pinned to `PAIRS` by
    `docs_site/test_gen_theme.py`; it is rendered on the site; README carries a
    parallel copy for now (one edit, two places, by decision 3).
  - New `docs_site/gen_theme.py`. **Top-level** `sys.path.insert(0,
    str(REPO_DIR))` then `from scripts import _crew_common` — top-level because of
    the MkDocs hook `sys.path` fact; wrap so an ImportError becomes a
    `CatalogError` naming `scripts/_crew_common.py`. Comment both points.
  - `render_theme_section() -> str` returns a fragment: `## The philosopher theme`,
    a two-to-three-sentence lead, a `| functional | philosopher | why |` table
    built by iterating `PAIRS` **in order** with `PAIR_RATIONALE[functional]`,
    then sentences derived from `TIERED_AGENTS` and `THEME_INVARIANT_ROSTER` (how
    many files are renamed in all; which agents keep their names under both
    themes), then the `python scripts/apply_theme.py philosophers` /
    `functional` invocations and the `--dry-run` note. **Every count computed from
    the constants, never typed.**
  - **Hard constraint**: the fragment must contain **no `### ` heading beginning
    with a backtick**. `ITEM_HEADING_RE = ^### \`` drives the agents count-guard;
    such a heading would corrupt it. Table rows only; `##`/`####` are fine.
  - Amend the stale comment: in `docs_site/test_gen_catalog.py` L372-377, narrow
    "`docs_site/` must not import from `scripts/`" to what is still true — the
    *fixture list* stays a literal because that test builds synthetic repos, while
    the live theme table now reads `_crew_common` directly through a top-level
    repo-root `sys.path` insert that needs no PYTHONPATH. **Comment text only — do
    not change a single assertion or fixture value.** Same for any equivalent
    sentence in `gen_catalog.py`'s module docstring.
  - **Do not touch `gen_catalog.py`'s code or `mkdocs.yml`.** T6 appends the
    fragment.
  **Files**: `scripts/_crew_common.py`, `docs_site/gen_theme.py` (new),
  `docs_site/test_gen_catalog.py` (**comment prose only**)
  **Acceptance criteria**:
  - `PYTHONPATH=scripts python -m unittest discover -s tests -v` passes —
    especially `tests/test_apply_theme.py` (726 lines, incl. `ThemeNamePinTest`).
  - `python -m unittest discover -s docs_site -p "test_gen_catalog.py" -v` passes;
    `git diff docs_site/test_gen_catalog.py` shows comment lines only.
  - `render_theme_section()` yields a 9-row table in `PAIRS` order, every why cell
    non-empty, no ditto marks, no backtick-leading `###`.
  - `set(PAIR_RATIONALE) == {f for f, _ in PAIRS}`.
  - `scripts/_crew_common.py` stays under 400 lines (was 325).
  **QA Scenarios**:
  - Add a scratch pair to `PAIRS` without a rationale → `PAIR_RATIONALE[...]`
    KeyErrors or the renderer raises a clear error rather than printing an empty
    cell; revert.
  - `python scripts/apply_theme.py philosophers --dry-run` then
    `functional --dry-run` → unchanged behaviour from before your edit.

- [ ] 4. Hand-written Hooks reference (`docs/hooks.md`)
  **Complexity**: standard
  **Depends on**: nothing (file-disjoint; scheduled in Wave 1)
  **What to do**: write `docs_site/docs/hooks.md`. Every fact below is verified in
  Context — use those words, and state nothing you have not read in the source.
  - Lead: two hooks, both installed by `install.py`; both observational; neither
    blocks or judges a turn.
  - ``## Stop — `record_stop.py` ``: fires once **per turn**; appends one JSONL
    line to `<$CLAUDE_CONFIG_DIR or ~/.claude>/learning-trail/<repo_key>.jsonl`;
    machine-local, never synced, never committed; it is the learning loop's raw
    trail.
    - **What may land in the trail** (revision 6): a timestamp, the session id, a
      `prompt_id`, the worktree and repository paths, the git branch, the
      transcript path as a **pointer stored verbatim and never opened**, and a
      one-line truncated preview of the **last assistant message**. Say
      explicitly that it is the assistant's message, not the user's prompt, and
      that no verdict or judgement is recorded.
    - **Redaction is best-effort** (revision 6): the preview is matched against a
      list of known secret shapes (OpenAI/Stripe/GitHub/AWS/Google/npm/Slack
      tokens, JWTs, PEM private-key headers, URL-embedded credentials) and, on a
      hit, **the whole preview is blanked to `[redacted]`** rather than partially
      masked — deliberately coarse. A secret in a shape the list does not know is
      **kept**. Matching runs before truncation, so a secret straddling the cut is
      still caught. Do not promise more than that.
    - **Retention is a floor, not a cap** (revision 6 — verified against
      `prune_lines`): pruning is opportunistic, only once the file passes a size
      threshold; a record is dropped only when it is **both** older than 14 days
      **and** already harvested. Un-harvested records are kept **regardless of
      age**, bounded only by an absolute ceiling on record count. Malformed lines
      and records with an unparseable timestamp are always dropped.
    - **How to delete it**: it is one machine-local file; delete or truncate
      `<config>/learning-trail/<repo_key>.jsonl` (and its `.watermark` sibling).
      Nothing syncs it; no server holds a copy.
    - **How to disable it**: remove the `Stop` entry from
      `~/.claude/settings.json` (the entry `install.py` wrote).
  - ``## SessionStart — `harvest_nudge.py` ``: the three things it can surface —
    an unfinished-harvest marker (`.harvest-pending-<repo_key>`), an un-harvested
    count at or over `CLAUDE_HARVEST_NUDGE_THRESHOLD` (**default 20**), and a
    fired or near ADR 0002 memory trigger via `scripts/check_memory_triggers.py`.
    How to tune (set the env var), how to disable (remove the `SessionStart`
    entry).
  - `## Where the data lives` — one short table: what / path / synced? / retention.
  - Close with source links to `hooks/record_stop.py`, `hooks/harvest_nudge.py`,
    `install.py`, and the Commands page's `/harvest-memory` entry.
  - **Discipline**: 100-160 lines. Summarise and link; do not restate docstrings.
    Use absolute `https://github.com/noctua84/nescio-ai/blob/main/...` links
    (`--strict` fails on broken internal links). Agent, file and env-var names in
    mono backticks. No front matter (only `index.md` uses `hide:`).
  **Files**: `docs_site/docs/hooks.md` (new)
  **Acceptance criteria**:
  - Contains the literal strings `CLAUDE_HARVEST_NUDGE_THRESHOLD`,
    `learning-trail`, `.harvest-pending-`, `record_stop.py`, `harvest_nudge.py`,
    `[redacted]`, `CLAUDE_CONFIG_DIR` (T10 greps for them).
  - States the threshold default, the 14-day retention **as a floor**, and
    best-effort redaction in the terms above.
  - Makes no claim the source does not support: no "all secrets are removed", no
    "records are deleted after 14 days", no claim that a verdict is stored.
  **QA Scenarios**:
  - Read the page beside both hook modules and list any sentence you could not
    source — there must be none; report the list as empty explicitly.
  - Confirm each stated default equals the module constant
    (`harvest_nudge.NUDGE_THRESHOLD`, `record_stop.RETENTION_DAYS`,
    `record_stop.PENDING_PREFIX` via `harvest_nudge`).

- [ ] 5. `gen_lifecycle.py` — generate the Orchestrator lifecycle page (module only)
  **Complexity**: complex
  **Depends on**: T1
  **Why complex**: a new pattern with no precedent in the repo — parsing an
  878-line agent definition into a page — plus genuine judgment about which five
  sections the prose summarises, which is what the staleness pin will be keyed to.
  Everything *else* about it is settled below; the judgment is the summary.
  **What to do**:
  - New `docs_site/gen_lifecycle.py`, top-level `from catalog_core import ...`.
    Public contract for T6: `orchestrator_path(repo_dir) -> Path`,
    `render_lifecycle(repo_dir) -> tuple[str, list[str]]`.
  - **Parse the factual spine from `agents/orchestrator.md`; type none of it:**
    - **Phase list** from `^## PHASE (\d+): (.+)$`, **tolerating trailing
      parentheticals** (`PHASE 0: TRIAGE (Every Request)`, `PHASE 2: ANALYZE
      (When Needed)`) — keep the bare name for prose and may keep the
      parenthetical as a note. **Skip fenced code blocks**: the file contains
      `## `-prefixed template skeletons inside fences (~L100-129, L163-187,
      L213-288) which a naive scan picks up. Raise `CatalogError` if fewer than
      two phases are found — a silently empty page is the failure this whole batch
      exists to prevent.
    - **Triage table** (L35-41): take the markdown table that follows the `PHASE
      0: TRIAGE` heading, verbatim rows, rendered as-is on the page.
    - **No hardcoded phase count anywhere**, and **the heading "The six phases"
      must not exist** — use "The phases" (or similar) and derive any count in
      prose from the parsed list.
  - **Prose** (hand-written, owned by the generator — a module-level template
    string or per-section constants, commented as the hand-written part):
    `## Triage` (the table + the **competence check**: "I don't know / no competent
    path" is a first-class outcome, stated rather than papered over with motion);
    `## The phases` (a short paragraph per parsed phase: what it produces and what
    the user is asked at the gate; name the on-disk artefacts
    `.sisyphus/discovery/*.md`, `.sisyphus/plans/*.md`); `## Gates` (approval
    between phases, the Delivery Boundary Check before a plan is presented, the
    Scope-Drift Reflex before each wave, the **routing quality gate** before a
    subagent's result is relayed or acted on); `## Tiering by reasoning load`
    (three tiers and their models; classify on reasoning load, not diff size;
    identical contract across tiers so over-tiering buys nothing; when in doubt go
    **lower**; escalate one tier at a time on `BLOCKED`; a `BLOCKED` naming a
    missing *decision* goes to the user, not up a tier); `## Work placement`
    (inline vs subagent vs spawned task; work found mid-wave is placed, not
    silently absorbed; a spawned task's brief must carry the whole context).
  - A `section_text(repo_dir, key) -> str` helper exposing, by stable key, the
    exact source text of the five sections the prose summarises —
    `work_placement`, `tiering`, `routing_quality_gate`, `competence_check`,
    `discovery_brief_carrying`. **T9's digest pin calls this**, so generator and
    test cannot disagree about what was hashed. Anchor each key on a heading or a
    bold-run literal (e.g. `**Routing quality gate.**`) and document the anchor;
    raise `CatalogError` if an anchor is not found.
  - Use **functional** agent names (`builder`, `builder-standard`,
    `builder-simple`) — the committed tree is the functional theme — and link to
    the theme table on the Agents page.
  - Close by naming `agents/orchestrator.md` as the source of truth and saying
    plainly that the agent file governs where the two differ. Absolute
    `REPO_BLOB_BASE` links only.
  - **Discipline**: the page is a summary, not a second copy of an 878-line file.
    Target 130-190 rendered lines. **Do not touch `gen_catalog.py` or
    `mkdocs.yml`.**
  **Files**: `docs_site/gen_lifecycle.py` (new)
  **Acceptance criteria**:
  - `render_lifecycle(REPO_DIR)` returns a page carrying `GENERATED_BANNER`, the
    seven parsed phase names (`TRIAGE`, `DISCOVER`, `ANALYZE`, `PLAN`, `EXECUTE`,
    `VERIFY`, `DELIVER`) exactly as the source spells them, and a triage table
    with one row per source row (6).
  - `grep -n "six phases" docs_site/gen_lifecycle.py` → nothing; no integer phase
    count literal anywhere in the module.
  - Phase parsing ignores fenced `## ` lines — prove it on the real file (a naive
    scan yields extra entries; yours must not).
  - `section_text` returns non-empty text for all five keys and raises for an
    unknown one.
  - Under 400 lines; no `import gen_catalog`.
  **QA Scenarios**:
  - Compare your parsed phases against
    `grep -n "^## PHASE" agents/orchestrator.md` (10 h2s total, 7 of them phases).
  - Compare your tier wording against the source table at L368-372 and the
    escalation paragraphs following it.
  - On a scratch copy with `## PHASE 5: VERIFY` renamed, the page changes
    accordingly with no edit to the generator.

- [ ] 6. Wire all three renderers into the generator, nav, and the committed pages
  **Complexity**: standard
  **Depends on**: T2, T3, T5 (and T4 for the nav entry)
  **Sole owner** of `gen_catalog.py`, `mkdocs.yml` and the generated pages — this
  task exists so no two parallel tasks edit the same file.
  **What to do**:
  - In `gen_catalog.py`, top-level `import gen_commands`, `gen_theme`,
    `gen_lifecycle` (top-level — the MkDocs hook `sys.path` fact).
  - `build_pages()`: add `"commands.md"` from `render_commands(discover_commands(
    repo_dir))` with `check_count("commands", page, gen_commands.command_paths(
    repo_dir), repo_dir)`; add `"lifecycle.md"` from `render_lifecycle(repo_dir)`;
    append `gen_theme.render_theme_section()` to the **end** of the rendered
    `agents.md` (after the detail sections, so the existing "at-a-glance precedes
    detail" test keeps holding). Collect every renderer's warnings into the
    existing warnings list.
  - `generate()`: add `commands` to the returned counts; keep `--check` semantics
    byte-identical (in-memory render, compare, never write in check mode) and
    `on_pre_build` check-only. Extend the CLI's closing print to name the command
    count. Introduce no hardcoded counts.
  - `mkdocs.yml`: extend `nav:` to `Home / Agents / Skills / Commands / Hooks /
    Lifecycle` (`commands.md`, `hooks.md`, `lifecycle.md`). Flat, no nav sections.
    Touch nothing else — the existing comment blocks stay verbatim. `gen_catalog.py`
    stays the only generator in `hooks:` (the new modules are imported by it, not
    registered).
  - Run `python docs_site/gen_catalog.py` and **commit** `docs/commands.md`,
    `docs/lifecycle.md` and the regenerated `docs/agents.md`.
  - If this pushes `gen_catalog.py` back over 400, record the before/after for the
    PR's `Module-check:` line and report it to T11.
  **Files**: `docs_site/gen_catalog.py`, `docs_site/mkdocs.yml`,
  `docs_site/docs/agents.md`, `docs_site/docs/commands.md` (new),
  `docs_site/docs/lifecycle.md` (new)
  **Acceptance criteria**:
  - `python docs_site/gen_catalog.py` then `git status --porcelain
    docs_site/docs/` → clean (all generated pages committed and current).
  - `python docs_site/gen_catalog.py --check` exits 0; running it twice is a no-op.
  - `test_gen_catalog.py` and `test_site_content.py` pass **untouched** — including
    the agents count-guard and the at-a-glance-precedes-detail test.
  - `grep -c '^### `' docs_site/docs/agents.md` is unchanged from before this task.
  - Nav has exactly six entries in that order and every target file exists.
  **QA Scenarios**:
  - Hand-edit one character of `commands.md` → `--check` exits 1 naming the file;
    regenerate to restore.
  - If material installs: `cd docs_site && mkdocs build --strict` passes with no
    missing-file, orphan-page or broken-link warning. If it does not install, say
    so and report the build as not run.

- [ ] 7. `test_gen_commands.py` + the one workflow pattern change
  **Complexity**: standard
  **Depends on**: T6
  **Agent**: test author (`euclid`) — must not edit the generator
  **What to do**:
  - New `docs_site/test_gen_commands.py`. House-style module docstring, including
    **why the module is named `test_gen_*`**: it is the pattern the docs job's step
    collects, and `test_ci_coverage.py::ScannerTest` fails CI for any `docs_site`
    test module no `-p` pattern reaches. Also say why it lives in `docs_site/` and
    not `tests/` (`tests/` is on FRAMEWORK_PATHS and syncs downstream, which never
    receives `docs_site/`; mirror `test_gen_catalog.py`'s wording).
  - Cover: every discovered command renders a name, a description **and its lead
    prose**; a `## ` heading inside a fenced block does not truncate the lead; a
    relative link in the lead is rewritten to `REPO_BLOB_BASE`; `/name` renders in
    mono; the `user-invocable` meta line; `GENERATED_BANNER` present; the
    count-guard raises when a command never reaches the page; a `name:`/filename
    mismatch raises `CatalogError`; `--check` detects a hand-edit of
    `commands.md`; the **committed** `docs/commands.md` matches a fresh render.
    Use temp fixture repos (the `FixtureRepoMixin` pattern in
    `test_gen_catalog.py`) for every raising case; the real tree only for the
    committed-page check.
  - `.github/workflows/tests.yml`: change the docs-tests step at **L345** from
    `-p "test_gen_catalog.py"` to `-p "test_gen_*.py"`, and update the two or
    three comment lines in that job which name `test_gen_catalog.py` as the only
    generator module. **Add no new step; change no `if:` condition; leave the
    `test_ci_coverage.py` and `test_site_content.py` steps alone.**
  **Files**: `docs_site/test_gen_commands.py` (new),
  `.github/workflows/tests.yml`
  **Acceptance criteria**:
  - `python -m unittest discover -s docs_site -p "test_gen_*.py" -v` collects
    `test_gen_catalog`, `test_gen_commands` (and, once T8-T10 land, the other
    three) and passes.
  - `python -m unittest discover -s docs_site -p "test_ci_coverage.py" -v` passes —
    the proof the single workflow edit is sufficient for the whole batch.
  - No file under `docs_site/` other than the new test module is modified.
  **QA Scenarios**:
  - Rename the new module to `test_zz_thing.py` → `ScannerTest` reports it
    uncovered; restore. (Confirms the glob is doing the work.)
  - Break the lead-prose extraction in a scratch edit of `gen_commands.py` → the
    lead test fails naming the command; revert.

- [ ] 8. `test_gen_theme.py`
  **Complexity**: standard
  **Depends on**: T6
  **Agent**: test author (`euclid`)
  **What to do**: new `docs_site/test_gen_theme.py`, docstring per T7's rules
  (name is for CI pickup; why not `tests/`). Cover:
  - The rendered table's rows equal `_crew_common.PAIRS` **in order** — derive
    both sides from `PAIRS`, except one deliberate outside-oracle assertion that
    there are 9 rows (mirroring `ThemeNamePinTest`'s rationale).
  - **`set(PAIR_RATIONALE) == {f for f, _ in PAIRS}`** — the anti-drift pin, with a
    failure message that says what to do: "add a why line to
    `scripts/_crew_common.PAIR_RATIONALE` when you add a pair".
  - Every rationale value is non-empty and contains no ditto mark (`"` alone) —
    the README defect this batch fixes.
  - The fragment contains no `` ^### ` `` heading, and the committed `agents.md`'s
    `` ^### ` `` count is unaffected by the section's presence.
  - Every member of `TIERED_AGENTS` and `THEME_INVARIANT_ROSTER` is named on the
    page, and the page's "files renamed in all" figure equals
    `len(PAIRS) + len(TIERED_AGENTS)`.
  - The committed `docs/agents.md` ends with the `## The philosopher theme`
    section (it is generated, so this also guards the wiring).
  **Files**: `docs_site/test_gen_theme.py` (new)
  **Acceptance criteria**: `-p "test_gen_*.py"` passes; each assertion derives at
  least one side from `_crew_common`; nothing outside the new file is modified.
  **QA Scenarios**:
  - Delete a `PAIR_RATIONALE` entry → the test fails naming the pair; restore.
  - Reorder two `PAIRS` entries → the order assertion fails; restore.

- [ ] 9. `test_gen_lifecycle.py` — facts parsed, prose digest-pinned
  **Complexity**: standard
  **Depends on**: T6
  **Agent**: test author (`euclid`)
  **What to do**: new `docs_site/test_gen_lifecycle.py`, docstring per T7's rules.
  - **Parsed-facts tests**: every phase name found by scanning
    `agents/orchestrator.md` (scan it in the test, independently of the generator,
    skipping fences) appears on the page; the triage table has one row per source
    row; all three tier names appear; the page contains no integer phase count and
    not the string "six phases"; the committed `docs/lifecycle.md` matches a fresh
    render.
  - **Staleness pin (revision 3)**: store a `dict[str, str]` of **sha256 digests**
    of the five sections the prose summarises, obtained via
    `gen_lifecycle.section_text(REPO_DIR, key)` for keys `work_placement`,
    `tiering`, `routing_quality_gate`, `competence_check`,
    `discovery_brief_carrying`. Assert each current digest equals the stored one.
    Failure message, substantially:

    > `agents/orchestrator.md` section `<key>` changed — re-read
    > `docs_site/docs/lifecycle.md`'s prose for that section, update it if the
    > summary no longer holds, then update the stored digest in this file. This
    > test cannot tell a reworded paragraph from a reversed decision; that
    > judgement is yours.

    Document in the docstring that updating a digest is a **deliberate act after
    re-reading the prose**, never a reflex to get CI green, and that the digests
    are hand-maintained for exactly that reason.
  - Normalise nothing silently: hash the exact text `section_text` returns, and say
    in a comment that whitespace changes will therefore fire the pin — that is
    accepted, because a cheap false positive beats a missed reversal.
  **Files**: `docs_site/test_gen_lifecycle.py` (new)
  **Acceptance criteria**:
  - `-p "test_gen_*.py"` passes with the five digests as committed.
  - The phase-name test derives its expectation from `orchestrator.md`, not from a
    literal list.
  - Nothing outside the new file is modified.
  **QA Scenarios**:
  - Append a sentence to the Work Placement section in a scratch copy → the digest
    test fails with the message above, naming `work_placement`; revert.
  - Rename `## PHASE 5: VERIFY` in a scratch copy → the phase test fails pointing
    at `docs/lifecycle.md`; revert.

- [ ] 10. `test_gen_reference.py` — pin the hand-written Hooks page
  **Complexity**: standard
  **Depends on**: T6 (nav) and T4 (page)
  **Agent**: test author (`euclid`)
  **What to do**: new `docs_site/test_gen_reference.py`. The name is deliberate and
  the docstring must say so: `docs/hooks.md` is **hand-written**, not generated, but
  the module is named `test_gen_*` so the single `-p "test_gen_*.py"` workflow step
  collects it and `ScannerTest` stays green. Also record why it lives in
  `docs_site/` and not `tests/`.
  - Import the hook modules with `REPO_ROOT` on `sys.path` and pin, reading **one**
    side from source and the other from the page — no number hardcoded on both
    sides: `harvest_nudge.NUDGE_THRESHOLD` (default 20) and the literal
    `CLAUDE_HARVEST_NUDGE_THRESHOLD`; `PENDING_PREFIX`;
    `record_stop.RETENTION_DAYS`; the trail path components `learning-trail` and
    `CLAUDE_CONFIG_DIR`; the `[redacted]` sentinel.
  - Assert the page states retention **as a floor**: it must contain the
    un-harvested-records-survive claim, and must **not** contain a bare "deleted
    after N days" / "kept for N days only" formulation. Keep this assertion
    narrow and comment that it is a wording guard, since the semantic is the one
    a reader is most likely to get wrong.
  - Assert the page makes no absolute redaction promise (no "all secrets", no
    "never records secrets") and does name redaction as best-effort.
  - Assert `hooks.md` links to `hooks/record_stop.py`, `hooks/harvest_nudge.py`
    and `install.py`, and that every link in the page is absolute (`http`) or
    resolves to a file under `docs_site/docs/` — the `--strict` broken-link guard,
    cheaply, without a build.
  - Assert `hooks.md` is **not** in `gen_catalog.build_pages()`'s output — it is
    hand-written and must stay so.
  - Failure messages that say what to do: "a hook constant changed — update
    `docs_site/docs/hooks.md`".
  **Files**: `docs_site/test_gen_reference.py` (new)
  **Acceptance criteria**: `-p "test_gen_*.py"` passes; every assertion derives at
  least one side from the hook modules; nothing outside the new file is modified.
  **QA Scenarios**:
  - Change `NUDGE_THRESHOLD`'s default to 21 in a scratch edit → the test fails
    pointing at `hooks.md`; revert.
  - Add "records are deleted after 14 days" to the page in a scratch edit → the
    wording guard fires; revert.

- [ ] 11. Full verification pass and delivery
  **Complexity**: simple
  **Depends on**: T1-T10
  **What to do**: run from the worktree root and report each result verbatim:
  1. `python -m unittest discover -s docs_site -p "test_gen_*.py" -v`
  2. `python -m unittest discover -s docs_site -p "test_site_content.py" -v`
  3. `python -m unittest discover -s docs_site -p "test_ci_coverage.py" -v`
  4. `PYTHONPATH=scripts python -m unittest discover -s tests -v` (the root suite —
     `_crew_common` and the hooks now have new consumers)
  5. `python -m unittest discover -s brand -v`
  6. `python docs_site/gen_catalog.py --check`
  7. `python docs_site/gen_catalog.py` then `git status --porcelain
     docs_site/docs/` — **must be clean**
  8. `python scripts/module_scan.py --json` — no new file over 400; record
     `gen_catalog.py`'s before (**732**) and after line counts
  9. `python -m pip install "mkdocs-material==9.7.7"` then
     `cd docs_site && mkdocs build --strict`. **If the install fails** (offline /
     no network), report the build as **not run** with the reason — do not report
     it as passing. CI's `docs-tests` job covers it either way.
  - **Delivery**: PR body states scope / what changed / how to test, and **must
    carry a `Module-check:` verdict for every >400-line file this branch grows** —
    name the file, its before/after line count, and the verdict (extracted /
    accepted-and-why). `gen_catalog.py` is the expected subject: T1 shrinks it and
    T6 grows it back somewhat; `scripts/_crew_common.py` crosses 400 only if T3
    overran, which the acceptance criteria forbid. Conventional commit prefixes
    (`refactor:` / `feat(docs):` / `test:`); branch `docs/site-framework-pages`,
    never committing to the default branch.
  **Files**: none (read-only; report only)
  **Acceptance criteria**: every command passes or is reported not-run with its
  reason; any failure reported with full output rather than worked around; the
  `Module-check:` line is present in the PR body with real numbers.
  **QA Scenarios**: step 7's clean status is the key one — a dirty tree there means
  a generator task forgot to commit its output, which is exactly the drift this
  batch exists to prevent.

## Success Criteria

1. Nav is `Home / Agents / Skills / Commands / Hooks / Lifecycle`, and
   `mkdocs build --strict` passes in CI.
2. `docs/commands.md` is generated from `commands/*.md` frontmatter **and** lead
   prose; `docs/lifecycle.md`'s phase list and triage table are parsed from
   `agents/orchestrator.md` with no phase count anywhere; `docs/agents.md` ends
   with a theme table whose names and rationale both come from
   `scripts/_crew_common`.
3. `docs/hooks.md` describes redaction as best-effort, retention as a floor, what
   may land in the trail, and how to delete and disable each hook — every number
   pinned to a hook constant by a test.
4. `python docs_site/gen_catalog.py --check` exits 0 on a clean checkout, and
   regenerating leaves the tree clean.
5. The lifecycle prose carries a sha256 staleness pin over the five orchestrator
   sections it summarises, with a failure message that demands a re-read.
6. All four new test modules run in CI behind the single
   `-p "test_gen_*.py"` change; `test_ci_coverage.py` is green;
   `test_gen_catalog.py` and `test_site_content.py` pass with no assertion edited.
7. `gen_catalog.py` is smaller than 732 at T1 and the PR body carries its
   `Module-check:` verdict; no new file exceeds 400 lines.
8. No README, styling or nav-structure changes beyond the four nav entries.
