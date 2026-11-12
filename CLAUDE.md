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

## Architecture

This section is optional. This repo declares no shape — the crew follows
whatever structure is already in the tree. That is the default, and deleting
this section changes nothing.

To declare one, replace this text with the shape your project uses and, if you
want it, a tripwire override:

- **Recognised shapes** — layered service, pipeline, plugin/registry, library.
  The `modular-design` skill defines each one; `layered-api-design` covers the
  layered case in full, and applies *only* when a project declares it here.
- **Tripwire** — a line such as `Module tripwire: <N> lines.` overrides the
  400-line default used by `scripts/module_scan.py`. `Test tripwire: <N> lines.`
  overrides the 800-line bar for test files, and `Module growth: <N> lines.` /
  `Module growth: <P>%.` override how much net growth (default
  min(150 lines, 25%)) an already-over-tripwire file needs before the CI gate
  asks for a verdict.

Nothing in the crew infers an architecture. If this section declares nothing, the
crew imposes nothing.

## Git / PRs

- Branch for changes; don't commit straight to the default branch.
- Use conventional commit messages (`feat` / `fix` / `chore` / `docs` / `refactor`).
- Keep PR descriptions matter-of-fact: scope, what changed, how to test.
- Never write a bare `#N` in a commit message or PR body unless you mean to
  close that issue — GitHub's closing keywords bind to whatever number follows
  them, and alert numbers, line numbers and versions all parse as issue
  references. Write `alert 2` or `line 2`.
- A `Refs #N` footer is **not** a safe non-closing form in this repo:
  release-please rewrites it into a closing reference when it generates the
  changelog, the release PR inherits the keyword, and merging fires it. It has
  auto-closed two issues this way. Reference an issue in prose (`issue 42`) or
  by full URL until that is fixed — see issue 242.

## Secrets

- Never commit credentials, tokens, or internal hostnames. Machine-local or
  private values go in `CLAUDE.local.md` (gitignored) or your OS keychain —
  never in tracked files.
- **Never name a private repository in a tracked file** — not your installed
  brain, not a client project. A bare directory name is itself the identifying
  string, and the `scrub_check.py` baseline cannot recognise one: it WARNs on an
  absolute home path but has no way to know a plain word names something
  private. Write "the brain" in prose, `<brain>` in a path, and cite its issues
  as `brain#N`.
- Copy `scrub-terms.local.example` to `scrub-terms.local`, fill in your own
  identifiers, and run `python scripts/scrub_check.py` before publishing. That
  file is gitignored, so it does not exist in CI and each checkout — every
  worktree included — needs its own copy, or `--terms <dir>` pointing at one.

---

Customize freely. `memory/` holds durable, on-demand knowledge; `agents/` is the
crew; `skills/` are on-demand capabilities.
