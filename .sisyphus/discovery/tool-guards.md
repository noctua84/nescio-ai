# Discovery Brief: tool-call guards (PreToolUse hooks enforcing crew boundaries)

## Codebase map
- `install.py` — `_wire_command_hook(config_dir, *, event_name, script_name, use_async, dry_run, matcher=None)`
  wires `{"type":"command","command":<interpreter>,"args":[<config_dir>/hooks/<script>]}` into
  `~/.claude/settings.json`; identity = (script path, group matcher); repairs interpreter/matcher drift.
  Callers `wire_stop_hook`, `wire_sessionstart_hook`, invoked from `main()` when `hooks_linked`.
- `hooks/` — symlinked to `~/.claude/hooks`; standalone scripts run by absolute path, import siblings by
  bare name (`hooks/__init__.py` puts the dir on sys.path). Pattern: `harvest_nudge.py`, `record_stop.py`.
- `tests/test_install_hooks.py` — wiring tests (matcher identity, drift). `tests/test_harvest_nudge.py` —
  hook tests via `from hooks import <mod>`. Run: `PYTHONPATH=scripts python -m unittest discover -s tests`.
- `scripts/_crew_common.py` `PAIRS` — functional <-> philosopher agent names (`qa-guard`/`cato`,
  `test-writer`/`euclid`, `doc-writer`/`cicero`, `planner`/`plato`). Runtime `agent_type` is whichever
  theme is installed, so a guard must accept both names.
- `agents/qa-guard.md` lines 10-23 — the check-file boundary text the guard enforces.

## Conventions to match
stdlib only, Python >=3.13 (tomllib available), unittest, `from __future__ import annotations`,
long docstrings explaining *why*. Conventional commits with `[impl]`/`[test]`/`[docs]` tags.

## Constraints and hazards
- A settings-level PreToolUse hook fires for **every** agent; the guard must no-op fast when
  `agent_type` is not the guarded agent, and a crash blocks everyone once `onFailure: "block"` is set.
- Hook docs: deny = stdout JSON `hookSpecificOutput.permissionDecision: "deny"`, exit 0; exit 2 also
  blocks; other exit codes / timeouts fail open unless `onFailure: "block"` (v2.1.295+).
- Matcher `Edit|Write|...` is an exact-name list, not a regex. Windows paths arrive with backslashes.
- Never name private repos in tracked files; run `python scripts/scrub_check.py`.

## External research
https://code.claude.com/docs/en/hooks — summarised in `docs/design/tool-guards.md`.

## Assessment
Prototype one guard (`qa-guard`/`cato` check-file guard) wired at settings level with
`onFailure: "block"`; frontmatter hooks are the scoped alternative, discussed in the design note.
