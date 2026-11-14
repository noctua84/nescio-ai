# Discovery Brief: dreaming (offline session review → memory proposals)

## Codebase map
- `hooks/record_stop.py` — Stop hook; appends one JSONL record per turn to
  `<config>/learning-trail/<repo_key>.jsonl`. Exposes `repo_key()`, `redact()`,
  `SECRET_PATTERNS`, `config_dir()`. Carries `transcript_path` but no verdict.
- `hooks/harvest_nudge.py` + `hooks/memory_trigger_nudge.py` — SessionStart
  nudges (harvest count threshold, pending-harvest marker, ADR 0002 triggers).
  The natural place for a "dream due" nudge later.
- `commands/harvest-memory.md` + `scripts/begin_harvest.py`,
  `promote_learnings.py`, `mark_harvested.py` — the one sanctioned path from
  machine-local exhaust into version-controlled `memory/`. `promote_learnings.py`
  validates nominations (scope/target/type/name/description/body/source/date),
  applies contradiction precedence, stamps provenance, writes the ledger.
- `scripts/session_anatomy.py` — existing transcript streamer (line-by-line,
  malformed-line tolerant, dedupe by message.id). Pattern to copy for parsing.
- `memory/CONVENTIONS.md` — provenance tag, precedence
  `user override > empirical > agent inference`, manifest schema.
- Transcripts: `<config>/projects/<path-slug>/<session>.jsonl`; worktrees get
  their own slug `<slug>--claude-worktrees-<name>`. Agent results appear in the
  parent transcript as `type: user` entries whose `toolUseResult` dict carries
  `agentType`, `status`, `totalTokens`, `resolvedModel`, and `content` (list of
  `{type: text, text}` blocks) holding the builder report.
- Builder report contract (`agents/builder*.md`): `<verdict>COMPLETE|PARTIAL|
  BLOCKED</verdict>`, `<deviations>` (labels `Inverted pin:`, `Deferred red:`),
  `<out-of-scope>`. Agent names are themeable (`apply_theme.py`); code must be
  theme-agnostic (tier = `-simple`/`-standard` suffix, family = stem).

## Conventions to match
Python 3 stdlib only; scripts in `scripts/` with a long design docstring;
`argparse`; tests in `tests/test_<name>.py` using `unittest`, fixtures built as
throwaway JSONL under `tempfile` (never real transcripts); run with
`PYTHONPATH=scripts python -m unittest discover -s tests`.

## Constraints and hazards
- Transcripts are private. Dream output stays machine-local
  (`<config>/dreams/<repo_key>/`), is redacted, home paths replaced by `~`.
- Never auto-edit agents/ or CLAUDE.md. Memory writes only via
  `promote_learnings.py`, and only from the brain (guard_brain).
- Public repo: no private repo names, paths, identifiers; `scrub_check.py`.

## External research
Anthropic Managed Agents "Dreams": async job over a memory store + 1–100
sessions → a *new* output store; input never modified; approval is structural
(attach or discard the output store). See docs/design/dreaming.md.

## Assessment
Deterministic extractor (no model call) writes a reviewable proposal; the
`/dream` command has Claude turn recurring signals into harvest nominations
or held prompt-tweak suggestions. Mirrors Dreams' "new store, never mutate
input" with "proposal file, never mutate memory".
