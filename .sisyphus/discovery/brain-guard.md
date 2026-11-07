# Discovery Brief: brain guard for the learning-promotion scripts

## Codebase map
- `scripts/_learning_common.py` (71 lines) — shared learning-loop helpers. Sets
  `REPO_DIR = Path(__file__).resolve().parent.parent` (line 32) and
  `LEARNING_LEDGER`. Imports `sha8` from `_adopt_common`. **No stdlib imports
  beyond hashlib/pathlib today; no subprocess, no os.**
- `scripts/promote_learnings.py` (1089 lines) — the write path. Imports
  `REPO_DIR` from `_learning_common`; `promote(records, repo_dir=REPO_DIR, ...)`
  takes the destination as a *parameter*. `main()` at line 1045 never passes
  `repo_dir`, so the CLI always uses the module default. This is the entry point
  the real incident went through.
- `scripts/begin_harvest.py` (295 lines) — opens the harvest. `main(argv=None)`
  at line 215; `default_out_dir()` (line 212) returns
  `REPO_DIR / "eval" / "learnings" / <stamp>`. Writes `read.json` and prints a
  `next: python scripts/promote_learnings.py ...` line.
- `scripts/compute_readiness.py` (690 lines) — defines its **own** `REPO_DIR`
  (line 104) and imports only `parse_ledger` from `_learning_common`. Read-only
  readiness report. **Out of scope** — guarding it would pull a 690-line file
  into the module gate for no write-path benefit.
- `scripts/_promoted_block.py` — imports `_learning_common` but uses no
  `REPO_DIR`. No guard needed.
- `hooks/record_stop.py:68` — `config_dir()`: `$CLAUDE_CONFIG_DIR` if set, else
  `Path.home() / ".claude"`. **This is the existing precedent to copy.**
- `install.py:62` — `LINKS` table; `("memory", "memory")` is what creates
  `<config>/memory -> <brain>/memory`.
- `commands/harvest-memory.md:55` — the `## Run it in the brain` prose from
  PR #233. The guard mechanises exactly that section.

## Conventions to match
- Entry points are `def main(argv=None) -> int`, return code not `sys.exit`.
- Errors print `error: <msg>` and return non-zero (see `promote_learnings.main`).
- `main()` reconfigures stdout to UTF-8 inside a `try/except
  (AttributeError, ValueError)` before printing anything non-ASCII.
- Module docstrings are long and explain *why*, with inline comments carrying
  the rationale for any non-obvious choice. Match that density.
- Tests: stdlib `unittest`, one `tests/test_<topic>.py` per concern, temp dirs
  via `tempfile`, `CLAUDE_CONFIG_DIR` saved/restored around each case (see
  `tests/test_begin_harvest.py:28-37` for the exact save/restore helper pair).
- `scripts/` modules are imported flat (`PYTHONPATH=scripts`), so
  `from _learning_common import ...`, never a package path.

## Constraints and hazards
- **No existing test calls `promote_learnings.main()` or exercises
  `begin_harvest` without a temp `CLAUDE_CONFIG_DIR`.** Every promote test calls
  `pl.promote(..., repo_dir=repo)` directly (57 call sites in
  `tests/test_promote_learnings.py`). A guard placed in `main()` therefore trips
  **zero** existing tests. A guard placed in `promote()` or at import time would
  trip hundreds. This is the decisive fact for the design.
- `tests/test_begin_harvest.py` points `CLAUDE_CONFIG_DIR` at a temp dir with a
  `learning-trail/` subdir and **no `memory` entry**. That is the
  "cannot resolve" branch, so it must degrade to a warning and rc 0 — those
  tests assert `rc == 0`.
- Worktrees: `git rev-parse --path-format=absolute --git-common-dir` returns the
  identical `.git` path from a worktree and from the main checkout (verified on
  this machine). `--show-toplevel` does **not** — it differs per worktree. So the
  comparison must be on common-dir.
- `--path-format=absolute` needs git >= 2.31. A git failure of any kind must
  degrade to "cannot resolve", never to a refusal.
- `scripts/` is mirrored downstream by `sync_from_upstream.py`. The guard must
  not assume the brain and the framework are the same checkout, and must not
  assume a symlink exists at all.
- `promote_learnings.py` (1089) is over the 400-line module tripwire, so touching
  it requires a `Module-check:` ack in the PR body.
- **PUBLIC repo.** The brain's repository name and any absolute path to it must
  not appear in any file, test, commit message or PR body.

## External research
Skipped — no external surface. Only stdlib (`os`, `subprocess`, `pathlib`) and
git CLI behaviour already demonstrated in this codebase (`hooks/record_stop.py`,
`scripts/_trail_scope.py`).

## Assessment
The guard is a **function in `_learning_common.py` that entry-point `main()`s
call**, not an import-time side effect and not a check inside `promote()`.
Three-state verdict: OK / cannot-resolve (warn, proceed) / mismatch (refuse).
Compare `--git-common-dir` of `REPO_DIR` against `--git-common-dir` of the
resolved `<config>/memory`.

## Open questions
None blocking. The refuse-vs-warn split and the escape-hatch shape are decided
in the plan.
