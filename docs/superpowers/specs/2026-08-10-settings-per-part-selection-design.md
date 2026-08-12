# Design: settings.json per-part selection (`install.py`)

- **Date:** 2026-08-10
- **Status:** Proposed
- **Scope:** Layer A / **A1 only** (settings.json granularity). CLAUDE.md
  section-level (A2) and MCP-as-a-part are explicit follow-ups, not in this spec.

## Problem
`install.py` offers only `--settings full|minimal|skip`: adopt the *entire*
framework `settings.json`, just the `agent` entrypoint, or nothing. There is no
way to adopt a **subset** — e.g. "add the agent entrypoint and plugins but leave
my permissions alone."

The merge itself is already non-destructive: `deep_merge` overlays the framework
keys over the user's file (nested dicts recurse, lists union-dedup, the user's
other keys and allow-list are preserved). So the gap is purely **which keys form
the overlay** — a selection problem, not a merge problem.

## Goals
- Let the user choose which top-level framework settings parts to adopt:
  `agent`, `permissions`, `plugins`.
- Preserve the existing non-destructive deep-merge (user's other keys/allow-list
  untouched).
- Backward-compatible CLI **and** interactive prompt; pure stdlib; idempotent;
  dry-run-able.

## Non-goals (explicit follow-ups)
- **A2** — CLAUDE.md section-level import (`CLAUDE.d/`): separate spec.
- **MCP as a settings part** — the framework ships no `mcpServers` block today;
  adding one (or offering `claude mcp add`) is separate work.
- **Layer B** — LLM-assisted reconciliation skill.

## Current behavior (baseline)
- `SETTINGS_CHOICES = ("full", "minimal", "skip")`; argparse `--settings` uses
  `choices=SETTINGS_CHOICES`.
- `resolve_settings_choice(cli)`: returns the choice string; interactive loops
  until one of the three; non-interactive without `--settings` exits 2.
- `install_settings(choice, dry_run)`: `skip` → no-op; overlay is
  `{"agent": "orchestrator"}` (minimal) or the whole repo `settings.json` (full);
  `merged = deep_merge(overlay, existing)`; writes a **real** file (unlinking a
  prior repo symlink). Hooks are wired separately, after.

The framework `settings.json` has exactly three top-level keys: `agent`,
`permissions`, `enabledPlugins`.

## Design

### Parts → keys
```python
PART_KEYS = {
    "agent":       ("agent",),
    "permissions": ("permissions",),
    "plugins":     ("enabledPlugins",),
}
```
The overlay for a selection is the framework `settings.json` restricted to the
selected parts' keys. The framework file is the single source of truth — the old
hardcoded `{"agent": "orchestrator"}` for `minimal` is replaced by reading the
real `agent` value, so `minimal` stays byte-identical in practice.

### CLI
`--settings VALUE`, where VALUE is **either**:
- a **keyword**: `full` (= all parts) · `minimal` (= `agent`) · `skip` (= none), **or**
- a **comma-list of parts**: `agent,plugins`, `permissions`, `agent,permissions,plugins`, …

Parsing rule: VALUE is a keyword iff it exactly equals one of `full|minimal|skip`;
otherwise it is split on commas and each token is validated against `PART_KEYS`.
Mixing (e.g. `full,agent`) or an unknown token → stderr usage line + exit 2. An
empty list → treated as `skip`.

argparse: **drop `choices=`** for `--settings` (accept a free string); validate in
`resolve_settings_choice`. Update the non-interactive help to list both keywords
and the part names.

### Resolution
`resolve_settings_choice(cli_value) -> frozenset[str]` returns the selected parts
(empty set = skip):
- **CLI given** → parse per above.
- **Non-interactive (no TTY) + no CLI** → exit 2 as today, with help listing
  keywords + parts.
