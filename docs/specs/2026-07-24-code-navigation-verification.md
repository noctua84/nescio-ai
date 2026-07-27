# Code-Navigation Doctrine — Verification Notes

Status: verification record for the `code-navigation` feature branch
`claude/serena-nescio-extension-48c43f` (spec: `docs/specs/2026-07-24-code-navigation-doctrine-design.md`,
plan: `docs/plans/2026-07-24-code-navigation-doctrine.md`).

Behavioral results are observed, not CI-asserted — prompts have no `pytest`
surface. This file is the honest record.

## Deterministic (whole-branch, base `04b8ea4`..`a3469e6`)

All passed:

- `serena.mcp.example.json` is valid JSON; args carry `--mode no-memories` and
  `--project-from-cwd`.
- `skills/code-navigation/SKILL.md` has `name: code-navigation`,
  `user-invocable: true`, and all four load-bearing sections (`## The rule`,
  `## Don't rationalize your way back to grep`, `## Backends`, `## Honest fallback`).
- Both `agents/explore.md` and `agents/reviewer.md` reference `skills/code-navigation`.
- Cross-references resolve: the skill points to the README heading "Optional:
  Serena semantic backend", and the README links `serena.mcp.example.json`.
- `settings.json` is untouched — Serena is not declared as a tracked runtime
  dependency (stays optional, per the design's no-hard-dep constraint).

## Behavioral conformance probe

A subagent was given `skills/code-navigation/SKILL.md` as its operating doctrine,
pointed at this repo (Python, `LSP` tool available), and asked two questions —
one semantic, one textual — with an honest-trajectory requirement.

| Golden scenario | Result | Evidence |
|---|---|---|
| 1. "Where is X defined / who calls X" → semantic first | **PASS** | Attempted `LSP workspaceSymbol` / references *before* any grep, citing the decision table. |
| 2. String / log-message search → `grep` | **PASS** | Went straight to `grep` for the "No typecheck config found" literal; no LSP attempt, cited the table. |
| 3. No language server → fall back to `grep` **and say so** | **PASS** | LSP errored (`pyright-langserver` not on `PATH`); agent explicitly reported the result was text-based, per the honest-fallback rule. |
| 4. With Serena connected, symbol-level edit → `rename_symbol` / `replace_symbol_body` | **DEFERRED** | Requires a live Serena connection; run post-install. |
| 5. Serena absent → doctrine still works on native `LSP` | **PASS (implied)** | The probe ran with no Serena connection; the doctrine drove correct behavior on the native path. |

## Environmental finding (not a defect in this branch)

`pyright-langserver` was not on `PATH` in the verification environment, so the
native `LSP` tool errored even though `pyright-lsp` is enabled in `settings.json`.
Enabling the plugin does not install the language-server binary. The doctrine's
honest-fallback section handled this correctly. Candidate follow-up (out of this
branch's scope): a README note that the native-LSP baseline requires the language
server binary on `PATH`, not just the plugin enabled — or that Serena (which
bundles servers via `solidlsp`) sidesteps this.

## Limitation, stated openly

The `explore`/`reviewer` agents active in the verification session were the
installed (symlinked, pre-change) versions, not this worktree's edited files. The
probe therefore tested the **doctrine's behavioral pull** (the thing built), not
the installed-agent wiring. Full installed-agent verification of all five
scenarios — including scenario 4 with a live Serena connection — should be run
after this branch is merged and `install.py` re-symlinks the edited agents.
