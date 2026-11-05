# Plan: brain guard for the learning-promotion scripts

## Objective

Make "run this in the brain" mechanical rather than remembered. The brain is
whichever repository `<config>/memory` resolves into. On a confirmed mismatch the
learning-loop entry points refuse; when the discriminator cannot be evaluated
they warn and proceed.

## Design decisions

### 1. A function the entry points call — not an import-time check

`_learning_common.py` is imported by four scripts and, transitively, by seven
test modules. An import-time check would fire in every one of them, including
hundreds of tests that legitimately promote into a temp tree, and the only way to
make the suite green would be to weaken the guard. That is the signal the task
warns about.

The decisive measurement: **no existing test calls `promote_learnings.main()`,
and all 57 promote call sites in the suite call `pl.promote(..., repo_dir=tmp)`
directly.** The guard therefore lives at the CLI boundary — where the real
incident happened — and the unit-level API stays free of it. Zero existing tests
need an opt-out.

It is also the correct seam on the merits: `promote()` takes `repo_dir` as a
parameter, so a caller that passes one has already stated its destination
explicitly. The thing that needs guarding is the *implicit* default, and `main()`
is the only place that relies on it.

Verified: every non-test invocation in the repo is a CLI call
(`commands/harvest-memory.md` steps 1 and 6). There is no programmatic caller to
bypass `main()`.

### 2. Three call sites

- `promote_learnings.main()` — the write path, and the one the incident went
  through. Refusal here is the point of the change.
- `begin_harvest.main()` — step 1, the earliest catch. It writes
  `REPO_DIR/eval/learnings/<stamp>` and prints a `next:` line naming the
  promoter, so a harvest opened in the wrong repo sends the operator onward with
  a wrong-tree manifest path.
- `compute_readiness.main()` — **guarded too, on correction.** An earlier draft
  of this plan excluded it as "read-only". That was false, and the measurement
  that disproves it: `--apply` writes `memory/repo/<name>/readiness.md`
  (`apply_plan`, line 543; path built at line 497), it reads
  `<memory_root>/learning-log.md` through the same `parse_ledger` (line 314), and
  `commands/harvest-memory.md:270` runs it **with `--apply`** as a flow step
  between promote and mark_harvested. So it is the second half of the same
  incident: readiness numbers derived from the wrong ledger, written into the
  wrong tree. The "module-gate cost" argument was wrong too — a `Module-check:`
  ack is one line of PR body per file, and the PR already carries one.

  One refinement, corrected during implementation: `compute_readiness` accepts
  `--memory-root`, so the first draft of this paragraph said the guard fires
  **only when that argument is left at its default** — an operator who names the
  destination has stated it explicitly, the same seam rule that keeps the guard
  out of `promote(repo_dir=...)`. The task-5 test bullet below ("`compute_readiness`
  with an explicit `--memory-root` does not fire") pins exactly that reading, and
  on its own the two are consistent.

  The contradiction is between that reading and the incident this guard exists to
  prevent. "An operator who names the destination has stated it explicitly" was
  read as "supplied the flag at all", but `--memory-root memory`, run from a
  non-brain checkout, resolves relative to `cwd` to that wrong checkout's own
  `memory/` tree — the exact wrong-destination incident — and under the
  flag-presence reading the guard stayed silent, because *a* flag was given, even
  though it did not name a different destination from the implicit default. The
  seam rule's symmetry with `promote(repo_dir=...)` (a parameter, once passed, is
  always a statement) does not transfer cleanly to a CLI flag whose value can
  *accidentally* spell out the same default it would have used anyway.
  Implementation resolved this in favour of safety over that symmetry: the guard
  now fires whenever the effective `--memory-root` — defaulted or spelled out,
  resolved via `Path.resolve()` and compared case/separator-insensitively via
  `os.path.normcase()` — is this checkout's own default tree, and is skipped only
  when the resolved value is a genuinely *different* tree. See the comment above
  the guard call in `compute_readiness.main()` for the implementation, and
  `tests/test_brain_guard.py`'s
  `test_compute_readiness_default_spelling_variants_all_fire_the_guard` (renamed
  from `..._all_skip_the_guard`, its assertion inverted on purpose) for the
  regression coverage.
- `mark_harvested.py` — correctly out of scope: it has no `REPO_DIR` at all and
  writes to `<config>/learning-trail`, so it is brain-independent.

### 3. Four verdicts

| Evidence | Verdict | Behaviour |
|---|---|---|
| Both sides resolve to git repos, common-dirs equal | `brain` | silent, proceed |
| Both resolve, common-dirs differ | `mismatch` | refuse, rc 2 |
| `<config>/memory` is a symlink that does not resolve | `broken` | refuse, rc 2 |
| Anything else unresolvable | `unknown` | loud warning, proceed |

`unknown` covers: no `<config>/memory` entry; it resolves outside any git repo (a
consumer who copied the tree instead of linking it); git missing or erroring;
`REPO_DIR` not in a git repo. There is no evidence of a wrong destination in any
of those, so none of them may hard-fail.

`broken` is split out of `unknown` on correction. A **dangling** symlink means
`install.py` ran and the brain has since moved, or a Windows relink failed
without Developer Mode (`install.py:144-200` goes to real trouble over exactly
this state, which is how we know it occurs). That is a *configured but broken*
brain, not an absent one — and lumping it into warn-and-proceed leaves the
original incident re-runnable with a success summary. Detected as
`is_symlink() and not exists()`, which is precisely distinguishable from "no
`memory` entry at all". The temp-dir fixtures in `tests/test_begin_harvest.py`
have no `memory` entry, so they stay in `unknown` and keep asserting rc 0.

