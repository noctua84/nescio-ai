# Discovery Brief: YAML-safe frontmatter emission in promote_learnings

## Codebase map
- `scripts/_promoted_block.py` (~400 ln) — the ACTUAL write path. `render_frontmatter(nom)`
  (line ~86) builds the block by f-string interpolation; `_refresh_frontmatter(fm_raw, nom)`
  (line ~306) rewrites managed keys with `f"{key}: {managed[key]}"` in two places
  (in-place rewrite loop + missing-key insert). Three interpolation sites total.
- `scripts/promote_learnings.py` (1053 ln) — only IMPORTS those helpers. The bug is not
  in this file; it is the caller named in the report.
- `scripts/_wiki_common.py` (105 ln) — READER. `split_frontmatter` is a hand-rolled
  `key: value` parser. It does NOT unquote: it returns `'"a: b"'` verbatim, quotes included.
- `scripts/wiki_index.py:135` — `desc = str(fm.get("description") or "")` goes straight
  into the generated `MEMORY.md` link line. A quoted value leaks quote characters here.
- `scripts/_adr_transform.py:118` — existing precedent `_yaml_quote`: always double-quotes,
  escapes `\` then `"`. Unconditional, so not directly reusable (brief wants readable output).
- `tests/test_promote_learnings.py` (982 ln) — `_seed_repo` / `_nom` fixtures.
- `tests/test_frontmatter_yaml.py` — the only place that imports `yaml`.

## Conventions to match
- Scripts are STDLIB-ONLY at runtime. `pyproject.toml`: `dependencies = []`, and
  `pyyaml==6.0.3` is in `[dependency-groups] dev` only. `_wiki_common.py`'s docstring
  states "without a YAML dependency". So a YAML *serializer* is unavailable on the write
  side; quote-and-escape is the only option. `yaml` is fine in tests.
- Ruff rules in force: `select = ["E9", "F"]`.

## Constraints and hazards
- HAZARD (not in the original report): quoting on the write side alone converts the bug
  rather than fixing it. `split_frontmatter` keeps the literal quotes, so every generated
  `MEMORY.md` line would read `— "no"`. The reader must learn to unquote, and must leave
  plain unquoted scalars byte-identical.
- Compatibility baseline: existing notes under `memory/repo/nescio/` and `memory/concepts/`
  are all plain unquoted scalars (verified: no quoted frontmatter exists anywhere in memory/).
- `memory/learning-log.md` must exist or the promoter exits 1 before writing.
- Dedup hash is over the nomination `body` only; changing `name` does not affect dedup.
- `_refresh_frontmatter` must keep preserving unmanaged keys, ordering and formatting.

## External research
Skipped — no external surface. YAML scalar rules are validated empirically in tests
against the already-present `pyyaml`.

## Assessment
Two-part fix: (1) a minimal-quoting stdlib helper used at all three write sites, plain
scalar where safe and double-quoted+escaped where not; (2) `split_frontmatter` learns to
unquote. Rejected: `yaml.dump` (dev-only dep); always-quoting like `_adr_transform`
(unreadable output, and the brief asks for plain scalars where safe).

## Open questions
None blocking.
