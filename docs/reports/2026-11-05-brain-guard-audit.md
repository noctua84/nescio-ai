# QA Audit Report: brain guard on the learning-loop write path

**Date:** 2026-11-05
**Auditor:** Pyrrho
**Scope:** Uncommitted working-tree changes on branch `feat/brain-guard-learning-scripts`
(base `f08e24d`): `scripts/_learning_common.py` (new `config_dir`, `git_common_dir`,
`check_brain`, `guard_brain`, `BRAIN_OVERRIDE_VAR`, `_GIT_ENV_OVERRIDES`) and the
guard wiring in `scripts/promote_learnings.py`, `scripts/begin_harvest.py`,
`scripts/compute_readiness.py`. `tests/test_brain_guard.py` and
`tests/test_promote_learnings.py` were read as secondary evidence only — both were
being edited concurrently during this audit, so claims about them are pinned either
to `HEAD` (`git show HEAD:<path>`) or to the working tree at the time of reading.
**Severity Summary:** 0 Critical | 1 Major | 7 Minor | 5 Info

## Executive Summary

The guard is sound in its central claim: the verdict model behaves as designed on
every configuration I could construct, the git-environment stripping is load-bearing
and demonstrably works, and no message any of the five verdicts can emit contains an
absolute path, a repository name, or a username — I constructed all five and scanned
the real strings. The refusal genuinely precedes the side effect in all three entry
points.

One Major defect: `git_common_dir` decodes git's output with the process locale and
then dereferences `result.stdout` unconditionally, so on a non-UTF-8 console with a
non-ASCII path in play it raises `AttributeError` out of `main()` instead of
degrading to `unknown` — a traceback where the design promises a verdict, in the one
function whose whole contract is "never fail, return `None`". The remaining findings
are narrower: one constructible false `brain` verdict (a non-git copy of the tree
nested inside the brain repository), an `unknown` downgrade reachable through a git
environment variable outside the stripped set, `begin_harvest --help` now exiting 2,
and a string-equality default check in `compute_readiness` that four equivalent
spellings of the default path slip past.

## Findings

### [MAJOR] `git_common_dir` raises instead of returning `None`, crashing all three entry points

**Category:** Bug
**File(s):** `scripts/_learning_common.py:175-192`
**Confidence:** [VERIFIED]
**Status:** New

**Description:**
`git_common_dir`'s docstring promises there is "no partial-credit result" and that
every failure yields `None`. Two gaps break that promise:

1. `subprocess.run(..., text=True)` is called with no `encoding=`/`errors=`, so
   git's output is decoded with the process locale encoding. Git emits paths as
   UTF-8 on every platform; a legacy Windows console locale (cp1252, cp932, …)
   cannot decode every UTF-8 byte sequence.
2. When that decode fails, `capture_output=True` raises *inside* subprocess's reader
   thread, `result.stdout` comes back as `None`, and `result.returncode` is `0` — so
   both guards above are passed and line 189 dereferences `None`.

`except (OSError, subprocess.TimeoutExpired)` does not catch it: `UnicodeDecodeError`
is a `ValueError`, and in any case the exception that reaches the caller is an
`AttributeError` raised after `subprocess.run` returned.

**Evidence:**
`scripts/_learning_common.py:175-192` (working tree):

```
175:        result = subprocess.run(
176:            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
177:            cwd=str(path),
178:            capture_output=True,
179:            text=True,
180:            env=env,
181:            timeout=10,
182:        )
183:    except (OSError, subprocess.TimeoutExpired):
...
187:    if result.returncode != 0:
188:        return None
189:    out = result.stdout.strip()
```

Reproduced against the working-tree module on this machine
(`locale.getencoding() = cp1252`, `sys.flags.utf8_mode = 0`), with a throwaway git
repo whose directory name contains U+7A81 (UTF-8 `E7 A2 81`; byte `0x81` is
undefined in cp1252). Redacted transcript:

```
locale.getencoding() = cp1252 | sys.flags.utf8_mode = 0
UnicodeDecodeError: 'charmap' codec can't decode byte 0x81 in position 57 ...
  (raised in Thread-N (_readerthread), subprocess.py -> encodings/cp1252.py)
git_common_dir RAISED: AttributeError 'NoneType' object has no attribute 'strip'
check_brain  RAISED: AttributeError 'NoneType' object has no attribute 'strip'
```

