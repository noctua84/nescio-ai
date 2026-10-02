# #70 — Derive a clean/flagged/unknown session verdict from the transcript

## TL;DR

> Add `scripts/_session_verdict.py`: a stdlib-only module that streams a
> session's transcript, counts `tool_use` blocks and `tool_result` blocks with
> `is_error is True`, and returns one of `clean` / `flagged` / `unknown` using
> `MIN_TOOL_CALLS = 30` and `FLAG_ERROR_RATE = 0.07`. Wire it into
> `compute_readiness.py` so the generated block's `### Outcome summary` reports
> three counts instead of the `INSUFFICIENT_OUTCOME` placeholder, and
> `## Recurring flags` reports erroring tool names (never error text). Locate
> transcripts by `transcript_path` first and by `session_id` glob second — the
> latter lifts backfill coverage from 11% of trail records to 99% of trail
> sessions. Every failure path returns `unknown`; `"clean"` is produced at
> exactly one return site and a test pins that count at 1.

## Context

`readiness.md`'s outcome section has rendered an explicit insufficient-data
block since #42 (`scripts/compute_readiness.py:146-157`) because no verdict
existed. #66 added `transcript_path` to every trail record
(`hooks/record_stop.py:225`), which makes derivation possible at harvest time.
#32 (earned per-repo autonomy dial) is blocked on this.

The decision record is **`memory/repo/nescio/adr/0004-session-verdict-from-transcript.md`**
(written alongside this plan). Read it before starting — it carries the
measured distributions, the rejected alternatives, and the reasoning behind
both constants. This plan implements that ADR and does not re-open it.

### The inviolable constraint

**A missing, unreadable, or too-small verdict must resolve to `unknown`, never
to `clean`.** A false `clean` silently raises a repo's autonomy cap and is
indistinguishable from a genuinely good record. Every task below is subordinate
to this.

### Measured facts this plan is built on (2026-09-04, `~/.claude/projects`)

- 3,119 transcript files, 1,569 MB, but only **312 distinct sessions** — 2,807
  files are subagent transcripts carrying the parent's `sessionId`.
- Full structural parse of the whole corpus: **11.4 s**. Cost is a non-issue at
  harvest time. **No cache is designed** (ADR 0004, Decision-adjacent note).
- Result-block shape: `{"type":"tool_result","tool_use_id","content","is_error"}`.
  In the 40 largest transcripts: 10,276 `is_error: false`, 4,649 with the key
  **absent**, 368 `is_error: true`. The predicate must be `is True`.
- Session-level distribution (parent transcript only, floor 30, n=249):
  p50=0.028, p90=0.061, **p95=0.073**, p99=0.118, max=0.143.
  Threshold 0.07 flags **16 sessions (6.4%)**; 63 of 312 sessions (20%) fall
  below the floor and are `unknown`.
- Trail: 3,534 records, **372 (11%) carry `transcript_path`** (all 372 resolve
  today), but **190 of 192 distinct `session_id`s (99%)** have a transcript at
  `~/.claude/projects/*/<session_id>.jsonl`.

### Environment / hazards

- Stdlib only, Python 3.13 (ADR 0001). No new dependency, no `pyproject` change.
- Baseline: `PYTHONPATH=scripts python -m unittest discover -s tests` → **750 OK**.
  Also `python -m unittest discover -s docs_site` → **80 OK**. Both must stay green.
- **#83/#84 CRLF**: `newline=""` on every read and write.
- **#71 cp1252 stdout**: `sys.stdout.reconfigure(encoding="utf-8")` already
  guarded in `compute_readiness.main()`; any new glyph in the report is covered.
- **#95 Git-Bash ERE traps**: avoid clever shell regex in any helper script.
- **#121/#125**: `compose()` now returns `(text_or_None, disposition)` and
  refuses on malformed markers. Do not change that contract.

## Work Objectives

1. Derive a per-session verdict from the session's own transcript, with three
   states and no path that defaults to `clean`.
