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
./install.sh          # POSIX (macOS / Linux)
# …or, any OS incl. Windows:
python install.py
```

The installer symlinks this repo's config — `agents/`, `skills/`, `commands/`,
and `memory/` — into `~/.claude`, and creates `CLAUDE.local.md` /
`settings.local.json` from the templates if missing. Edits here then take effect
everywhere. It **refuses to overwrite an existing real file** at a target — back
it up (or use `install.py`'s adoption flow) and re-run; both installers are
idempotent. `settings.json` sets `orchestrator` as the default agent, so you talk
to the crew by default.

On Windows, creating symlinks needs **Developer Mode** (Settings → Privacy &
security → For developers) or an elevated terminal; otherwise `install.py` reports
what it couldn't link and continues.

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
