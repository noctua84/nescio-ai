# Theme-aware overlay sync (issue #133)

## TL;DR

> A themed downstream instance exactly in step with upstream permanently reports
> `would change: 11 added, 3 updated, 11 deleted`, because `plan_sync` compares by filename
> (the eleven theme renames read as add/delete pairs) and by content (the three
> theme-invariant charters have their prose rewritten by the theme). We fix it by
> **materialisation**: when — and only when — the dest is themed, `main()` copies upstream's
> `agents/` into a temp directory, runs the **existing** `apply_theme()` renderer over that copy,
> and then runs **today's completely unmodified** `plan_sync` / `apply_sync` / `render_diff`
> against it. `plan_sync`, `apply_sync` and `_files_equal` are **not touched**; `render_diff` gains
> two display-only keywords and nothing else.
> The only new shared code is a classifier module, `scripts/_theme_common.py`. Deletion
> mirroring is untouched *structurally* — `plan_sync` is the same function it is today.
> 13 tasks over 6 waves; the two contract tests in Wave 4 ARE the invariant.

---

## Context

### The repository

Work happens **only** in the worktree
`C:\Users\marku\PycharmProjects\nescio-ai\.claude\worktrees\vigilant-bouman-c0d77c`.
Branch `fix/theme-aware-sync-plan` is already cut from `origin/main` (6566dbd). Do **not** `cd`
to the main checkout at `C:\Users\marku\PycharmProjects\nescio-ai`.

Tracking issue: <https://github.com/noctua84/nescio-ai/issues/133>
(`gh issue view 133 --repo noctua84/nescio-ai`).

### The two moving parts

`scripts/sync_from_upstream.py` overlay-syncs a fixed `FRAMEWORK_PATHS` allowlist from an upstream
Nescio checkout into a downstream private fork ("instance"), mirroring additions, updates and
deletions inside those paths only.

`scripts/apply_theme.py philosophers` is an **opt-in cosmetic** rename: it renames eleven agent
charters (nine `PAIRS` + the two `builder-simple` / `builder-standard` tiers) and rewrites crew
names in the prose of every `agents/*.md`, including the ones whose filenames do not change.

The two are unaware of each other.

### The bug, reproduced exactly

A themed instance exactly in step with upstream reports `would change: 11 added, 3 updated,
11 deleted`. Every one of the 25 entries is fiction. Two causes:

1. **11 added / 11 deleted.** `plan_sync` compares by base-relative filename
   (`scripts/sync_from_upstream.py:154-162`). Upstream ships `planner.md`; the themed instance
   holds `plato.md`. Each functional file reads as an addition, each themed file as a deletion —
   forever.
2. **3 updated.** `agents/orchestrator.md`, `agents/scout.md` and `agents/validator.md` keep
   functional filenames but their *prose* is rewritten by the theme
   (`scripts/apply_theme.py:270-278`), so their content never matches upstream.

**Reproduction harness** (verified to give exactly 11/3/11):

```bash
# from the worktree root
TMP=$(mktemp -d)
# copy the allowlisted paths of this repo into $TMP
python scripts/apply_theme.py philosophers --agents-dir "$TMP/agents"
python scripts/sync_from_upstream.py --upstream . --dest "$TMP"
```

### Why it matters

`_files_equal`'s own docstring (`scripts/sync_from_upstream.py:82-136`) makes the argument: the
dry run is "the only thing standing between an operator and a destructive `--apply`", and burying
the real changes among phantom ones "trains them to skim past it". That argument was made about
CRLF noise and acted on in #100 / `d52af12`. The theme render reintroduces the identical failure
mode through a different door — and worse, because it is not a one-off migration artefact but
**every sync, forever, for every themed instance**. An operator who has learned that "11 added,
11 deleted" is normal will not notice the twelfth deletion that is a real file loss.

---

## Decisions already made — DO NOT RE-OPEN

These were settled by the user. An implementer who disagrees should report `BLOCKED` rather than
redesign.

1. **Route A.** Make the sync theme-aware. `apply_sync` writes the *themed* content to the
   *themed* path, so a subsequent `apply_theme.py philosophers` is a genuine no-op and the next
   dry run is empty. **Not** "sync functional filenames and re-render locally".
2. **Both theme representatives present in dest** (`agents/planner.md` **and** `agents/plato.md`):
   refuse loudly, exit non-zero, name the offending files, write nothing — mirroring
   `scripts/apply_theme.py:197-206`.
3. **Half-renamed dest tree** (exactly one representative, but `desynced_agents` non-empty):
   **warn**, naming the files and pointing at `python scripts/apply_theme.py <theme>`, then
   **proceed**. Do **not** refuse — that would block a legitimate framework sync on a cosmetic
   inconsistency. (This deliberately diverges from issue #133's original text, which proposed
   refusing here.)
4. **Zero representatives in dest** (a fresh or crewless instance — including *every* existing
   fixture in `tests/test_sync_from_upstream.py`, whose `_make_checkout` seeds only
   `agents/explore.md`): fall back to **exactly today's behaviour**. This is the bootstrap case
   and it must keep working.

---

## The construction — VERIFIED BY EXECUTION, do not redesign

### Materialise, then run today's code

The chain that produced the previous draft framed the problem as *"the comparison needs to know
about the theme"*, which points at a lens threaded through three functions. Framed instead as
*"the comparison needs an upstream that is already in dest-space"*, it points at materialising a
themed copy of upstream and running today's unmodified code against it.

In `main()`, **only when the dest is themed**:

```python
OTHERS = [p for p in FRAMEWORK_PATHS if p != "agents"]

with tempfile.TemporaryDirectory() as tmp:
    shutil.copytree(upstream / "agents", Path(tmp) / "agents")
    rc = apply_theme(Path(tmp) / "agents", theme)      # the EXISTING renderer
    if rc != 0:
        return 2                                        # upstream crew is incoherent
    a1 = plan_sync(Path(tmp), dest, paths=["agents"])   # UNMODIFIED
    a2 = plan_sync(upstream, dest, paths=OTHERS)        # UNMODIFIED
    added, updated, deleted = (x + y for x, y in zip(a1, a2))
```

`apply_sync` and `render_diff` are split the same way over the same `tmp` root, which **must live
for the whole plan -> diff -> apply sequence**.

**`plan_sync`, `apply_sync` and `_files_equal` are NOT MODIFIED AT ALL.**
No `ThemeLens`. No `_source_map`. No `themed_stem`. No `_content_equal` extraction. No
keyword-only lens parameter anywhere. The only signature change in the whole of
`sync_from_upstream.py` is two **display-only** keywords on `render_diff` — `summary: bool = True`
and `provenance` (see Wrinkle 2 and T2). Both default to today's behaviour, so every existing
call site stays green unedited. No plan *data* — what is added, updated or deleted — is computed
anywhere but in the unmodified `plan_sync`.

Verified results from the orchestrator's spike, against the real reproduction harness:

```
dest theme: philosophers
SPIKE plan -> 0 added, 0 updated, 0 deleted
render_diff on temp root: ok
after upstream deletes qa-guard.md -> deleted=['agents/cato.md']
```

### Two properties that are REQUIREMENTS, not nice-to-haves

**P1 — An untheme'd instance must execute literally today's code path.** Gate the whole
materialisation branch behind "dest is themed": no split, no temp dir, no import of the theme
renderer module, **one** `plan_sync` call with no `paths=` argument. This is strictly stronger
than the previous draft's identity-lens approximation.

It also disposes of an ordering question. `"agents"` is **first** in `FRAMEWORK_PATHS`, so
`a1 + a2` happens to reproduce today's ordering — but an untheme'd instance must not depend on
that coincidence at all. On the themed path we *do* depend on it, and Wave 4 pins it.

**P2 — `rc != 0` from the materialising `apply_theme` call must refuse the sync**, exit non-zero,
and surface the captured stderr. It must **not** be softened to a warning. This is what makes the
"upstream carrying two representatives" case free.

### Coupling verdict — extract ONLY the classifier

This **replaces** the previous draft's coupling verdict and its amendment in full.

Move into a new `scripts/_theme_common.py`:

- `THEME_REPRESENTATIVES` (`apply_theme.py:60-68`, comment included)
- `theme_representatives` (`:71-79`)
- `detect_theme` (`:82-108`)
- `_FRONTMATTER_RE` (`:56-57`), `_frontmatter_name` (`:111-120`), `desynced_agents` (`:123-143`)

