# Discovery Brief: docs site — first batch of framework/tooling pages

## Objective
The docs site (docs.nescio-ai.org, MkDocs Material under `docs_site/`) has three
pages: Home, Agents, Skills. It shows *who* the crew is but not *how it runs* or
*how to operate it*. First batch adds four things:
1. **Commands** catalogue — generated from `commands/*.md` frontmatter.
2. **Philosopher theme mapping** — generated table on the Agents page (or its own
   section) from `scripts/_crew_common.PAIRS`.
3. **Hooks** reference — Stop + SessionStart: what they record, where, how to tune/disable.
4. **Orchestrator lifecycle** — phases, gates, tiering, work placement, refusal.

## Codebase map
- `docs_site/mkdocs.yml` — nav (Home/Agents/Skills), hooks: `gen_catalog.py`
  (check-only drift guard, raises on stale pages), `hooks/assets.py`,
  `hooks/inline_svg.py`. `mkdocs build --strict`.
- `docs_site/gen_catalog.py` — generator AND CLI (`python docs_site/gen_catalog.py`
  writes; `--check` verifies). Has `split_frontmatter`, `Item`, `Catalog`,
  `discover_agents/skills`, `render_agents/skills`, `GENERATED_BANNER`,
  `AGENT_GROUPS`, `REPO_BLOB_BASE`. Tested by `docs_site/test_gen_catalog.py`.
- `.github/workflows/docs.yml` — deploy runs `python docs_site/gen_catalog.py`
  BEFORE `mkdocs build --strict` (regenerates, never refuses). mkdocs-material
  pinned 9.7.7.
- `commands/` — `harvest-memory.md`, `assess-repo.md`; frontmatter `name`,
  `description`, `user-invocable: true`. Same `---` YAML shape as agents/skills.
- `scripts/_crew_common.py` — `PAIRS` (functional↔philosopher name pairs),
  `THEMES`. `scripts/apply_theme.py` applies/reverts the theme.
  README §"Optional: the philosopher theme" has a hand-written table with a *why* column.
- `hooks/record_stop.py` — Stop hook, async; fires per TURN; appends one JSONL
  line to `<CLAUDE_CONFIG_DIR or ~/.claude>/learning-trail/<repo_key>.jsonl`;
  machine-local, never synced; redacts; stores `transcript_path` pointer, no verdict;
  opportunistic pruning/retention.
- `hooks/harvest_nudge.py` — SessionStart: (1) unfinished-harvest marker
  `.harvest-pending-<repo_key>`, (2) un-harvested count ≥
  `CLAUDE_HARVEST_NUDGE_THRESHOLD` (default 20), (3) fired/near ADR 0002 memory
  triggers via `scripts/check_memory_triggers.py` subprocess.
- `install.py` — wires both hooks into `~/.claude/settings.json` (~lines 756-780).
- `agents/orchestrator.md` (33 KB) — source of truth for the lifecycle.
- `docs_site/test_site_content.py` — being split into six modules by PR #220
  (stacked on #219). New site tests must land in the post-split layout or
  conflict.
- `README.md` — covers install, sync, theme, memory/loop, prerequisites, Serena.
- `docs/design/design-system.md` §6, `docs_site/docs/assets/css/nescio.css` — site styling.

## Conventions to match
- Generated pages carry `GENERATED_BANNER`, are committed, and are drift-checked;
  regenerate deliberately, never by a writing mkdocs hook.
- Agent/skill names in mono (backticks). Heavy "why" comments in config and generator.
- unittest-style tests; conventional commits; branch per change; PR body states
  scope / what changed / how to test; `Module-check:` line when a >400-line file grows.

## Constraints and hazards
- **Drift is the failure mode we just fixed** ("Ten agents" vs 16). Prefer
  generated content; where prose restates a source (orchestrator, hooks), keep it
  short and link to the source file, or pin key facts with a test.
- Hand-written pages must not claim specifics that a test cannot hold (counts,
  thresholds) unless pinned.
- `gen_catalog.py` is already sizeable — adding commands + theme may trip the
  module gate; decide extend vs. separate module.
- Theme mapping must render correctly whichever theme the *repo* is on (the
  committed tree is functional); source from `PAIRS`, not from `agents/`.
- Do not duplicate README text wholesale; site becomes canonical, README links.
- Base: PR #219 (`claude/docs-page-review-2ee91d`) and #220 are unmerged.

## External research
Skipped — no external surface (MkDocs Material features already in use).

## Assessment
Two generated additions (Commands page, theme table) extend `gen_catalog.py`
patterns. Two hand-written pages (Hooks, Orchestrator) summarise sources with
links, and pin the facts most likely to drift (threshold default, trail path,
phase list) with tests.

## Open questions
- Theme table: on Agents page vs. own page? (planner decides; user can override)
- Should README sections shrink to links in this batch or later? (user)

## Addendum (after plan review, 2026-10-30)
- Base changed: work happens on branch `docs/site-framework-pages` from origin/main
  (#219 merged at 3c3ca4e) in worktree
  `.claude/worktrees/docs-framework-pages`.
  Not stacked on #220. All new tests are `docs_site/test_gen_*.py`; `test_site_content.py` untouched.
- Wiring of renderers into `gen_catalog.py`/`mkdocs.yml`/generated pages is owned by ONE task (T6).
- Lifecycle page is generated (phases + triage table parsed from orchestrator.md, fences skipped);
  prose summaries are digest-pinned to orchestrator.md sections.
- Theme rationale moves to `scripts/_crew_common.PAIR_RATIONALE`; `docs_site/` importing
  `scripts/` is accepted (stdlib-only module, full checkout in CI) — amends the comment in
  `test_gen_catalog.py` ~L372.
- Hooks page: redaction is best-effort; 14-day retention is a floor; preview is of the last
  assistant message, not the user prompt.
