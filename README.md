# NescioAI

> *"I know that I do not know."*
>
> An agent crew for Claude Code that says **"I don't know"** — and argues with
> itself before it argues with you.

NescioAI (**Nescio** for short — Latin *"I do not know,"* the Socratic starting
point of real knowledge) is a portable, version-controlled configuration for
[Claude Code](https://claude.com/claude-code): a crew of specialized agents, a
memory that grows over time, and a learning loop. Built for software development
with a security edge.

*Status: early and evolving — the name is provisional and the layout may shift.*

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

Requires [Claude Code](https://claude.com/claude-code) and Python 3.

```bash
git clone <this-repo> ~/dev/nescio
cd ~/dev/nescio
python install.py               # any OS incl. Windows (prompts for settings + CLAUDE.md)
```

`install.py` symlinks the config Claude Code reads at user scope — `agents/`,
`skills/`, `memory/`, `commands/`, `hooks/` — into `~/.claude`, then asks two
consent questions: how to integrate **`settings.json`** and **`CLAUDE.md`**.

**`settings.json`** — `full | minimal | skip`:

- **full** — the whole `settings.json` (default agent + permissions + plugins) + hooks
- **minimal** — only `agent: orchestrator` (+ the learning-loop hooks)
- **skip** — change nothing

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
versions.) Pass `--settings full|minimal|skip` and `--claude-md import|replace|skip`
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
| `advisor` | Read-only architecture/design advice for hard tradeoffs. |
| `reviewer` | QA audit of implemented code — bugs, regressions, security. |
| `critic` | Devil's advocate — challenges the approach before it's built. |
| `librarian` | External docs / OSS research with cited sources. |
| `explore` | Fast codebase search. |
| `vision` | Reads media (PDFs, images, diagrams, screenshots) and returns the extracted data; read-only. |

## Skills

On-demand capability modules under `skills/`, loaded by name when relevant. Nescio
ships a working set spanning development and security/compliance — e.g.
`secure-code-review`, `threat-model`, `vuln-assessment`,
`api-security-assessment`, the compliance suite (`soc2-report`, `iso27001-isms`,
`hipaa-assessment`, `pci-dss-assessment`, `compliance-gap-analysis`), plus
dev-workflow skills (`create-adr`, `repo-hygiene`, `handle-pr-comments`,
`gh-milestones-projects`) and prompt/agent-evaluation skills. Add your own by
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
per-repo `readiness.md` tracks how sessions have gone — the input for a planned
autonomy dial.

## Optional: the philosopher theme

The agent names above are functional on purpose. If you'd like personality, an
optional theme renames the thinker/advisor agents after Graeco-Roman philosophers
(`planner`→`plato`, `advisor`→`aristotle`, `reviewer`→`pyrrho`, `critic`→
`socrates`) — tracing the Socrates → Plato → Aristotle lineage, plus Pyrrho the
skeptic.

Apply it with `python scripts/apply_theme.py philosophers` (and
`python scripts/apply_theme.py functional` to revert). It renames the agent files,
frontmatter, and all cross-references; it's idempotent and reversible.

## Prerequisites

- **Claude Code** and **Python 3**.
- Recommended plugins (declared in `settings.json`, installed per machine):
  `superpowers` (skills used across workflows) and `typescript-lsp` /
  `pyright-lsp` (semantic code search for `explore`). No agent hard-depends on a
  plugin — the crew works without them.

## Keeping private data out

If you fork Nescio and fill `memory/` with real, work-specific knowledge, keep it
out of anything you publish: copy `scrub-terms.local.example` to
`scrub-terms.local` (gitignored), add your employer / repo / personal
identifiers, and run `python scripts/scrub_check.py` before pushing. The bundled
`scrub` CI workflow runs a secret/path baseline on every push.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE)