Sync needs exactly these, unconditionally, for the four theme-state decisions. They are cheap,
I/O-only, and carry no CLI.

**`_mappings`, `_transform` and `apply_theme` STAY in `apply_theme.py`.** They are imported
**lazily, inside the themed branch only**, so an untheme'd instance never touches the cosmetic
module at all (P1). If that lazy import fails on a themed instance, **refuse loudly** — do not
fall back to identity. A fallback whose failure mode is a destructive 11/11 plan is not
degradation.

`apply_theme.py` re-exports the moved classifier symbols so its four existing test call sites
(`tests/test_apply_theme.py:212`, `:220`, `:252`, `:273`) and the two in
`tests/test_agent_definitions.py` (`:126`, `:316`, `:329`) stay green **untouched**.

Rationale to record **in the new module's docstring**:

1. This is `_crew_common.py`'s own argument applied one level down — *a fact needed by two
   consumers must not live inside the deletable script*. Only the classifier is a two-consumer
   fact; the renderer is not.
2. **Why the renderer did NOT move with it.** Calling `apply_theme`'s **public** function is a
   legitimate API use. That is what makes the lazy import acceptable where the previous draft's
   direct-import design was not: that design reached into `_mappings` and `_transform`, i.e. into
   the module's *privates*, which is what made "importing apply_theme from sync" look like an
   inversion. Importing the public entry point, lazily, under a theme gate, is a different act.
3. **Rejected: hosting this in `_crew_common.py`.** That module's docstring says "Stdlib-only, no
   I/O: pure data, one small value type describing it, and derivations over it" — and
   `detect_theme` / `desynced_agents` do I/O. This module explicitly permits I/O; say so.
4. **Rejected: a graceful-degradation import with an identity fallback.** Its failure mode on a
   themed instance is a *destructive* 11-added/11-deleted plan.
5. **R9** (below): the mapping is many-to-one, so an upstream edit that changes exactly
   `planner` -> `plato` is invisible to a themed instance. A chosen property, not a bug.

---

## The three wrinkles — all verified, all must be implemented

### W1 — `apply_theme` is chatty, and its output must never leak into sync output

Verified: **13 stdout lines** on a normal render, and on a genuine upstream deletion it puts
`! expected qa-guard.md not found — skipping` on **stderr**.

Both streams must be captured with `contextlib.redirect_stdout` / `redirect_stderr` and
**discarded on `rc == 0`**, **surfaced on `rc != 0`**. An uncaptured render would put rename
chatter (`renamed planner.md -> plato.md`, `switched crew: functional -> philosophers`) in the
middle of the sync's own output, describing a temp directory the operator has never heard of.

On `rc != 0`, `main()` must print **its own framing line first** — naming `--upstream` and saying
that the sync refused because upstream's crew could not be rendered into the instance's theme —
*then* the captured stderr. Without the framing line the operator sees a bare error about a
`/tmp/...` path with no explanation of where it came from.

### W2 — `render_diff` emits its own `net-new:` footer

`render_diff` ends by appending `net-new: N added file(s), N updated, N deleted`
(`scripts/sync_from_upstream.py:273-277`). Two calls means two footers.

**Chosen:** add a `summary: bool = True` keyword to `render_diff`; the themed branch calls both
halves with `summary=False` and `main()` appends one footer with the combined counts.

*The cost, stated:* `render_diff`'s public signature grows one keyword, and on the themed path
`main()` — not `render_diff` — owns the footer. The rejected alternative (stitch entirely in
`main()` by string-surgery on two returned blobs) makes `main()` parse `render_diff`'s output
format, which is worse coupling for the same result. `RenderDiffTest`
(`tests/test_sync_from_upstream.py:112-160`) passes unedited because the default is `True`.

*A second, cosmetic cost that must be recorded in the docstring:* two calls means the sections
interleave — `UPDATED(agents) / ADDED(agents) / DELETED(agents)` then
`UPDATED(others) / ADDED(others) / DELETED(others)` — rather than one grouped set of three. This
affects **only** a themed instance running `--diff`. It is accepted, not overlooked.

### W3 — provenance header

After materialisation the sync does not know `plato.md` came from `planner.md`. This is
recoverable cheaply and is **display-only**: `renamed_agents(theme)` from `_crew_common` already
returns `[('planner','plato'), ('advisor','aristotle'), ...]` (verified).

Add a `provenance: dict[str, str] | None = None` keyword to `render_diff` mapping dest-relative
path -> upstream-relative path. When an UPDATED or ADDED entry is in the map, the `tofile` becomes:

```
b/agents/plato.md (upstream agents/planner.md, themed)
```

Otherwise it stays exactly today's `b/<posix> (upstream)`. `main()` builds it on the themed path
as:

```python
prov = {str(Path("agents") / f"{dst}.md"): str(Path("agents") / f"{src}.md")
        for src, dst in renamed_agents(theme)}
```

A file the map does not cover — `agents/orchestrator.md`, whose *content* is themed but whose name
is not — simply gets no note. That is graceful and correct (the paths are identical), and **no
correctness depends on this header at all**. Say so in the docstring: it exists because a themed
diff is rendered in philosopher vocabulary, which is more useful for the operator reading their
own tree but costs them the ability to locate the upstream file.

---

## Risk register

Six of the previous draft's eleven risks are **dissolved by construction**. They are listed here
with one line each so a reader of the old draft can see what happened to them, and so nobody
re-introduces machinery to solve a problem that no longer exists.

### Dissolved

- **R1 — `FileNotFoundError` from `apply_sync:184` / `render_diff:224,248` resolving plan strings
  against upstream.** Gone: `agents/plato.md` is a real file under `tmp`, so `upstream / rel`
  resolves. No `_source_map`, no triple-of-pairs, no sixteen rewritten assertions.
- **R2 — a blanket transform destroying `scripts/_crew_common.py`'s `PAIRS` and making the theme
  permanently unrevertable.** **Unreachable by construction:** only `agents/` is copied into
  `tmp`, so `scripts/` is not present for the transform to reach. Keep a *cheap* replacement
  assertion (`tmp` contains only `agents/`); the 13-file scope-guard test is dropped.
- **R3 — themed content for `orchestrator.md` / `scout.md` / `validator.md`.** Free:
  `apply_theme` already rewrites their prose and leaves their filenames alone. This is the same
  code path the theme itself uses, so it cannot drift from it.
- **R5 — rename collisions** (a genuinely new upstream `agents/plato.md`). Free:
  `apply_theme.py:247-260` pre-flights all-or-nothing and returns 2, which P2 turns into a refusal.
  **One renamer, and it is the one with the pre-flight** — the previous draft's two-renamer problem
  is gone.
- **R6 — newlines, `copy2` vs in-memory strings.** Gone: `shutil.copy2` and the `filecmp` fast
  path still apply to *every* file; `_files_equal` is untouched; `LineEndingTest` needs no
  re-pinning; `copy2` metadata preservation is not lost for any file. No `_content_equal`
  extraction.

### R7 — a themed `--upstream` (PARTIALLY dissolved; a cheap guard is retained)

Precisely what the `rc != 0` check covers, and what it does not:

| upstream state | dest state | outcome |
|---|---|---|
| carries **both** representatives | themed | **T5 step 2 refuses it first**, before the branch. `apply_theme`'s own both-themes refusal (`:197-206`) would also catch it, but is never reached. Do not write a test asserting that stderr — see T9/P2. |
| cleanly themed, **same** theme as dest | themed | `apply_theme` reports "already on the theme", `rc=0`, tmp holds the themed tree, the comparison is themed-vs-themed and **correct**. No guard wanted. |
| cleanly themed | **untheme'd** | **The materialisation branch never runs.** Today's destructive 11-added/11-deleted plan in the opposite direction, unchanged. |

The third row is a residual hole, and it is the one case the previous draft's explicit R7 guard
covered. It costs one `theme_representatives(upstream / "agents")` call in `main()`, before the
branch, with **no import of the cosmetic module** — so it does not violate P1. **Keep it**
(task T5, step 2). Refuse with exit 2 naming the theme and the representative file found.

`_is_nescio_checkout` (`:63-65`) requires only `install.py` + `agents/`, so nothing else stops
this.

### R4 — do NOT implement suppression or filtering of individual add/delete entries — NOW STRUCTURAL

Render upstream's agent set into dest-space **totally**, then apply the existing set difference
unchanged. **This is now enforced structurally rather than by discipline: `plan_sync` is not
modified, so there is no place to put a filter.** The requirement survives as a prohibition on
re-opening the file.

