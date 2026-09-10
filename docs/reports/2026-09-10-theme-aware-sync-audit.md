# QA Audit Report: Theme-aware overlay sync (#133) and residue check (#137)

**Date:** 2026-09-10
**Auditor:** Pyrrho
**Scope:** Branch `fix/theme-aware-sync-plan`, `origin/main...HEAD` (three-dot).
`BASE_SHA` = `d605033f4de57e23376e3f636d82e73490e5549b`, `HEAD_SHA` = `0400e3138feace30044cdb9d43ec7b75cc488e0f`.
Production: `scripts/sync_from_upstream.py`, `scripts/_theme_common.py`, `scripts/apply_theme.py`.
Tests: the eight new `tests/test_*theme*.py` modules. Docs: `README.md`, `ROADMAP.md`, the plan.
**Severity Summary:** 0 Critical | 3 Major | 5 Minor | 5 Info

All line numbers below are at `HEAD_SHA` unless marked `BASE`. Every finding marked
"verified by execution" was reproduced with a throwaway script in the session scratchpad
against this worktree's code; nothing under audit was modified. Suite: 839 OK.

## Executive Summary

The materialisation design does what the plan claims: `plan_sync` / `apply_sync` / `_files_equal`
are untouched, the untheme'd path is byte-identical to `BASE` (verified differentially across
crewless/functional x dry/diff/apply), the temp root spans plan -> diff -> apply and is cleaned on
both exits, renderer output is captured, and deletion mirroring survives the render. No finding
here is a bug in the set-difference itself.

The three Major findings are all at the *edges* of the new guard logic: (1) a foreseeable upstream
change — a new `builder-<tier>` charter, or any charter whose stem embeds a mapped roster word —
locks every themed instance out of syncing permanently, because #137's residue check and P2's
refusal compose into a refusal that also blocks delivery of the `_crew_common.py` that would fix
it; (2) `desynced_agents` now runs on every path and decodes every `agents/*.md` as strict UTF-8,
so one non-UTF-8 file in a dest crashes the sync where `BASE` produced a plan — a P1 regression;
(3) a themed dest that has lost only its representative (`plato.md`) classifies as crewless and
gets the silent 11/3/10 destructive plan this change exists to prevent. None blocks the merge on
its own — each has a workaround and (3) is plan-sanctioned — but (1) and (2) deserve fixes before
the first themed instance syncs on this code.

## Findings

### [MAJOR] Upstream adding a charter whose stem embeds a mapped word locks themed instances out of sync permanently

**Category:** Bug (design interaction: #137 residue check x P2 refusal x R8 one-pass-behind)
**File(s):** `scripts/sync_from_upstream.py:792-809`, `scripts/apply_theme.py:248-258`, `scripts/sync_from_upstream.py:101-105` (docstring claim)
**Confidence:** [VERIFIED] — verified by execution
**Status:** New

**Description:**
`_crew_common.TIERED_AGENTS` is an existing extension point (`builder-simple`, `builder-standard`).
If upstream adds a tier — `agents/builder-fast.md` plus `"fast"` in `TIER_VARIANTS` — a themed
instance materialises upstream with its *own* (old) `_crew_common`, so the renderer rewrites the
new charter's `name: builder-fast` to `name: archimedes-fast` (word-boundary match on `builder`)
but has no rename entry for the file. After #137 the residue check runs on every pass and returns 2;
P2 turns that into a full refusal *before anything is applied*, so the `scripts/_crew_common.py`
that would resolve it is never delivered. Pass 2 fails identically. The same holds for any
`<roster-word>-<suffix>.md` upstream might add (`reviewer-lite.md`, `planner-v2.md`).

The module docstring asserts the opposite for this shape of change.

**Evidence:**
`scripts/sync_from_upstream.py:794` — `        if rc != 0:` -> `:809` — `            return 2`
(refusal precedes both `apply_sync` calls at `:854-855`).
`scripts/apply_theme.py:248` — `    residue = [] if dry_run else desynced_agents(agents_dir)` and
`:258` — `        return 2`.
`scripts/sync_from_upstream.py:102-105` — `Consequence, stated so it is a chosen property: a pair *added*
upstream, or *retargeted* upstream (say ``doc-writer`` -> ``quintilian`` replacing ``cicero``),
converges only on a later pass`.

Execution (scratchpad `exp4.py`: real `agents/` copied, upstream gains `builder-fast.md` and
`TIER_VARIANTS = ("simple", "standard", "fast")`, dest themed philosophers):
```
themed dest sync, pass 1:  rc 2
  stderr: error: could not render upstream's crew (...) into the 'philosophers' theme ... the pass ran, but 1 file(s) still declare a `name:` ...
  dest _crew_common delivered? False
themed dest sync, pass 2:  rc 2
```

**Impact:**
Every themed downstream instance is hard-locked out of *all* framework updates (hooks, scripts,
tests, security fixes) from the moment upstream ships such a charter until the operator intervenes
by hand. The refusal text quotes `apply_theme`'s remediation — "Edit the frontmatter (or the
filename) by hand so the two agree ... re-running will not help" — about a temp directory that no
longer exists, so the operator is not told what to actually do.