This is the load-bearing claim: **the incident lands in `mismatch`, not
`unknown`.** The operator's symlink was valid and resolvable and the sibling
checkout was a real git repo, so both sides resolve, the common-dirs differ, and
the guard refuses.

### 4. Compare `--git-common-dir`, with the git environment stripped

`git rev-parse --path-format=absolute --git-common-dir` returns the identical
`.git` path from a worktree and from its main checkout (verified on this
machine); `--show-toplevel` differs per worktree. Comparing common-dirs is what
keeps the brain's own worktrees out of the `mismatch` branch. Compared as
case-folded posix strings, following `_trail_scope.py`'s normalisation
precedent — git emits forward slashes, `pathlib` emits backslashes, and Windows
paths differ in case.

**Both calls run with `GIT_DIR`, `GIT_COMMON_DIR` and `GIT_WORK_TREE` removed
from the environment.** Inherited, they would pin both invocations to the same
answer regardless of cwd — a silent *match*, which is the one failure direction
where the guard confidently blesses a wrong destination. Nothing in this repo
sets them, so this is cheap insurance rather than an observed bug, and the
docstring says so because the stripping is otherwise inexplicable.

Any non-zero git exit, missing binary, or empty output degrades to `unknown`.
`--path-format=absolute` needs git >= 2.31; an older git errors, which is
`unknown`, not a refusal. Residual normalisation gaps (8.3 short names, `subst`
drives, junctions, UNC vs drive-letter) fail toward a false `mismatch`, i.e.
toward refusing — the override is the remedy, and that is the safe direction.

### 5. The messages name no paths

The guard's own output is the system's most prolific producer of
brain-identifying strings, and this repository is public. `scrub-terms.local` is
gitignored and absent here (so it never runs in CI), and the baseline
home-path pattern is WARN, not FAIL — so a pasted path has no mechanical
protection. Agents routinely paste a blocked run's stderr into `.sisyphus/`
notes, PR bodies and issue comments, all of which are tracked.

So the refusal prints **no absolute path and no repository name** — not even
basenames, since the brain's basename *is* the identifying string. It prints the
verdict and the one command that recovers the answer locally:

    readlink -f ~/.claude/memory

mirroring `commands/harvest-memory.md:58-62`. The operator learns where to go by
running it; nothing quotable into a tracked file is ever emitted. The docstring
records this as deliberate, so a later reader does not "improve" the diagnostics
by adding the paths back.

### 6. One escape hatch, and it names its destination

`NESCIO_LEARNING_ALLOW_NON_BRAIN=<basename of the intended repo dir>` downgrades
`mismatch` or `broken` to a loud warning naming the override.

**The value must equal `REPO_DIR.name`, or it does nothing.** A bare `=1` is not
an override. This is the fix for the real failure mode: an env var is inherited
silently by every subprocess, so a boolean exported once to unblock one run
would silence the guard for every repo in that session — and the actor most
likely to export it is an agent that just hit the refusal. Requiring it to name
its destination means a stale export cannot bless a different repository.

A single mechanism, not an env var *and* a flag: two spellings of one override
double the surface and the docs for nothing. The env var is also the form a test
and a scripted consumer can both use, and `scripts/` is mirrored downstream.

Deliberately **not** done: recording the override in `write_receipt`. The
receipt is versioned and `mark_harvested.check_receipt` matches on that version,
so changing its shape risks a compatibility break well outside this change.
Carried as a follow-up finding instead.

## Tasks

1. **`scripts/_learning_common.py`** — add `config_dir()`, `brain_common_dir()`,
   `check_brain(repo_dir) -> (verdict, lines)` and `guard_brain(repo_dir) -> int`.
   Four verdicts per decision 3; git env stripped per 4; no paths in messages per
   5; override predicate per 6. Docstring prose for each non-obvious choice.
   **Complexity: standard.** Placement: `inline`.
2. **`scripts/promote_learnings.py`** — guard at the top of `main()`, after the
   stdout reconfigure, before the manifest read. **Complexity: simple.**
3. **`scripts/begin_harvest.py`** — same, at the top of `main()`.
   **Complexity: simple.**
4. **`scripts/compute_readiness.py`** — guard in `main()`, fired only when
   `--memory-root` was left at its default. **Complexity: simple.**
5. **`tests/test_brain_guard.py`** — new module. Cases: match; a worktree of the
   brain matches; confirmed mismatch refuses; dangling symlink refuses; no
   `memory` entry warns and proceeds; `memory` as a real dir outside git warns;
   git failure warns; inherited `GIT_DIR` does not force a false match; bare `=1`
   does **not** override; correct-basename override downgrades and logs;
   `CLAUDE_CONFIG_DIR` honoured over `~`; no message contains an absolute path or
   a repo name; all three entry points refuse end-to-end; `compute_readiness`
   with an explicit `--memory-root` does not fire. **Complexity: standard.**
6. **Verify** — full suite (baseline 1558, green), ruff `E9,F`, `module_gate.py`,
   `scrub_check.py`.

## Constraints carried into every task

- PUBLIC repo: no private repository name, absolute filesystem path, client name
  or hostname in any file, test, commit message or PR body. `scrub_check.py` is
  the mechanical check.
- Portable: no assumption that brain and framework are the same checkout, that a
  symlink exists, or that git is present.
- `promote_learnings.py` (1089 lines) and `compute_readiness.py` (690 lines) are
  both over the 400-line tripwire, so the PR body carries a `Module-check:` ack
  for each from the moment it is opened.
- The guard's runtime output is a leak channel in its own right (decision 5): no
  absolute path and no repository name in any message, and none in test
  assertions either.