The three failure modes, kept on the record because a future reader will propose each of them:

- Skipping dest files with philosopher stems swallows a real deletion of `qa-guard.md` /
  `cato.md`.
- Skipping a delete when *some* upstream agent maps onto it does the same one indirection later,
  and additionally hides stale orphans.
- Rendering names without comparing as a **set** can put a file in both `added` and `deleted`, and
  `apply_sync` deletes before it copies (`:181-187`), so ordering decides the outcome.

Deletion mirroring is **the safety property of this whole script**. It must not weaken.

### R8 — bootstrap / one-pass-behind

`sync_from_upstream.py`, `apply_theme.py` and `_crew_common.py` all live inside the synced
`scripts/` allowlist entry. **The script that runs is the *dest's* copy.** So the first sync
carrying this fix behaves like today (noisy plan) and only the *second* is clean — including the
arrival of the new `_theme_common.py`. Document that in the module docstring; do **not** try to
engineer around it.

Related choice, now explicit: the materialisation renders using the **dest's** `apply_theme.py` /
`PAIRS` — the instance's notion of its own theme — not upstream's. Consequence to record: a *new*
pair added upstream, or a *retargeted* pair (`doc-writer` -> `quintilian` replacing `cicero`),
converges only on a later pass. In the retargeted case it additionally leaves an orphan
`cicero.md` that `desynced_agents` will **not** catch, because that oracle compares `name:`
against the filename stem and the orphan is self-consistent.

### R9 — false negatives: a property to choose, not to discover

The mapping is many-to-one: `planner` / `Planner` / `PLANNER` all map to `plato` / `Plato` /
`PLATO`, and a literal upstream `plato` also maps to `plato`. An upstream edit that changes
exactly `planner` -> `plato` renders identically and is therefore **invisible** to a themed
instance.

Practical impact is nil — the instance's rendering genuinely did not change — but state it in the
docstring so it is a *chosen* property rather than a latent surprise, and pin it with a named test
(T7).

### R10 — `ApplyThemeRoundTripTest` becomes load-bearing for data integrity

Once `apply_sync` writes themed bytes, the instance never holds functional charters again, and
`apply_theme functional` is its only inverse. `ApplyThemeRoundTripTest`
(`tests/test_apply_theme.py:79-112`) copies the **real** `agents/` tree and checks byte-identity
round trip.

**It MUST NOT be weakened, narrowed to a fixture, or made to seed its own tree.** Verified
currently green; verified that no functional charter contains a philosopher word; verified that
`_transform` is idempotent and round-trips over all 17 real charters.

### R11 — documentation that goes stale

Verified by grep: **nothing** outside these scripts references `plan_sync` / `apply_sync` /
`render_diff` / `apply_theme` — no CI workflow, hook, command, skill, `github-action/`, or
`install.py`; nothing asserts on the `would change: N added...` line. The only importers of
`apply_theme` are `tests/test_agent_definitions.py:22` and `tests/test_apply_theme.py:30`.

The couplings are documentation only:

- `README.md:261-264` — "The philosopher theme is rendered, not committed... so syncs never fight
  your renames." Today that is simply **wrong**; after this change it needs **rewriting, not
  deleting**.
- `scripts/sync_from_upstream.py:19-20` (module docstring) and `:333-335` (the post-apply hint) —
  both advertise the manual re-render and become misleading.
- `ROADMAP.md:44`.
- `CONTRIBUTING.md:64-70` stays true and is unaffected. Do not touch it.

Note also: `plan_sync(paths=...)` is parameterised (`:139`), and this design keeps it that way —
`plan_sync` performs **no theme-detection I/O at all**, because every theme decision is made in
`main()` before it is called. A caller passing a `paths` subset excluding `"agents"` is
unaffected, by construction.

---

## Route D and the near-miss — record, do not implement

Both belong as paragraphs in the `scripts/sync_from_upstream.py` module docstring.

**Route D — "make the theme a projection rather than a mutation"** (resolve names at load time
instead of renaming files) removes the root cause but is infeasible: Claude Code loads charters
from real files at `agents/<name>.md` with no name-resolution hook. Give it one paragraph
recording that it was considered and why it lost — a future reader *will* propose it.

**The cheap-looking near-miss:** having `apply_sync` simply invoke `apply_theme` as a post-sync
step. It fixes nothing, because **the plan is the broken artefact** — the operator still reads
25 fictional entries before deciding whether to run `--apply` at all, and the dry run (which never
calls `apply_sync`) stays exactly as wrong as it is today. Note the distinction from what we
*are* doing: we run `apply_theme` over a **temp copy of upstream, before planning**, not over the
**dest, after applying**.

---

## Also noted — separate issues, do NOT fold into #133's scope

- **noctua84/nescio-ai#137** — `apply_theme` exits 0 after leaving an agent whose `name:`
  disagrees with its filename. Verified: a synthetic `reviewer-lite.md` ends up as
  `pyrrho-lite.md` still declaring `name: reviewer-lite`, because the residue check at
  `scripts/apply_theme.py:304-326` is gated inside `if repairing:`, which is `False` on a
  direction switch. **The user has approved fixing this in THIS PR** — it is task **T3**, clearly
  labelled as closing **#137, not #133**.
- **noctua84/nescio-ai#138** — gate deletions behind an explicit opt-in in `--apply`.
  **Do NOT implement.** Mentioned here only so an implementer does not "helpfully" add it.

---

## The docstring standard — a stated user requirement

`scripts/sync_from_upstream.py` and `scripts/apply_theme.py` set a standard: their docstrings
argue **actively against plausible simplifications** — *"Do NOT 'simplify' this back into
`filecmp.cmp(..., shallow=False)`"*, *"the two derivations must not disagree about that"*.

**Every non-obvious choice introduced by this plan gets that treatment.** In particular:

- Why the renderer is imported lazily and only inside the themed branch.
- Why the untheme'd path is a separate branch and not a `paths=` parameterisation of the themed
  one.
- Why `plan_sync` is called twice rather than being taught about themes.
- Why `rc != 0` refuses instead of warning.
- Why the provenance header is display-only and nothing depends on it.

A task that lands mechanism without the argument is incomplete.

---

## Work objectives

1. Extract the theme's **classifier** into `scripts/_theme_common.py`, consumed by both
   `apply_theme.py` and `sync_from_upstream.py`, with zero behaviour change to `apply_theme.py`
   and zero edits to its tests.
2. Give `render_diff` the two display keywords the split needs (`summary`, `provenance`), both
   defaulted so today's callers are unaffected.
3. Make `main()` classify the dest, refuse the two refusable states, warn on the third, and — only
   when the dest is themed — materialise a themed copy of upstream's `agents/` and run today's
   unmodified plan/diff/apply against it.
4. Close **#137** as its own small, separately-labelled task.
5. Prove the invariant with tests, above all the two contract tests.
6. Correct the documentation that this change makes false.

---

## Verification strategy

- **Baseline: 751 tests, OK.** Every task's acceptance criteria include "the full suite still
  passes, with no test file edited that the task does not name".
- Run the suite as:
  ```bash
  python -m unittest discover -s tests -t tests
  ```
  pytest is a broken shim on this Windows box (wrong venv; Python 3.12, below the declared
  `requires-python >=3.13`; crashes on cp1252 output). **Do not use pytest.** The unittest summary
  goes to **stderr**; read it with `2>&1 >/dev/null | tail -20`.
- New test modules go in `tests/` as `test_*.py`. `.github/workflows/tests.yml` runs
  `discover -s tests`, so new modules are covered automatically and **no workflow edit is needed**
  — `docs_site/test_ci_coverage.py` will not red on them.
- `docs_site/test_ci_coverage.py:20-34` documents that `tests/` ships downstream. **Any new test
  must be theme-agnostic** (it may not assume this repo is on the functional theme) **and must not
  read this repo's `.github/`.** `tests/test_agent_definitions.py:118-141` (`_current_theme` /
  `_themed`) is the pattern to copy.
- **End-to-end acceptance**, run manually at the end (task T13): the reproduction harness above
  must print `framework already in sync — nothing to do.`

### The gate

**Neither `tests/test_apply_theme.py` nor `tests/test_sync_from_upstream.py` may be edited by any
task in this plan.** Verified as achievable, including for T3: `desynced_agents` on the real
`agents/` tree is `[]` both before and after a philosophers switch, so moving the residue check
out of `if repairing:` cannot red any existing test. A task that believes it must edit either file
reports **BLOCKED**.

