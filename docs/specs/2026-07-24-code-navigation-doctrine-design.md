# `code-navigation` — semantic-first navigation doctrine + optional Serena backend

Status: draft — awaiting review

> Brainstormed from the question "would Serena be a good extension to Nescio, or
> parts of it?" The conclusion: borrow the *idea* (navigate code like an IDE, not
> like `grep`), write it in Nescio's own voice, and offer Serena as an optional
> engine for those who want it. Nescio owns the doctrine; the engine stays
> borrowed.

## Purpose

Give the crew IDE-like code navigation by default. Two parts:

1. **The doctrine (Nescio's own).** A new `skills/code-navigation/SKILL.md` plus
   thin hooks in `agents/explore.md` and `agents/reviewer.md` that make the crew
   reach for **semantic, symbol-level** operations first — *where is this defined,
   who references it, who implements it, what's the call hierarchy* — and fall
   back to text search only when the question is genuinely textual (strings,
   comments, logs, config). This is prompt/config, not machinery.

2. **The engine (borrowed, layered).** The doctrine runs on whatever semantic
   backend is present:
   - **Baseline, zero-setup:** Claude Code's native `LSP` tool, already fed by the
     `typescript-lsp` and `pyright-lsp` plugins Nescio enables in `settings.json`
     (TypeScript + Python).
   - **Optional upgrade:** [Serena](https://github.com/oraios/serena) as a
     documented, **memory-disabled** MCP connection — adds symbol-level *editing*
     and 40+ languages for those who want breadth or already run it.

No new runtime, no hard dependency, no second memory system.

## Why this design

- **The capability half-exists; the gap is discipline.** Claude Code's `LSP` tool
  already does `goToDefinition` / `findReferences` / `documentSymbol` /
  `workspaceSymbol` / `goToImplementation` / call-hierarchy for the languages whose
  servers are enabled (TS + Python today). What's missing — and what actually
  moves output quality — is that the model defaults to `grep`-and-read even when a
  symbol jump is faster and more precise. The cheapest lever is therefore *policy*,
  which is exactly what Nescio is made of. (Same "the idea is a policy, not
  machinery" reasoning as the `critic` spec.)

- **Borrowed engine, not rebuilt.** Reimplementing LSP-wrapping symbolic tools
  (especially the editing ones) would turn Nescio from a config layer into a
  software product with a runtime, LSP-subprocess management, and per-language
  toolchain handling — and would duplicate Serena (MIT, ~27k stars, ~weekly
  releases, wrapping `solidlsp`/`multilspy`). Rejected: it contradicts Nescio's
  own "battle-tested over clever" and "no agent hard-depends on a plugin."

- **Serena optional and memory-disabled — one memory, not two.** Serena ships its
  own `write_memory`/`read_memory`/onboarding surface. Left on, it would stand up a
  competing `.serena/memories/` store beside Nescio's `memory/` tree — two brains,
  guaranteed confusion. The launch config below removes that surface entirely, so
  Serena contributes *only* stateless code intelligence. Nescio keeps the brain;
  Serena is a hand.

- **Backend-agnostic doctrine.** The skill speaks in behaviors ("prefer semantic
  navigation," "edit at the symbol level") rather than tool names, so it holds
  whether the backend is the native `LSP` tool or Serena, and degrades honestly to
  `grep` when no language server exists for the file.

## Licensing (the gating question)

Serena is **MIT** (`Copyright (c) 2025 Oraios AI`); Nescio is **MIT**. Compatible.

- **Borrowing the idea** — semantic-first navigation, the anti-rationalization
  framing — carries **no obligation**. Copyright protects expression, not ideas,
  methods, or concepts. The doctrine is written from scratch in Nescio's voice.
- **We copy no Serena code or text.** The only Serena-derived artifact is a
  documented launch command (`serena start-mcp-server …`), which is not
  copyrightable expression. If any Serena file/prose is ever lifted verbatim
  later, MIT requires preserving its notice + attribution — not triggered here.
- **Out of bounds:** Serena's **JetBrains plugin backend is a separate paid,
  non-MIT product.** This design uses only the OSS LSP backend and never touches
  the JetBrains path.

## Component 1 — the doctrine skill (`skills/code-navigation/SKILL.md`)

`user-invocable: true`, structured like the other skills. Sections:

- **Purpose.** Navigate and edit code at the symbol level first; use text search
  only when the target *is* text.

- **The decision table** — the load-bearing content:

  | Question | Tool of first resort |
  |---|---|
  | Where is this symbol defined? | semantic: `goToDefinition` / `find_symbol` |
  | Who references / calls this? | semantic: `findReferences` / `find_referencing_symbols`, call-hierarchy |
  | Who implements this interface? | semantic: `goToImplementation` / `find_implementations` |
  | What symbols live in this file / project? | semantic: `documentSymbol` / `workspaceSymbol` / `get_symbols_overview` |
  | A string literal, comment, log line, config key, non-code text | text: `grep` |
  | A file by name / extension | `glob` |
  | When/why something changed | `git` (blame/log) |

- **Semantic-first method.** Get an overview → jump by symbol → follow
  references / implementations / call-hierarchy — rather than grep-then-read-then-
  guess. Generalizes the thin "Tool Strategy" already in `explore.md`.

- **Anti-rationalization list** (Nescio's voice; the borrowed *concept*, original
  text). Explicitly reject the excuses that pull the model back to `grep`:
  *"it's just one symbol," "grep is faster to type," "I already know roughly where
  it is," "the file is small."* Same shape as the `using-superpowers` red-flags
  table and Nescio's anti-fabrication ethos.

- **Backends.** Baseline = native `LSP` tool (needs a configured language server;
  TS + Python enabled by default). Optional = Serena MCP (adds symbol-level
  *editing* + 40+ languages). If **no** semantic backend serves the file's
  language, fall back to `grep`/`glob` **and say so** — navigation was text-based,
  not semantic. (Same honest-fallback discipline as `explore`'s "honest not-found.")

## Component 2 — agent hooks (thin)

Single source of truth is the skill; agents point to it.

- **`agents/explore.md`** — the "Tool Strategy" block (currently lines ~62–71,
  where "Semantic search … : LSP tools" is one line). Restate the default —
  *prefer semantic navigation for where/what/who-calls/who-implements; `grep` for
  strings/comments/logs; `glob` for filenames; `git` for history* — and reference
  `skills/code-navigation` for the method. Keep it thin.

- **`agents/reviewer.md`** — in "Review Methodology → Static Analysis" (which
  already says "Trace execution paths by reading the actual code, not by inferring
  from names"), add one line: use semantic navigation (references / implementations
  / call-hierarchy) to establish what "correct" looks like before judging, per
  `skills/code-navigation`.

- Other agents (`advisor`, `planner`) may adopt the hook later; deliberately out of
  scope now (YAGNI). Because the doctrine lives in the skill, each future opt-in is
  one line.

## Component 3 — the optional Serena connection

Shipped as a **documented example**, not an install-time prompt — mirroring
`stores.example.json`, and honoring "no agent hard-depends on a plugin." Deliver a
`serena.mcp.example.json` plus a README section.

**Prerequisite:** `uv tool install -p 3.13 serena-agent` (`uv` is Serena's only
hard prerequisite; supported Python is 3.11–3.14, and `-p 3.13` merely pins the
interpreter `uv` provisions).

**Config (verified against Serena source at HEAD 2026-07-22 — `src/serena/cli.py`
`start_mcp_server` click options, `contexts/claude-code.yml`, `modes/no-memories.yml`):**

```json
{
  "mcpServers": {
    "serena": {
      "command": "serena",
      "args": [
        "start-mcp-server",
        "--context", "claude-code",
        "--mode", "no-memories",
        "--project-from-cwd"
      ]
    }
  }
}
```

Equivalent one-liner (the form Serena's docs recommend):

```
claude mcp add --scope user serena -- \
  serena start-mcp-server --context claude-code --mode no-memories --project-from-cwd
```

**Flag rationale (each verified, not guessed):**

- `--context claude-code` — **mandatory.** Serena's default context is
  `desktop-app`; the `claude-code` context is what excludes the tools that
  duplicate Claude Code's own `Read`/`Edit`/`Grep`/shell and injects the
  "prefer symbolic tools" prompt. It also carries a live workaround
  (`structured_tool_output: false`) for a current Claude Code structured-output
  bug — a reason to defer to Serena's shipped context rather than hand-roll.
- `--mode no-memories` — removes Serena's memory tools **and** its onboarding tool
  (the `no-memories` mode already excludes `onboarding`, which depends on memory).
  This is the single flag that guarantees no competing memory store. `--mode` is
  repeatable and *overrides* config defaults; a redundant `--mode no-onboarding`
  can be added for defensiveness but is not required.
- `--project-from-cwd` — Serena's flag for CLI agents (Claude Code / Gemini /
  Codex); scopes to the current repo and, with the context's `single_project: true`,
  drops `activate_project` / `get_current_config`.

**What the agent gains (surviving tool set with this exact config):**

- Symbol navigation: `get_symbols_overview`, `find_symbol`,
  `find_referencing_symbols`, `find_implementations`, `find_declaration`
- Symbol diagnostics: `get_diagnostics_for_file`
- Symbol-safe editing (no first-class Claude Code equivalent): `replace_symbol_body`,
  `insert_after_symbol`, `insert_before_symbol`, `rename_symbol`, `safe_delete_symbol`
- Regex bulk-edit: `replace_content`, `replace_in_files`
- `initial_instructions`

Not present: any memory tool, `onboarding`, `activate_project`,
`get_current_config`, file/shell/search tools (Claude Code's own handle those), and
all JetBrains-only tools. A stateless code-intelligence layer, which is the point.

## Component 4 — README

One sentence near the existing `typescript-lsp` / `pyright-lsp` note (README.md
~149–150): position Serena as an optional semantic backend that broadens
navigation to 40+ languages and adds symbol-level editing, pointing to the example
config. Keep the "no agent hard-depends on a plugin" framing intact.

## Testing

The doctrine is prompts + one JSON example + docs. As with the `critic` spec,
prompts have no `pytest` surface, and Nescio's test suite targets *scripts*, not
markdown. So:

- **Mechanical (cheap, do it):** assert `serena.mcp.example.json` is valid JSON and
  the arg vector is well-formed. This is the only artifact with a deterministic
  check; if it's not worth a standalone test, it's covered by the reviewer reading
  it.
- **Behavioral (the real verification):** use Nescio's own evaluation skills rather
  than a hand-rolled scheme — `prompt-testing-plan` for golden cases,
  `agent-evaluation` for trajectory/tool-use scoring. Golden scenarios:
  1. *"Where is X defined / who calls X"* → `explore` uses semantic ops, not
     grep-then-read.
  2. *Find a log message / string literal* → correctly uses `grep` (the doctrine
     doesn't over-apply semantics).
  3. *File in a language with no configured server* → falls back to `grep`/`glob`
     **and states** navigation was text-based.
  4. *With Serena present, rename/replace a symbol* → uses `rename_symbol` /
     `replace_symbol_body`, not blind line edits.
  5. *Serena absent* → doctrine still works on the native `LSP` tool; no errors, no
     dangling tool references.

  Behavioral results are observed via the Task tool in VERIFY, not asserted in CI.
  Stated openly, matching Nescio convention.

## Operational risk to flag

Serena's own docs note that recent Claude Code / Opus versions **under-use external
MCP tools** because Claude Code's built-in tool descriptions (~16k tokens) bias the
model toward its internal tools. Oraios' mitigation (a system-prompt override plus
`serena-hooks` for `PreToolUse`/`SessionStart`) is marked **alpha**. Consequences
for this design:

- The doctrine's anti-rationalization section is aimed squarely at this bias and is
  the cheapest available mitigation.
- The **native `LSP` tool is first-party** and less subject to this than a
  third-party MCP — another reason to keep it the baseline and Serena the optional
  upgrade, and to set expectations honestly: without Serena's alpha hooks, the
  agent's uptake of *Serena's* tools is not guaranteed reliable.
- We do **not** bundle Serena's alpha hooks or system-prompt override (alpha, and a
  tighter coupling than "optional" warrants). Noted as a future option.

## Deliverables

- `skills/code-navigation/SKILL.md` — the doctrine (decision table, semantic-first
  method, anti-rationalization list, backends, honest fallback).
- `agents/explore.md`, `agents/reviewer.md` — thin hooks referencing the skill.
- `serena.mcp.example.json` — optional, memory-disabled backend config.
- `README.md` — one positioning sentence.
- This spec; behavioral scenarios verified via the eval skills.

## Out of scope

- Rebuilding any semantic engine (the explicitly rejected option).
- Serena's memory / onboarding / modes machinery beyond the disable-flags.
- Serena's alpha Claude Code hooks and system-prompt override.
- Non-Claude-Code contexts and the JetBrains backend.
- A dedicated Serena-driver agent or orchestrator-lifecycle wiring (the deeper
  integration considered and declined).

## Open risks / notes

- **Tool-adherence bias** (above) — behavioral, not fully fixable at the config
  layer.
- **Serena setup burden** — `uv` + per-language LSP toolchains. Mitigated by
  keeping Serena optional with the native `LSP` tool as the zero-setup baseline.
- **Native coverage is TS + Python only** today (the two enabled plugins). Adding
  more languages to the *baseline* is a separate, trivial `settings.json` change;
  Serena is the alternative for breadth without per-plugin management.
- **Doctrine drift** — new agents must opt into the hook to inherit the behavior;
  cost is one line each because the doctrine lives in the skill.
