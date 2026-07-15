# Nescio

> *"I know that I do not know."*
>
> An agent crew for Claude Code that says **"I don't know"** — and argues with
> itself before it argues with you.

Nescio is a portable, version-controlled configuration for
[Claude Code](https://claude.com/claude-code): a crew of specialized agents, a
memory that grows over time, and a learning loop. Built for software development
with a security edge.

> **Status:** early / working name. This README is a stub — full docs land in a
> later phase.

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

## Memory & the learning loop

An on-demand `memory/` tree (per-repo, per-project, feedback, glossary) that ships
here as *structure and templates* — you fill it with your own learnings, which
sync across your machines via your own copy. A learning loop captures session
activity and promotes durable learnings into memory with source-precedence and
de-duplication.

## Optional: the philosopher theme

The agent names above are functional on purpose. If you'd like personality, an
optional theme renames the thinker/advisor agents after Graeco-Roman philosophers
(`planner`→`plato`, `advisor`→`aristotle`, `reviewer`→`pyrrho`, `critic`→
`socrates`).

## Install

_TODO (later phase): `git clone … && ./install.sh` — symlinks the crew, skills,
and memory into `~/.claude`._

## License

[MIT](LICENSE)
