# Discovery Brief: harvest_nudge split + wiki-engine de-duplication

Two independent subjects, both measured 2026-11-01 against `origin/main` @ bab92e4.

## Codebase map

### Subject A — the SessionStart hook
- `hooks/harvest_nudge.py` (411 lines) — the SessionStart hook. Three reminders:
  two priority-exclusive harvest reminders, plus an independent ADR 0002
  memory-trigger reminder printed *in addition*.
- `hooks/record_stop.py` (394) — the Stop hook; `harvest_nudge` imports it as
  `rs` by bare name and uses `repo_key`, `trail_dir`, `git_roots`,
  `read_watermark`, `watermark_path`, `_is_unharvested`.
- `hooks/__init__.py` (9) — puts the hooks dir on `sys.path` so siblings import
  by bare name AND `from hooks import X` works. A new sibling needs no wiring.
- `install.py:67` symlinks the whole `hooks/` dir; `install.py:781` wires
  `script_name="harvest_nudge.py"`. **That filename is load-bearing** — the
  entry point must keep it.
- `tests/test_harvest_nudge.py` (1329) — 8 top-level blocks. Harvest-side:
  `HarvestNudgeTest` (15), `WorktreeScopingTest` (447). Trigger-side helper
  `_FakeRun` (620), then `TriggerLineRenderingTest` (684),
  `TriggerPayloadBoundaryTest` (867), `TriggerMessageTest` (976),
  `TriggerNudgeMainTest` (1143), `TriggerEndToEndTest` (1282).

### Subject B — the knowledge-wiki engine
- `scripts/_wiki_common.py` (88) — shared helpers: `REPO_DIR`,
  `extract_wikilinks`, `split_frontmatter`, `iter_notes`, `load_stores`.
- `scripts/wiki_index.py` (423) — has `_resolve_dir` at :384.
- `scripts/wiki_lint.py` (110) — has `_resolve_dir` at :80. Textually different
  from the index copy, functionally equivalent. Both import `REPO_DIR` and
  `load_stores` from `_wiki_common` and call `load_stores()` with its default.
- `tests/test_wiki_lint.py:109-118` calls BOTH `wiki_lint._resolve_dir` and
  `wiki_index._resolve_dir` as module attributes.
- `tests/test_wiki_common.py` (74) — `json`/`tempfile` imported mid-file at
  42-43; line 44 re-imports `Path`, already imported at line 4.

## Conventions to match
- Phase brackets in commit subjects: `[refactor]`, `[fix]`, `[test]`, `[chore]`.
- Conventional commits (`refactor:`, `fix:`, `chore:`).
- `# noqa: E402` after a `sys.path.insert` — **70 files do this**. House pattern.
- A first-line `# <path/to/self>` comment — **26 files do this**. House pattern.
- `_wiki_common.py` is stdlib-only and path-parameterised for tests.
- Hooks never import from `scripts/` — duplication is deliberate, pinned by test.

## Constraints and hazards
- `hooks/harvest_nudge.py` must keep its filename (install.py:781).
- A pure move must not change behaviour. Baselines to match exactly:
  `tests/test_harvest_nudge.py` → **67 passed**;
  `test_wiki_common.py + test_wiki_lint.py + test_wiki_index.py` → **71 passed**;
  `test_record_stop.py + test_install_hooks.py` → **115 passed**.
- `ruff check .` currently passes with `select = ["E9", "F"]`. Keep it passing.
- Moves and behaviour changes must not share a commit (modular-design skill).

## External research
Skipped — no external surface. Both subjects are internal refactors.

## Assessment
Subject A: 3 reasons to change (harvest-state reminders / ADR 0002 trigger
reminder / hook entry point). No shared mutable state — only read-only
constants, and `trigger_nudge` deliberately re-resolves the repo root rather
than sharing it. Names pass. Split the trigger half out; leave the harvest pair
and `main()` in place.

Subject B: `_resolve_dir` duplication is real and its predicted cost already
materialised (#46 had to fix both copies).

## Open questions
Where `TriggerNudgeMainTest`'s coverage of `main()` belongs — `main()` stays in
`harvest_nudge.py`, but those tests assert the trigger line is printed. The
implementer decides; splitting by what each test asserts is the rule.

## Measured retirements — issue 2's remaining cosmetic items

Two of the three surviving items in issue 2 do not survive measurement, in the
same way two of its original five were retired on 2026-10-28.

**"Drop the inert file-top path-label comments" — retired.** The issue names
three files. **26 tracked files** carry a first-line `# <path/to/self>` comment.
It is a house pattern, not three stragglers; dropping three of 26 reduces
consistency. Either all go (a real decision with a real diff) or none.

**"Drop the `# noqa: E402` on test_wiki_common.py:9" — retired.** It suppresses
a TRUE positive. Measured:

    python -m ruff check --select E402 --ignore-noqa tests/test_wiki_common.py  -> 4
    python -m ruff check --select E402             tests/test_wiki_common.py  -> 3

The difference is line 9, whose import genuinely follows the `sys.path.insert`
on line 7 — exactly as **70 other files** in this repo do, all carrying the same
noqa. The remaining 3 findings are the *unguarded* mid-file imports at 42-44,
which is the real fix; line 44 also re-imports `Path` already imported at line 4.
Hoisting them takes the file from 3 unguarded findings to 0 and leaves the noqa
doing its job.
