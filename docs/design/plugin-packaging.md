# Plugin packaging: design spike

**Status:** research only. Nothing here changes `install.py`, `agents/`, or any
other production file.
**Date:** 2026-11-12. Claude Code v2.1.322.
**Question:** can NescioAI ship as a Claude Code plugin, instead of or alongside
the `install.py` symlinks? What would a `claude plugin eval` suite for the crew
look like?

## TL;DR

- **Partly.** Agents, skills and commands load from a plugin as-is.
  `claude plugin validate .` passes on the repo root today, with no manifest.
  CLAUDE.md, `permissions`, `enabledPlugins`, `memory/` and the two hooks
  can't come from a plugin, or can't without a refactor.
- **Namespacing is the blocker, and it is confirmed.** A plugin agent is only
  reachable as `<plugin>:<name>`. A bare `subagent_type: "builder-simple"`
  fails to resolve (tested, see [Evidence](#evidence)). All 12 dispatch
  declarations in `agents/orchestrator.md` use bare names, and so do
  `tests/test_agent_definitions.py` and `scripts/apply_theme.py`. One source
  tree can't serve both install paths unless a render step rewrites the names.
- **Recommendation:** keep `install.py` as the way to install the crew. Add a
  **generated plugin build** (`scripts/build_plugin.py` → `dist/plugin/`),
  first only so the crew can be tested with `claude plugin eval`. Decide on
  plugin distribution later, from real eval results. See
  [Recommendation](#6-recommendation).
- **Update: the split is the better target.** NescioAI is meant for other
  people too, so §7 looks at splitting it into a **crew plugin** and a **brain
  template you fork**, joined by a small explicit contract. This is the stronger
  long-term shape. If the crew is *only* ever installed as a plugin, its source
  can use `nescio:` names directly. The render step is then no longer needed,
  and `sync_from_upstream.py` no longer has to handle themes. Seven steps,
  in §7.

## Evidence

Docs read on 2026-11-12: `plugins-reference.md`, `plugins/components.md`,
`plugins/create-marketplace.md`, `plugins/marketplace-reference.md` (the
strict-mode table was only read through a summary), and `plugin-evals.md`.
Not read: `hooks.md`, `settings-reference.md`, `host-marketplace.md`.

Checks run in a scratch directory with Claude Code 2.1.322:

| Check | Result |
|---|---|
| `claude plugin validate .` on this repo's root, no manifest | **Passed.** One `ICON_MISSING` warning and a `MANIFEST_NOT_FOUND` note. No CLAUDE.md warning was printed. The docs say there is one, so it may only appear when a manifest exists. |
| `claude plugin eval init --bare first-case` in a minimal plugin | Wrote `evals/first-case/prompt.md` (frontmatter `max_turns: 10`, `allowed_tools: [Read, Glob, Grep, Skill]`) and `graders/criteria.md` (`type: llm`). It refuses to run in a directory that isn't a plugin. |
| `claude -p --plugin-dir <spike>`: dispatch `subagent_type: builder-simple` (bare) | **Not found.** Only `nescio:builder-simple` is visible, and it dispatched correctly. |
| Plugin-root `settings.json` `{"agent": "builder-simple"}` (bare) and `{"agent": "nescio:builder-simple"}` | **Both work**, but only with `--setting-sources project`. With normal sources, the user's `~/.claude/settings.json` `"agent": "orchestrator"` (written by `install.py`) wins, so the plugin default is ignored. |

## 1. Mapping: what moves into a plugin and what doesn't

Plugin layout: `.claude-plugin/plugin.json` (optional; only `name` is required),
and component directories at the plugin root.

| Repo path | Plugin? | Notes |
|---|---|---|
| `agents/` (17 files) | **Yes** | Default scan location. Frontmatter is compatible, see §2. Dispatch names break, see §3. |
| `skills/` (36 skills) | **Yes** | Default scan location. They become `/nescio:<skill>`. |
| `commands/` (`assess-repo`, `harvest-memory`) | **Yes** | They become `/nescio:assess-repo` and `/nescio:harvest-memory`. The docs prefer `skills/` for new plugins, but `commands/` is still supported. |
| `hooks/*.py` + the `Stop`/`SessionStart` wiring | **Mechanically yes, in practice no.** See below. | Needs a `hooks/hooks.json` with the `{"hooks": {...}}` wrapper. Without the wrapper the file fails to load. |
| `scripts/` | **Ships as files.** | 10 references in `agents/` and `skills/` use `~/.claude/scripts/<name>.py`. The plugin form is `${CLAUDE_PLUGIN_ROOT}/scripts/<name>.py`, which Claude Code substitutes inside agent and skill Markdown. It is **not** set in Bash tool commands, so the substituted path has to reach the model through the prompt text. `bin/` (put on `PATH`) is an alternative for a few entry points. |
| `settings.json` → `agent` | **Yes, as a default.** | Plugin-root `settings.json` honours only `agent` and `subagentStatusLine`. The user's own `agent` setting overrides it (tested). |
| `settings.json` → `permissions` | **No** | Dropped from plugin settings. Stays in `install.py`'s settings merge. |
| `settings.json` → `enabledPlugins` | **No** | Same. A plugin can declare `dependencies` on other plugins, but it can't enable them in user settings. |
| `CLAUDE.md` | **No** | A plugin-root `CLAUDE.md` isn't loaded. The docs suggest a skill instead, but a skill loads **on demand**. The operating brief is meant to be always loaded, so a skill is weaker. Keep `install_claude_md()` (import/replace/skip). |
| `memory/` | **No** | It's user data in a git checkout that `/harvest-memory` writes to. `${CLAUDE_PLUGIN_ROOT}` is a cache copy that changes on every update ("don't write state there"). 12 references to `~/.claude/memory` need it at a stable, writable path. |

### Why the hooks don't move cleanly

1. **The interpreter.** `_wire_command_hook` writes an absolute base-interpreter
   path into `command`. It deliberately avoids venvs, because a hook whose
   interpreter has vanished fails silently (issue 144, and `check_hooks` was
   added to make that visible). `hooks.json` would have to use something like
   `"command": "python \"${CLAUDE_PLUGIN_ROOT}/hooks/record_stop.py\""` and rely
   on `PATH`. On Windows, `python`/`python3` can resolve to the Store alias.
   That reintroduces the silent failure `install.py` was built to avoid.
2. **Repo-root coupling.** `memory_trigger_nudge.py` finds the repo through
   `Path(__file__).resolve().parent.parent` and shells out to
   `<root>/scripts/check_memory_triggers.py` against `<root>/memory/`. From a
   plugin, `<root>` is the plugin cache. It holds a stale `memory/` or none, so
   the nudge would check the wrong tree without any error. Fixing this means
   taking the brain path from configuration, for example a `userConfig` option,
   which hook processes receive as `CLAUDE_PLUGIN_OPTION_<KEY>`.
3. `record_stop.py` writes to `$CLAUDE_CONFIG_DIR` or `~/.claude`, so it is not
   affected. It is still blocked by point 1.
4. Whether plugin hooks support `Stop` was not checked (`hooks.md` not read).
   `SessionStart` appears in a plugin `hooks.json` example in the docs.

## 2. Agent frontmatter compatibility

Plugins honour `name`, `description`, `model`, `effort`, `maxTurns`,
`autoCompactWindow`, `tools`, `disallowedTools`, `skills`, `memory`,
`background`, `omitClaudeMd`, `isolation` (only `"worktree"`), `color`, and
`experimental.cacheTtl`. They **ignore** `permissionMode`, `hooks`,
`mcpServers`, and `initialPrompt`.

Keys used across all 17 `agents/*.md` files:

| Keys | Agents |
|---|---|
| `name, description, model, effort, tools` | advisor, builder, builder-simple, builder-standard, critic, doc-writer, planner, qa-guard, reviewer, scout, test-writer, validator, vision |
| `+ omitClaudeMd` | doc-researcher, explore, librarian |
| `name, description, model, effort, disallowedTools` | orchestrator |

**Every key is supported, and no agent uses an ignored key.** Frontmatter is not
a blocker.

`tests/test_agent_definitions.py` assumes:

- **Agent files sit at `ROOT / "agents"`, named after the bare (possibly
  themed) agent name.** Still true in a plugin build, because filenames don't
  change. Only the runtime identity gains the prefix.
- **`DISPATCH_RE = r'subagent_type: "([^"]*)"'` values match agent file
  names**, split on `|` (`_dispatch_targets`). If the orchestrator's text
  becomes `nescio:builder`, these checks fail unless they strip the prefix.
- **The `ALLOWED_MODELS` and `ALLOWED_EFFORTS` allowlists.** Unaffected.
- **Theme awareness through `_themed()` and `apply_theme.detect_theme()`.**
  Unaffected. `apply_theme`'s word-boundary rename would rewrite `builder`
  inside `nescio:builder` correctly, but this is untested.

## 3. Namespacing: what breaks

Confirmed: plugin agents are `<plugin>:<name>`, skills `/<plugin>:<dir>`,
commands `/<plugin>:<file>`. Bare agent names **do not resolve** to plugin
agents.

What breaks:

1. **`agents/orchestrator.md`: all 12 `subagent_type:` declarations** (`explore`,
   `scout`, `advisor`, `planner`, `validator`, `critic`, `builder | builder-standard
   | builder-simple`, `doc-researcher`, `test-writer`, `qa-guard`, `reviewer`,
   `doc-writer`). The orchestrator dispatches by copying these strings, so a
   plugin-loaded orchestrator would emit names that aren't found. The likely
   result is a fallback to `general-purpose`, or a stalled phase.
2. **Prose references** to agents and skills in charters and skills, such as
   "load the `modular-design` skill" or "dispatch `builder-simple`". The model
   can often work these out, but the result isn't reliable.
3. **`tests/test_agent_definitions.py`** dispatch-target checks, see §2.
4. **`scripts/apply_theme.py`**, which already rewrites names across the crew.
   This is the precedent for the fix.
5. **Name collisions in a hybrid install.** With the symlinked crew in
   `~/.claude/agents/` *and* the plugin enabled, the user sees 17 bare agents
   and 17 `nescio:` agents, with the same descriptions competing for routing.
   Each machine must use one or the other, never both.
6. **The root `agent` setting** is fine, because a bare name inside the plugin's
   own `settings.json` resolves (tested). But `install.py`'s user-level
   `"agent": "orchestrator"` takes precedence. If the bare orchestrator is
   uninstalled, that setting points at nothing.

**Fix pattern:** a render step, like `apply_theme.py`, that rewrites
`subagent_type: "X"` to `"nescio:X"`, rewrites `~/.claude/scripts/` to
`${CLAUDE_PLUGIN_ROOT}/scripts/`, and writes the result to a build directory.
The source tree keeps bare names. Rendering in place would break the symlink
install and the tests. The render should run after theming, so a themed brain
gets `nescio:archimedes`.

## 4. Marketplace

Verified against `plugins/create-marketplace.md` and `marketplace-reference.md`:

- File: `.claude-plugin/marketplace.json` at the marketplace root. Required:
  `name`, `owner` (`{name}`), and `plugins[]`. Each entry requires `name` and
  `source`. Relative sources must start with `./` and can't contain `..`.
  `"./"` or `"."` means the root.
- Commands: `claude plugin validate <dir>`,
  `claude plugin marketplace add <path | owner/repo>`, and
  `claude plugin install <plugin>@<marketplace>`. In a session:
  `/plugin marketplace add …` and `/plugin install …`.
- Local relative-path marketplaces pick up edits "at the next session start or
  when you run `/reload-plugins`", with no `version` bump needed. Setting
  `version` in `plugin.json` pins users to it until it changes.
- `extraKnownMarketplaces` in settings can pre-register a git marketplace.
- Reserved names include `claude-plugins-official`, `github`, and any
  `claudeai-*` name. `nescio` is not reserved.

Sketch, with the marketplace and the plugin in one repo, pointing at the built
tree rather than the repo root:

```json
{
  "name": "nescio",
  "owner": { "name": "NescioAI maintainers" },
  "plugins": [
    { "name": "nescio", "source": "./dist/plugin",
      "description": "The NescioAI agent crew: orchestrator, builders, reviewers, skills" }
  ]
}
```

Why not `"source": "./"`: the repo root also holds `memory/`, `tests/`, `docs/`
and `CLAUDE.md`. On a private brain fork, `memory/` is personal. Installing
copies the whole source into the plugin cache, and anyone who adds the fork as a
marketplace would get it too. Point `source` at the build output, which must be
committed (or published to a release branch) for a git marketplace to see it.

Not verified: how updates and auto-update work for hosted marketplaces
(`host-marketplace.md`), and the exact JSON shape of `enabledPlugins`.

## 5. A `claude plugin eval` suite for the crew

Facts from `plugin-evals.md` (needs v2.1.269+):

- A case is `evals/<case>/prompt.md` (frontmatter plus prompt body) and
  `graders/*.md`. An optional `case.yaml` adds `context.*` fields such as
  `history_file`, `scaffold_script` (only runs with `--scaffold`) and
  `add_dirs`.
- Grader types: `regex`, `tool_used` (regex on the JSON-encoded tool input;
  `min`/`max`, where `max: 0` forbids a call), `tool_order`, `file_exists`,
  `llm` (passes on 2 of 3 judge votes), and `baseline`.
- The sandbox loads **only the plugin under test**: no user CLAUDE.md, no
  other plugins. `Agent` is a read-only tool, so it is allowed. Bash, Write and
  Edit need `--allow-tools`, and granting Bash on native Windows needs WSL2.
- Defaults: 3 runs per arm, with an extra arm that runs without the plugin,
  and `--threshold 1.0`.

Two design points specific to this crew:

- **Run with `--ablation none`.** Without the plugin there is no orchestrator,
  so that arm measures nothing useful and doubles the cost.
- **Get past the approval gates with `context.history_file`.** The orchestrator
  stops for approval after triage and after each phase. A case that tests
  dispatch supplies a prior conversation in which the user has already
  approved. Don't add an `append_system_prompt` that says "skip the gates": it
  changes the behaviour being tested.

The cases below assume the rendered build (`nescio:` dispatch names). The
`input_match` field name `subagent_type` is **not stated in the docs** and must
be checked against the first run's `--keep-temp` trace. Whether a plugin-root
`settings.json` `agent` key takes effect in the eval sandbox is also unchecked.
If it doesn't, each case needs `--agent`-equivalent setup.

### Case 1: `route-mechanical-to-simple-tier`

Catches the costliest regression the charter warns about: over-tiering to Opus.

```markdown
<!-- evals/route-mechanical-to-simple-tier/prompt.md -->
---
max_turns: 12
allowed_tools: [Read, Glob, Grep, Agent]
---
Approved — go ahead with the plan. (history: plan has one task, "rename
`get_usr` to `get_user` in 3 files", Complexity: simple)
```

```markdown
<!-- graders/dispatched-simple.md -->
---
type: tool_used
tool: Agent
input_match: '"subagent_type"\s*:\s*"nescio:builder-simple"'
---
<!-- graders/not-opus-tier.md -->
---
type: tool_used
tool: Agent
input_match: '"subagent_type"\s*:\s*"nescio:builder"'
max: 0
---
```

The closing `"` in the second pattern stops it matching `builder-simple`. This
is the same token-vs-substring hazard that `_dispatch_targets` guards against.

### Case 2: `librarian-gate-skips-internal-work`

An internal refactor with no external API should get `explore` and not
`librarian`. The charter calls an unnecessary librarian dispatch "pure cost".

- `tool_used` Agent, `input_match: '"nescio:explore"'`, `min: 1`
- `tool_used` Agent, `input_match: '"nescio:librarian"'`, `max: 0`
- `regex` on `last_message`, `pattern: 'librarian.{0,40}skip'`, `flags: i`.
  The charter requires a one-line note when librarian is skipped.

### Case 3: `discover-before-build`

The orchestrator must not implement anything before discovery.

- `tool_order`: `before: { tool: Agent, input_match: '"nescio:explore"' }`,
  `after: { tool: Agent, input_match: '"nescio:builder' }`. The trailing
  pattern deliberately leaves the closing quote off, so it matches all three
  tiers.
- `tool_used` Edit, `max: 0`. The orchestrator has `disallowedTools: Edit`, so
  a pass also confirms the frontmatter survived packaging.

### Case 4: `blocked-on-decision-goes-to-user`

A `history_file` in which `builder-simple` returned `BLOCKED` because a decision
is missing ("which timezone should timestamps use?"). The charter says this goes
to the user, not up a tier.

- `tool_used` Agent, `input_match: '"nescio:builder-standard"'`, `max: 0`
- `llm`: "The response asks the user to make the missing decision (timezone)
  and does not re-dispatch an implementer or guess the answer."

### Case 5: `triage-sensitivity-flag-fires-critic`

A one-line change to an authorization check. It is Trivial by size but
sensitive, so the plan phase must include the devil's-advocate review even
though the triage class is trivial.

- `regex`, `pattern: 'Type\*\*:\s*\w+'`. Checks that the triage block is
  present.
- `llm`: "The response flags the change as touching authN/authZ and states that
  `critic` (devil's advocate) will review the plan, or asks to run it, despite
  the trivial size."

### Running it

```bash
claude plugin eval dist/plugin --ablation none --runs 3 --judge-model claude-haiku-4-5 --max-cost-usd 10 --no-publish --json evals-results.json
```

**Cost:** each run is a real orchestrator session on the crew's own models.
The orchestrator runs on Opus, and the subagents it dispatches run on their own
tiers. Five cases × 3 runs gives about 15 orchestrator sessions, plus 3 judge
calls per `llm` grader per run. This is too expensive for every PR. Run it
before a release or when charters change, and keep `--max-cost-usd` set.
Spike reference: one Haiku dispatch round-trip cost $0.019.

## 6. Recommendation

| Option | What it takes | Cost | What it buys |
|---|---|---|---|
| **A. Stay as-is** | Nothing | None | Nothing new. The crew has no behavioural tests, only structural ones. |
| **B. Plugin only** | Render step; hooks refactored for configured brain path and interpreter; brief moved into a skill; `install.py` removed | **High.** Loses the always-on CLAUDE.md brief, the `permissions` and `enabledPlugins` merge, `memory/` at a stable writable path, and the safe hook interpreter. The brain's purpose is a checkout you edit and harvest into; a read-only plugin cache works against that. | One-command install, versioned updates |
| **C. Hybrid**: plugin for agents, skills and commands; slim `install.py` for CLAUDE.md, permissions, enabledPlugins, memory, scripts, hooks | Render step; `install.py` stops linking `agents/`, `skills/`, `commands/` and installs the marketplace instead; migration step that unlinks the old symlinks so there are no duplicate agents; `"agent"` setting moved to `nescio:orchestrator` | **Medium.** Two install mechanisms to document and test. `/nescio:` prefixes in every user-facing command. Every charter edit needs a re-render and reload. | Versioned crew updates; `claude plugin eval` |
| **D. Eval-only plugin build** (recommended now) | `scripts/build_plugin.py` (render to `dist/plugin/`, gitignored) + tests for the render + `evals/` with the five cases above | **Low to medium.** One script modelled on `apply_theme.py`; no change to how users install | Behavioural regression tests for routing, which no current test covers. Each piece is also a prerequisite for C. |

**Recommendation: D now, then decide on C based on its results.** D keeps the
source of truth and the install path unchanged. It creates the render step that
both C and the evals need, and it tests whether eval results are stable enough
to rely on before any distribution changes. Move to C only if (a) the evals
prove useful, and (b) there is real demand for one-command installs from
people other than the maintainer. B is not recommended. It gives up the
always-on brief and writable memory, which make this a brain rather than a
bundle of agents.

### Open questions for the D follow-up

1. The `tool_used` input field name for Agent dispatches. Check with
   `--keep-temp` on the first run.
2. Whether a plugin-root `settings.json` `agent` key applies inside the eval
   sandbox.
3. Whether plugin hooks support `Stop`. Read `hooks.md`. This only matters for
   B and C.
4. Whether `history_file` can hold a mid-conversation subagent result (Case 4),
   or only user and assistant turns.

## 7. Evaluation: splitting the crew (plugin) from the brain (fork)

**The goal:** someone can install the crew as a plugin and use it with no
brain. Someone else can fork the brain and use it with that same plugin. The
two parts should work together without any glue the user has to write.

### 7.1 Where each part goes

From `agents/`, `skills/`, `commands/`, the scripts those three reference, and
`FRAMEWORK_PATHS` in `scripts/sync_from_upstream.py`:

| Crew plugin (`nescio`) | Brain template (fork) |
|---|---|
| All 17 agents | `CLAUDE.md` (the always-loaded brief) |
| Engineering skills: `code-navigation`, `modular-design`, `layered-api-design`, `handle-pr-comments`, `dependency-pr-ci-fix`, `gh-milestones-projects`, `fix-security-vulnerabilities` | `memory/` |
| Crew scripts: `module_scan.py` (builders, planner, two skills), `verify_commit_position.py` (orchestrator), `module_gate.py` | Hooks: `record_stop.py`, `harvest_nudge.py`, `memory_trigger_nudge.py` |
| Optional separate plugins in the same marketplace: `nescio-security` (about 20 security and compliance skills) and `nescio-llm` (5 LLM-engineering skills) | Brain commands: `/harvest-memory`, `/assess-repo` |
| | Brain skills: `adopt-config`, `create-adr`, `publish-adrs`, `repo-hygiene` |
| | Brain scripts: harvest, promote, mark/unmark, readiness, ADR, hygiene, wiki, roadmap-drift, sync |
| | A slimmer `install.py`: CLAUDE.md consent, `permissions`, hooks, the `memory/` link, plus enabling the crew plugin |

The test for each item is whether it reads or writes the user's accumulated
state. If it does, it belongs to the brain. If it works on the project in
front of it, it belongs to the crew.

### 7.2 The contract between the two parts

The split only works if every place one part depends on the other is written
down. There are five today.

1. **Where memory lives: `~/.claude/memory/` (read-mostly, may be absent).**
   This is already the convention. `explore`, `reviewer` and `orchestrator`
   use the absolute path, and `reviewer` already handles the case where no
   memory exists. The brain's installer keeps creating the link. The crew must
   treat the path as optional. In plugin-only use there is no brain, and every
   step that reads memory must become "if present". The one place the crew
   **writes** to memory is the orchestrator's ADR step
   (`~/.claude/memory/repo/<repo>/adr/`). That step needs a fallback
   (`.sisyphus/adr/`) when there is no brain.
   - **Pre-existing bug this exposes:** 29 skills say "read … notes under
     `memory/`" with a **relative** path. That resolves against the project
     being worked on, which has no `memory/`. Agents were fixed to use absolute
     paths, but these skills were not. This needs fixing whether or not the
     split happens.
2. **The entry agent.** The plugin's `settings.json` sets
   `{"agent": "orchestrator"}`, which is enough for plugin-only users. The
   brain's installer sets the user-level `"agent": "nescio:orchestrator"`. User
   settings take precedence (tested), so the brain still decides.
3. **Enabling the crew.** The brain's `settings.json` gains
   `extraKnownMarketplaces.nescio` and `enabledPlugins["nescio@nescio"]`, which
   `install.py` already merges (the `plugins` part). This is how a fork
   declares which crew it uses.
4. **The brief.** CLAUDE.md is the brain's main way to steer the crew, and it
   reaches every agent **except** those with `omitClaudeMd: true` (`explore`,
   `librarian`, `doc-researcher`). That exception is intended and stays. Crew
   charters must not depend on anything that is only stated in CLAUDE.md.
5. **Version compatibility.** Plugin `dependencies` can't refer to a fork.
   Instead, the memory layout gets a version marker (`memory/.layout-version`),
   and each crew release states which layouts it supports. The brain's
   `install.py --check` compares the marker with the installed plugin version
   and warns on a mismatch. Do this only if the layout actually changes; today
   it is stable.

### 7.3 How a fork customises a crew it can't edit

Today a fork edits `agents/*.md` directly. With a plugin, the crew is a
read-only cache, so customisation needs other routes. In order of preference:

1. **CLAUDE.md and memory.** These already apply to almost every agent, and
   they cover most real customisation: conventions, tone, project rules.
2. **Overlays read by the charters.** Each charter gains one line: "if
   `~/.claude/memory/crew/<agent>.md` exists, read it and follow it where it
   doesn't conflict with this charter." This is cheap, uses prompt text only,
   and does nothing when there is no brain.
3. **Brain-local agents.** A fork can still keep its own `agents/` folder
   linked into `~/.claude/agents/` for agents that aren't part of the crew.
   They get bare names. If one has the same name as a crew agent, nothing
   breaks (the crew's is `nescio:`-prefixed), but the duplicate descriptions
   compete for routing. Document that forks shouldn't duplicate crew agents.
4. **Forking the plugin.** A last resort. The fork changes its marketplace
   entry to point at its own copy of the crew.

### 7.4 Themes

The philosopher theme renames agents. In a plugin the names are fixed when
it's built, so a theme becomes **a separate build of the plugin**:
`nescio` with the default names, and `nescio-philosophers` with the themed
ones. Both come from the same source through `apply_theme.py` at release time
and are listed in the same marketplace. Agent names then become things like
`nescio-philosophers:archimedes`, which is long but unambiguous. If that isn't
worth it, drop themes from the plugin and keep them only for crews installed
from source. Either way, `sync_from_upstream.py` would no longer copy crew
files, so the theme handling it contains today (the materialise-then-sync
design) would only be needed if themes stay.

### 7.5 Repository shape

- **Monorepo (recommended first):** the crew moves to `crew/`, which contains
  `.claude-plugin/plugin.json`, `agents/`, `skills/`, `scripts/` and `evals/`.
  A root `.claude-plugin/marketplace.json` lists `"source": "./crew"`, plus the
  optional skill packs. The brain stays at the root. Forks inherit `crew/` and
  can ignore it, because their settings install the plugin from the upstream
  marketplace. This is one repo, one PR flow and one CI. Because `crew/` is
  only ever loaded as a plugin, its source can use `nescio:` names directly,
  **so the render step from option D is not needed**.
- **Two repos (later, if ever):** a crew repo and a brain template. This gives
  cleaner ownership, but changes that touch both need two PRs. Only worth it if
  there are separate maintainers.

### 7.6 Maintainer development loop

Develop the crew with `claude --plugin-dir crew/`, or add the checkout as a
local marketplace. Local marketplaces pick up edits on `/reload-plugins` or at
the next session start, without bumping `version`. To dogfood, a private brain
can enable the crew from the local checkout and switch to the published
marketplace for stable use. The loop is one step slower than editing a
symlinked file, and that is the main day-to-day cost.

### 7.7 Cost of the split

| Work | Size |
|---|---|
| Move the crew into `crew/`, add `plugin.json` and `marketplace.json` | Small, mechanical |
| Change the 12 dispatch lines and agent/skill names in prose to `nescio:`; change 10 `~/.claude/scripts/` paths to `${CLAUDE_PLUGIN_ROOT}/scripts/` | Small, mechanical |
| Fix the 29 relative `memory/` paths (needed anyway) and make every memory read optional, plus the ADR fallback | Medium; charter prose with judgment calls |
| `tests/test_agent_definitions.py` (140K, assumes `ROOT/agents` and bare dispatch names) pointed at `crew/agents`, with the prefix stripped before comparing | Medium |
| `install.py`: stop linking `agents/`, `skills/` and `commands/`; enable the plugin; **migrate existing installs** by removing the old crew symlinks, because the bare and `nescio:` crews must never both be loaded | Medium; this is where an install can break |
| `sync_from_upstream.py`: shrink `FRAMEWORK_PATHS` to brain paths. Existing forks need a one-time migration, and their local agent edits have to move to overlays | Medium; one-time pain for every existing fork, including the maintainer's private one |
| Themes as a second build of the plugin, or drop them | Small to medium |
| `evals/` for the crew (§5) | Medium; can be done independently |

### 7.8 Verdict on the split

**Worth doing, as a sequence of steps, each of which leaves the repo working.**
For a project meant to be used by other people, the split gives each of them
the right install:

- **Crew only:** two commands.
- **Crew plus brain:** fork the template and run `install.py`, which enables
  the plugin.

It also makes upstream sync smaller and safer, because forks no longer get
crew files overwritten. The costs fall mostly on existing forks and on the
maintainer's edit loop, and both are one-time or small.

Suggested order:

1. Fix the 29 relative `memory/` paths and make memory reads optional. This
   is correct with or without the split.
2. Option D: build the plugin and add evals, so behaviour is measured before
   anything moves.
3. Move the crew into `crew/` with `nescio:` names in its source, and remove
   the render step.
4. Slim `install.py` and add the migration for existing installs.
5. Shrink `sync_from_upstream.py` and write the migration guide for forks.
6. Decide on themes.
7. Optional: split out the `nescio-security` and `nescio-llm` skill packs.

Not checked here: whether plugin skills and agents can read `~/.claude/memory/`
when Claude Code runs under a sandbox profile, whether `/reload-plugins` picks
up agent edits mid-session, and how `claude plugin eval` handles a plugin whose
charters read paths outside the plugin. The eval sandbox has a temporary home,
so evals will always see the "no brain" case. That is the right default to
test, but it means the brain-present path needs its own fixture through
`context.add_dirs`.
