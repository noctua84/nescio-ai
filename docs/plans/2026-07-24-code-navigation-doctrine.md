# Code-Navigation Doctrine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the crew navigate code semantically (by symbol) by default, on top of a borrowed engine — Claude Code's native `LSP` tool as the baseline plus an optional, memory-disabled Serena MCP connection.

**Architecture:** A new `skills/code-navigation/SKILL.md` holds the doctrine (decision table, semantic-first method, anti-rationalization list, honest fallback). Thin hooks in `agents/explore.md` and `agents/reviewer.md` point the crew at it. Serena is offered as a documented, opt-in MCP connection (`serena.mcp.example.json` + a README section), never a hard dependency. Nescio owns the doctrine; the engine stays borrowed.

**Tech Stack:** Markdown (skills/agents), JSON (MCP example config), Claude Code's native `LSP` tool, optional Serena (MIT, `serena-agent` via `uv`).

## Global Constraints

- **License boundary:** copy no Serena code or prose. The only Serena-derived artifact is its documented launch command (not copyrightable). Serena's JetBrains backend is paid/non-MIT — never referenced.
- **No second memory system:** the Serena config MUST include `--mode no-memories` (removes memory + onboarding tools). Never document a Serena config without it.
- **No hard dependency:** Serena stays optional; the native `LSP` tool is the zero-setup baseline. Preserve the README's "no agent hard-depends on a plugin" framing.
- **Exact verified Serena launch vector** (source: `oraios/serena` HEAD 2026-07-22, `src/serena/cli.py`): `serena start-mcp-server --context claude-code --mode no-memories --project-from-cwd`.
- **Install prerequisite copy:** `uv tool install -p 3.13 serena-agent` (`uv` required; supported Python 3.11–3.14; `-p 3.13` only pins the interpreter).
- **Single source of truth:** the doctrine lives in the skill; agents reference it, never re-state it. The Serena config lives in `serena.mcp.example.json` + README; the skill references those, never duplicates the block.
- **Commit style:** conventional commits; end each commit body with `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`. Branch is `claude/serena-nescio-extension-48c43f` (never `main`).

---

### Task 1: Optional Serena backend (config example + README)

Create the single source of the Serena connection config and document it as opt-in. Done first so the doctrine skill (Task 2) can reference it without a forward-dangling path.

**Files:**
- Create: `serena.mcp.example.json`
- Modify: `README.md` (add a subsection after the plugins note, ~line 149–150)

**Interfaces:**
- Consumes: nothing.
- Produces: the file path `serena.mcp.example.json` and the README subsection heading **"Optional: Serena semantic backend"** — Task 2's skill "Backends" section links to this heading.

- [ ] **Step 1: Write the example config file**

Create `serena.mcp.example.json` with exactly:

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

- [ ] **Step 2: Validate the config mechanically**

Run:

```bash
python3 -c "import json; d=json.load(open('serena.mcp.example.json')); s=d['mcpServers']['serena']; a=s['args']; assert s['command']=='serena'; assert a[0]=='start-mcp-server'; assert a[a.index('--context')+1]=='claude-code'; assert a[a.index('--mode')+1]=='no-memories'; assert '--project-from-cwd' in a; print('OK')"
```

Expected: prints `OK` (valid JSON; context is `claude-code`; memory disabled; cwd-scoped).

- [ ] **Step 3: Add the README subsection**

In `README.md`, immediately after the sentence about the `superpowers` / `typescript-lsp` / `pyright-lsp` plugins (~line 149–150), insert:

````markdown
### Optional: Serena semantic backend