---

## Execution strategy

**Six waves.** Waves 2 and 3 are separated **only because they edit the same file**
(`scripts/sync_from_upstream.py`) and parallel agents would conflict.

| Wave | Tasks | Parallel? |
|---|---|---|
| 1 | T1 | single — `_theme_common.py` must exist before anything imports it |
| 2 | T2, T3, T4 | yes — `sync_from_upstream.py` / `apply_theme.py` / a new test file |
| 3 | T5 | single — same file as T2 |
| 4 | T6, T7, T8, T9, T10 | yes — five distinct new test files |
| 5 | T11, T12 | yes — different files |
| 6 | T13 | single (verification gate) |

Six waves, six rows. There is no optional task and no display-only extra: the `renamed (theme)`
plan section from the previous draft is dropped (see "What was removed").

---

## TODOs

### Wave 1

- [ ] **1. Create `scripts/_theme_common.py` (classifier only) and rewire `apply_theme.py`**

  **Complexity**: standard

  **What to do**:
  - Create `scripts/_theme_common.py`. Move these, **unchanged in behaviour**, out of
    `scripts/apply_theme.py`:
    - `_FRONTMATTER_RE` (`:56-57`) and its comment
    - `THEME_REPRESENTATIVES` (`:60-68`) and its comment
    - `theme_representatives` (`:71-79`)
    - `detect_theme` (`:82-108`)
    - `_frontmatter_name` (`:111-120`)
    - `desynced_agents` (`:123-143`)
  - **Move the docstrings with the functions, verbatim.** They argue against specific
    "simplifications" (source-order classification; trusting `detect_theme` alone) and those
    arguments must not be lost in transit.
  - **Do NOT move `_mappings`, `_transform`, or `apply_theme`.** They stay in `apply_theme.py`.
    Do **not** add a `themed_stem`; nothing needs one under this construction.
  - The module needs the same `sys.path` bootstrap `apply_theme.py:50-52` uses so it resolves when
    run as a script, imported by tests, or collected under `PYTHONPATH=scripts`. Copy that idiom
    and its comment. Note that this module imports nothing from `_crew_common` today — keep it
    dependency-free and say so.
  - **Write the module docstring.** It must contain, in this order, the five points from the
    "Coupling verdict" section above: (1) what the module is — the theme's *classifier*, shared by
    `apply_theme.py` and `sync_from_upstream.py`; (2) why the classifier is a two-consumer fact
    while the **renderer is not**, and that the renderer is therefore imported lazily through its
    **public** entry point, which is a legitimate API use unlike reaching into `_mappings` /
    `_transform`; (3) rejected: hosting in `_crew_common.py` — that module is I/O-free by
    contract and this one is not; (4) rejected: a graceful-degradation import with an identity
    fallback — "a fallback whose failure mode is destruction is not degradation"; (5) R9, the
    many-to-one mapping and the deliberate invisibility that follows.
  - In `scripts/apply_theme.py`, replace the moved definitions with, alongside the existing
    `_crew_common` import:
    ```python
    from _theme_common import (  # noqa: E402
        THEME_REPRESENTATIVES,  # noqa: F401 — re-exported: tests reach it through this module
        desynced_agents,
        detect_theme,
        theme_representatives,
    )
    ```
    `THEME_REPRESENTATIVES` is genuinely unused in `apply_theme.py`'s own body after the move; the
    `# noqa: F401` **must** carry that explanatory comment, because a future reader removing a
    "dead" import would red `tests/test_apply_theme.py:291` and `:313`.
    Keep `PAIRS`, `THEMES` and `renamed_agents` imported from `_crew_common` exactly as today, and
    keep the `re` import (`_transform` at `:181-184` still needs it).
  - **Do not change any behaviour in `apply_theme.py`.** Its CLI, `apply_theme()`, and the
    rename-conflict pre-flight stay exactly as they are. T3 is the only task allowed to change its
    behaviour, and it does so for a different issue (#137).

  **Files**: `scripts/_theme_common.py` (new), `scripts/apply_theme.py` (modify)

  **Acceptance criteria**:
  - `python scripts/apply_theme.py --dry-run philosophers` behaves identically to before.
  - `tests/test_apply_theme.py` and `tests/test_agent_definitions.py` pass with **zero edits** —
    `apply_theme.detect_theme`, `apply_theme.desynced_agents`, `apply_theme.THEME_REPRESENTATIVES`,
    `apply_theme.THEMES`, `apply_theme._mappings`, `apply_theme._transform`, `apply_theme.PAIRS`
    and `apply_theme.apply_theme` all still resolve.
  - Full suite green at the 751 baseline.
  - `git diff scripts/apply_theme.py` shows only deletions of the moved blocks plus one import
    block — no reworded docstrings, no behaviour edits.

  **QA scenarios**:
  1. `python -c "import sys; sys.path.insert(0,'scripts'); import _theme_common as t; from pathlib import Path; print(t.detect_theme(Path('agents')), t.desynced_agents(Path('agents')))"`
     prints `functional []`.
  2. `python -c "import sys; sys.path.insert(0,'scripts'); import apply_theme as a, _theme_common as t; print(a.detect_theme is t.detect_theme, a.desynced_agents is t.desynced_agents)"`
     prints `True True`.
  3. `python -m unittest discover -s tests -t tests 2>&1 >/dev/null | tail -5` reports OK.

---

### Wave 2

- [ ] **2. Give `render_diff` its two display keywords (`summary`, `provenance`)**

  **Complexity**: simple

  **Depends on**: nothing (may run alongside T1)

  **What to do**: in `scripts/sync_from_upstream.py`, change **only** `render_diff` (`:213-277`):
  - Add `*, summary: bool = True` and `provenance: dict[str, str] | None = None`.
  - When `summary` is False, skip the final `net-new: ...` line (`:273-276`) — everything else,
    including the `return ""` early-out for an empty plan (`:270-271`), is unchanged.
  - When `provenance` contains the entry's `rel`, the `tofile` on an UPDATED diff (`:239`) and the
    `+++ ADDED` line's annotation become
    `b/<posix> (upstream <provenance-posix>, themed)`; otherwise they stay byte-identical to today
    (`b/<posix> (upstream)` and the bare `(NET-NEW)` marker).
  - Docstring both keywords with **why they exist**, not just what they do:
    - `summary`: a themed instance calls `render_diff` twice over two different upstream roots
      (a temp themed copy for `agents/`, the real upstream for everything else), so exactly one of
      the two may print the footer. Record the accepted cosmetic cost from W2 above — the three
      sections interleave on the themed path. **Do NOT "simplify" this by making `main()` parse
      or splice `render_diff`'s output**; that trades a defaulted keyword for a format dependency.
    - `provenance`: display-only. State explicitly that **no correctness depends on it**, that a
      file the map does not cover (`agents/orchestrator.md` — themed content, unthemed name)
      correctly gets no note, and why the operator wants it (a themed diff is rendered in
      philosopher vocabulary, which costs them the ability to locate the upstream file).
  - **Do not touch** `plan_sync`, `apply_sync`, `_files_equal`, `_read_text`, or `main()`.

  **Files**: `scripts/sync_from_upstream.py`

  **Acceptance criteria**:
  - `RenderDiffTest` (`tests/test_sync_from_upstream.py:112-160`) passes **unedited**; the default
    call produces byte-identical output to today, including the footer and no annotations.
  - Full suite green at baseline.
  - `git diff` shows changes inside `render_diff` only.

  **QA scenarios**:
  1. A plan with one updated file, `summary=False`: output has no `net-new:` line and is otherwise
     identical.
  2. Same plan with `provenance={"agents/plato.md": "agents/planner.md"}` and `rel` matching:
     the `+++` header line reads `b/agents/plato.md (upstream agents/planner.md, themed)`.
  3. Full suite green.

---

- [ ] **3. `[#137]` Run `apply_theme`'s residue check after every non-dry-run pass**

  **Complexity**: standard

  **Closes**: noctua84/nescio-ai#137 — **not** #133. Keep it in its own commit with its own
  `fix(theme):` subject so the two issues stay separable in history.

  **Depends on**: T1 (same file; T1's import rewire must land first)

  **What to do**:
  - **The bug**, verified: `apply_theme.py:304-326` re-asks `desynced_agents` only when
    `repairing` is True (`repairing = current == target`, `:227`). On a **direction switch**
    `repairing` is False, so the check never runs and the script exits 0 over a tree it left
    broken. Reproduced: a synthetic out-of-roster `agents/reviewer-lite.md` becomes
    `pyrrho-lite.md` still declaring `name: reviewer-lite` — an agent that does not load — and the
    run reports `switched crew: functional -> philosophers` and exits 0.
  - Move the residue check **out of** `if repairing:` so it runs after **every non-dry-run pass**,
    in both directions. Keep the dry-run exemption exactly as it is today and keep its reason in
    the comment (`:313-315`: nothing was written, so every desync is trivially still present and a
    re-check could only report a failure the run never attempted).
  - Keep the two distinct success messages (`converged crew onto...` vs `switched crew: X -> Y`)
    and the error wording unchanged. Only the *gating* moves.
  - Extend the comment block at `:304-315` to say **why the gate was wrong**: the claim
    "switched crew" is exactly as much of a claim as "converged crew", and a residue check that
    only guards one of the two guards the wrong half — the repair path is the one the operator
    already distrusts.
  - **Tests go in a NEW file `tests/test_apply_theme_residue.py`, not in
    `tests/test_apply_theme.py`** (the gate). Cover:
    - Synthetic out-of-roster agent, **functional -> philosophers**: seed a copied tree with an
      extra `agents/reviewer-lite.md` declaring `name: reviewer-lite`; the switch must now exit
      non-zero, name `pyrrho-lite.md` and `reviewer-lite` on stderr, and **not** print
      `switched crew`.
    - The **reverse direction** (philosophers -> functional) with the mirror-image synthetic file.
    - **Regression guard**: a *clean* direction switch over the real `agents/` tree still exits 0
      and still prints `switched crew`. Verified currently true — `desynced_agents` is `[]` both
      before and after a philosophers switch of the real tree — and this test is what keeps the
      new check from becoming a false-positive tripwire.
    - **Dry-run**: the dry-run path still exits 0 over the synthetic tree, because it wrote
      nothing. Docstring why that is not a loophole.
    - Theme-agnostic throughout (`tests/test_agent_definitions.py:118-141` pattern); must not read
      this repo's `.github/`.

  **Files**: `scripts/apply_theme.py` (modify), `tests/test_apply_theme_residue.py` (new)

  **Acceptance criteria**:
  - `tests/test_apply_theme.py` passes **unedited** — in particular
    `test_a_desync_the_theme_cannot_fix_is_reported_and_fails`
    (`tests/test_apply_theme.py:231-274`), which exercises the *repair* direction and is
    unaffected, and `ApplyThemeRoundTripTest` (`:79-112`), which switches the real tree in both
    directions and must stay green (R10).
  - Full suite green above baseline.
  - `git diff scripts/apply_theme.py` shows a dedent and a comment extension, no rewording of the
    error text.

  **QA scenarios**:
  1. Copy `agents/` to a temp dir, add `reviewer-lite.md` declaring `name: reviewer-lite`, run
     `apply_theme(tmp, "philosophers")`: exit 2, stderr names `pyrrho-lite.md`.
  2. Same without the synthetic file: exit 0, stdout contains `switched crew`.
  3. Full suite green.

---

- [ ] **4. `[test]` `_theme_common` unit tests and the re-export pin**

  **Complexity**: simple

  **Depends on**: T1

  **What to do**: create `tests/test_theme_common.py`.
  - `theme_representatives` / `detect_theme` over a seeded temp `agents/` dir: zero
    representatives -> `{}` / `None`; one -> the right theme; **both** -> two entries and `None`.
    (These re-pin the classifier at its new home; the originals in `tests/test_apply_theme.py`
    reach it through `apply_theme`, which is a different surface.)
  - `desynced_agents` over a seeded dir: a charter whose `name:` matches its stem is absent from
    the result; one that disagrees is present with its declared name; a charter with no
    frontmatter yields `(name, None)`.
  - **Re-export pin**: assert that `apply_theme.detect_theme`, `apply_theme.desynced_agents`,
    `apply_theme.theme_representatives` and `apply_theme.THEME_REPRESENTATIVES` are the **same
    objects** as the `_theme_common` originals. Docstring: two live test modules and the theme CLI
    reach these through `apply_theme`; the extraction must stay a **re-export, not a fork**, or
    the two copies drift and only one of them is the one `sync_from_upstream` consults.
  - **Negative pin**: assert `_theme_common` does **not** define `apply_theme`, `_mappings` or
    `_transform`. Docstring it: the renderer deliberately stayed behind, and pulling it in later
    "for symmetry" would put the cosmetic module back on an untheme'd instance's import path,
    breaking P1.
  - Theme-agnostic; must not read this repo's `.github/`.

  **Files**: `tests/test_theme_common.py` (new)

  **Acceptance criteria**: all pass; full suite green above baseline.

---

### Wave 3

- [ ] **5. Wire `main()`: classify the dest, refuse, warn, materialise**

  **Complexity**: complex

  **Depends on**: T1, T2

  **What to do**: this is the whole of the change to `scripts/sync_from_upstream.py`'s behaviour.
  Work in `main()` (`:280-338`) and the module docstring (`:1-21`). **Do not modify `plan_sync`,
  `apply_sync`, `_files_equal`, `_iter_files`, `_normalize_newlines` or `_read_text` — not one
  line.** If you believe you must, report **BLOCKED**.

  **Step 0 — imports.** At module level add `import contextlib`, `import io`,
  `import tempfile`, the `sys.path` bootstrap idiom from `apply_theme.py:50-52` if `scripts/` does
  not already resolve, and
  `from _theme_common import desynced_agents, detect_theme, theme_representatives`.
  **`apply_theme` and `renamed_agents` are NOT imported at module level** — see step 5.

  **Step 1 — decision 2: refuse a both-representatives dest.** After the three existing
  checkout/identity guards (`:299-309`): `reps = theme_representatives(dest / "agents")`; if
  `len(reps) > 1`, mirror `apply_theme.py:197-206` in wording and shape — name each offending file
  with its theme, state that nothing was changed, `return 2`. This guard is **load-bearing**:
  `detect_theme` returns `None` for such a tree, which would otherwise route it to the untheme'd
  branch and produce a fully destructive plan. Say so in a comment.

  **Step 2 — R7 residual: refuse a themed upstream.** `up_reps = theme_representatives(upstream /
  "agents")`; if it is non-empty and does not consist solely of `"functional"`, print to stderr
  naming the theme(s) and representative file(s), explain that `--upstream` must be a canonical
  (unthemed) framework checkout and that syncing *from* a themed instance produces a fully
  destructive plan in the opposite direction, and `return 2`. Comment the reason this guard
  survives while R1/R2/R3/R5/R6 dissolved: the materialisation branch only runs when the **dest**
  is themed, so it cannot catch a themed upstream against an **untheme'd** dest. Note it costs one
  `theme_representatives` call and **no import of the cosmetic module**, so P1 holds.

  **Step 3 — classify, and take today's path when untheme'd (P1).**
  ```python
  theme = detect_theme(dest / "agents")
  if theme in (None, "functional"):
      added, updated, deleted = plan_sync(upstream, dest)
      diff_text = render_diff(upstream, dest, added, updated, deleted) if args.diff else ""
      if args.apply:
          apply_sync(upstream, dest)
      return _report(args, added, updated, deleted, diff_text, theme=None)
  ```
  This branch must be **literally today's four lines** — one `plan_sync` with no `paths=`, one
  `render_diff` with no keywords, one `apply_sync`. No temp dir is created and
  `scripts/apply_theme.py` is never imported. Comment it as the P1 requirement, naming what would
  be lost by "unifying" the two branches (a `paths=` split whose correctness depends on `"agents"`
  being first in `FRAMEWORK_PATHS`, plus a temp-dir and a cosmetic-module import for an instance
  that has no theme).

  **Step 4 — decision 3: warn on a half-renamed dest, and proceed.**
  `desynced = desynced_agents(dest / "agents")`; if non-empty, print to **stderr** naming every
  file and its declared `name:`, pointing at `python scripts/apply_theme.py <theme>`, and saying
  **explicitly that the sync will proceed**. Comment the *reason* it warns rather than refuses: a
  cosmetic inconsistency must not block a legitimate framework sync — and note that this is where
  the implementation deliberately diverges from issue #133's original proposal.

  **Step 5 — the lazy renderer import (refuse loudly on failure).**
  ```python
  try:
      from apply_theme import apply_theme as _render_crew   # noqa: E402  (lazy on purpose)
      from _crew_common import renamed_agents               # noqa: E402
  except ImportError as exc:
      print(f"error: this instance is on the '{theme}' theme, but the theme renderer "
            f"(scripts/apply_theme.py) could not be imported: {exc}", file=sys.stderr)
      print("refusing to sync: without it the plan would compare functional upstream names "
            "against themed instance names and report every agent as both added and deleted.",
            file=sys.stderr)
      return 2
  ```
  **Do NOT add an identity fallback.** Comment why, in the words of the module docstring: a
  fallback whose failure mode is a destructive 11-added/11-deleted plan is not degradation.
  Comment why the import is *here* and not at module scope: P1 — an untheme'd instance must never
  touch the cosmetic module.

  **Step 6 — materialise and run today's code.**
  ```python
  OTHERS = [p for p in FRAMEWORK_PATHS if p != "agents"]

  with tempfile.TemporaryDirectory() as tmp:
      root = Path(tmp)
      shutil.copytree(upstream / "agents", root / "agents")
      # Cheap structural guard, replacing the previous design's 13-file scope test:
      # only agents/ is ever copied, so the renderer physically cannot reach
      # scripts/_crew_common.py's PAIRS — the transform that would make the theme
      # permanently unrevertable in every instance that syncs.
      assert [p.name for p in root.iterdir()] == ["agents"]

      out, err = io.StringIO(), io.StringIO()
      with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
          rc = _render_crew(root / "agents", theme)
      if rc != 0:
          print(f"error: could not render upstream's crew ({upstream}) into the "
                f"'{theme}' theme — refusing to sync. The renderer reported:", file=sys.stderr)
          print(err.getvalue(), end="", file=sys.stderr)
          return 2
      # rc == 0: discard both streams. 13 stdout lines of rename chatter about a
      # temp directory would be noise in the middle of the sync's own output.

      a1 = plan_sync(root, dest, paths=["agents"])
      a2 = plan_sync(upstream, dest, paths=OTHERS)
      added, updated, deleted = (x + y for x, y in zip(a1, a2))

      prov = {str(Path("agents") / f"{dst}.md"): str(Path("agents") / f"{src}.md")
              for src, dst in renamed_agents(theme)}
      diff_text = ""
      if args.diff:
          diff_text = (render_diff(root, dest, *a1, summary=False, provenance=prov)
                       + render_diff(upstream, dest, *a2, summary=False))
          if diff_text:
              diff_text += (f"net-new: {len(added)} added file(s), {len(updated)} updated, "
                            f"{len(deleted)} deleted\n")
      if args.apply:
          apply_sync(root, dest, paths=["agents"])
          apply_sync(upstream, dest, paths=OTHERS)

      return _report(args, added, updated, deleted, diff_text, theme=theme)
  ```
  - The `with` block **must span plan -> diff -> apply**. `apply_sync` re-plans internally and
    re-reads `root`, so the temp tree cannot be released early. Comment that.
  - `a1` **first** in every concatenation: `"agents"` is first in `FRAMEWORK_PATHS`, so this
    reproduces today's ordering. Comment it as a dependency, not a coincidence — T8 pins it.
  - **Do NOT filter, suppress or special-case any entry** (R4). `plan_sync` is unmodified; there is
    nowhere to put a filter and there must not become one.

  **Step 7 — the reporting tail.** Extract `:317-338` (the total/summary/listing/diff/hint block)
  into a private `_report(args, added, updated, deleted, diff_text, *, theme)` used by **both**
  branches, so the two cannot drift in output format. Changes inside it:
  - When `theme` is not `None`, print one line before the plan summary naming the detected theme,
    so the operator can see which rendering produced the numbers they are about to act on.
  - **Fix the post-apply hint at `:333-335`.** It currently tells the operator to re-run
    `apply_theme.py philosophers`. Under route A the themed rendering was written directly, so
    that is now a no-op and saying it is misleading. Replace it with text saying so, and keep the
    "memory/ and all non-framework paths were left untouched" sentence intact.

  **Step 8 — rewrite the module docstring** (`:1-21`). Keep everything it says about the overlay
  and the allowlist, **correct lines 19-20** (which advertise the manual re-render), and add, each
  as its own paragraph:
  - **What theme-awareness means here**, and the framing that produced it: the comparison does not
    need to know about the theme; it needs an upstream that is already in dest-space. So a themed
    instance materialises a themed copy of upstream's `agents/` in a temp directory using the
    *existing* renderer and runs the ordinary, unmodified sync against it. State plainly that
    `plan_sync` / `apply_sync` / `_files_equal` are untouched by this feature, and that **the
    deletion-mirroring safety property is therefore preserved structurally rather than by
    discipline** (R4).
  - **Why the untheme'd path is a separate branch** (P1) and what a "unified" version would cost.
  - **Why the renderer is imported lazily** and why an ImportError refuses rather than degrades.
  - **R8 bootstrap**: this script, `apply_theme.py`, `_crew_common.py` and the new
    `_theme_common.py` all live inside the synced `scripts/` allowlist, so the running script is
    the *dest's* copy — the first sync carrying this fix is noisy, only the second is clean.
    Deliberate; not engineered around.
  - **R8 second half**: the rendering uses **dest's** `apply_theme.py` / `PAIRS`, not upstream's;
    a new or retargeted pair converges only on a later pass, and a retargeted pair leaves an orphan
    that `desynced_agents` cannot see because it is self-consistent.
  - **R9**: the many-to-one mapping makes an upstream edit of exactly `planner` -> `plato`
    invisible. A chosen property.
  - **Route D**, one paragraph: considered, infeasible — Claude Code loads charters from real files
    at `agents/<name>.md` with no name-resolution hook.
  - **The near-miss**: calling `apply_theme` on the *dest* as a post-sync step fixes nothing,
    because the *plan* is the broken artefact and the dry run never calls `apply_sync` at all.
    Distinguish it explicitly from what this does — render a **temp copy of upstream, before
    planning**.

  **Files**: `scripts/sync_from_upstream.py`

  **Acceptance criteria**:
  - `tests/test_sync_from_upstream.py` passes **unedited**. Its fixtures seed only
    `agents/explore.md` (zero representatives), so every one of them takes the untheme'd branch.
  - `git diff scripts/sync_from_upstream.py` shows **no change** to `plan_sync`, `apply_sync`,
    `_files_equal`, `_iter_files`, `_normalize_newlines` or `_read_text`.
  - Reproduction harness prints `framework already in sync — nothing to do.` and exits 0.
  - A dest holding both `planner.md` and `plato.md` exits 2, names both, writes nothing.
  - A themed `--upstream` against an untheme'd dest exits 2.
  - Full suite green at baseline.

  **QA scenarios**:
  1. Reproduction harness -> `framework already in sync — nothing to do.`, exit 0.
  2. Reproduction harness with `plato.md` copied back to `planner.md` in dest -> exit 2 naming both.
  3. Reproduction harness with `--upstream` and `--dest` swapped -> exit 2 on the step-2 guard.
  4. Half-renamed dest (rename `plato.md` back to `planner.md` *without* rewriting its `name:`) ->
     stderr warning naming the file, sync proceeds, exit 0.
  5. Reproduction harness with `--diff` after a real upstream edit: exactly **one** `net-new:` line
     in the output, and no `renamed ... -> ...` chatter anywhere.
  6. Full suite green.

---

### Wave 4 — tests (all five run in parallel; each creates its own new file)

Every task in this wave: new module in `tests/`, `test_*.py`, stdlib `unittest` only,
**theme-agnostic** (do not assume this repo is on the functional theme — copy the
`_current_theme` / `_themed` pattern at `tests/test_agent_definitions.py:118-141`), and **must not
read this repo's `.github/`** (`docs_site/test_ci_coverage.py:20-34` explains why: `tests/` ships
downstream). No workflow edit is required.

**None of these tasks may edit `tests/test_apply_theme.py` or `tests/test_sync_from_upstream.py`.**
If a task believes it must, that is a signal the implementation drifted — report **BLOCKED**.

- [ ] **6. `[test]` The two contract tests, the headline case, and the identity path**

  **Complexity**: standard

  **Depends on**: T5

  **What to do**: create `tests/test_sync_theme_contract.py`.
  - Helper: build a temp "upstream" by copying this repo's real `agents/` (converged to
    `functional` first if the repo is themed) plus a minimal `install.py`, and a temp "dest" by
    copying the same tree and running `apply_theme.apply_theme(dest_agents, "philosophers")`.
  - **Contract test (a)**: sync a functional upstream into a themed dest, then run
    `apply_theme.apply_theme(dest / "agents", "philosophers")` and assert it (i) returns 0,
    (ii) prints `already on the '<theme>' theme — nothing to do.`, and (iii) **changes zero bytes**
    (snapshot the whole tree before and after and compare byte-for-byte).
  - **Contract test (b)**: an in-step themed instance produces an empty plan — three empty lists
    across the two `plan_sync` calls (drive it through `main()`'s dry run, or replicate the split;
    assert the combined triple).
  - Headline case: `main(["--upstream", ..., "--dest", ...])` dry run prints
    `framework already in sync — nothing to do.` and returns 0.
  - **Identity path (P1)**: a dest with **zero** representatives (seed only `agents/explore.md`)
    produces a plan byte-identical to today's, and — the stronger assertion — the run creates no
    temporary directory and never imports the renderer. Assert the second half by monkeypatching
    `tempfile.TemporaryDirectory` in the module under test to raise, and confirming the untheme'd
    run still succeeds. Docstring it: this is P1, and it is what the previous design could only
    approximate with an identity lens.
  - **Docstring the class**: contract (a) and (b) are the whole invariant. If either can go red,
    the design has drifted — the correct response is to fix the implementation, never the test.

  **Files**: `tests/test_sync_theme_contract.py` (new)

  **Acceptance criteria**: all pass; full suite green; test count rises above 751.

  **QA scenarios**: deliberately skip the `_render_crew` call in the themed branch and confirm
  contract test (a) goes red; revert.

