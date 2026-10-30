# Plan: crew model bump, contradiction fixes, trio roles, ADR rationale

Brief: `.sisyphus/discovery/2026-10-30-crew-models-and-contradictions.md`
Branch: `claude/agent-crew-review-7243d7` (one PR).
Baseline first: `python -m pytest -q` (or the repo's CI test command) — record result.
Installed agent names are themed: builder-simple→archimedes-simple, builder-standard→archimedes-standard, test-writer→euclid, qa-guard→cato, reviewer→pyrrho.

## Decisions (user, 2026-10-30)
- Pin exact 5.5 IDs. Effort: **all three builder tiers `high`** (tier doctrine "differ only in model" stays true); other Opus roles `high`; Sonnet roles `medium`; explore `low`.
- qa-guard may not create new check-config files.
- scripts/: link the whole dir, documented in the LINKS comment.
- Trio: scout = "did we miss something specific to the task?" (pre-plan); advisor = recommends design shape; critic = devil's advocate on the plan, incl. "what breaks in existing code / combines into new bugs if built as proposed". All three: no criticism for its own sake.
- ADRs record rationale and rejected alternatives (why not taken), mandatory except as-built.

## Wave 1

### T1 — Bump models, pin effort, record the probe
**Complexity**: simple · **Placement**: subagent (`builder-simple`)
- All 17 `agents/*.md` frontmatter: `claude-opus-5`→`claude-opus-5-5`, `claude-sonnet-5`→`claude-sonnet-5-5`, `claude-haiku-4-5`→`claude-haiku-5-5`.
- Add `effort:` after `model:` — high: orchestrator, planner, critic, reviewer, scout, advisor, validator, test-writer, builder, builder-standard, builder-simple · medium: qa-guard, doc-researcher, doc-writer, librarian, vision · low: explore.
- `tests/test_agent_definitions.py` `ALLOWED_MODELS`: ADD the three 5.5 IDs; KEEP all existing IDs, with a comment "superseded IDs kept so a model revert is a one-line change".
- CONTRIBUTING.md, next to the `[1m]` provenance paragraph (~l.86-119), add a short measured note (text in brief §Probe).
- Regenerate `docs_site/docs/agents.md`: `python docs_site/gen_catalog.py` (CI runs `--check`).
- **Accept**: full suite + `python docs_site/gen_catalog.py --check` green; no frontmatter still names a superseded ID; every agent has `effort:`.

## Wave 2 (parallel — disjoint files)

### T2 — Blocked-builder routing
**Complexity**: standard · **Placement**: subagent (`builder-standard`)
- orchestrator.md After Each Task rule 4 (~l.449-455): `COMPLETE` → accept; `PARTIAL` → follow-up naming remaining work; `BLOCKED` → the orchestrator classifies the named blocker: a missing decision or fact → user; "harder than the tier" → escalate one tier per the Escalate section (max one step at a time; `builder` (top tier) blocked → user, never a loop).
- Builder tier paragraph (builder*.md:17-20, identical wording across tiers): the builder names the blocker plainly (what decision/fact is missing, or what proved harder than expected); the orchestrator decides routing. No new enum field.
- planner.md:130-132: align wording.
- **Accept**: suite green; three builder files differ only in frontmatter + tier paragraph.

### T3 — qa-guard boundary
**Complexity**: simple · **Placement**: subagent (`builder-simple`)
- qa-guard.md: add "Do not commit — leave fixes in the working tree; the orchestrator audits and commits them."
- Add new check-config files (conftest.py, pytest.ini, ruff.toml, .flake8, mypy.ini, setup.cfg, tox.ini) to the forbidden boundary (l.11-17); keep all existing boundary terms (`BOUNDARY_SCOPE_TERMS` test).
- l.59 "missing fixtures": only fixtures inside existing test files; anything needing a new config file → `BLOCKED`.
- **Accept**: suite green; consistent with orchestrator.md CI Gate Audit (l.573-613).

### T4 — Sharpen the scout / advisor / critic trio
**Complexity**: standard · **Placement**: subagent (`builder-standard`)
- **scout.md**: frame as pre-plan completeness check — "did we miss something specific to this task?" (unstated requirements, edge cases, scope gaps, hidden intent). Take the triage class it is handed instead of re-classifying (soften the MANDATORY Phase 0 into "use the class you were given; only reclassify if it is clearly wrong, and say so"). Keep the refactor git-archaeology directive.
- **advisor.md**: owns design recommendation. Remove the `interrogate` mode (plan stress-testing belongs to critic); update description if it mentions it.
- **critic.md**: keep devil's-advocate identity and lenses; add a lens "Integration / regression — for each change the plan makes, what in the existing codebase depends on it (callers, shared state, invariants, covering tests), and what breaks or combines into a new bug if built as proposed?" Update description + "What you are NOT" so the three roles are distinct. Replace l.81-85 research paragraph: "Substantiate with Read/Grep/git. When a challenge needs external evidence, say so in the challenge so the orchestrator can dispatch `librarian`."
- **All three**: one plain sentence — raise only material findings; never criticise for its own sake or pad to look thorough; "nothing material" is a valid result. (critic already has this — align wording, don't duplicate.)
- Check orchestrator.md references to advisor interrogate mode / scout classification and fix any (read-only otherwise — T2 owns orchestrator edits; if an orchestrator change is needed, report it in `<deviations>` rather than editing).
- **Accept**: suite green (dispatch-rights + roster tests unchanged); descriptions distinguish the three roles in one line each.

### T5 — create-adr: rationale and rejected alternatives
**Complexity**: simple · **Placement**: subagent (`builder-simple`)
- skills/create-adr/SKILL.md Step 4 + skills/create-adr/adr-template.md: make `## Options considered` (or "Alternatives considered") REQUIRED for proposed/accepted ADRs — each option with pros/cons and **why it was not taken**; always include "do nothing / status quo". Add rationale to `## Decision` ("why this option won, against which drivers"). Exempt as-built ADRs (they document existing code). Keep the anti-padding line, reworded: list the alternatives actually weighed; don't invent straw men.
- Update Common mistakes table: "No rejected alternatives recorded" → add them with reasons.
- Fix frontmatter mismatch: template uses `title/status/source_repo`, SKILL uses `name/description/type/status`. Check which one existing ADRs (`~/.claude/memory/repo/*/adr/` or `memory/repo/*/adr/`) and `scripts/publish_adrs.py` / `_adr_transform.py` expect; align the other. If they're intentionally different (e.g. template = published form), say so in a comment instead of changing.
- **Accept**: suite green (incl. test_publish_adrs / test_adr_transform).

## Wave 3

### T6 — Link scripts/ for product checkouts
**Complexity**: standard · **Placement**: subagent (`builder-standard`)
- install.py `LINKS`: add `("scripts", "scripts")`; extend the LINKS comment: whole dir linked deliberately — scripts are already on disk, the link only gives agents a stable path.
- Replace `python scripts/…` with `python "$HOME/.claude/scripts/…"` (works in bash and PowerShell) in orchestrator.md:445, planner.md:144-146, all three builder tiers (~l.60-61), identical across tiers.
- Update tests/test_install.py for the new link.
- **Accept**: suite green; `grep -rn "python scripts/" agents/` empty.

### T7 — Tests for the new contracts
**Complexity**: simple · **Placement**: subagent (`test-writer`)
- tests/test_agent_definitions.py: every agent declares `effort` ∈ {low, medium, high, xhigh, max}; the three builder tiers have identical `effort`; builder tier bodies identical after stripping frontmatter + tier paragraph.
- Update the stale docstring of `test_orchestrator_routes_blocked_to_the_user` to the new routing.
- If cheap: a create-adr test asserting the template contains an alternatives section.
- **Accept**: new tests pass; regression gate (test commits touch tests only).

## Verify
`qa-guard` CI gate + CI Gate Audit; `reviewer` audit against this plan.

## Out of scope (carried)
Remaining capability gaps (bug-fix diagnosis step, skill routing from critic/reviewer, refactor triage class, vision/app verification, PR-comment handling, create-adr wiring in orchestrator); prompt de-shouting; orchestrator trim; validator/planner/doc-researcher contradictions; ai-os themed copy sync and its `[1m]` suffix; effort shown in generated catalog.
