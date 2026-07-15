# Project instructions

Your Nescio operating brief — the always-loaded instructions for the crew. Keep
it short; put deep or on-demand knowledge in `memory/`. Everything below is a
sensible default — **replace it with your own.**

## How I want you to work

- Challenge my assumptions; if you disagree, say so and explain why.
- Look up documentation before acting — don't guess at APIs.
- Lead with the answer, then the reasoning. No filler.
- Say when you're uncertain instead of fabricating. **"I don't know" is a valid,
  respected answer** — a wrong confident guess is worse than an honest gap.

## Engineering defaults

- Follow the existing patterns in the codebase over inventing new ones.
- Test-cover the changes you make.
- Prefer small, battle-tested approaches over clever ones.
- Fix root causes, not symptoms.

## Git / PRs

- Branch for changes; don't commit straight to the default branch.
- Use conventional commit messages (`feat` / `fix` / `chore` / `docs` / `refactor`).
- Keep PR descriptions matter-of-fact: scope, what changed, how to test.

## Secrets

- Never commit credentials, tokens, or internal hostnames. Machine-local or
  private values go in `CLAUDE.local.md` (gitignored) or your OS keychain —
  never in tracked files.

---

Customize freely. `memory/` holds durable, on-demand knowledge; `agents/` is the
crew; `skills/` are on-demand capabilities.