---

- [ ] **7. `[test]` Deletion mirroring and addition through the materialised upstream**

  **Complexity**: standard

  **Depends on**: T5

  **What to do**: create `tests/test_sync_theme_mirroring.py`.
  - Upstream genuinely deletes `agents/qa-guard.md` -> the themed dest's `agents/cato.md` **is**
    reported deleted **and is removed** by `--apply`. (Verified in the spike:
    `deleted=['agents/cato.md']`.) Docstring it as the R4 safety property, and note that it holds
    because `plan_sync` is the same unmodified function it is today.
  - Upstream genuinely adds a new charter (e.g. `agents/newbie.md` whose body mentions `planner`
    and `reviewer`) -> reported added, written with **themed content** (assert the written bytes
    contain `plato` / `pyrrho` and neither `planner` nor `reviewer`).
  - No dest path ever appears in both `added` and `deleted` for the same run.
  - `agents/` files that the theme renames appear under their **themed** names in the plan and
    nowhere under their functional names.
  - Theme-invariant charters (`orchestrator.md`, `scout.md`, `validator.md`) appear at most once
    each and under their own unchanged filenames.

  **Files**: `tests/test_sync_theme_mirroring.py` (new)

  **Acceptance criteria**: all pass; full suite green.

---

- [ ] **8. `[test]` Real changes are still reported, and the R9 chosen property**

  **Complexity**: standard

  **Depends on**: T5

  **What to do**: create `tests/test_sync_theme_updates.py`.
  - A real upstream content change to a themed instance's charter -> still reported `updated`, and
    `--apply` writes the new themed bytes.
  - A real upstream change to **exactly the words the theme rewrites** (e.g. `advisor` -> `critic`
    in `agents/orchestrator.md`, which renders as `aristotle` -> `socrates`) -> still reported
    `updated`.
  - A change to one of the three theme-invariant charters -> reported once, under its own unchanged
    filename (R3), and applied with **themed** content, so `subagent_type:` dispatch still resolves
    against the files actually on disk.
  - **R9 pin, as a documented expectation**: an upstream edit that changes exactly
    `planner` -> `plato` in a charter body renders identically and is **not** reported. Assert the
    current behaviour and docstring it as the chosen property from the module docstring, not as a
    defect. Name it `test_a_change_the_mapping_collapses_is_deliberately_invisible`.

  **Files**: `tests/test_sync_theme_updates.py` (new)

  **Acceptance criteria**: all pass; full suite green.