The repo already has an in-tree precedent for the correct call shape —
`scripts/module_gate.py:120-128`:

```
122:            ["git", *args],
123:            cwd=repo,
124:            capture_output=True,
125:            text=True,
126:            encoding="utf-8",
```

**Impact:**
On any machine whose configured brain path (or whose git-emitted diagnostic text)
contains a character whose UTF-8 form includes a byte undefined in the active ANSI
codepage, `check_brain` raises and all three entry points die with a traceback and a
stray thread exception — *including when run correctly inside the brain*. The whole
learning flow is blocked, and the override cannot rescue it: the override is only
consulted after both git calls (line 241). The failure direction is "no write", so
this is not a data-loss bug; it is a hard, inscrutable breakage in exactly the
locale this repository has been bitten in before (the `#55` cp1252 class of defect,
which has a whole test module, `tests/test_console_encoding_guard.py`). It also
violates the project instruction to follow existing patterns — `module_gate.py`
already shows the shape.

**Reproduction Steps:**
1. On Windows with a non-UTF-8 console locale (`locale.getencoding()` = cp1252),
   create `<tmp>/repo-突/`, `git init` it, commit a file, and create
   `<tmp>/repo-突/memory/`.
2. Point `CLAUDE_CONFIG_DIR` at an empty dir and symlink `<that dir>/memory` to
   `<tmp>/repo-突/memory`.
3. Call `_learning_common.check_brain(<some other git repo>)`.
4. Expected: verdict `mismatch` (or `unknown`). Actual:
   `AttributeError: 'NoneType' object has no attribute 'strip'`, plus a
   `UnicodeDecodeError` traceback from a subprocess reader thread.

**Recommended Fix:**
Add `encoding="utf-8", errors="replace"` to the `subprocess.run` call (git's output
is UTF-8; `errors="replace"` mangles both sides identically, so string equality still
holds), and make the function defensive about the promise it documents:

```
    if result.returncode != 0 or not result.stdout:
        return None
```

widening the `except` tuple to `(OSError, ValueError, subprocess.TimeoutExpired)` as
belt-and-braces. Note `hooks/record_stop.py:88-96` carries the same latent shape
(`text=True`, no `encoding=`) — pre-existing and out of scope here, but worth a
follow-up.

---

### [MINOR] A non-git copy of the tree nested inside the brain repository verdicts as `brain`

**Category:** Bug
**File(s):** `scripts/_learning_common.py:226-235`
**Confidence:** [VERIFIED]
**Status:** New

**Description:**
The comparison establishes "`repo_dir` and the brain's `memory/` belong to the same
git repository" — not "`repo_dir/memory` *is* the brain's `memory/`". If `REPO_DIR`
is a directory inside the brain's working tree that has no `.git` of its own (an
unzipped or `cp -r`'d copy of the framework tree, a vendored drop), git discovery
walks up and returns the brain's common dir for both sides, the verdict is `brain`,
and the guard prints nothing at all.

**Evidence:**
`scripts/_learning_common.py:226-235` (working tree):

```
226:        brain_key = git_common_dir(mem.resolve())
227:        repo_key = git_common_dir(repo_dir)
...
234:        if brain_key == repo_key:
235:            return "brain", []
```

Constructed against the working-tree module: brain repo with `memory/` symlinked from
`<config>/memory`, plus a plain directory `<brain>/vendor/framework/scripts/` holding
no `.git`:

```
A nested-non-git-copy -> brain
   common(nested) = <tmp>/brainrepo/.git        (identical to the brain's own key)
A2 nested-clone     -> mismatch                 (a real clone has its own .git)
B  submodule-of-brain -> mismatch               (common dir is .git/modules/sub)
```

**Impact:**
The original incident recurs in a narrower layout: notes are promoted into
`<brain>/vendor/framework/memory/`, and because dedup and contradiction resolution
read that same wrong tree, the pass's conclusions about memory are falsified in the
same direction as the incident. Likelihood is low — the common ways of getting a
second copy (`git clone`, `git worktree`) both produce a correct verdict, as measured
above — but the failure is silent, which is the direction the design treats as worst.

