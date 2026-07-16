# Contributing to Nescio

Thanks for your interest. Nescio is a configuration framework for Claude Code —
mostly Markdown (agents, skills, memory) plus small Python glue.

## Ground rules

- **Portable and self-contained.** No hard dependency on a specific plugin,
  employer, or machine. The crew must work on a fresh clone with no plugins.
- **Never commit private or machine-specific data.** Copy
  `scrub-terms.local.example` → `scrub-terms.local` (gitignored), add your own
  identifiers, and run `python scripts/scrub_check.py` before pushing. CI runs the
  secret/path baseline on every push.
- **Match the existing style.** Functional agent names, concise charters,
  on-demand memory and skills, no prompt-stuffing.

## Adding an agent

Create `agents/<name>.md` with frontmatter (`name`, `description`, `model`, and
`disallowedTools` or `tools`) and a prose charter. Keep the name functional and
the mission single-purpose.

## Adding a skill

Create `skills/<name>/SKILL.md` with `name` / `description` frontmatter and the
capability's instructions. It's discovered by name and loaded on demand.

## Changing behavior

Agents are prompts, so verify a change by **exercising it**, not just reading it —
the `agent-evaluation`, `prompt-testing-plan`, and `prompt-evaluation-harness`
skills help. See `docs/specs/` for worked example design specs (the brainstorm →
spec format).

## Commits & PRs

- Conventional commits: `feat` / `fix` / `chore` / `docs` / `refactor`.
- Keep PRs focused; describe the scope and how to verify.
- Branch for changes; don't commit straight to the default branch.

## License

By contributing, you agree that your contributions are licensed under the
project's [MIT License](LICENSE).