---

- [ ] **9. `[test]` The four theme states, the themed-upstream refusal, and the refusal on `rc != 0`**

  **Complexity**: standard

  **Depends on**: T5

  **What to do**: create `tests/test_sync_theme_guards.py`. Drive `sfu.main([...])` with
  `contextlib.redirect_stdout` / `redirect_stderr` and assert on return codes and message content.
  - **Both representatives in dest** (decision 2) -> returns 2, stderr names both `planner.md` and
    `plato.md`, and **nothing was written** (snapshot the dest tree before/after, byte-for-byte).
  - **Half-renamed dest** (decision 3: one representative, `desynced_agents` non-empty) -> **warns**
    on stderr, names the offending file(s), mentions `apply_theme.py`, **returns 0**, and the sync
    proceeds (assert a genuine pending change was applied under `--apply`).
  - **Zero representatives** (decision 4) -> no warning, today's behaviour.
  - **Functional dest** -> no warning, today's behaviour.
  - **Themed upstream, untheme'd dest** (R7 residual) -> returns 2, stderr names the theme,
    nothing written.
  - **P2 — `rc != 0` refuses.** The fixture must **survive T5 step 2** and still fail the render,
    or the test proves nothing about the `rc != 0` path. A both-representatives upstream does NOT
    qualify — step 2 rejects it earlier. Use either of these two, both verified:
    (a) an upstream `agents/` with **neither** representative -> step 2 sees `{}` and passes,
    then `apply_theme` returns 2 with "could not detect the crew" (`apply_theme.py:207-211`); or
    (b) an upstream carrying **both** `agents/qa-guard.md` and `agents/cato.md`, with only
    `planner.md` as a representative -> `theme_representatives` is `{'functional': 'planner.md'}`
    so step 2 passes, then the all-or-nothing rename pre-flight returns 2 ("1 rename destination(s)
    already exist"). In either case the sync must return **2**, surface that stderr, and write
    nothing.
    Docstring: this is what makes the rename-collision class free — one renamer, and it is the one
    with the all-or-nothing pre-flight (`scripts/apply_theme.py:238-260`). **This must never be
    softened to a warning.**
  - **Ordering pin**: on a themed instance with pending changes in both `agents/` and another
    allowlist path, the reported entries list all `agents/` entries before the others, matching
    today's `FRAMEWORK_PATHS` order. Docstring it: the split relies on `"agents"` being first.

  **Files**: `tests/test_sync_theme_guards.py` (new)

  **Acceptance criteria**: all pass; full suite green.

---

- [ ] **10. `[test]` Hygiene: output capture, temp-dir scope and cleanup, `--diff`, CRLF**

  **Complexity**: standard

  **Depends on**: T5

  **What to do**: create `tests/test_sync_theme_hygiene.py`.
  - **W1 — capture.** On a successful themed run, neither stdout nor stderr contains any of
    `apply_theme`'s chatter: no `renamed `, no `switched crew`, no `would update refs in`, no
    `expected `…` not found`. Docstring: 13 stdout lines were verified on a normal render, and a
    genuine upstream deletion also puts a line on stderr; both describe a temp directory the
    operator has never heard of.
  - **W1 — surfaced on failure.** Covered in T9's P2 case; here just assert the *framing* line is
    present before the captured text, so the operator is told which `--upstream` the error is about.
  - **R2 replacement — the temp root holds only `agents/`.** Assert the structural guard: run a
    themed sync against an upstream that also has `scripts/_crew_common.py` and confirm the dest's
    `scripts/_crew_common.py` after `--apply` is **byte-identical to upstream's**, i.e. its `PAIRS`
    were not transformed. Docstring: transforming `PAIRS` into `[("plato","plato"), ...]` makes
    `themed_name` the identity and **the theme permanently unrevertable in every instance that
    syncs**. It is unreachable here only because `scripts/` is never copied into the temp root —
    a structural fact, so this is a cheap pin rather than the 13-file audit the lens design needed.
  - **Cleanup.** The temporary directory does not survive the call — capture the path (e.g. by
    wrapping `tempfile.TemporaryDirectory`) and assert it no longer exists after `main()` returns,
    on the success path **and** on the `rc != 0` refusal path.
  - **`--diff` on a themed instance.** With a pending update: `render_diff` does **not** raise
    (this was the previous design's confirmed `FileNotFoundError`, now impossible because the plan
    strings name real files under the temp root), the paths it renders are exactly the plan's, and
    the output contains **exactly one** `net-new:` line (W2).
  - **Provenance header (W3).** An upstream edit to `agents/planner.md` yields a diff headed
    `b/agents/plato.md (upstream agents/planner.md, themed)`; an edit to `agents/explore.md`
    yields the plain `b/agents/explore.md (upstream)`.
  - **CRLF (R6).** A CRLF themed dest holding the same themed text as the rendered upstream reads
    as **not updated**. Docstring: this holds because `_files_equal` is untouched and the temp copy
    is written by `copy2` and the existing renderer's `newline=""` writes — but pin it anyway,
    because it is the exact failure `LineEndingTest` exists for.

  **Files**: `tests/test_sync_theme_hygiene.py` (new)

  **Acceptance criteria**: all pass; full suite green.

---

### Wave 5 — documentation (parallel; different files)

- [ ] **11. Rewrite the README's theme/sync claim**

  **Complexity**: simple

  **Depends on**: T5

  **What to do**: `README.md:261-264` currently reads "**The philosopher theme is rendered, not
  committed.** After a sync, if you use the philosopher theme, re-apply it with `python
  scripts/apply_theme.py philosophers` — the framework ships the functional names, and the theme is
  a local render step, so syncs never fight your renames."

  That is **wrong today** (syncs fight the renames on every run) and would be **stale after this
  change**. Rewrite it — do not delete it. The replacement must say:
  - The framework still ships functional names; the theme is still a local render.
  - The sync is now theme-aware: it detects the instance's theme, renders a temporary copy of
    upstream's crew into that theme, and compares (and writes) against it — so a themed instance in
    step with upstream sees an empty plan and `apply_theme.py` afterwards is a no-op.
  - **The bootstrap caveat (R8)**: because the sync scripts themselves are synced, the *first*
    sync that carries this fix still reports the old noise; the second is clean.
  - Keep the surrounding bullet style and the existing anchor link to
    `#optional-the-philosopher-theme`.

  **Files**: `README.md`

  **Acceptance criteria**: no claim in the section is false after this change; the anchor still
  resolves; full suite green (the docs tests read this file).

---

- [ ] **12. Update `ROADMAP.md`**

  **Complexity**: simple

  **Depends on**: T5

  **What to do**: `ROADMAP.md:44` currently reads "Overlay-sync for downstream instances
  (`sync_from_upstream`, with a `--diff` preview)." Extend it to record that the overlay sync is
  theme-aware. Then run:
  ```bash
  python scripts/check_roadmap_drift.py --offline
  ```
  and confirm it is green. **`--offline` is required locally** (verified at
  `scripts/check_roadmap_drift.py:75`, `:1147`, `:1195-1199`): without it the script reconciles
  against GitHub, which needs `gh` plus network and exits 2 on an outage. CI runs it online; the
  offline checks are the ones a `ROADMAP.md` edit can break.

  **Files**: `ROADMAP.md`

  **Acceptance criteria**: `python scripts/check_roadmap_drift.py --offline` green; full suite
  green.

  **Note**: `CONTRIBUTING.md:64-70` stays true and is unaffected — **do not touch it**.

---

### Wave 6 — verification gate

- [ ] **13. Full verification and commit**

  **Complexity**: standard

  **Depends on**: T1-T12

  **What to do**:
  - Run the reproduction harness end to end and confirm `framework already in sync — nothing to do.`
  - Run the harness again with `--diff` after a real upstream edit; confirm exactly one `net-new:`
    line and no renderer chatter.
  - Run `python -m unittest discover -s tests -t tests 2>&1 >/dev/null | tail -20`; confirm OK and
    a count **above** the 751 baseline.
  - Run `python -m unittest discover -s docs_site 2>&1 >/dev/null | tail -20` and
    `python -m unittest discover -s brand 2>&1 >/dev/null | tail -20`; confirm both green.
  - Run `python scripts/check_roadmap_drift.py --offline`; confirm green.
  - `git diff --stat` and confirm: **`tests/test_apply_theme.py` and
    `tests/test_sync_from_upstream.py` are not in the diff at all** (R10 and the gate).
  - `git diff scripts/sync_from_upstream.py` and confirm **`plan_sync`, `apply_sync`,
    `_files_equal`, `_iter_files`, `_normalize_newlines` and `_read_text` are unchanged**. This is
    the structural claim the whole design rests on; verify it, do not assume it.
  - Confirm `ApplyThemeRoundTripTest` still copies the real `agents/` tree and was not narrowed to
    a fixture.
  - Commit with conventional-commit messages, one commit per coherent unit. Keep **#137 in its own
    commit**, separate from the #133 work, so the two issues stay separable:
    - `fix(theme): verify the residue check after every apply_theme pass, not only repairs` (#137)
    - `fix(sync): make the overlay sync theme-aware by materialising a themed upstream` (#133)
    - plus the tests and docs commits.
  - Do **not** implement noctua84/nescio-ai#138.

  **Files**: none modified (verification only, plus git)

  **Acceptance criteria**: every check above green; branch `fix/theme-aware-sync-plan` holds the
  work; nothing committed to `main`.

---

## Success criteria

1. The reproduction harness prints `framework already in sync — nothing to do.` — the 11/3/11 is
   gone.
2. **Contract (a)**: after a themed `--apply` from a functional upstream, `apply_theme.py <theme>`
   reports "already on the theme — nothing to do" and changes zero bytes.
3. **Contract (b)**: an in-step themed instance's plan is three empty lists.
4. **P1**: an untheme'd instance runs literally today's code — one `plan_sync`, no temp dir, no
   import of `scripts/apply_theme.py` — and `tests/test_sync_from_upstream.py` and
   `tests/test_apply_theme.py` pass with **zero edits**.
5. **Structural**: `git diff` shows `plan_sync`, `apply_sync` and `_files_equal` unchanged.
6. Deletion mirroring is intact: upstream deleting `agents/qa-guard.md` still deletes the themed
   instance's `agents/cato.md`.
7. Nothing outside `agents/` is ever transformed — unreachable by construction, pinned cheaply.
8. All three theme-invariant charters receive themed **content**, so `subagent_type:` dispatch
   keeps resolving.
9. **P2**: an upstream whose crew cannot be rendered (`rc != 0`) refuses with exit 2 and the
   renderer's own message; a both-representatives dest refuses; a themed upstream against an
   untheme'd dest refuses; a half-renamed dest warns and proceeds; a crewless or functional dest
   behaves exactly as today.
10. `apply_theme`'s output never leaks into sync output, and the temp directory never survives the
    call.
11. **#137** is closed by its own commit: `apply_theme` verifies its residue after every
    non-dry-run pass, in both directions.
12. The full suite is green above the 751 baseline, plus `docs_site` and `brand`, plus
    `check_roadmap_drift.py --offline`.
13. Every non-obvious decision above is argued in a docstring, in the style the existing modules
    set — including the ones that argue against plausible simplifications.

---

## What was removed relative to the previous draft

Recorded so a reader who saw the old plan knows these were deliberately dropped, not forgotten.

- **`ThemeLens`, `theme_lens`, `IDENTITY_LENS`, `ThemeRenderConflict`** — the whole lens seam.
- **`_source_map`** and the `dest_rel -> upstream_rel` association (R1's "decided shape", its
  three-walks cost, and the rejected triple-of-pairs alternative).
- **`themed_stem`** and the entire `themed_stem` vs `themed_name` / `renamed_agents` argument.
  `apply_theme`'s own rename list is the only renamer now.
- **`_content_equal`** extracted from `_files_equal`.
- **Moving `_mappings` / `_transform` into `_theme_common.py`** — they stay in `apply_theme.py`.
- **The lens's `_in_scope` predicate** and the 13-file R2 scope-guard test, replaced by the
  structural "only `agents/` is copied" fact plus one cheap assertion.
- **The standalone R5 rename-collision pre-flight** — `apply_theme.py:247-260` is it.
- **The standalone R7 themed-upstream guard for the themed-dest case** — subsumed by `rc != 0`.
  A *reduced* version survives for the themed-upstream/untheme'd-dest case only.
- **The optional `renamed (theme)` display section** (old T16).
- **Five tasks collapsed into one**: old T2 (`_content_equal`), T3 (lens + `_source_map`),
  T4 (thread through plan/apply), T5 (thread through diff) and T6 (`main()`) are now a single
  `main()`-only task, T5.
- **Old T11** (`tests/test_sync_theme_scope.py`, the 13-file audit) and **old T12's `themed_stem`
  unit tests**.

Added relative to the previous draft: **T3** (issue #137, user-approved for this PR) and the
output-capture / temp-dir-lifetime / `rc != 0` coverage in T10 and T9.