**Reproduction Steps:**
1. In a brain repository (`<config>/memory` resolves into it), create
   `<brain>/vendor/framework/` and copy `scripts/` into it without a `.git`.
2. Run `python <brain>/vendor/framework/scripts/promote_learnings.py <manifest>`.
3. Expected: refusal (the destination is not the brain's `memory/`). Actual: silent
   `brain` verdict; notes land under `<brain>/vendor/framework/memory/`.

**Recommended Fix:**
Add a second, cheap evidence channel before the common-dir comparison: if
`(repo_dir / "memory").resolve()` and `mem.resolve()` both exist and are not the
same path, that is positive evidence of a wrong destination even when the common
dirs agree. Keeping the common-dir comparison as the *fallback* preserves the
deliberate worktree allowance (a worktree of the brain has a different `memory/`
path but the same repo, so it would need the fallback to stay `brain`); the nested
copy fails both channels. If that is judged too clever, record the gap in the
docstring: the current check proves repository identity, not tree identity.

---

### [MINOR] `unknown` (warn-and-proceed) is reachable through git env vars outside the stripped set

**Category:** Bug
**File(s):** `scripts/_learning_common.py:133`, `scripts/_learning_common.py:228-233`
**Confidence:** [VERIFIED]
**Status:** New

**Description:**
`_GIT_ENV_OVERRIDES` strips the three variables that could force a false *match*.
It does not strip variables that make git decline to answer, and a `None` on either
side degrades a confirmed `mismatch` to `unknown` — warn on stderr, rc 0, proceed to
write. `GIT_CEILING_DIRECTORIES` does exactly that, as does removing git from `PATH`.

**Evidence:**
`scripts/_learning_common.py:133`:

```
133: _GIT_ENV_OVERRIDES = ("GIT_DIR", "GIT_COMMON_DIR", "GIT_WORK_TREE")
```

Measured against the working-tree module (same throwaway fixtures as above):

```
F no-ceiling nested -> <tmp>/brainrepo/.git
F ceiling nested    -> None
F ceiling verdict   -> unknown
```

and lines 228-233 turn either `None` into `unknown`:

```
228:        if brain_key is None or repo_key is None:
229:            return "unknown", [
230:                "warning: could not determine whether this repository is the"
```

**Impact:**
Design decision 6 deliberately rejects a boolean escape hatch because "an env var is
inherited silently by every subprocess, so a boolean exported once to unblock one
refusal would silence the guard for every repository in that shell session".
`GIT_CEILING_DIRECTORIES=<any ancestor>` is precisely that boolean: it does not name
a destination, it is inherited session-wide, and it converts the refusal into a
warning with rc 0 for every repository. The actor the design names as most likely —
an agent that just hit the refusal — can reach it. This cannot produce a false
`brain` (no silence), only a downgrade to a printed warning, which is why it is Minor
rather than Major.

**Reproduction Steps:**
1. Stand in a non-brain checkout; confirm `python scripts/begin_harvest.py` returns 2.
2. `export GIT_CEILING_DIRECTORIES=<an ancestor of both the checkout and the brain>`.
3. Re-run. Expected: still 2. Actual: `unknown` warning on stderr, rc 0, the harvest
   opens and writes `read.json`.

**Recommended Fix:**
Extend `_GIT_ENV_OVERRIDES` to `("GIT_DIR", "GIT_COMMON_DIR", "GIT_WORK_TREE",
"GIT_CEILING_DIRECTORIES", "GIT_DISCOVERY_ACROSS_FILESYSTEM")` — nothing in this flow
needs any of them, and the comment above the tuple already frames stripping as cheap
insurance. The residual (git absent from `PATH`) is inherent to the warn-on-no-
evidence policy and should simply be recorded as a known limitation.

---

### [MINOR] `begin_harvest.py --help` now exits 2 with a refusal and prints no help

**Category:** Regression
**File(s):** `scripts/begin_harvest.py:243-247`
**Confidence:** [VERIFIED]
**Status:** New

**Description:**
In `begin_harvest.main()` the guard runs *before* `argparse` is constructed, so every
invocation — including `--help` — is refused first. The other two entry points guard
*after* `parse_args`, so their `--help` still works.

**Evidence:**
`scripts/begin_harvest.py:243` is `    rc = guard_brain()`; line 247 is
`    ap = argparse.ArgumentParser(`. Compare `scripts/promote_learnings.py:1050`
(`    args = ap.parse_args()`) ahead of `:1066` (`    rc = guard_brain()`), and
`scripts/compute_readiness.py:644` (`    args = ap.parse_args(argv)`) ahead of
`:660` (`        rc = guard_brain(REPO_DIR)`).

Observed from this (non-brain) checkout:

```
$ python scripts/begin_harvest.py --help    -> rc=2, refusal text, no help
$ python scripts/promote_learnings.py --help -> rc=0, help
$ python scripts/compute_readiness.py --help -> rc=0, help
```

**Impact:**
An operator who lands in the wrong repo cannot read the tool's own documentation of
`--repo`/`--out`, which is part of how `commands/harvest-memory.md:112` expects scope
to be widened. It also makes the design's own seam rule inconsistent: decision 2
exempts an explicitly named destination (`compute_readiness --memory-root`), but
`begin_harvest --out <dir>` names its destination explicitly *and* makes `REPO_DIR`
unused for that run (`default_out_dir` is the only `REPO_DIR` consumer in `main`),
yet is still refused — and with the guard ahead of `parse_args` it cannot be
honoured.

**Reproduction Steps:**
1. From any checkout that is not the brain, run `python scripts/begin_harvest.py --help`.
2. Expected: argparse help, rc 0. Actual: the brain refusal, rc 2.

**Recommended Fix:**
Move the guard to immediately after `args = ap.parse_args(argv)` (line 263), matching
the other two entry points. Nothing between those points touches the destination
tree, so the "refusal precedes the side effect" property is preserved — the write is
`write_read(...)` further down. Whether `--out` should additionally exempt the run is
a design call worth stating explicitly either way.

---

### [MINOR] `compute_readiness`'s default detection is a raw string compare; four spellings of the default skip the guard

**Category:** Bug
**File(s):** `scripts/compute_readiness.py:636`, `scripts/compute_readiness.py:659-663`
**Confidence:** [VERIFIED]
**Status:** New

**Description:**
The guard fires only when `args.memory_root == str(DEFAULT_MEMORY_ROOT)`. Because
argparse hands back the raw string, any other spelling of the *same* default
destination compares unequal and skips the guard entirely.

**Evidence:**
`scripts/compute_readiness.py:636` and `:659-660`:

```
636:    ap.add_argument("--memory-root", default=str(DEFAULT_MEMORY_ROOT),
...
659:    if args.memory_root == str(DEFAULT_MEMORY_ROOT):
660:        rc = guard_brain(REPO_DIR)
```

Measured against the working-tree module:

```
exact default string   guard_fires=True  resolves_to_default=True
trailing separator     guard_fires=False resolves_to_default=True
forward slashes        guard_fires=False resolves_to_default=True
lowercased drive       guard_fires=False resolves_to_default=True
dot segment            guard_fires=False resolves_to_default=True
```

**Impact:**
This is the unsafe direction: a spelling the operator believes *is* the default
silently disables the check, and `--apply` then writes
`<memory_root>/repo/<name>/readiness.md` from a ledger read out of the same wrong
tree (`scripts/compute_readiness.py:314`, `:497`, `:543`). The relative form is the
sharpest case — `--memory-root memory` from a sibling checkout resolves against cwd,
names the wrong tree, and is unguarded. Conversely the check is noisy in the other
direction: an operator who deliberately passes the default path verbatim *does* get
the guard, contradicting the stated "an operator who names the destination has
stated it" rationale.

**Reproduction Steps:**
1. From a checkout that is not the brain, run
   `python scripts/compute_readiness.py --apply --memory-root "<that checkout>/memory/"`
   (note the trailing separator).
2. Expected: refusal, rc 2. Actual: rc 0; the readiness block is computed from, and
   written into, the non-brain tree.

**Recommended Fix:**
Detect "flag not given" exactly rather than by value: `default=None`, then
`if args.memory_root is None: rc = guard_brain(REPO_DIR); ...` and
`memory_root = DEFAULT_MEMORY_ROOT if args.memory_root is None else Path(args.memory_root)`.
If keeping the string default is preferred, compare resolved paths
(`Path(args.memory_root).resolve() == DEFAULT_MEMORY_ROOT.resolve()`), which closes
all four spellings above. Either way, add a test for one non-canonical spelling —
`tests/test_brain_guard.py`'s current pair covers only the exact default and a
genuinely different root.

---

### [MINOR] A dangling junction verdicts as `unknown`, not `broken`

**Category:** Bug
**File(s):** `scripts/_learning_common.py:214-224`
**Confidence:** [VERIFIED]
**Status:** New

**Description:**
`broken` is detected as `is_symlink() and not exists()`. On Windows,
`Path.is_symlink()` is `False` for a directory junction, so a *dangling* junction
falls through to `elif not mem.exists()` and is reported as "no brain is configured"
— warn and proceed.

**Evidence:**
`scripts/_learning_common.py:214` is `    if mem.is_symlink() and not mem.exists():`
and `:220` is `    elif not mem.exists():`. Measured on this machine (junction made
with `mklink /J`, then its target removed):

```
junction live:     is_symlink=False exists=True   -> verdict depends on the target
junction dangling: is_symlink=False exists=False  -> verdict unknown
```

**Impact:**
Exactly the state the design argues must refuse — "a brain was configured and has
since moved" — degrades to warn-and-proceed, leaving the incident re-runnable with a
success summary. Severity is held at Minor because `install.py` creates symlinks only
(`install.py:134`, `:183` use `Path.symlink_to`; there is no junction fallback), so
reaching this needs a hand-made link.

**Reproduction Steps:**
1. `mklink /J <config>\memory <some dir>`; delete `<some dir>`.
2. Run any guarded entry point from a non-brain checkout.
3. Expected: `broken`, rc 2. Actual: "no brain is configured", rc 0.

**Recommended Fix:**
Treat "a reparse point that does not resolve" uniformly, e.g.
`if (mem.is_symlink() or os.path.isjunction(mem)) and not mem.exists():`
(`os.path.isjunction` is 3.12+; the project floor is 3.13 per `requires-python`), or
widen the comment to record the junction case as knowingly out of scope.

---

### [MINOR] `<config>/memory` pointing at a file verdicts as `unknown`, not `broken`

**Category:** Bug
**File(s):** `scripts/_learning_common.py:225-233`
**Confidence:** [VERIFIED]
**Status:** New

**Description:**
If `<config>/memory` is a regular file, or a symlink to a file, `mem.exists()` is
`True`, so the code takes the `else` branch and passes a non-directory as
`subprocess.run(cwd=...)`. That raises `NotADirectoryError` (an `OSError`), which
`git_common_dir` converts to `None`, which becomes `unknown` — warn and proceed.

**Evidence:**
Measured against the working-tree module:

```
is_symlink True exists True is_file True
8 memory->file   -> unknown  ("could not determine whether this repository is the brain")
9 memory-is-file -> unknown
```

**Impact:**
Another "configured but broken" state reported as "unverifiable", with the same
consequence as the junction case: the refusal the design wants is downgraded to a
warning. Low likelihood (no code path in the repo creates it), so Minor.

**Reproduction Steps:**
1. `echo x > <config>/memory` (or symlink `<config>/memory` to a file).
2. Run a guarded entry point from a non-brain checkout.
3. Expected: a refusal. Actual: the generic "could not determine" warning, rc 0.

**Recommended Fix:**
Guard the `else` branch on `mem.is_dir()`: a `<config>/memory` that exists but is not
a directory is positively broken, not merely unverifiable, and belongs in the
`broken` branch (where the override still applies).

---

### [MINOR] The guard adds 18 warning lines to the canonical test-suite output

**Category:** Maintainability
**File(s):** `scripts/_learning_common.py:300-307` (`guard_brain` default stream),
`tests/test_begin_harvest.py:48-53`
**Confidence:** [VERIFIED]
**Status:** New

**Description:**
`tests/test_begin_harvest.py`'s `_run` redirects stdout only. Its fixtures point
`CLAUDE_CONFIG_DIR` at a temp dir with no `memory` entry, so every `main()` call now
emits the `unknown` warning to the real stderr.

**Evidence:**
```
$ PYTHONPATH=scripts python -m unittest tests.test_begin_harvest -v \
    2>&1 | grep -c "warning: no brain is configured"
18
```
(21 tests, all passing.) `tests/test_begin_harvest.py:50-52` redirects stdout alone:
`out = io.StringIO()` / `with contextlib.redirect_stdout(out):` / `rc = begin_harvest.main(argv)`.

**Impact:**
`python -m unittest discover` is the canonical command (`.github/workflows/tests.yml:35`)
and does not capture stderr, so CI logs and local runs gain 18 lines of noise. The
repo treats this as a real concern: `tests/test_console_encoding_guard.py:125-128`
records that "this suite's own stdout leak is pre-existing and tracked separately; a
new stderr leak from this test would not be". pytest hides it, which is why the
working tree looks clean under `pytest`.

**Reproduction Steps:** as the command above.

**Recommended Fix:**
Add `contextlib.redirect_stderr(io.StringIO())` to `_run` in
`tests/test_begin_harvest.py` (one line, no assertion changes). This is a test-file
change in a file the task scoped as secondary — flagged, not applied.

---

### [INFO] The guard makes three `main()`s environment-dependent, and CI cannot see it

**Category:** Maintainability
**File(s):** `scripts/_learning_common.py:212`, `tests/test_promote_learnings.py:878-897` (at `HEAD`)
**Confidence:** [VERIFIED]
**Status:** New

**Description:**
`check_brain` reads ambient state (`<config>/memory`) whenever a test does not
override `CLAUDE_CONFIG_DIR`. In CI there is no such entry, so the verdict is
`unknown` and the guard is inert; on a developer machine whose brain is a different
repository the same call returns `mismatch` and rc 2. The plan's load-bearing
measurement — "no existing test calls `promote_learnings.main()`" — is false:
`git show HEAD:tests/test_promote_learnings.py` line 893 is `            rc = pl.main()`,
inside `ConsoleEncodingTest._run_main`, which asserts `rc == 0` and inspects stdout.
On this machine `check_brain()` returns `mismatch` for this checkout, so that test
would have failed locally and passed in CI.

**Evidence:**
Verdict for this checkout under the real environment: `mismatch`
(`<config>/memory` is a symlink that resolves). The working tree already carries the
remediation — `git diff tests/test_promote_learnings.py` adds
`tempfile.TemporaryDirectory() as cfg` + `mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": cfg})`
to `_run_main`, with a comment explaining it. Full suite at the time of audit:
`1584 passed, 0 failed, 1 skipped`.

**Impact:**
No current failure. The durable hazard is that any *future* test exercising one of
these three `main()`s breaks only on machines where the checkout is not the brain —
a failure CI structurally cannot reproduce. Worth one line in the `guard_brain`
docstring ("a test that calls one of these `main()`s must pin `CLAUDE_CONFIG_DIR`")
next to the existing note about stdout assertions.

**Recommended Fix:** docstring note as above; optionally a module-level
`CLAUDE_CONFIG_DIR` fixture for the entry-point test modules.

---

### [INFO] `casefold()` is applied unconditionally, including on case-sensitive filesystems

**Category:** Bug
**File(s):** `scripts/_learning_common.py:192`
**Confidence:** [VERIFIED]
**Status:** New

**Description:** `return out.replace("\\", "/").casefold()` normalises case on every
platform. On a case-sensitive filesystem two distinct repositories whose paths differ
only in case compare equal, yielding a false `brain`. Contrived enough to be an
observation rather than a defect; if it is cheap, case-fold only on
`os.name == "nt"` / `sys.platform == "darwin"`.

---

### [INFO] The override value is compared without stripping whitespace

**Category:** Bug
**File(s):** `scripts/_learning_common.py:241-242`
**Confidence:** [VERIFIED]
**Status:** New

**Description:** `override.casefold() == repo_dir.name.casefold()` — a value carrying
a trailing space or newline (easy to produce from a shell or a CI variable) silently
does not match, and the operator sees the refusal again with no hint why. The failure
direction is safe (refuse), so this is a usability note only; `.strip()` on the
environment value would close it.

---

### [INFO] Accepting any worktree of the brain accepts a destination tree that is not `<config>/memory`

**Category:** Bug
**File(s):** `scripts/_learning_common.py:226-235`
**Confidence:** [INFERRED]
**Status:** New

**Description:**
Comparing `--git-common-dir` is deliberate and correct for the stated goal (the
brain's own worktrees must not trip the guard) — measured: a `git worktree add` of the
brain verdicts `brain`, and its key is byte-identical to the main checkout's. The
consequence not recorded anywhere is that in that case the promotion's destination
(`<worktree>/memory`) is a *different tree* from the one `<config>/memory` resolves
to. If the worktree sits on a branch that predates recent promotions, the ledger read
for dedup and contradiction resolution is stale, which is a weakened form of the
incident's "conclusions wrong in the same direction" failure. Accepted-risk, not a
defect; worth a sentence in the module docstring so a later reader does not have to
re-derive it.

---

### [INFO] Positive verifications worth recording

**Category:** Bug
**File(s):** `scripts/_learning_common.py:169-192`
**Confidence:** [VERIFIED]
**Status:** New

Measured, not assumed — each of these is a hypothesis from the audit brief that the
implementation survives:

- **The env stripping is load-bearing and works.** With `GIT_DIR`, `GIT_COMMON_DIR`
  and `GIT_WORK_TREE` all exported at a third repository, an unstripped
  `git rev-parse --git-common-dir` run inside the brain's `memory/` returns that
  third repository's `.git` — the silent false MATCH the comment at
  `scripts/_learning_common.py:126-132` predicts. `check_brain` under the same
  environment still returns `mismatch`.
- **`subst` drives and symlink chains do not cause a false mismatch.**
  `Path.resolve()` canonicalises through both; a `subst` alias of the brain verdicts
  `brain`, and a two-hop symlink chain verdicts `brain`/`mismatch` correctly.
- **Submodules and nested clones verdict `mismatch`.** A submodule's common dir is
  `<super>/.git/modules/<name>`; a nested clone has its own `.git`. Both refuse
  (false-refusal direction, with the override as the remedy).
- **`GIT_OBJECT_DIRECTORY` / `GIT_ALTERNATE_OBJECT_DIRECTORIES` do not skew the
  comparison**; neither does a bogus `GIT_CONFIG_GLOBAL`.
- **Leak audit is clean.** All five verdicts were constructed and their real strings
  inspected: the only path-like token any message contains is the literal
  `~/.claude/memory`; no absolute path, no drive letter, no repository basename, no
  username. The one informational filename is `install.py`.
- **`mark_harvested.py` / `unmark_harvested.py` need no guard**, confirming the
  plan's scoping: they write watermarks under `<config>/learning-trail`, and
  `commands/harvest-memory.md` invokes no other script that writes into the
  destination tree.

**Residual question (unresolved):** whether git config injected through
`GIT_CONFIG_COUNT`/`GIT_CONFIG_KEY`/`GIT_CONFIG_VALUE` can redirect
`--git-common-dir`. I found no such config key, but I did not exhaust git's config
surface, so I am recording it rather than asserting either way. `[UNVERIFIED]` —
resolved by a read of git's `setup.c` discovery path or a targeted experiment.

---

## Regression Check Results

| Feature/Contract | Status | Notes |
|-------------------|--------|-------|
| `begin_harvest.main()` "Always returns 0" docstring | Pass | Rewritten in the same diff (`scripts/begin_harvest.py:215-220`) to document rc 2; no stale promise left. |
| ADR 0003 point 4, "refusing to stamp is not failing" (rc 0) | Pass | Scoped to `mark_harvested._refuse` (ADR line 151-155, `scripts/mark_harvested.py`), which is untouched. The ADR's rejected-option row that argues against a hard non-zero rc reasons from "by step 8 the notes, the ledger and the readiness updates are already on disk" — the opposite of `begin_harvest`, which is step 1 with nothing on disk yet. No contradiction. |
| `mark_harvested.py` consuming `begin_harvest` output | Pass | Consumes `read.json` via `--read`, not the rc or stdout of `begin_harvest`; a refused harvest writes no `read.json` at all. |
| `hooks/harvest_nudge.py` | Pass | Mentions `begin_harvest.py` in comments only (`:133`, `:154`); never invokes it. |
| Any non-test caller of the three entry points | Pass | No `import`/`subprocess` invocation anywhere in `scripts/`, `hooks/`, `docs_site/` or `.github/workflows/`; the only call sites are `commands/harvest-memory.md` steps 1, 7 and 8 (operator-run). |
| stdout shape of the three entry points | Pass | `guard_brain` defaults to stderr (`scripts/_learning_common.py:304-306`); `tests/test_brain_guard.py` pins stdout empty on both a warning and a refusing verdict. |
| stderr consumers | Pass | No consumer or test parses these scripts' stderr. See the Minor finding on new stderr noise in the unittest runner. |
| `--help` on the three entry points | **Fail** | `begin_harvest.py --help` now returns 2 and prints no help (Minor finding above). The other two are unaffected. |
| Full test suite | Pass | `1584 passed, 0 failed, 1 skipped` (pytest) at the time of audit; `tests.test_begin_harvest` 21/21 and `tests.test_brain_guard` pass under the canonical unittest command too. |
| `scrub_check.py` | Pass | `scrub: clean (baseline + no custom terms)`. Note it WARNed on pre-existing home paths in two older `docs/reports/` files and still exited clean — confirming the design's premise that the no-path discipline has no mechanical backstop. |
| Module tripwire | Pass | `scripts/_learning_common.py` is 307 lines, under the 400-line default. `promote_learnings.py` (1098) and `compute_readiness.py` (700) were already over and need their `Module-check:` acks, as the plan states. |
| Brain memory for this repo | Pass (no evidence) | `~/.claude/memory/repo/<this repo>/` holds four notes (CI/metadata/merge-commit/readiness) and no note about the learning loop or a prior guard failure mode, so there is nothing recorded for this change to reintroduce. |

## Recommendations

Priority order:

1. **Fix `git_common_dir`'s decoding and its `None` dereference** (Major). Add
   `encoding="utf-8", errors="replace"`, test `result.stdout` for falsiness, widen the
   `except` to include `ValueError`. Add a test that the function returns `None`
   rather than raising when `stdout` cannot be decoded — the existing
   `test_none_on_timeout` / `test_none_when_git_is_not_on_path` pair shows the shape.
2. **Make `compute_readiness`'s default detection exact** (`default=None` sentinel, or
   compare resolved paths), and cover one non-canonical spelling in the tests. This is
   the only finding that silently skips the guard in the unsafe direction by operator
   typing alone.
3. **Move `begin_harvest`'s guard after `parse_args`** so `--help` works and the three
   entry points are consistent; decide explicitly whether `--out` exempts the run.
4. **Add `GIT_CEILING_DIRECTORIES` (and `GIT_DISCOVERY_ACROSS_FILESYSTEM`) to
   `_GIT_ENV_OVERRIDES`**, and record in the docstring that `unknown` remains
   reachable by removing git from `PATH` — a known limit of warn-on-no-evidence.
5. **Fold "exists but is not a directory" into `broken`**, and either handle dangling
   junctions or document them as out of scope.
6. **Redirect stderr in `tests/test_begin_harvest.py::_run`** to keep the canonical
   unittest output clean.
7. **Docstring additions** (no behaviour change): the comparison proves repository
   identity, not tree identity (nested-copy and stale-worktree consequences); and a
   test that calls one of these `main()`s must pin `CLAUDE_CONFIG_DIR`.

Nothing here argues against landing the change. The guard closes the incident it was
written for — the incident's own configuration lands squarely in `mismatch` and
refuses, which I verified by construction — and findings 2 through 7 are narrowing
work on top of a correct core.

## Files Reviewed

- `scripts/_learning_common.py` (working tree and `git diff`)
- `scripts/begin_harvest.py`, `scripts/promote_learnings.py`, `scripts/compute_readiness.py`
- `scripts/module_gate.py` (subprocess decoding precedent), `hooks/record_stop.py` (same)
- `install.py` (symlink creation, `can_symlink` probe)
- `hooks/harvest_nudge.py`, `scripts/mark_harvested.py` (consumer check)
- `commands/harvest-memory.md`
- `memory/repo/nescio/adr/0003-learning-loop-write-path-verified.md`
- `.sisyphus/plans/brain-guard.md`
- `tests/test_brain_guard.py`, `tests/test_begin_harvest.py`,
  `tests/test_compute_readiness.py`, `tests/test_console_encoding_guard.py`,
  `tests/test_promote_learnings.py` (at `HEAD` and working tree), `conftest.py`
- `.github/workflows/tests.yml`
- `CLAUDE.md`, `~/.claude/memory/repo/<this repo>/` (no relevant notes)