- **Interactive** → prompt:
  ```
  How should this framework's settings.json integrate?
  (deep-merged over your existing file — your other keys and allow-list are kept)
    full     agent + permissions + plugins   (recommended)
    minimal  agent entrypoint only
    custom   choose parts individually
    skip     leave settings.json unchanged
  choose [full/minimal/custom/skip] (default: full):
  ```
  Blank/Enter → `full` (all three — the agreed default). `custom` → per-part,
  each defaulting to **Y**:
  ```
    adopt agent entrypoint?       [Y/n]
    adopt permissions allow-list? [Y/n]
    adopt plugins?                [Y/n]
  ```
  A `custom` run that deselects everything → empty set → treated as `skip` (with
  a printed note).

### `install_settings(parts, dry_run)`
- Signature changes from `choice: str` to `parts: frozenset[str]` (resolved
  upstream) — cleaner to unit-test than re-parsing inside.
- Empty set → skip (same message as today).
- `overlay = {k: fw[k] for part in parts for k in PART_KEYS[part] if k in fw}`
  where `fw = load_json(REPO_DIR / "settings.json")`.
- `merged = deep_merge(overlay, existing)`; write the real file (unlink a prior
  symlink exactly as today).
- Dry-run: print the selected parts and the concrete keys that would be merged.
- Hook wiring is unchanged and still runs after.

### Call sites
`do_default` and `do_relink` thread the resolved parts set through to
`install_settings`. `resolve_settings_choice`'s return type changes (str →
parts set) — update both callers and the `--settings` plumbing.

## Error handling
- Invalid part token / mixed keyword+parts → stderr usage + exit 2.
- Empty selection (interactive deselect-all, or `--settings skip`) → no-op with a
  clear message; the file is not written.
- Defensive: a selected part whose key is absent from the framework file is
  skipped silently (keeps the installer robust to future settings changes).

## Backward compatibility
- `--settings full|minimal|skip` behave exactly as before: `full` = all parts
  (same keys), `minimal` = `agent` only, `skip` = none. Existing unattended
  installs, README examples, and CI/tests keep working.
- Internal signatures change (`resolve_settings_choice` return type,
  `install_settings` parameter) — update the tests that call them directly.
- README `--settings` documentation gains the parts syntax + an example
  (`--settings agent,plugins`).

## Testing (TDD — write first)
- **Keyword back-compat:** `full` → `{agent,permissions,plugins}`; `minimal` →
  `{agent}`; `skip` → `∅`.
- **Part-list parse:** `agent,plugins` → `{agent,plugins}`; whitespace tolerated;
  duplicates collapsed.
- **Validation:** unknown token → exit 2; mixed `full,agent` → exit 2.
- **Overlay correctness:** only selected keys present; with `permissions` selected,
  `deep_merge` unions the allow-list and preserves an unrelated pre-existing user
  key; with `permissions` NOT selected, the user's `permissions` is left untouched.
- **Empty selection:** file unchanged / not written (skip semantics).
- **Dry-run:** writes nothing; prints the selected parts.
- **Non-interactive without `--settings`:** exit 2 with help.
- **Idempotent:** running twice yields an identical file.

## Files touched
- `install.py`: add `PART_KEYS`; `--settings` argparse (free string);
  `resolve_settings_choice` (returns parts set + `custom` flow); `install_settings`
  (parts set); `do_default` / `do_relink` call sites; non-interactive help text.
- `tests/test_install.py` (+ `tests/test_install_hooks.py` if it calls these):
  update signatures, add the cases above.
- `README.md`: `--settings` docs + `agent,plugins` example.

## Rollout / risk
Low risk — reuses `deep_merge` untouched. The one thing to guard carefully is
keeping the keyword behavior byte-identical for existing unattended installs;
the back-compat tests above lock that in.

## Follow-ups (tracked separately)
- **A2:** CLAUDE.md section-level import via `CLAUDE.d/` (its own spec).
- **MCP-as-a-part:** requires the framework to ship an `mcpServers` block or the
  installer to offer `claude mcp add`.
