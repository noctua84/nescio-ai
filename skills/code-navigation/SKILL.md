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