2. Aggregate per repo and replace `INSUFFICIENT_OUTCOME` in the generated block.
3. Populate `## Recurring flags` from tool names and counts only.
4. Expose the three counts to #32 via `--json`, with no ratio field.
5. Recover pre-#66 outcome history by `session_id` backfill.

### Explicit non-goals

- **No verdict cache.** 11.4 s corpus-wide; a cache adds an invalidation path in
  which a stale `clean` can outlive the code that produced it.
- **No subagent (`agent-*.jsonl`) transcripts.** ADR 0004 Decision 5 — accepted,
  measured blind spot (72% of tool calls) with a named reopen trigger.
- **No un-harvested-only filter in v1.** Legitimate cheap win, unnecessary now;
  tracked as follow-up F1 below.
- **No change to `hooks/record_stop.py`.** The Stop hook's hot path stays a
  single O_APPEND write and never opens a transcript.
- **No turn-level verdict.** The unit is the session (ADR 0004 Decision 4).

## Verification Strategy

Every task states its own acceptance criteria. Globally, a task is done when:

1. `PYTHONPATH=scripts python -m unittest discover -s tests` is green and the
   test count has **increased** from 750 (never decreased).
2. `python -m unittest discover -s docs_site` is still 80 OK.
3. New tests use `tempfile` fixtures — **never** the operator's real
   `~/.claude/projects`. Tests must pass on a machine with no transcripts.
4. `python scripts/compute_readiness.py` (dry run, no `--apply`) runs clean
   against the real corpus and its output is eyeballed against the ADR's
   expected counts before any `--apply`.

## Execution Strategy

```
WAVE 1  (parallel, 2 tasks)      T1 core module        T2 transcript fixtures
                                       |                      |
                                       +----------+-----------+
                                                  |
WAVE 2  (parallel, 2 tasks)          T3 verdict tests    T4 resolution tests
                                                  |
WAVE 3  (SEQUENTIAL — same file)   T5 -> T6 -> T7   (all edit compute_readiness.py)
                                                  |
WAVE 4  (parallel, 3 tasks)      T8 readiness tests   T9 docs   T10 corpus smoke
                                                  |
WAVE 5  (single)                        T11 index regen + final gate
```

Wave 3 is deliberately sequential: T5, T6 and T7 all edit
`scripts/compute_readiness.py` and would conflict. Everything else parallelises.

---

## TODOs

