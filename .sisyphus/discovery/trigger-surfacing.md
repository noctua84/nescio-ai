# Discovery Brief: surface a fired ADR 0002 memory trigger at SessionStart

## The gap

`scripts/check_memory_triggers.py` turns ADR 0002's four revisit triggers into a
runnable report. It is a reporter with no reader: nothing invokes it, so a trigger
can fire and stay silent indefinitely. Measured 2026-10-26:

| Corpus | Notes | T2 (~500) | T1 largest dir (~100) |
|---|---|---|---|
| this repo's `memory/` | 12 | clear | clear |
| the operator's live brain repo | 556 | **FIRED** (111%) | clear, largest at 95 |

So T2 is already fired in the repo that matters and nothing says so, and T1's largest
directory is at 95 of 100 — the script's docstring argues explicitly that proximity
matters as much as the verdict ("a directory at 80 of 100 is a different situation
from one at 12, and a bare `clear` hides that").

`hooks/harvest_nudge.py` is the existing precedent and the obvious host: a SessionStart
hook that already exists to make an invisible memory-state fact visible.

## Codebase map

- `hooks/harvest_nudge.py` (8.2 KB) — SessionStart hook. Two reminders in priority
  order: an unfinished harvest (`.harvest-pending-<repo_key>` marker) outranks the
  un-harvested record count. `NUDGE_THRESHOLD` defaults to 20, overridable via
  `CLAUDE_HARVEST_NUDGE_THRESHOLD`. Fires only on `startup`/`resume`; silent on
  `clear`/`compact`. **Exits 0 always**; every failure degrades to the next reminder.
  Writes to stdout, which Claude Code injects as session context.
- `hooks/record_stop.py` — sibling, imported as `rs`. Supplies `rs.git_roots(cwd)[1]`
  (repo root), `rs.trail_dir()`, `rs.repo_key()`, `rs.watermark_path()`, `rs.config_dir()`.
- `scripts/check_memory_triggers.py` (1500+ lines) — the trigger reporter. Relevant CLI:
  `--memory-root` (default: this repo's `memory/`), `--skip-transcripts` ("Minutes
  faster"; T4 then reports `unknown`), `--json`. **Never writes anything.**
- `tests/test_harvest_nudge.py` — 598 lines, 25 tests. The existing test shape to follow.
- `install.py` — `LINKS` symlinks `memory`, `skills`, `agents`, `commands`, `hooks`
  into `~/.claude/`. **`scripts` is NOT linked.**

## JSON contract (verified by running it)

`--skip-transcripts --json` emits `corpus_notes`, `directory_notes` (dict), `limits`
(`{"directory": 100, "corpus": 500}`), and a list of per-trigger objects each carrying
`trigger` (`t1-directory-size`, `t2-corpus-size`, `t3-unrouted-harvest`,
`t4-index-bypass`), `verdict` (`clear` / `FIRED` / `unknown`), `headline`, `detail`.
Confirm the exact top-level key for the trigger list by running it; do not assume.

## Measured timing

`--skip-transcripts --json`: **0.17 s** on the 12-note tree, **0.23–0.26 s** on the
556-note brain (min of 3 runs each). Acceptable for SessionStart. The full run
(transcript scan) is minutes and must never be invoked here.

## Conventions to match

- The hook's degradation discipline is absolute: **exit 0 always**, catch everything,
  fall through to the next reminder. A hook that raises breaks session start.
- `harvest_nudge.py` deliberately **does not import from `scripts/`** — it duplicates
  `PENDING_PREFIX` rather than importing it, with a test pinning both sides. Honour
  that boundary: invoke the trigger script as a **subprocess**, do not import it.
- Equally, do **not** re-implement the note count. The script's docstring insists the
  count come from `_wiki_common.iter_notes` so the reported and indexed numbers cannot
  drift; a second counter in the hook recreates exactly that drift.
- Tests live in `tests/`; `unittest`-style, runnable under `pytest`.

## Constraints and hazards

- **`scripts/` is not installed.** The hook runs from `~/.claude/hooks/` (a symlink to
  the repo's `hooks/`), so the framework root is reachable as
  `Path(__file__).resolve().parent.parent` — verify this resolves through the symlink
  rather than assuming it. If `scripts/check_memory_triggers.py` is not found there,
  **stay silent**; a copy-install or relocated framework must not produce an error line.
- **Memory root is the current repo's, not the framework's.** `rs.git_roots(cwd)[1] /
  "memory"`. If absent, stay silent — a repo with no brain has no triggers. Passing the
  framework's own `memory/` would report 12 notes in every repo and be worse than
  nothing.
- **Subprocess needs a timeout.** A pathological tree must not hang session start.
  On timeout, stay silent.
- **Return code 1 is success, not failure.** *(Corrected 2026-10-26 — this brief
  originally said "on timeout or non-zero rc, stay silent", which is wrong.)*
  `check_memory_triggers.py` defines `EXIT_PASS = 0`, `EXIT_FIRED = 1`,
  `EXIT_ERROR = 2`, so **the fired case is the non-zero-rc case** and the obvious
  reading would make this feature a no-op exactly when it has something to say.
  Accept rc in {0, 1}; treat only rc outside that pair as failure.
- The two harvest reminders are priority-exclusive because they concern the same
  subject. A fired trigger is a *different* subject, so it should print **in addition**,
  not instead. Collapsing them would repeat the failure class T3's `unknown` state was
  built to prevent.
- `t4-index-bypass` always reports `unknown` here by construction (transcripts skipped).
  It must never be rendered as a finding, and `unknown` must never read as `clear`.
- The hook's filename will understate its scope once it carries a third, unrelated
  reminder. **Do not rename it** — `install.py` wires it by name into each user's
  `~/.claude/settings.json` and a rename orphans every existing install. Widen the
  module docstring instead.

## External research

Skipped — no external surface. Entirely stdlib (`subprocess`, `json`, `pathlib`) against
this repo's own scripts, consistent with ADR 0001.

## Assessment

Extend `hooks/harvest_nudge.py` with one additional reminder that shells out to
`scripts/check_memory_triggers.py --memory-root <current repo>/memory --skip-transcripts
--json`, parses the verdicts, and prints at most a couple of lines naming fired triggers
and (optionally) a near-threshold one. Everything degrades to silence.

Rejected: importing the checks (violates the stated no-`scripts`-import boundary);
re-counting notes in the hook (recreates the drift the script exists to prevent); a
separate hook file (duplicates root resolution and needs its own `install.py` wiring for
one printed line).

## Open questions

- Whether to surface near-threshold proximity as well as FIRED, and at what fraction.
  The implementer should decide and justify; T1 at 95/100 is the live case that makes it
  non-academic. Keep total output to at most two lines either way.
