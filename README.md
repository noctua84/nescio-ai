# NescioAI

[![Python 3.13+](https://img.shields.io/badge/python-3.13%2B-blue.svg)](pyproject.toml)
![Platform: Windows | macOS | Linux](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![tests](https://github.com/noctua84/nescio-ai/actions/workflows/tests.yml/badge.svg)](https://github.com/noctua84/nescio-ai/actions/workflows/tests.yml)

> *"I know that I do not know."*
>
> An agent crew for Claude Code that says **"I don't know"** — and argues with
> itself before it argues with you.

NescioAI (**Nescio** for short — Latin *"I do not know,"* the Socratic starting
point of real knowledge) is a portable, version-controlled configuration for
[Claude Code](https://claude.com/claude-code): a crew of specialized agents, a
memory that grows over time, and a learning loop. Built for software development
with a security edge.

*Status: 1.0 — the name and layout are settled; actively developed and in daily use.*

## What makes it different

Most agent setups optimize for always producing an answer. Nescio does two things
they don't:

- **Principled refusal.** *"I don't know / no competent path"* is a first-class,
  respected output. Agents refuse to fabricate a confident guess when they lack
  the basis, and the orchestrator won't relay a sub-answer it trusts less than its
  own read — no telephone-game hallucinations.
- **A built-in devil's advocate.** A dedicated `critic` agent red-teams a plan
  *before* it's built — blind spots, shaky premises, overlooked alternatives, and
  PII/legal exposure — in one bounded pass, and is free to conclude "the plan
  holds."

Together: an assistant with the humility to stop and the discipline to challenge
itself.

## The four C's

Nescio is organized around four dimensions of a useful AI operator:

- **Context** — what it knows about you, your repos, and your conventions: the
  `memory/` tree, grown and curated over time.
- **Connections** — the live data and tools it can reach (via Claude Code's MCP
  and tools) without being spoon-fed.
- **Capabilities** — what it can produce: multi-step work from a short phrase,
  run through the crew's lifecycle (triage → … → deliver).
- **Cadence** — when it acts on its own over time: the learning loop that turns
  sessions into durable memory. *(Unattended, autonomous action is on the
  roadmap, gated behind a readiness/autonomy dial.)*

## Quickstart

Requires [Claude Code](https://claude.com/claude-code) and Python 3.13+.

```bash
git clone <this-repo> ~/dev/nescio
cd ~/dev/nescio
python install.py               # any OS incl. Windows (prompts for settings + CLAUDE.md)
```

`install.py` symlinks the config Claude Code reads at user scope — `agents/`,
`skills/`, `memory/`, `commands/`, `hooks/` — into `~/.claude`, then asks two
consent questions: how to integrate **`settings.json`** and **`CLAUDE.md`**.

**`settings.json`** — a keyword (`full | minimal | skip`) **or a comma-list of parts** (`agent,permissions,plugins`):

- **full** — the whole `settings.json` (default agent + permissions + plugins) + hooks
- **minimal** — only `agent: orchestrator` (+ the learning-loop hooks)
- **skip** — change nothing
- **parts** — adopt a subset, e.g. `--settings agent,plugins` keeps your own permissions while adding the entrypoint and plugins (deep-merged; your other keys and allow-list are preserved)

It's written as a **real, merged file** in `~/.claude` (not a symlink): the chosen
keys win, your existing settings are preserved, and the hooks — which Claude Code
honors **only** in `~/.claude/settings.json` — are wired with absolute paths.

**`CLAUDE.md`** — `import | replace | skip`:

- **import** — your `~/.claude/CLAUDE.md` `@`-imports the framework's, keeping any
  instructions you already have (the recommended, non-destructive default)
- **replace** — symlink the framework's `CLAUDE.md` as your global (an existing one
  is backed up first)
- **skip** — leave `~/.claude/CLAUDE.md` untouched

`CLAUDE.md` is composed via Claude Code's `@path` import because only one
user-scope `CLAUDE.md` is read: **import** makes `~/.claude/CLAUDE.md` a real file
whose first line is `@<repo>/CLAUDE.md` (resolved live) with your own lines below.

(`~/.claude/settings.local.json` and `~/.claude/CLAUDE.local.md` are *not* read by
Claude Code, so the installer doesn't create them, and removes any left by older
versions.) Pass `--settings full|minimal|skip|<parts>` and `--claude-md import|replace|skip`
for an unattended install; re-runs are idempotent.

`install.py` is the single installer (pure standard-library Python, no
dependencies). On Windows, symlink creation needs **Developer Mode** (Settings >
Privacy & security > For developers) or an elevated terminal — the script says so
and changes nothing if it can't.

## The crew

| Agent | Role |
|-------|------|
| `orchestrator` | Coordinates the lifecycle (triage → discover → analyze → plan → execute → verify → deliver); delegates, never writes production code itself. |
| `scout` | Pre-plan risk/intent triage — surfaces assumptions and likely failure points. |
| `planner` | Interviews for requirements and writes the work plan. |
| `validator` | Checks a plan is executable before work starts. |
| `builder` | Implements one scoped task from a plan — the complex/unclassified tier. Verifies before reporting. |
| `builder-standard` | Same contract as `builder`, for tasks the plan classifies `standard`; runs on Sonnet. |
| `builder-simple` | Same contract as `builder`, for mechanical tasks the plan classifies `simple`; runs on Haiku. |
| `test-writer` | Writes and extends tests against the intended interface; may not touch implementation files. |
| `qa-guard` | Discovers and runs the project's CI checks, fixing mechanical failures until they pass. |
| `advisor` | Read-only architecture/design advice for hard tradeoffs. |
| `reviewer` | QA audit of implemented code — bugs, regressions, security. |
| `critic` | Devil's advocate — challenges the approach before it's built. |
| `librarian` | External docs / OSS research with cited sources. |
| `explore` | Fast codebase search. |
| `vision` | Reads media (PDFs, images, diagrams, screenshots) and returns the extracted data; read-only. |
| `doc-researcher` | Maps the existing docs — coverage, gaps, update targets; writes nothing. |
| `doc-writer` | Writes docs from `doc-researcher`'s findings; may not touch implementation files. |

Six agents write files: `builder` and its two tiers plus `qa-guard` write
production code; `test-writer` and `doc-writer` write only within their declared
file boundaries. The rest are read-only.

## Skills

On-demand capability modules under `skills/`, loaded by name when relevant. Nescio
ships a working set spanning development and security/compliance — e.g.
`secure-code-review`, `threat-model`, `vuln-assessment`,
`api-security-assessment`, the compliance suite (`soc2-report`, `iso27001-isms`,
`hipaa-assessment`, `pci-dss-assessment`, `compliance-gap-analysis`), plus
dev-workflow skills (`create-adr`, `repo-hygiene`, `handle-pr-comments`,
`gh-milestones-projects`, `dependency-pr-ci-fix`) and prompt/agent-evaluation skills. Add your own by
dropping a `SKILL.md` into a new folder.

## Memory & the learning loop

**Memory** (`memory/`) is durable, on-demand knowledge — per-repo notes,
per-project notes, standing feedback, and a glossary — loaded only when relevant,
not into the always-on prompt. It ships here as *structure + templates + one
`EXAMPLE` note*; you fill it with your own learnings, which sync across your
machines through your own clone.

**The learning loop** captures session activity (a Stop hook writes a local
trail) and, via `/harvest-memory`, curates durable learnings into `memory/` with
source-precedence, contradiction resolution, and a de-duplication ledger. A
per-repo `readiness.md` summarises how recent harvested sessions have gone —
refreshed during `/harvest-memory`, and the input for a planned autonomy dial.

## Optional: the philosopher theme

The agent names above are functional on purpose. If you'd like personality, an
optional theme renames the thinker/advisor agents after Graeco-Roman philosophers
(`planner`→`plato`, `advisor`→`aristotle`, `reviewer`→`pyrrho`, `critic`→
`socrates`, `builder`→`archimedes`) — tracing the Socrates → Plato → Aristotle
lineage, plus Pyrrho the skeptic, plus Archimedes the engineer and craftsman
(not part of that lineage, which is fitting for the agent that builds rather
than reasons). The two builder cost tiers follow `builder`, so seven files are
renamed in all: `builder-simple.md`→`archimedes-simple.md` and
`builder-standard.md`→`archimedes-standard.md`.

The remaining agents — `orchestrator`, `scout`, `validator`, `librarian`,
`explore`, `vision`, `test-writer`, `qa-guard`, `doc-researcher`, `doc-writer` —
keep their functional names under both themes.

Apply it with `python scripts/apply_theme.py philosophers` (and
`python scripts/apply_theme.py functional` to revert). It renames the agent files,
frontmatter, and all cross-references; it's idempotent and reversible.
`--dry-run` prints what it would do without touching anything.

## Prerequisites

- **Claude Code** and **Python 3.13+**.
- Recommended plugins (declared in `settings.json`, installed per machine):
  `superpowers` (skills used across workflows) and `typescript-lsp` /
  `pyright-lsp` (semantic code search for `explore`). No agent hard-depends on a
  plugin — the crew works without them.

### Optional: Serena semantic backend

The `code-navigation` doctrine works out of the box on Claude Code's native `LSP`
tool (TypeScript + Python, via the enabled plugins) — provided the language-server
binary is on your `PATH` (e.g. `pyright-langserver` for Python); enabling the
plugin does not install the server itself. If it's missing, the doctrine falls
back to text search and says so. For 40+ languages and symbol-level *editing* —
and to sidestep the `PATH` requirement, since it bundles its own servers via
`solidlsp` — connect [Serena](https://github.com/oraios/serena) as an optional MCP
server; it stays fully optional, and no agent depends on it.

Install once (`uv` required):

```bash
uv tool install -p 3.13 serena-agent
```

Register it at user scope, **memory-disabled** so it never competes with Nescio's
own `memory/` tree:

```bash
claude mcp add --scope user serena -- \
  serena start-mcp-server --context claude-code --mode no-memories --project-from-cwd
```

The equivalent `mcpServers` block is in [`serena.mcp.example.json`](serena.mcp.example.json).
This exposes only Serena's symbol navigation and symbol-safe editing tools; Claude
Code's own Read/Edit/Grep/shell continue to handle everything else. Serena's
JetBrains backend (paid, non-MIT) is not used.

## Keeping private data out

If you fork Nescio and fill `memory/` with real, work-specific knowledge, keep it
out of anything you publish: copy `scrub-terms.local.example` to
`scrub-terms.local` (gitignored), add your employer / repo / personal
identifiers, and run `python scripts/scrub_check.py` before pushing. The bundled
`scrub` CI workflow runs a secret/path baseline on every push.

## Keeping your instance in sync

Nescio is the framework's **source of truth for everything except your memory
records**. Your private instance keeps its own history and its own `memory/`, and
pulls *framework* updates from here by overlay — not by a git merge.

Why overlay and not `git pull`: your private instance and this repo have
**unrelated git histories** (a derived instance starts from its own `initial`
commit, not a fork of this one), so a merge isn't meaningful. Instead, a script
copies just the framework files across.

- **Update the framework.** Point the sync script at a checkout of this repo; it
  copies the framework paths (agents, skills, commands, hooks, scripts,
  `github-action/`, installer, examples) into your instance and mirrors any
  removals — **without ever touching `memory/`, `docs/`, your notes, or your
  instance config**:

  ```bash
  python scripts/sync_from_upstream.py --upstream /path/to/nescio-ai            # dry run
  python scripts/sync_from_upstream.py --upstream /path/to/nescio-ai --diff     # dry run + per-file content diff
  python scripts/sync_from_upstream.py --upstream /path/to/nescio-ai --apply    # perform
  ```

  Review the diff, then commit it in your instance like any other change.

- **Your memory stays private.** It lives only in your instance's own remote —
  the sync never reads or writes it, and you never push framework changes back to
  this public repo except deliberately, on a scrubbed branch (see *Keeping private
  data out* above).

- **The philosopher theme is rendered, not committed.** After a sync, if you use
  the [philosopher theme](#optional-the-philosopher-theme), re-apply it with
  `python scripts/apply_theme.py philosophers` — the framework ships the functional
  names, and the theme is a local render step, so syncs never fight your renames.

## Guarding against orphaned commits

Implementer subagents occasionally commit while `HEAD` is detached: the commit
succeeds and prints a sha, but lands on *no branch* — so the controller's next
`git log <branch>` reports green for work that isn't there. The orchestrator
therefore verifies every reported commit itself rather than trusting the agent's
self-report:

```bash
python scripts/verify_commit_position.py <sha> <branch> --base origin/main
```

Exit 1 means the commit orphaned or `HEAD` is detached (with recovery
instructions); exit 2 means the check couldn't run; a stale base is a warning
only, never a failure.

A repo-local `pre-commit` hook that rejects detached-HEAD commits is a good
*complementary* guard, and you may want to adopt one **in your own project
repos** — [noctua84/holo-mind#5](https://github.com/noctua84/holo-mind/issues/5)
is a worked example. Nescio deliberately does **not** ship or enable it: the
installer only ever writes to `~/.claude`, never into your project repos, so
there is no delivery vehicle — and setting `core.hooksPath` globally would hijack
every repo on the machine and silently disable any repo's own `.git/hooks`, which
the framework's non-destructive charter rules out.

## Checking ROADMAP.md against GitHub

`ROADMAP.md` duplicates state GitHub owns — which issues are open, and which
milestone each belongs to — and it has drifted before. `check_roadmap_drift.py`
reconciles the two. It **never writes**: the bullets there are hand-written
editorial prose, deliberately shorter and clearer than the issue titles they
track, so the script reports and you decide.

```bash
# structure only — no network, no `gh`, no token
PYTHONPATH=scripts python scripts/check_roadmap_drift.py --offline

# the same, plus the live reconciliation against the issue tracker
PYTHONPATH=scripts python scripts/check_roadmap_drift.py
```

`--offline` runs the four checks that need nothing but the two files in this
repo: reference uniqueness, link well-formedness, the milestone tag vocabulary,
and that this README's roadmap summary has not acquired issue numbers of its
own. It is what to run without `gh`, and it never exits 2. The plain invocation
adds five reconciliation checks against GitHub.

Exit 0 is clean; 1 means the file and GitHub disagree; 2 means the check could
not run at all — `gh` missing, unauthenticated, or the API unreachable — which
is deliberately not the same answer as "clean", and the reason is named on
stderr rather than left as a traceback.

**Advisories print without failing.** An issue referenced in `ROADMAP.md` that
does not carry the `roadmap` label is reported with the exact `gh issue edit`
command that fixes it, and the run still exits 0: applying a label is GitHub
metadata no commit in this repo can carry, so failing there would block someone
who has no way to clear it. What earns a line in the first place is in
[CONTRIBUTING.md](CONTRIBUTING.md#what-goes-on-the-roadmap).

## Roadmap

See [ROADMAP.md](ROADMAP.md) for where Nescio is headed. Near-term work is the
learning loop: making it trustworthy end to end, turning the trail into a real
readiness signal, then lifting learnings across repos. **Earned per-repo autonomy
is parked** — deliberately held until the loop has run long enough to produce
evidence worth arguing with, not abandoned. An OpenAI Codex adapter and the
installer's config-reconciliation arc are on the roadmap but unscheduled.

It's directional, not dated; the [open issues](https://github.com/noctua84/nescio-ai/issues)
and [milestones](https://github.com/noctua84/nescio-ai/milestones) are the source
of truth.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE)