- [ ] **1. `_session_verdict.py` — the derivation core**

  **What to do**: Create `scripts/_session_verdict.py`, stdlib only
  (`json`, `os`, `pathlib`, `typing`). Module docstring in the house style
  (see `scripts/_trail_scope.py` and `scripts/_marker_block.py`) stating the
  inviolable constraint in the first paragraph.

  Public surface:

  ```python
  MIN_TOOL_CALLS = 30       # below this the rate is noise -> unknown
  FLAG_ERROR_RATE = 0.07    # strictly greater than this -> flagged

  class Verdict(NamedTuple):
      state: str            # "clean" | "flagged" | "unknown"
      calls: int
      errors: int
      rate: float | None    # None when calls == 0
      reason: str           # "" unless state == "unknown"
      tools: dict[str, int] # erroring tool name -> error count

  def scan_transcript(path) -> tuple[int, int, dict[str, int]]   # raises OSError
  def classify(calls, errors, tools) -> Verdict                  # pure
  def find_transcript(session_id, transcript_path, projects_dir) -> Path | None
  def verdict_for_session(session_id, transcript_path, projects_dir) -> Verdict
  ```

  Implementation requirements, each of which is separately load-bearing:

  - **Stream, never `read_text()`.** Iterate the open file handle line by line.
    The largest transcript is 26.8 MB and a `MemoryError` must never be the
    thing standing between a bad session and a `clean` verdict.
  - Open with `encoding="utf-8", newline="", errors="replace"`. `newline=""`
    for #83/#84; `errors="replace"` so one bad byte does not turn a real
    session into `unknown`. `.strip()` each line before `json.loads`.
  - Skip: blank lines, `json.JSONDecodeError`, records that are not `dict`,
    records whose `message` is not a `dict`, and `message.content` that is not
    a `list`. None of these raise.
  - Count a call for each block with `block.get("type") == "tool_use"`; record
    `block["id"] -> block["name"]` so errors can be attributed to a tool name.
  - Count an error for each block with `block.get("type") == "tool_result"`
    **and `block.get("is_error") is True`**. Identity check, not truthiness —
    `is_error: false` is present on the majority of blocks and the string
    `"true"` must not count. Attribute it via `tool_use_id` to the tool name,
    falling back to `"?"`.
  - `classify` is pure and total: `calls == 0` → `unknown/no-tool-calls` (no
    `ZeroDivisionError`); `calls < MIN_TOOL_CALLS` → `unknown/below-floor`;
    `errors / calls > FLAG_ERROR_RATE` → `flagged`; else `clean`.
  - `find_transcript` order: (1) `transcript_path` if truthy and
    `Path(...).is_file()`; (2) first match of
    `projects_dir.glob(f"*/{session_id}.jsonl")` that `is_file()`; (3) `None`.
    Guard the glob — a `session_id` containing `/`, `\`, or `..` returns `None`
    rather than escaping `projects_dir`.
  - `verdict_for_session` returns `unknown/no-transcript` when `find_transcript`
    is `None`, and `unknown/unreadable` on `OSError` (covers
    `PermissionError`, `IsADirectoryError`).
  - **Structural rule: the literal `"clean"` is produced at exactly one return
    site**, inside `classify`, reachable only after both guards. No default
    argument, no `or "clean"`, no bare `except` that falls through to a state.

  **Files**: `scripts/_session_verdict.py` (new)

  **Acceptance criteria**: module imports under `PYTHONPATH=scripts`;
  `classify(30, 3, {})` is `flagged`; `classify(30, 2, {})` is `clean`;
  `classify(3, 1, {})` is `unknown` with reason `below-floor` (not `flagged`);
  `classify(0, 0, {})` is `unknown/no-tool-calls`. `grep -c '"clean"'` over the
  module returns 1 for return sites.

  **QA scenarios**: point `scan_transcript` at the real largest transcript
  (26.8 MB) and confirm it completes without materialising the file (check RSS
  stays flat, or simply that it returns in < 1 s).

- [ ] **2. Transcript fixtures**

  **What to do**: Create `tests/fixtures/transcripts/` with small hand-written
  `.jsonl` files matching the *verified* record shape. Independent of T1 — the
  shape is fully specified here, so this runs in parallel.

  Files to create, each a few lines:
  - `clean.jsonl` — 30 `tool_use`, 1 `tool_result` with `is_error: true`
    (rate 0.033 → clean)
  - `flagged.jsonl` — 30 `tool_use`, 4 errors (rate 0.133 → flagged)
  - `boundary_clean.jsonl` — 100 calls, 7 errors (rate exactly 0.07 → clean)
  - `boundary_flagged.jsonl` — 100 calls, 8 errors (0.08 → flagged)
  - `below_floor.jsonl` — 3 calls, 1 error (→ unknown/below-floor)
  - `no_calls.jsonl` — assistant/user records, zero `tool_use`
  - `noise.jsonl` — mixes: `is_error: false`, `is_error` absent,
    `is_error: "true"` (string), a bare `[1,2,3]` line, a `"not json{"` line,
    a record whose `message.content` is a string, a blank line
  - `crlf.jsonl` — byte-identical content to `clean.jsonl` but CRLF-terminated
    (write with `newline=""` and explicit `\r\n`)

  A tiny generator helper in the test module is acceptable and preferred over
  1,000 hand-typed lines — but the *shape* must be the measured one, not
  invented.

  **Files**: `tests/fixtures/transcripts/*.jsonl` (new)

  **Acceptance criteria**: every fixture parses line-by-line with
  `json.loads`; `noise.jsonl` deliberately contains lines that do not.

- [ ] **3. Verdict tests — scanning and classification**

  **What to do**: Create `tests/test_session_verdict.py` covering the scan and
  classify matrix (full table in *Test Matrix* below). Use the T2 fixtures.

  **Files**: `tests/test_session_verdict.py` (new)

  **Acceptance criteria**: all rows of Test Matrix sections A and B pass.
  Includes the boundary tests proving `>` and not `>=`, and the
  `is_error: "true"` string case counting as **not** an error.

- [ ] **4. Verdict tests — resolution, backfill, and the structural pin**

  **What to do**: Create `tests/test_session_verdict_resolve.py` covering
  transcript location and every `unknown` reason. Build a temp `projects/`
  tree with `tempfile.TemporaryDirectory`; **never touch `~/.claude`**.

  Must include the **structural pinning test** (ADR 0004 Decision 6, same
  technique as `tests/test_mark_harvested.py:197`): read
  `scripts/_session_verdict.py` as text and assert the literal `return` of
  `"clean"` occurs exactly once. This is the test that stops a future refactor
  from reintroducing a fallback-to-clean.

  **Files**: `tests/test_session_verdict_resolve.py` (new)

  **Acceptance criteria**: all rows of Test Matrix section C pass, plus the
  structural pin.

- [ ] **5. `compute_readiness` — data layer**

  **What to do**: Edit `scripts/compute_readiness.py`.

  - Import `_session_verdict` alongside the existing `_trail_scope` imports.
  - `collect_activity`: alongside `bucket["sessions"]`, accumulate
    `bucket["session_paths"]: dict[str, str]` mapping `session_id` →
    the **most recent** non-empty `transcript_path` seen for it. Records
    predating #66 contribute nothing, which is what the T1 glob fallback is for.
  - New `derive_outcome(sessions, session_paths, projects_dir) -> dict`
    returning `{"available", "clean", "flagged", "unknown", "sessions",
    "threshold", "min_tool_calls", "unknown_reasons", "flag_tools"}`.
    Memoise per `session_id` within a run so a session shared across many trail
    records is scanned once. `flag_tools` is `{tool_name: [error_count,
    session_count]}` accumulated **only from flagged sessions** — input for T6's
    Recurring flags.
  - **Assert the invariant in code**: `clean + flagged + unknown == sessions`.
    A bare `assert` is fine — it is a programming-error guard, not input
    validation.
  - **Emit no ratio field.** No `clean_rate`, no `pass_rate`. ADR 0004
    Decision 9: a ratio dissolves the `unknown`/`clean` distinction by
    arithmetic.
  - `summarise()`: gain `projects_dir` and `derive: bool = True` params; attach
    `stats["outcome"]`.
  - **`plan()` must filter by `--repo` BEFORE deriving.** Today `plan()` calls
    `summarise()` for every repo and filters after
    (`scripts/compute_readiness.py:508-511`); leaving that order would make
    `--repo x` scan every session on the machine. Restructure so verdict
    derivation only runs for the selected repos.
  - `--json` payload: replace the top-level `"outcome_summary": {"available":
    false, ...}` stub with the per-repo `outcome` object (it already rides along
    in the `repos` list via the `{k: v for k, v in e.items() if k != "new_text"}`
    comprehension — verify it does).

  **Files**: `scripts/compute_readiness.py`

  **Acceptance criteria**: `python scripts/compute_readiness.py --json` emits a
  per-repo `outcome` object whose three counts sum to `sessions`, and contains
  no key matching `rate` other than `threshold`. `--repo <name>` scans only that
  repo's sessions (verify by timing, or by instrumenting the memo dict size).

- [ ] **6. `compute_readiness` — rendering** *(sequential after T5)*

  **What to do**: Edit `scripts/compute_readiness.py`.

  - Delete the `INSUFFICIENT_OUTCOME` constant
    (`scripts/compute_readiness.py:146-157`) and its use in `render_block`
    (`:345`). Delete it outright rather than keeping it for a fallback branch —
    a retained "insufficient" constant is one `if` away from becoming the
    default again.
  - Update the module docstring's `## The outcome summary` section
    (`:59-65`) — it currently states the signal "does not exist". Replace with a
    pointer to ADR 0004 and the two constants.
  - `render_block`: `### Outcome summary (generated)` becomes

    ```
    - Clean sessions: 12
    - Flagged sessions: 2  (tool-error rate above 7%)
    - Unknown: 5  (below-floor 3, no-transcript 1, unreadable 1)

    Verdict: tool-error rate over each session's own transcript;
    `unknown` is a distinct state and is never counted as clean.
    See `memory/repo/nescio/adr/0004-session-verdict-from-transcript.md`.
    ```

    `unknown_reasons` renders only the non-zero reasons, sorted by name for
    determinism.
  - `render_block` gains a **`## Recurring flags` sub-block** inside the
    generated markers: tool names appearing in **≥ 2 distinct flagged
    sessions**, rendered `- \`Bash\` — 9 errors across 3 sessions`, sorted by
    error count descending then name. `_(none)_` when empty.
    **Never render `tool_result.content`.** Error text is unredacted
    model-visible output that can carry credentials and absolute paths;
    `record_stop.redact()` is not applied to transcripts and `memory/` is a
    published tree.
  - `render_block` must stay **deterministic in `stats` alone** — no clock
    reads. The existing docstring at `:313` promises this and a test relies on it.
  - `render_report`: replace the trailing "Outcome summary is emitted as
    INSUFFICIENT DATA" paragraph (`:588-592`) with the per-repo counts, and add
    `clean/flagged/unknown` to the per-entry stat line.

  **Files**: `scripts/compute_readiness.py`

  **Acceptance criteria**: `grep -c INSUFFICIENT scripts/compute_readiness.py`
  returns 0. `render_block` called twice on the same `stats` returns
  byte-identical text. The rendered block contains the literal word `unknown`
  and never a percentage that merges unknown into clean.

- [ ] **7. `compute_readiness` — CLI flags** *(sequential after T6)*

  **What to do**: Edit `scripts/compute_readiness.py`.

  - `--projects-dir` (default `rs.config_dir() / "projects"`) — required for
    tests to run hermetically, and useful for pointing at an archived corpus.
  - `--no-verdicts` — skip derivation entirely; `outcome.available` becomes
    `false` and counts are omitted. This is the **only** thing that may set
    `available: false`; a run in which every session happens to be `unknown`
    still reports `available: true` with `unknown: N`. Two ways to express
    "we learned nothing" is one way too many.
  - Thread both through `plan()` → `summarise()` → `derive_outcome()`.
  - `main()` keeps returning 0 in every case (this runs from `/harvest-memory`,
    not CI) — do not add a non-zero exit for flagged sessions.

  **Files**: `scripts/compute_readiness.py`

  **Acceptance criteria**: `--help` lists both flags;
  `--no-verdicts --json` emits `"available": false` and no counts; the
  `#71` stdout guard at `:620` still runs before any glyph is printed.

- [ ] **8. `compute_readiness` tests**

  **What to do**: Extend `tests/test_compute_readiness.py` (50 KB, follow its
  existing fixture conventions). Cover Test Matrix section D. Every test that
  exercises derivation must pass an explicit `--projects-dir` / `projects_dir`
  pointing at a temp tree.

  Critically: add a test that an existing readiness file containing the old
  `INSUFFICIENT_OUTCOME` prose **between the markers** is spliced cleanly (that
  text is inside the generated block, so it is overwritten — confirm it is, and
  confirm identical prose *outside* the markers survives byte-for-byte).

  **Files**: `tests/test_compute_readiness.py`

  **Acceptance criteria**: section D green; total suite > 750 and OK.

- [ ] **9. Docs**

  **What to do**:
  - `commands/harvest-memory.md` step 9 (`:234-255`): the paragraph claiming
    "the outcome summary and the recurring flags are not derivable from the
    trail, so the script emits an explicit *insufficient data* note there
    instead of a number, and you write the real thing by hand" is now false.
    Rewrite: the counted outcome summary and recurring flags are generated;
    the operator's judgement goes in `## Notes` and in prose *outside* the
    markers.
  - `ROADMAP.md:67` — move #70 out of the planned list per the repo's existing
    convention (see commit `f27f942`, which did exactly this for the drift
    check). Check `scripts/check_roadmap_drift.py` still passes afterwards.
  - `memory/repo/EXAMPLE/readiness.md` — leave unchanged. It is the template for
    the hand-written portion; the generated block is appended below it.

  **Files**: `commands/harvest-memory.md`, `ROADMAP.md`

  **Acceptance criteria**: `python -m unittest discover -s docs_site` is 80 OK;
  roadmap drift check passes.

- [ ] **10. Real-corpus smoke run**

  **What to do**: With T5–T7 landed, run the dry run against the operator's real
  corpus and reconcile against the ADR's measured expectations:

  ```bash
  python scripts/compute_readiness.py --json | python -m json.tool | head -60
  ```

  Confirm: counts sum per repo; the corpus-wide flagged share is in the
  neighbourhood of 6% of floor-passing sessions; roughly a fifth of sessions
  are `unknown/below-floor`; `unknown/no-transcript` is small (99% of trail
  sessions resolved at measurement time). A flagged share of **0%** or of
  **>25%** means the `is_error` predicate or the unit is wrong — stop and
  re-measure rather than adjusting the constant to make the number look right.

  **Files**: none (verification only — do **not** run `--apply` in this task)

  **Acceptance criteria**: the reconciliation above holds and is recorded in
  the PR description.

- [ ] **11. Index regeneration and final gate**

  **What to do**:
  - Run `python scripts/wiki_index.py --apply` (or the repo's documented
    invocation) so `memory/repo/nescio/adr/MEMORY.md` gains the ADR 0004 line
    between its `memory-index:generated` markers. **Do not hand-edit it** — it
    is generated, and hand-editing is how the two generators drift.
  - Full gate: `PYTHONPATH=scripts python -m unittest discover -s tests` and
    `python -m unittest discover -s docs_site`.
  - `python scripts/wiki_lint.py` if it covers `memory/`.

  **Files**: `memory/repo/nescio/adr/MEMORY.md` (generated)

  **Acceptance criteria**: both suites green, test count > 750, `git status`
  shows no unexpected files.

---

## Test Matrix

### A. `scan_transcript` — parsing

| # | Input | Expect |
|---|---|---|
| A1 | block `{"type":"tool_use","id":"x","name":"Bash"}` | calls += 1 |
| A2 | `tool_result` with `is_error: true` | errors += 1, attributed to `Bash` |
| A3 | `tool_result` with `is_error: false` | **not** an error |
| A4 | `tool_result` with `is_error` **absent** | **not** an error |
| A5 | `tool_result` with `is_error: "true"` (string) | **not** an error |
| A6 | `message.content` is a string | skipped, no raise |
| A7 | record is a bare list / int | skipped, no raise |
| A8 | one malformed JSON line among valid ones | that line skipped, rest counted |
| A9 | blank lines, trailing newline | skipped |
| A10 | CRLF file vs LF file, same content | identical counts |
| A11 | invalid UTF-8 byte mid-file | file still fully scanned |
| A12 | `tool_use_id` with no matching `tool_use` | attributed to `"?"`, still counted |
| A13 | 26.8 MB real transcript | completes; memory does not track file size |

### B. `classify` — the arithmetic

| # | calls | errors | Expect |
|---|---|---|---|
| B1 | 0 | 0 | `unknown` / `no-tool-calls` (no `ZeroDivisionError`) |
| B2 | 3 | 1 | `unknown` / `below-floor` — **not** `flagged`; this is the 33% trap |
| B3 | 29 | 0 | `unknown` / `below-floor` |
| B4 | 29 | 29 | `unknown` / `below-floor` — the floor wins over a 100% rate |
| B5 | 30 | 0 | `clean` |
| B6 | 30 | 2 | `clean` (0.0667 ≤ 0.07) |
| B7 | 30 | 3 | `flagged` (0.10 > 0.07) |
| B8 | 100 | 7 | `clean` — exactly at threshold, proves `>` not `>=` |
| B9 | 100 | 8 | `flagged` |
| B10 | 1000 | 71 | `flagged` — no float drift at the boundary |

### C. Resolution and `unknown` reasons

| # | Setup | Expect |
|---|---|---|
| C1 | `transcript_path` resolves | scanned from that path |
| C2 | `transcript_path` set but file missing; `session_id` glob hits | scanned via glob (**backfill**) |
| C3 | `transcript_path` empty/absent; glob hits | scanned via glob |
| C4 | neither resolves | `unknown` / `no-transcript` |
| C5 | path exists but is a directory | `unknown` / `unreadable` |
| C6 | path unreadable (`PermissionError`) | `unknown` / `unreadable` |
| C7 | `session_id` contains `..` or a separator | `None`, no escape from `projects_dir` |
| C8 | `projects_dir` does not exist | `unknown` / `no-transcript`, no raise |
| C9 | two files match the glob | deterministic pick (first sorted), no raise |
| C10 | **structural pin** | `return "clean"` occurs exactly once in the module source |

### D. Aggregation and rendering

| # | Case | Expect |
|---|---|---|
| D1 | mixed repo: 2 clean, 1 flagged, 3 unknown | counts sum to 6; invariant assert holds |
| D2 | every session `unknown` | `available: true`, `clean: 0`, `flagged: 0`, `unknown: N` |
| D3 | `--no-verdicts` | `available: false`, no counts, no scan performed |
| D4 | `--json` payload | contains no `clean_rate` / `pass_rate` key |
| D5 | `render_block(stats)` twice | byte-identical |
| D6 | flagged sessions erroring in `Bash` ×3 sessions, `Edit` ×1 | Recurring flags lists `Bash` only (≥ 2 sessions) |
| D7 | Recurring flags rendering | contains no substring of any `tool_result.content` |
| D8 | file with markers containing the old insufficient-data prose | spliced; identical prose *outside* markers survives byte-for-byte |
| D9 | malformed markers (#121) | still `skipped-malformed`, `new_text is None`, nothing written |
| D10 | CRLF readiness.md | round-trips unchanged apart from the block (#83/#84) |
| D11 | `--repo x` | derivation runs only for `x`'s sessions |
| D12 | no trail data at all | existing honest-empty-state report unchanged |

## Success Criteria

1. `INSUFFICIENT_OUTCOME` no longer exists in the codebase, and no branch can
   reintroduce a "we don't know, so call it clean" path.
2. `clean` / `flagged` / `unknown` are three distinct states end to end — in
   `Verdict`, in the aggregate dict, in `--json`, and in the rendered
   `readiness.md` block. `clean + flagged + unknown == sessions` is asserted in
   code and in a test.
3. `--json` emits **no ratio field**, so #32 cannot accidentally consume a
   number in which `unknown` has already dissolved into `clean`.
4. A missing, dangling, unreadable, or below-floor session yields `unknown`
   with a machine-readable reason — proven by tests C4–C8 and B1–B4, not by
   intention.
5. The structural pin (C10) is green: `"clean"` is returned from exactly one
   site.
6. Backfill works: a session with no `transcript_path` but a transcript on disk
   is scanned (C2, C3).
7. `## Recurring flags` is populated from tool names and counts only; no
   `tool_result.content` reaches `memory/` (D7).
8. Both suites green — `tests` > 750 OK, `docs_site` 80 OK — and the real-corpus
   dry run reconciles with ADR 0004's measured expectations (T10).
9. `memory/repo/nescio/adr/MEMORY.md` lists ADR 0004, regenerated not hand-edited.

## Follow-ups (not in this plan)

- **F1** — un-harvested-only filter: skip sessions at or below the trail
  watermark. Cheap win, not needed at 11.4 s corpus-wide.
- **F2** — subagent transcripts: ADR 0004 Decision 5's reopen trigger. Requires
  re-calibrating `FLAG_ERROR_RATE` upward, since aggregation smooths the rate.
- **F3** — a format-change canary: a corpus-wide error rate that drops to zero,
  or a `clean` share that jumps, should be treated as an `is_error` semantics
  change until proven otherwise.
- **F4** — permission denials as a **second, separate** axis (never folded into
  the error rate — a denial is the guardrail working).
