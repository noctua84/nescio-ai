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

An agent is registered in three places, and two of them fail the build if you
skip them.

1. **Create `agents/<name>.md`** with frontmatter (`name`, `description`,
   `model`, and `disallowedTools` or `tools`) and a prose charter. Keep the name
   functional and the mission single-purpose.
2. **Register it in `scripts/_crew_common.py`.** Add it to `PAIRS` if the
   philosopher theme should rename it, or to `THEME_INVARIANT_ROSTER` if the
   name stays put. Then add it to whichever write-policy set applies:
   `CODE_WRITERS` for an agent that edits production code, `BOUNDED_WRITERS` for
   one whose charter limits it to tests or docs, `WRITE_BOUNDED` for one barred
   from `Edit` but holding `Write` for a single named purpose.
3. **Route it in `AGENT_GROUPS` in `docs_site/gen_catalog.py`.** That table is a
   routing table, not a roster: it is checked strictly in both directions, so an
   unrouted agent **fails the build** rather than falling into an "Other"
   bucket. Pick the lifecycle bucket it belongs in.
4. **Regenerate the catalog and commit its output:**

   ```
   python docs_site/gen_catalog.py
   ```

   `docs_site/docs/agents.md` is a generated artefact — do not hand-edit it. The
   required `tests` CI job runs `gen_catalog.py --check` and fails on drift.
5. **Run both suites.** There are two unittest roots; `discover -s tests` does
   **not** reach the second one:

   ```
   PYTHONPATH=scripts python -m unittest discover -s tests
   python -m unittest discover -s docs_site
   ```

The crew diagram (`brand/make_diagrams.py`, inlined on the docs homepage) is
**not** regenerated from `agents/`. It draws a fixed subset and is a known
manual follow-up, tracked separately — adding an agent does not update it.

## Adding a skill

Create `skills/<name>/SKILL.md` with `name` / `description` frontmatter and the
capability's instructions. It's discovered by name and loaded on demand.

## Changing behavior

Agents are prompts, so verify a change by **exercising it**, not just reading it —
the `agent-evaluation`, `prompt-testing-plan`, and `prompt-evaluation-harness`
skills help. See `docs/specs/` for worked example design specs (the brainstorm →
spec format).

## Running the tests

```
PYTHONPATH=scripts python -m unittest discover -s tests
```

That is the canonical command, and what CI runs. Python 3.13 is the floor
(`requires-python = ">=3.13"`).

If a local `pytest` wrapper reports `Path.read_text() got an unexpected keyword
argument 'newline'`, it is invoking an out-of-contract interpreter — `newline=`
is valid on `read_text` from 3.13 onward. That is a stale interpreter, not a real
failure, and it is **not** a reason to delete the `newline=""` arguments in
`scripts/apply_theme.py`: they are the fix that stops a rewritten charter coming
back as CRLF against a `.gitattributes` that pins `eol=lf`.

## What goes on the roadmap

`ROADMAP.md` lists **planned features** — capabilities the project intends to
have. It is not a mirror of the issue tracker. An issue gets a line when a
**maintainer** applies the `roadmap` label, which happens at triage, not at
filing. Contributors cannot apply it themselves, and nothing written in an issue
grants or forfeits it.

**Gets a line:** a new capability, skill, agent, or subsystem; a deliberate
change to how an existing capability is designed; an evaluative spike whose
outcome is a capability decision. Work in the *Parked* milestone still gets a
line — `deferred` means held, not abandoned, and the two labels coexist.
*Example: #29, an OpenAI Codex CLI adapter — a capability the project does not
have yet.*

**Does not get a line:** bugs and crashes; CI, release, and packaging plumbing;
documentation debt; housekeeping and audits. These are tracked as issues and
shipped normally — the roadmap is about direction, not about the backlog.
*Example: #71, a cp1252 crash in `promote_learnings.py` — a defect in something
that already ships.*

**To be roadmap-ready an issue needs:** a title that reads as a capability (not a
symptom); the problem or use case in one paragraph; the proposed shape; and what
you considered instead. If a maintainer cannot write a one-line roadmap bullet
from your issue, it is not ready for one.

When you open or close an issue that carries the `roadmap` label, update
`ROADMAP.md` in the same breath — the `roadmap` CI job will tell you if you
forgot.

## Commits & PRs

- Conventional commits: `feat` / `fix` / `chore` / `docs` / `refactor`.
- Keep PRs focused; describe the scope and how to verify.
- Branch for changes; don't commit straight to the default branch.

## License

By contributing, you agree that your contributions are licensed under the
project's [MIT License](LICENSE).