The `code-navigation` doctrine works out of the box on Claude Code's native `LSP`
tool (TypeScript + Python, via the enabled plugins). For 40+ languages and
symbol-level *editing*, connect [Serena](https://github.com/oraios/serena) as an
optional MCP server — it stays fully optional; no agent depends on it.

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
````

- [ ] **Step 4: Verify the README renders the block**

Run:

```bash
grep -n "Optional: Serena semantic backend" README.md && grep -n "no-memories" README.md && grep -n "no agent depends on it" README.md
```

Expected: three matching lines printed (heading present, memory-disable present, optional framing present).

- [ ] **Step 5: Commit**

```bash
git add serena.mcp.example.json README.md
git commit -m "$(printf 'feat(connections): document optional memory-disabled Serena MCP backend\n\nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>')"
```

---

### Task 2: The `code-navigation` doctrine skill

Create the doctrine — the single source the crew reads. References the README section from Task 1.

**Files:**
- Create: `skills/code-navigation/SKILL.md`

**Interfaces:**
- Consumes: the README heading "Optional: Serena semantic backend" (Task 1).
- Produces: the skill name `code-navigation` and path `skills/code-navigation/SKILL.md` — Task 3's agent hooks reference this exact path.

- [ ] **Step 1: Write the skill file**

Create `skills/code-navigation/SKILL.md` with exactly:

````markdown
---
name: code-navigation
description: Use when locating, reading, or editing code — finding where a symbol is defined, who calls or implements it, tracing call paths, or making symbol-level edits. Navigate semantically first (LSP/symbol tools); fall back to text search only for genuinely textual targets. Triggers on "where is X defined", "who calls X", "find references", "find implementations", "rename symbol", "trace this function".
user-invocable: true
---

# Code Navigation

Navigate and edit code the way an IDE user does: by **symbol** first, by **text**
only when the target is genuinely text. Semantic navigation is faster, cheaper in
tokens, and more precise than grep-and-read on any non-trivial codebase — and that
precision is what lifts output quality.

## The rule

Ask *what kind of question is this?* before reaching for a tool:

| The question | First-resort tool |
|---|---|
| Where is this symbol defined? | semantic — `goToDefinition` / `find_symbol` |
| Who references or calls this symbol? | semantic — `findReferences` / `find_referencing_symbols`, call-hierarchy |
| Who implements this interface / overrides this method? | semantic — `goToImplementation` / `find_implementations` |
| What symbols exist in this file / across the project? | semantic — `documentSymbol` / `workspaceSymbol` / `get_symbols_overview` |
| Type, signature, or doc at a position | semantic — `hover` |
| A string literal, comment, log message, config key, or other non-code text | text — `grep` |
| A file by name or extension | `glob` |
| When or why something changed | `git blame` / `git log -S` |

## Method: overview → jump → follow

Don't grep a name and read whole files hoping to understand structure. Instead:

1. **Overview** the file or workspace symbols to see the shape.
2. **Jump** to the symbol by its definition, not by scrolling.
3. **Follow** references, implementations, and the call hierarchy to build the
   picture — each hop is a precise semantic query, not a re-read.

For edits, prefer symbol-level operations (replace a function body, insert
before/after a symbol, rename, safe-delete) over blind line edits when a semantic
backend offers them — they respect scope and are far less error-prone than line math.

## Don't rationalize your way back to grep

These thoughts mean stop — you're about to trade precision for habit:

| Thought | Reality |
|---|---|
| "It's just one symbol, grep is fine" | One symbol is exactly what `find_symbol` is for — and it won't match a comment or a shadowed name. |
| "grep is faster to type" | Faster to type, slower to be right. A wrong location costs more than the query. |
| "I already know roughly where it is" | "Roughly" is how you read the wrong overload. Jump to the definition. |
| "The file is small" | Small files still have references elsewhere. `findReferences` sees the whole project; your eyes see one file. |

## Backends

The doctrine is backend-agnostic — it names behaviors, not products:

- **Baseline (zero setup):** Claude Code's native `LSP` tool, fed by the
  `typescript-lsp` and `pyright-lsp` plugins Nescio enables — semantic navigation
  for TypeScript and Python.
- **Optional upgrade:** the Serena MCP connection (see the README's *"Optional:
  Serena semantic backend"*) adds symbol-level *editing* and 40+ languages.

## Honest fallback

If no language server serves the file's language, the semantic operations will
error. Fall back to `grep`/`glob` — and **say so**: state that navigation was
text-based, not semantic, so the caller knows the difference. Text-based navigation
is a valid answer; pretending it was semantic is not. (Same discipline as
`explore`'s honest not-found.)
````

- [ ] **Step 2: Verify frontmatter and required sections**

Run:

```bash
head -5 skills/code-navigation/SKILL.md | grep -q "name: code-navigation" && \
grep -q "user-invocable: true" skills/code-navigation/SKILL.md && \
grep -qE "^## The rule" skills/code-navigation/SKILL.md && \
grep -qE "^## Don't rationalize your way back to grep" skills/code-navigation/SKILL.md && \
grep -qE "^## Backends" skills/code-navigation/SKILL.md && \
grep -qE "^## Honest fallback" skills/code-navigation/SKILL.md && echo "OK"
```

Expected: prints `OK` (frontmatter keys present; all four load-bearing sections present).

- [ ] **Step 3: Confirm the skill is discoverable in the skills listing**

Run:

```bash
ls skills/code-navigation/SKILL.md
```

Expected: the path prints (file exists at the location Claude Code scans for `user-invocable` skills).

- [ ] **Step 4: Commit**

```bash
git add skills/code-navigation/SKILL.md
git commit -m "$(printf 'feat(skills): add code-navigation doctrine (semantic-first navigation)\n\nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>')"
```

---

### Task 3: Wire the doctrine into `explore` and `reviewer`

Thin hooks so the crew follows the doctrine by default. Both edits reference the skill from Task 2; neither restates it (DRY).

**Files:**
- Modify: `agents/explore.md` (the "Tool Strategy" section, ~lines 62–71)
- Modify: `agents/reviewer.md` (the "2. Static Analysis" section)

**Interfaces:**
- Consumes: the skill path `skills/code-navigation` (Task 2).
- Produces: nothing downstream.

- [ ] **Step 1: Update `explore.md` Tool Strategy**

Replace this block in `agents/explore.md`:

```markdown
## Tool Strategy

Use the right tool for the job:
- **Semantic search** (definitions, references): LSP tools
- **Text patterns** (strings, comments, logs): grep
- **File patterns** (find by name/extension): glob
- **History/evolution** (when added, who changed): git commands
```

with:

```markdown
## Tool Strategy

Navigate by **symbol first** — see `skills/code-navigation` for the full doctrine
and the grep-vs-semantic decision table. Default routing:
- **Semantic navigation** (where defined, who references, who implements, call
  hierarchy): the `LSP` tool (or Serena's symbol tools if connected). Prefer this
  for any code-structure question — don't fall back to grep for "just one symbol".
- **Text patterns** (strings, comments, logs, config keys): grep
- **File patterns** (find by name/extension): glob
- **History/evolution** (when added, who changed): git commands
```

(Leave the "Prior work (last resort)" bullet and the "Flood with parallel calls" line that follow it unchanged.)

- [ ] **Step 2: Verify the `explore.md` edit**

Run:

```bash
grep -n "skills/code-navigation" agents/explore.md && \
grep -n "just one symbol" agents/explore.md && \
grep -n "Prior work (last resort)" agents/explore.md && echo "OK"
```

Expected: the skill reference and the anti-grep nudge are present, and the untouched "Prior work" bullet still exists (`OK`).

- [ ] **Step 3: Update `reviewer.md` Static Analysis**

In `agents/reviewer.md`, find the "### 2. Static Analysis" section. Immediately after the bullet:

```markdown
- Trace execution paths by reading the actual code, not by inferring from names.
```

insert a new bullet:

```markdown
- Use semantic navigation to establish what "correct" looks like — follow
  references, implementations, and the call hierarchy (per `skills/code-navigation`)
  rather than grepping names, so you judge the real callers and contracts, not
  guessed ones.
```

- [ ] **Step 4: Verify the `reviewer.md` edit**

Run:

```bash
grep -n "skills/code-navigation" agents/reviewer.md && \
grep -n "Trace execution paths by reading the actual code" agents/reviewer.md && echo "OK"
```

Expected: the skill reference is present and the original "Trace execution paths" bullet is intact (`OK`).

- [ ] **Step 5: Commit**

```bash
git add agents/explore.md agents/reviewer.md
git commit -m "$(printf 'feat(agents): route explore and reviewer through code-navigation doctrine\n\nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>')"
```

---

### Task 4: Behavioral verification (golden scenarios)

The doctrine is prompts; the deterministic checks in Tasks 1–3 cover structure only. Behavior is verified with Nescio's own evaluation skills, not CI. This task produces a short verification record, not code.

**Files:**
- Create (optional): `docs/specs/2026-07-24-code-navigation-verification.md` (the run notes)

**Interfaces:**
- Consumes: everything from Tasks 1–3.
- Produces: a pass/fail record for the review gate.

- [ ] **Step 1: Define golden cases with `prompt-testing-plan`**

Invoke the `prompt-testing-plan` skill to formalize these five cases and their pass/fail criteria:
1. *"Where is X defined / who calls X"* → `explore` uses semantic ops (`LSP` / symbol tools), not grep-then-read.
2. *Find a log message / string literal* → correctly uses `grep` (doctrine does not over-apply semantics).
3. *File in a language with no configured server* → falls back to `grep`/`glob` **and states** navigation was text-based.
4. *With Serena connected, rename/replace a symbol* → uses `rename_symbol` / `replace_symbol_body`, not blind line edits.
5. *Serena absent* → doctrine still works on the native `LSP` tool; no errors, no dangling tool references.

- [ ] **Step 2: Score with `agent-evaluation`**

Invoke the `agent-evaluation` skill against the five cases, driving `explore` (and `reviewer` for case 1's contract-reading) via the Task tool. Record trajectory and tool-use correctness per case.

- [ ] **Step 3: Record the outcome**

Write the pass/fail per case into the verification notes (or report inline). For any failure, note whether the fix is doctrine wording (edit the skill) or a hook wording issue (edit the agent), and loop back to the relevant task. State openly that results are behavioral, not CI-asserted.

- [ ] **Step 4: Commit (if notes were written)**

```bash
git add docs/specs/2026-07-24-code-navigation-verification.md
git commit -m "$(printf 'docs(specs): code-navigation behavioral verification notes\n\nCo-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>')"
```

---

## Notes for the implementer

- **Anti-rationalization is the point, not decoration.** Serena's docs admit recent
  Claude Code / Opus versions under-use external tools (their built-in tool
  descriptions bias the model inward). The "Don't rationalize your way back to grep"
  table is the cheapest mitigation — keep it sharp; don't soften it into a
  suggestion.
- **Do not** bundle Serena's alpha `serena-hooks` or system-prompt override — out of
  scope, alpha, and a tighter coupling than "optional" warrants.
- **Do not** add Serena to `settings.json` `enabledPlugins` or any tracked runtime
  config — it stays a documented example only.
- If `README.md` line numbers have drifted, anchor on the sentence naming
  `typescript-lsp` / `pyright-lsp` rather than the line number.