**Reproduction Steps:**
1. Copy the repo's `agents/` into `up/agents` (functional) and `dst/agents`, theme `dst` philosophers.
2. In `up/agents` add `builder-fast.md` (copy of `builder-simple.md` with the name swapped).
3. `python scripts/sync_from_upstream.py --upstream up --dest dst --apply`.
4. Expected: plan delivered, or at least the non-agents half; actual: exit 2, nothing written,
   identical on every re-run.

**Recommended Fix:**
Any one of: (a) in the themed branch, treat *residue* (as opposed to a rename collision or an
unclassifiable crew) as a warning naming the affected upstream file(s) and proceed — the rendered
tree is complete, one charter merely does not load, which is exactly the state `desynced_agents`
warns about on the dest side; (b) keep P2 strict but print an accurate remediation in `main()`
("upstream ships `builder-fast.md`, which this instance's theme roster cannot express; run
`apply_theme.py functional`, sync, then `apply_theme.py philosophers`" — verified to work); (c) at
minimum, correct the docstring paragraph at `:101-108` so the deadlock is a stated property. Add a
test that seeds a new `builder-<tier>.md` upstream and pins whichever behaviour is chosen.

---

### [MAJOR] P1 regression: `desynced_agents` on every path crashes the sync on a non-UTF-8 (or directory) `agents/*.md` in dest

**Category:** Regression
**File(s):** `scripts/sync_from_upstream.py:685`, `scripts/_theme_common.py:243-244`
**Confidence:** [VERIFIED] — verified by execution
**Status:** New

**Description:**
`5d4c825` moved the desync warning above the classification, so `desynced_agents(dest / "agents")`
now runs unconditionally — including on the untheme'd path that P1 promises is "literally today's
code". It reads every top-level `*.md` with `encoding="utf-8"` and no error handling. A Latin-1
notes file, a directory named `something.md`, or an unreadable file in `dest/agents` raises out of
`main()` as a traceback. `BASE` produced a plan for the same tree (the stray file is simply listed
under `- delete`, which is the correct answer).

**Evidence:**
`scripts/sync_from_upstream.py:685` — `    desynced = desynced_agents(dest / "agents")`
`scripts/_theme_common.py:243` — `    for md in sorted(agents_dir.glob("*.md")):`
`scripts/_theme_common.py:244` — `        block = _frontmatter_block(md.read_text(encoding="utf-8", newline=""))`

Execution (scratchpad `exp1.py`, crewless dest with `agents/notes.md` = `b"caf\xe9 notes\n"`):
```
HEAD: EXCEPTION on untheme'd path: UnicodeDecodeError 'utf-8' codec can't decode byte 0xe9 ...
BASE: rc = 0 / would change: 1 added, 0 updated, 1 deleted / - delete agents\notes.md
```
Execution (scratchpad `exp2.py`, directory `dir.md` inside agents/):
`dir.md -> PermissionError [Errno 13] Permission denied`.

**Impact:**
An instance that could sync yesterday cannot sync today, on every path, until it removes the file;
the failure is an uncaught traceback rather than a plan entry. Likelihood is low (the file is
already doomed to deletion by the overlay) but the promise broken is the one the plan calls a
REQUIREMENT.

**Reproduction Steps:**
1. Crewless or functional dest; write `dest/agents/notes.md` with bytes `caf\xe9`.
2. Dry-run sync. Expected (BASE behaviour): plan listing `agents/notes.md` under delete.
3. Actual: `UnicodeDecodeError` traceback, exit 1.

**Recommended Fix:**
In `desynced_agents`, guard the read: `try: text = md.read_text(...) except (OSError,
UnicodeDecodeError): continue` (a file that cannot be read as UTF-8 text is not a charter, by the
same argument the a935f97 commit makes for a frontmatter-less file), or catch in `main()` and
downgrade to a warning. Pin with a test in `tests/test_sync_theme_guards.py` (untheme'd dest, one
binary `.md`, expect BASE's plan and empty stderr) and one in `tests/test_theme_common.py`.

---

### [MAJOR] A themed dest missing only its representative (`plato.md`) gets the silent destructive plan

**Category:** Bug (plan-sanctioned edge; premise of decision 4 is false)
**File(s):** `scripts/sync_from_upstream.py:642`, `:718`, `scripts/_theme_common.py:124-127`
**Confidence:** [VERIFIED] — verified by execution
**Status:** New

**Description:**
Classification is by a single representative file. A themed instance whose operator removed
`agents/plato.md` (does not use the planner, archived it, renamed it to something custom) has zero
representatives, `detect_theme` returns `None`, the tree is internally self-consistent so
`desynced_agents` is `[]`, and `main()` takes the untheme'd branch: eleven functional charters
added, ten philosopher charters deleted, three updated — no warning, no theme line. This is the
exact 11/x/11 phantom plan #133 exists to remove, produced for a tree that is unmistakably themed
(ten philosopher-named charters on disk). The plan's decision 4 equates "zero representatives" with
"a fresh or crewless instance"; that equivalence does not hold.

**Evidence:**
`scripts/sync_from_upstream.py:642` — `    theme = detect_theme(dest / "agents")`
`scripts/sync_from_upstream.py:718` — `    if theme in (None, "functional"):`
`scripts/_theme_common.py:125-127` — `    if len(found) == 1:` / `        return next(iter(found))` / `    return None`

Execution (scratchpad `exp7.py`: real crew, dest themed, then `dst/agents/plato.md` unlinked):
```
rc 0
STDERR: ''
would change: 11 added, 3 updated, 10 deleted
```

**Impact:**
Silent, fully destructive plan on a themed tree; `--apply` converts the instance back to functional
and deletes ten philosopher charters. Operator-induced precondition, but a plausible one, and the
outcome is the class of failure the docstring calls "a safety problem, not a cosmetic one".

**Reproduction Steps:**
1. Themed dest in step with a functional upstream (contract fixture).
2. Delete `dest/agents/plato.md`.
3. Dry-run. Expected: a refusal or at least a warning that ten philosopher charters are on disk with
   no representative. Actual: silent 11/3/10.

**Recommended Fix:**
Cheap, no renderer import: when `theme is None`, check whether any file in `dest/agents` is named
after the *other* theme's roster (`renamed_agents` is in `_crew_common`, already on the path, or
just the two representative stems plus `THEME_INVARIANT_ROSTER` complement). If so, refuse with the
same shape as the both-representatives guard ("the crew is themed but its representative is
missing — restore `agents/plato.md` or run `apply_theme.py functional`"). Pin with a guards test.
If the team prefers to keep decision 4 verbatim, record this case explicitly in the plan and the
docstring as accepted.

---

### [MINOR] `_frontmatter_block` now silently ignores genuinely broken charters (unterminated fence, BOM, no trailing newline)

**Category:** Regression
**File(s):** `scripts/_theme_common.py:76`, `:146-147`, `:245-246`
**Confidence:** [VERIFIED] — verified by execution
**Status:** New

**Description:**
`a935f97` correctly stops reporting frontmatter-less docs, but the "no block" answer is now taken
for *any* regex miss, including files that clearly intend to be charters and do not load: an
opening `---` with no closing fence, a UTF-8 BOM before `---` (even when the declared name is
wrong), and a closing fence with no trailing newline. At `BASE` all three were reported (as
`(name, None)`). Now neither `apply_theme`'s residue check nor the sync's warning sees them.

**Evidence:**
`scripts/_theme_common.py:76` — `_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)`
`scripts/_theme_common.py:245-246` — `        if block is None:` / `            continue  # not a charter at all — e.g. agents/README.md`

Execution (scratchpad `exp2.py`):
```
unterminated.md   block=NO   reported=<not reported>
bom.md            block=NO   reported=<not reported>
bom_wrongname.md  block=NO   reported=<not reported>   <- declares name: other, silently ignored
no_trailing_nl.md block=NO   reported=<not reported>
crlf_ok.md        block=yes  reported=<not reported>   <- CRLF handled correctly
crlf_bad.md       block=yes  reported=nope
```

**Impact:**
A hand-corrupted charter (the very case #137 is about) can now pass both consumers silently. Narrow
in practice; the theme renderer's own edits never produce these shapes.

**Reproduction Steps:**
1. `agents/x.md` = `"﻿---\nname: other\n---\nbody\n"`.
2. `desynced_agents(agents_dir)` -> `[]`. Expected: `[("x.md", "other")]` or at least a report.

**Recommended Fix:**
Distinguish "starts with `---` (after optional BOM) but does not parse" from "does not start with
`---`": strip a leading `﻿`, and if `text.lstrip("﻿").startswith("---")` but the regex
misses, report it as `(name, None)` — it is claiming to be a charter. Add these three cases to
`tests/test_theme_common.py`.

---

### [MINOR] Quoted `name: "x"` is a pre-existing false positive that #137 makes gating

**Category:** Bug
**File(s):** `scripts/_theme_common.py:161-165`, `scripts/apply_theme.py:248-258`
**Confidence:** [VERIFIED] — parse result verified by execution; consequence [INFERRED]
**Status:** New

**Description:**
`_declared_name` returns the raw value after `name:`; `"planner"` (valid YAML, loads fine) compares
unequal to the stem. Before #137 that only produced advisory chatter on a repair pass. Now a
direction switch over such a tree rewrites and renames everything and then exits 2 "the theme
machinery cannot converge these — re-running will not help"; and if upstream ever ships a quoted
name, every themed sync refuses (P2). No real charter uses quotes today, so this is latent.

**Evidence:**
`scripts/_theme_common.py:163-164` — `        if sep and key.strip() == "name":` / `            return value.strip()`
Execution (`exp2.py`): `quoted.md  block=yes  reported="quoted"`.

**Impact:** Latent tripwire; a stylistic YAML change upstream would fail every themed instance.

**Reproduction Steps:**
1. Real `agents/` copy; change `planner.md` frontmatter to `name: "planner"`.
2. `apply_theme(copy, "philosophers")` -> writes the full switch, then exit 2 naming `plato.md`.

**Recommended Fix:** `value.strip().strip("'\"")` in `_declared_name`, with a unit test.

---

### [MINOR] Themed path materialises symlinked directories that the untheme'd path ignores; dangling symlinks crash it

**Category:** Bug / Security (defence in depth; upstream is a trusted input)
**File(s):** `scripts/sync_from_upstream.py:774`, `:221-223` (`_iter_files`, unchanged)
**Confidence:** [VERIFIED] — verified by execution
**Status:** New

**Description:**
`shutil.copytree(..)` defaults to `symlinks=False` and therefore *follows* a symlinked directory
inside `upstream/agents/`, materialising its full contents as real files; `plan_sync` then reports
them as additions. `_iter_files` uses `rglob`, which on Python 3.13+ does not follow directory
symlinks, so the untheme'd path never sees them. A dangling file symlink makes `copytree` raise
`shutil.Error` (uncaught) on the themed path only; the untheme'd path skips it (`is_file()` False).

**Evidence:**
`scripts/sync_from_upstream.py:774` — `        shutil.copytree(upstream / "agents", root / "agents")`
Execution (`exp8.py`, `up/agents/linked -> <dir outside upstream>`):
```
dest=functional   rc=0  linked entries in plan: []
dest=philosophers rc=0  linked entries in plan: ['+ add     agents\\linked\\deep\\secret.md']
dangling symlink, themed dest:     rc = EXC Error: [(... 'dangling.md' ... WinError 2)]
dangling symlink, functional dest: rc = 0
```

**Impact:** The two branches disagree about what upstream *contains*, which is the one thing the
design says they must not do; a symlink in a trusted upstream checkout (accidental, or from a
compromised fork used as `--upstream`) pulls an arbitrary directory tree into `dest/agents/`.

**Reproduction Steps:** as in the execution above.

**Recommended Fix:** `shutil.copytree(..., symlinks=True)` so the temp root mirrors upstream's
link structure and `_iter_files` treats it identically on both paths; or copy via the same
`_iter_files` + `copy2` loop `apply_sync` uses. Pin with a test that is `skipUnless` symlinks can be
created.

---

### [MINOR] Exceptions raised by the renderer escape unframed (streams are restored; temp dir is cleaned)

**Category:** Maintainability / operator UX
**File(s):** `scripts/sync_from_upstream.py:791-793`
**Confidence:** [VERIFIED] — verified by execution
**Status:** New

**Description:**
Only a non-zero `rc` is handled. A `PermissionError` (read-only upstream file preserved by
`copy2` into the temp root, then `write_text` fails), a `UnicodeDecodeError` on a non-UTF-8
upstream charter, or the `shutil.Error` above propagate as tracebacks naming a `tmpXXXX` path with
no framing line. The redirect and `TemporaryDirectory` context managers do unwind correctly —
verified: nothing leaked, stdout/stderr restored.

**Evidence:**
`scripts/sync_from_upstream.py:792-793` — `        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):` / `            rc = _render_crew(root / "agents", theme)`
Execution (`exp3.py` case C, `planner.md` chmod read-only upstream):
`rc EXC PermissionError: [Errno 13] Permission denied: '...\\tmpx8asptba\\agents\\planner.md'`.

**Impact:** Operator sees a bare traceback about a path that no longer exists.

**Recommended Fix:** Wrap the render in `try/except (OSError, UnicodeDecodeError)`, print the same
framing line as the `rc != 0` branch plus the exception, `return 2`.

---

### [MINOR] The `rc != 0` refusal quotes remediation text that cannot be followed

**Category:** Maintainability / operator UX
**File(s):** `scripts/sync_from_upstream.py:805-808`, `scripts/apply_theme.py:255-256`
**Confidence:** [VERIFIED] — verified by execution
**Status:** New

**Description:**
The framing line is correct and precedes the quote (W1 holds), but the quoted renderer stderr for
the residue case tells the operator to "Edit the frontmatter (or the filename) by hand so the two
agree" and that "re-running will not help" — both about the discarded temp copy. For the
both-representatives-upstream case the message "is itself on a theme" lists both files, which is
adequate.

**Evidence:** `exp3.py` case A output, quoted under the first Major finding.

**Recommended Fix:** After quoting, append one line from `main()`: the file(s) named live in
`--upstream`'s `agents/`; the instance's theme roster cannot express them; give the
functional-sync-retheme workaround. Folds naturally into the fix for the first Major finding.

---

### [INFO] The `assert` at `:782` is a tautology, not a guard

**Category:** Maintainability
**File(s):** `scripts/sync_from_upstream.py:782-784`
**Confidence:** [VERIFIED]

`root` is a freshly created empty directory and exactly one `copytree` into `root / "agents"`
precedes the assertion, so the condition cannot be false; `python -O` stripping it changes nothing.
The comment already frames it as "pinning the property", which is honest. No action needed; if a
future edit adds a second copy into `root`, the pin is what will catch it, so keep it.

### [INFO] Plan alignment: `a935f97` and its message changes are not in the plan document

**Category:** Maintainability
**File(s):** `scripts/_theme_common.py:130-184`, `scripts/apply_theme.py:154`, `:253`, `.sisyphus/plans/theme-aware-sync-plan.md`
**Confidence:** [VERIFIED]

T1 said "no reworded docstrings, no behaviour edits" to `apply_theme.py`; T3 said "no rewording of
the error text". `a935f97` introduces `desync_reason` and changes the None-case wording ("declares
no `name:` at all"), splits `_frontmatter_name`, and both consumers now call it. The tests cite a
"T14" that the plan file does not contain. The change is well argued in the docstrings and `tests/
test_apply_theme.py` stays green; this is a paperwork gap, not a defect. Add the T14 entry to the
plan (or a one-line amendment) so the plan and the branch agree. Everything else the plan mandates
is present: two `render_diff` keywords with defaults, lazy import with refusal, `_report`
extraction, R8/R9/Route D/near-miss paragraphs, README/ROADMAP rewrites, #137 in its own commit,
#138 not implemented.

### [INFO] Test-quality notes on the eight new modules

**Category:** Maintainability
**File(s):** `tests/test_sync_theme_hygiene.py:135-148`, `tests/test_sync_theme_guards.py:385-416`, `tests/test_sync_theme_contract.py:237-275`, `tests/test_sync_theme_mirroring.py:104-124`
**Confidence:** [VERIFIED]

All eight are theme-agnostic (they converge a scratch copy of the real `agents/` or use synthetic
fixtures) and none reads `.github/`. They test contracts through `main()` rather than internals,
which is the right altitude. Gaps:

- `RendererOutputCaptureTest` asserts *absence* of five phrases without first proving the renderer
  emits them in this fixture; if `apply_theme` rewords its chatter the test passes vacuously.
  Prove presence once by calling `apply_theme.apply_theme` directly on a copy under capture.
- `test_agents_entries_ordered_before_other_paths` would also pass if the plan were globally
  sorted (`agents` < `skills`). Use a non-agents path that sorts *before* `agents` (e.g.
  `CONTRIBUTING.md`, which is in `FRAMEWORK_PATHS`) so only the `a1 + a2` order satisfies it.
- `IdentityPathTest` poisons the temp dir and the renderer import only for a zero-representative
  dest; there is no poisoned run for a `functional`-classified dest, which is the other half of P1.
- The lazy-import refusal at `:755-764` has no direct test (only the contract test's negative
  space). A `patch.dict(sys.modules, {"apply_theme": None})` on a *themed* dest, asserting rc 2 and
  the "could not be imported" text, is cheap.
- `test_sync_theme_mirroring.py`'s fixtures call `apply_theme.apply_theme` without capturing
  stdout: 70 lines of `renamed ...` chatter land in the test runner's output per module run.
- `tests/test_theme_common.py` writes fixtures with platform newlines, so CRLF frontmatter is
  covered on Windows by accident only; add an explicit CRLF case.

### [INFO] The T5a remediation hint converges a mostly-philosophers tree to functional

**Category:** Maintainability
**File(s):** `scripts/sync_from_upstream.py:703-714`
**Confidence:** [VERIFIED]

For the T5a fixture (`planner.md` declaring `name: plato` beside ten philosopher charters) the hint
is `apply_theme.py functional`, which the comment explains hits the repair path. It does — and
repairs the tree to *functional*, rewriting ten philosopher charters, which is the opposite of what
an operator with ten philosopher files probably wants. The comment states this is deliberate and
verified; recording here that the operator then needs a second `apply_theme.py philosophers`. A
one-clause addition to the printed hint would save that operator a surprise.

### [INFO] Verified-correct items (recorded so they are not re-derived)

- **P1 output parity**: differential run of `HEAD` vs `BASE` `main()` over crewless and functional
  dests x {dry, --diff, --apply, --diff --apply}: byte-identical stdout/stderr/rc, modulo the
  plan-sanctioned post-apply hint text. (`exp5.py`)
- **Temp-dir lifetime**: the `with` spans `plan_sync` -> `render_diff` -> `apply_sync` -> `_report`
  (`:772-857`); every `return` inside is a normal context exit; cleanup verified on success, on
  `rc != 0`, and on an exception thrown inside the redirect.
- **`render_diff`**: default call path is line-for-line `BASE` (`:435-504` vs `BASE:259-315`);
  `summary=False` output plus `main()`'s footer reproduces the single-call spacing exactly
  (`exp6.py`); provenance keys are POSIX and match on Windows; binary branch `continue`s before the
  annotation, which is harmless for `.md`.
- **`_report`/`_self_was_replaced`**: the concatenated `added + updated` is joined to `dest`
  (`:361`), so `agents/` entries can never alias the running script and `scripts/` entries arrive
  via the `others` half exactly as at `BASE`.
- **Guard ordering**: both-reps refusal -> themed-upstream refusal -> classify -> desync warning ->
  branch. Enumerated dest x upstream x desync states; the only unwarned destructive state found is
  the third Major finding.
- **Path traversal**: all plan strings are `relative_to(base)` joins; rename targets are
  roster-derived; nothing user-controlled reaches a path outside `dest`.
- **Deletion mirroring**: `qa-guard.md` deleted upstream -> `agents/cato.md` deleted in dest,
  reported and applied (`exp6.py`, and `tests/test_sync_theme_mirroring.py`).
- **#137**: residue check fires on both directions, is exempt on dry-run, and the real tree's
  round trip stays clean (`tests/test_apply_theme_residue.py`, `ApplyThemeRoundTripTest` untouched).

## Regression Check Results

| Feature/Contract | Status | Notes |
|---|---|---|
| P1 — untheme'd path runs today's code, identical output | **Warning** | Output byte-identical (verified); but `desynced_agents` now runs unconditionally and can raise on a non-UTF-8 / directory `.md` (Major #2). |
| P2 — `rc != 0` refuses, nothing written, framed stderr | Pass | Verified for crewless upstream and rename collision; but see Major #1 for the residue-class deadlock the strictness produces. |
| Contract (a)/(b) — in-step themed instance yields empty plan; `apply_theme` afterwards is a no-op | Pass | `tests/test_sync_theme_contract.py`; reproduced. |
| R4 — deletion mirroring through the materialised upstream | Pass | Reported and applied; no add/delete overlap. |
| R2 — only `agents/` in the temp root | Pass | Structural; assertion is tautological (Info). |
| R6 — CRLF dest not reported updated | Pass | `CrlfThemedDestTest`. |
| R7 — themed upstream vs untheme'd dest refused | Pass | Guard at `:631-640`. |
| R8 — one-pass-behind converges on a later pass | **Fail** | False for new tiers / stem-embedding charters: permanent refusal (Major #1). |
| R9 — `planner`->`plato` edit invisible (chosen) | Pass | Pinned. |
| Decision 2 — both reps in dest refused | Pass | Verified. |
| Decision 3 — half-renamed dest warns and proceeds (both classifications) | Pass | T5a fixture verified. |
| Decision 4 — zero reps = today's behaviour | **Warning** | Correct as specified; the premise "zero reps == crewless" is false (Major #3). |
| `render_diff` defaults unchanged; `RenderDiffTest` unedited | Pass | Verified line-for-line. |
| `_self_was_replaced` reminder preserved | Pass | Same call, same triple semantics. |
| `tests/test_apply_theme.py`, `tests/test_sync_from_upstream.py` untouched | Pass | Confirmed by the orchestrator; suite 839 OK. |
| Both consumers tolerate `agents/README.md` | Pass | `a935f97`; but unterminated/BOM charters now silently skipped (Minor). |
| Symlinks in `upstream/agents` behave the same on both paths | **Fail** | Themed path follows dir symlinks and crashes on dangling ones (Minor). |
| No memory-recorded failure modes reintroduced | Pass | `memory/repo/nescio/` holds no sync/theme notes; judged on contracts and types. |

## Recommendations

1. **Before merge:** fix Major #2 (guard the read in `desynced_agents`) — it is a five-line change,
   restores P1 fully, and removes a traceback path from every sync.
2. **Before the first themed instance syncs on this code:** decide Major #1. Either downgrade the
   *residue-only* renderer failure to a warning in the themed branch (rename collisions and an
   unclassifiable crew stay refusals), or keep P2 strict and print the accurate workaround. Correct
   the R8 docstring paragraph either way, and add a `builder-<tier>` regression test.
3. **Cheap and worth it:** close Major #3 with a "themed roster present, representative missing"
   refusal that needs no renderer import; it is the same shape as the both-representatives guard.
4. `copytree(..., symlinks=True)` and a `try/except` around `_render_crew` (Minors) — small, local,
   and they make the two branches agree about what upstream contains.
5. Tighten `_frontmatter_block` (BOM / unterminated) and `_declared_name` (quotes), each with a unit
   test.
6. Test hygiene items in the Info section; the vacuous-absence and alphabetical-order weaknesses are
   the two worth fixing.
7. Record `a935f97` as T14 in the plan so the branch and the plan agree.

## Files Reviewed

- `.sisyphus/plans/theme-aware-sync-plan.md` (HEAD)
- `scripts/sync_from_upstream.py` (HEAD, and BASE `d605033`)
- `scripts/_theme_common.py` (HEAD)
- `scripts/apply_theme.py` (HEAD, and BASE for the moved classifier)
- `scripts/_crew_common.py` (HEAD, `PAIRS`, `TIERED_AGENTS`, `renamed_agents`)
- `tests/test_sync_theme_contract.py`, `tests/test_sync_theme_guards.py`,
  `tests/test_sync_theme_hygiene.py`, `tests/test_sync_theme_mirroring.py`,
  `tests/test_sync_theme_updates.py`, `tests/test_apply_theme_residue.py`,
  `tests/test_theme_common.py`, `tests/test_theme_common_charters.py` (HEAD)
- `tests/test_sync_from_upstream.py` (`_make_checkout` only, unchanged)
- `README.md`, `ROADMAP.md` (diff)
- `memory/repo/nescio/` (no relevant notes)
- Issues noctua84/nescio-ai#133 and #137 (both OPEN)

Scratchpad scripts (`exp1.py` .. `exp8.py`) live in the session scratchpad and were not added to
the repo.
