# wiki_index: stop destroying hand-written `MEMORY.md` content

> **Revision 2.** Scope cut to the safety fix only after socrates review. The
> predicate was replaced (shape+containment → line-identity) and an append-path
> de-duplication requirement was added. Deferred decisions are retained below,
> marked, so the follow-up issue can reference them by number.

## TL;DR

> `scripts/wiki_index.py` overwrites a folder's whole `MEMORY.md` from a
> non-recursive note walk, destroying hand-written prose and links — unattended,
> behind a swallowed `except` at `scripts/promote_learnings.py:481`. This PR gives
> the generator an **owned block delimited by HTML markers**, a **line-identity
> migration predicate** (a marker-less file is replaced only when every line in it
> is byte-identical to a line this run would emit — otherwise the block is
> appended and nothing is touched), **de-duplication on the append path** so a
> preserved hand-maintained list is never doubled by the generated block,
> **refuse-on-malformed-markers** so the file is never rewritten when the block's
> extent is unknowable, and **`newline=""` on both read and write**. Nothing else.
> Subfolder links, `--recursive`, the `NON_NOTE_NAMES` move, the parent-chain
> reindex and the CI gate are all deferred.

---

## Why the scope was cut

The `## Subfolders` feature is what dragged in `--recursive` (to check the tree),
which dragged in the parent-chain reindex in `promote_learnings.py` (or CI reds on
the next promote), which dragged in three new committed root index files and a CI
gate. **None of that chain was required to stop data destruction.** The review
surface it created is what let two holes through the first draft's predicate.

This PR does one thing: make `wiki_index.py` incapable of losing a byte.

---

## Context

### Verified current behaviour (read at plan time, this worktree)

| Fact | Location |
|---|---|
| Emits only `- [name](file.md) — desc` lines; no heading, no prose | `scripts/wiki_index.py:25-31` |
| Whole-file replacement, no `newline=` argument | `scripts/wiki_index.py:42` |
| `--check` compares the ENTIRE file → any prose is permanently stale | `scripts/wiki_index.py:37-41` |
| Runs unattended, rc discarded, exceptions swallowed | `scripts/promote_learnings.py:474-482` |
| `NON_NOTE_NAMES` and its comment block | `scripts/wiki_lint.py:28-31` |
| `iter_notes` default `recursive=True`, shared with `wiki_lint.lint` | `scripts/_wiki_common.py:56-73` |

### The three committed index files — measured, not assumed

The first draft claimed all three were byte-identical to generator output. **That
was wrong.** Measured with `tail -c 1 | od` and the current `--check`:

| File | Size | Last byte | Current `--check` |
|---|---|---|---|
| `memory/concepts/MEMORY.md` | 140 | `0a` | **rc 0 — up-to-date** |
| `memory/repo/EXAMPLE/MEMORY.md` | 166 | `0a` | **rc 1 — stale** |
| `memory/repo/nescio/adr/MEMORY.md` | 812 | `2e` (`.`) | **rc 1 — stale** |

Two distinct pre-existing drifts, both confirmed by running the generator:

1. **`adr/MEMORY.md` has no trailing newline.** `build_index` always ends in `\n`.
   Content is otherwise identical. The fix is one byte.
2. **`EXAMPLE/MEMORY.md` has two drifted lines**, for two different reasons:
   - `overview.md`'s frontmatter `description` drifted from the committed bullet.
     Genuine staleness — frontmatter is the source of truth, the bullet is the
     stale artefact.
   - `readiness.md` has **no `description` in its frontmatter at all** (only
     `last_updated`), so the generator emits the bare `- [readiness](readiness.md)`
     — exactly the symptom issue #102 item 3 describes. The committed bullet's
     description, `EXAMPLE readiness summary (the autonomy-dial input)`, is
     **hand-written**. It exists nowhere else.

Fact 2b is the one the coordinator's §4 did not have: a naive "resync with the
current generator" would **delete a hand-written description** in the very commit
whose purpose is to stop deleting hand-written things. Task 1 resolves it by
fixing the source of truth instead. See D16.

### Still true, and still load-bearing

- **There is no reproducer in this repo.** All lossy shapes are synthetic.
- **`install.py:54` symlinks `memory/` → `~/.claude/memory`**, and
  `scripts/sync_from_upstream.py` never touches `memory/` (`:7-8`, `:33`). The
  migration in this PR is the only thing that will ever touch a downstream
  instance's index files. The predicate must be right for *their* content.
- The three folders damaged in `ai-os#138` all take the **append** path under the
  new predicate — including `repo/soulsgate-payment`, which is pure bullets with
  no prose at all and is saved only because its bullets link `adr/….md` targets
  this run does not emit.

### Platform hazards designed around

- **CRLF (#83/#84)**: `wiki_index.py:42` is the exact defect shape.
  `scripts/apply_theme.py:83-97` is the in-repo fix pattern (`newline=""` on
  **both** read and write). See D10.
- **cp1252 stdout (#71)**: `wiki_index.main()` has no guard and will start
  printing `⚠`. `compute_readiness.py:539-543` is the pattern.
- **Git-Bash ERE traps (#95)**: no shell regexes are introduced. No CI wiring in
  this PR at all.

---

## Decision record

Deferred entries are kept, numbered, for the follow-up issue to reference.

| # | Decision | Status |
|---|---|---|
| D1 | Migration must be lossless in every case | **KEPT** |
| D2 | `## Subfolders` section linking subdirectory indexes | **DEFERRED** |
| D3 | `NON_NOTE_NAMES` → `_wiki_common`; `readiness.md` reconciliation | **DEFERRED** |
| D4 | Marker names and block shape | **KEPT** |
| D5 | "Indexable directory" definition | **DEFERRED** |
| D6 | Migration predicate | **REPLACED** — line-identity |
| D7 | Refuse on malformed markers | **KEPT** |
| D8 | `--recursive` tree mode | **DEFERRED** |
| D9 | `--check` reporting and exit codes | **KEPT** (revised) |
| D10 | Encoding and line endings | **KEPT** |
| D11 | Parent-chain reindex in `promote_learnings` | **DEFERRED** |
| D12 | CI wiring into `tests.yml` | **DEFERRED** |
| D13 | De-duplication against preserved text | **NEW** |
| D14 | De-duplication applies on the splice path too | **NEW** (derived) |
| D15 | Empty-folder handling | **NEW** (D5's remnant) |
| D16 | Pre-existing drift resolution | **NEW** |

Because D2, D3, D5 and D8 are deferred: the note walk stays non-recursive,
`scripts/_wiki_common.py` is **untouched**, `scripts/wiki_lint.py` is
**untouched**, `readiness.md` keeps being indexed, and
`scripts/promote_learnings.py` gains **only a comment**.

---

### D4 (KEPT) — Marker names and block shape

```
<!-- memory-index:generated start -->
<!-- memory-index:generated end -->
```

Namespaced to match `readiness:generated` (`compute_readiness.py:95-96`). Defined
in `scripts/wiki_index.py`, not `_wiki_common.py` — `wiki_lint.py` has no use for
them, and `_wiki_common.py` is untouched this PR.

```markdown
<!-- memory-index:generated start -->

<!-- Generated by scripts/wiki_index.py. Edits between these markers are
     overwritten; everything outside them is preserved. -->

- [alpha](a.md) — first
- [beta](b.md) — second

<!-- memory-index:generated end -->
```

No `## Notes` heading — `build_index()`'s output stays the literal block body,
which keeps the D6 predicate trivial to state. Body placeholders per D13/D15.

### D6 (REPLACED) — Line-identity, not shape

**The first draft's shape+containment regex had an unconditional hole.** This line
passes both a `^- \[[^\]]*\]\(([^)]+)\)(?: — .*)?$` match and a target-containment
check, yet is unambiguously hand-written:

```
- [START HERE — read before touching sessions](auth-model.md) — ask Markus first
```

`[^\]]*` swallows the annotation, `— .*` swallows the note, and `auth-model.md` is
a generated target. It would be silently flattened to the plain generated bullet.
Shape asks *"does this look like a generated line"*; the safety question is
*"is this **the** line I would generate"*.

**The predicate:**

> A marker-less `MEMORY.md` is safely replaceable iff every non-blank line in it
> is **byte-identical to a line this run would emit** — set membership against the
> emitted line set, order-insensitive.

No regex. No `NON_NOTE_NAMES` coupling. No `droppable_targets`. Strictly stronger
than shape+containment and considerably simpler to review — which is the point.

**Stated, accepted loss:** a set test does not preserve hand-curated *ordering*.
A file whose lines are all generated lines but deliberately reordered is replaced
in generator order. This is documented in the function's docstring and in
`memory/CONVENTIONS.md` (Task 8). Ordering is the only thing this predicate can
lose, and only in a file that contains nothing but generated lines.

Verified against the real downstream `ai-os` brain: all three damaged folders take
the append path — `repo/ui` (blockquote prose), `repo/streaming` (prose plus
`## Notes` / `## Incidents` / `## ADRs`), and `repo/soulsgate-payment`, which has
**no prose at all** and is saved only because its `adr/….md` bullets are not lines
this run emits.

### D7 (KEPT) — Malformed markers

`compute_readiness.compose()` (`:388-398`) tests marker *presence* and splices with
`.index()`. A begin marker with no end falls to the append branch and **duplicates
the block on every run**. This implementation classifies instead:

| begin | end | order | Action |
|---|---|---|---|
| 0 | 0 | — | Migration path (D6) |
| 1 | 1 | begin < end | Splice in place |
| 1 | 0 | — | **Refuse** |
| 0 | 1 | — | **Refuse** |
| 1 | 1 | end < begin | **Refuse** |
| ≥2 | any | — | **Refuse** |
| any | ≥2 | — | **Refuse** |

Refusal returns `rc=2` and a `⚠ malformed index markers:` summary line, in
**both** `--check` and write mode, writing nothing. It never raises, so
`promote_learnings.py:479` surfaces it as a summary line rather than swallowing an
exception.

With a begin marker and no end, the block's extent is unknowable: appending
duplicates (the known bug), truncating at EOF may delete prose. A human resolves
it. Exit 2 = "cannot check", 1 = "stale" — the split `check_roadmap_drift.py` uses
and `.github/workflows/tests.yml:66-71` documents as deliberate.

### D9 (KEPT, revised) — `--check` reporting

| Situation | rc | Message |
|---|---|---|
| Block matches | 0 | `up-to-date: <path>` |
| No notes and no file | 0 | `skipped (no notes): <path>` |
| Markers present, block differs | 1 | `stale: <path> (generated block differs; run without --check to regenerate)` |
| No markers, replaceable | 1 | `stale: <path> (no index markers; run without --check to adopt them)` |
| No markers, curated | 1 | `stale: <path> (no index markers; run without --check to append a block — hand-written content is preserved)` |
| Malformed markers | 2 | `⚠ malformed index markers: <path> (<which>); refusing to write` |

Write mode replaces `stale:` with `wrote:`, and the curated path additionally emits
the D13 warning line.

### D10 (KEPT) — Encoding and line endings

- **Read**: `read_text(encoding="utf-8", newline="")` — translation off, so the
  comparison is against what is on disk.
- **Write**: `write_text(text, encoding="utf-8", newline="")` — no `\n` → `\r\n`
  expansion on Windows. The `apply_theme.py:90,97` pattern; closes the #83/#84
  defect shape at this call site.
- The block always uses `\n`. Splicing an LF block into a CRLF file yields mixed
  endings **once**; run 2 reads the LF block back, renders LF, compares equal.
  **Idempotent, and `--check` is green on run 2.**
- All predicate and link parsing uses `str.splitlines()`, which handles `\n`,
  `\r\n` and `\r` — so a CRLF pure-generated file still migrates.
- `.gitattributes` pins `* text=auto eol=lf`, so committed files are LF even on
  Windows. CRLF arises only downstream; it is still handled.

### D13 (NEW) — De-duplication against preserved text

All three folders damaged downstream take the **append** path. Without this,
`repo/ui/MEMORY.md` ends up with 27 curated bullets **plus** a generated block
re-listing ~25 of the same notes. `memory/` is what agents read as ground truth; a
doubled index is a correctness regression landing on exactly the files this fix
exists to protect.

> When composing the block, omit any note whose target is already linked anywhere
> in the **preserved text**.

- Targets are parsed from the preserved text with `\]\(([^)]+\.md)\)` — the same
  expression as `wiki_lint._MDLINK_RE:25`. A **local copy** is used, because D3 is
  deferred and `_wiki_common.py` is untouched this PR. The duplication is
  deliberate and belongs in the follow-up issue.
- Matching is exact string comparison on the link target after stripping a leading
  `./`. A miss produces a duplicate bullet (noisy, non-destructive); a spurious hit
  omits a bullet from the block for a note the file demonstrably already links.
  Both failure directions are safe; document that.
- When de-duplication empties the block, the body is
  `_(every note in this folder is already linked above)_` — the block is still
  written, because the markers are what make the next run splice instead of
  appending again.
- The warning line: `⚠ appended a generated block to <path> — it had no index
  markers and content that is not ours. Nothing was removed; the existing
  hand-maintained list was preserved and the generated block covers only the notes
  it did not already link.`

### D14 (NEW, derived) — De-duplication applies on the splice path too

**Not in the coordinator's §3, but forced by idempotency.** If de-duplication ran
only on append, then run 2 — which takes the splice path, the markers now being
present — would splice the *full* note list back in and the doubling would return.

> De-duplication is computed against **everything outside the markers**, on every
> path, always.

Stateless, idempotent, and consistent between append and splice. Side effect: a
note mentioned in passing in prose (`see [alpha](a.md) for context`) is
permanently omitted from the generated block. This is acceptable — the file
demonstrably links it, so the index is not lying, and `wiki_lint._memory_referenced`
(`wiki_lint.py:39-46`) scans the whole `MEMORY.md` with the same regex, so the note
still does not become an orphan. **Flagged** — see Open Question 1.

### D15 (NEW) — Empty folder

D5's indexable-directory definition is deferred with the subfolder feature, but the
empty-folder question still needs an answer:

- No notes and no `MEMORY.md` on disk → **no file is created**; rc 0,
  `skipped (no notes): <path>`. (This preserves today's behaviour: `build_index`
  returns `""`, `old` is `""`, they compare equal.)
- No notes but `MEMORY.md` exists (all notes deleted) → the block **is** written,
  body `_(no notes yet)_`. Refusing would leave a stale index `--check` can never
  satisfy.

### D16 (NEW) — Pre-existing drift resolution

Under D6, `EXAMPLE/MEMORY.md` and `adr/MEMORY.md` currently **fail** the predicate
and would take append+warn in our own repo. That must be resolved before the new
code runs. The coordinator suggested resyncing all three with the current
generator; that is right for `adr/` but wrong for `EXAMPLE/`, because it would
delete the hand-written `readiness.md` description (see Context).

**Resolution — fix the source of truth, not the artefact:**

- `adr/MEMORY.md` — add the trailing newline. Zero content change.
- `EXAMPLE/readiness.md` — add `description: EXAMPLE readiness summary (the
  autonomy-dial input)` to its frontmatter. **Verified**: the generator then emits
  the committed bullet byte-identically. Nothing is lost, and the bare-link symptom
  of #102 item 3 is fixed at its cause without prejudging D3.
- `EXAMPLE/MEMORY.md` — update the `overview` bullet to match `overview.md`'s
  frontmatter. This is a genuine staleness correction; the frontmatter is the
  source of truth and **must not be reverted to match the index**.

Note this is a **hand edit**, not a generator run. Running the current generator on
Windows would write CRLF (`wiki_index.py:42` has no `newline=`) — the very defect
this PR fixes. The hand edit is machine-verified by the *unchanged* `--check`.

---

## Verification Strategy

- **Unit**: `PYTHONPATH=scripts python -m unittest discover -s tests -v` — green
  at the end of Wave 2 and thereafter. Hermetic,
  `tempfile.TemporaryDirectory()`-based, matching `tests/test_wiki_index.py`.
- **Idempotency**: every write-path test re-runs the operation and asserts
  **`read_bytes()`** equality — a `read_text()` comparison would normalise away a
  CRLF regression.
- **Repo tree**: `--check` on all three leaf dirs exits 0, before the code change
  (after Task 1) and after it (after Task 8).
- **No linter regression**: `python scripts/wiki_lint.py --dir memory --check`
  produces the same finding count before and after.
- **Encoding**: a cp1252-backed `TextIOWrapper` test, per
  `tests/test_console_encoding_guard.py`.

---

## Execution Strategy

```
Wave 1  Task 1                        separate commit, no code change
Wave 2  Task 2 → Task 3 → Task 4      SEQUENTIAL — all edit scripts/wiki_index.py
Wave 3  Task 5 ‖ Task 6 ‖ Task 7      parallel, 3 agents, distinct test files
Wave 4  Task 8                        repo content + docs
```

Little genuine parallelism survives the scope cut, and pretending otherwise would
produce merge conflicts in one 120-line file. Wave 2 must be a single agent.

> **Expected red suite during Wave 2.** `tests/test_wiki_index.py:41-44`
> (`test_write_then_check_clean`) asserts the file's exact content is
> `"- [alpha](a.md) — first\n"`, which becomes the marker block. It goes red the
> moment Task 2 lands and is repaired inside Task 4. An executor following
> verification-before-completion must expect this and not stall on it, and must not
> "fix" it by weakening the assertion — Task 4 replaces it with the block-aware
> equivalent.

---

## TODOs

### Wave 1 — resolve the pre-existing drift (separate commit)

- [ ] **1. Make the three committed leaf indexes match the current generator**

  **What to do**: three hand edits, no code change, committed on their own so the
  diff is reviewable in isolation.
  1. `memory/repo/nescio/adr/MEMORY.md` — append a trailing newline. No other byte
     changes.
  2. `memory/repo/EXAMPLE/readiness.md` — add one frontmatter line after
     `last_updated: 2026-01-01`:
     `description: EXAMPLE readiness summary (the autonomy-dial input)`
     (the exact text of the currently hand-written bullet). Safe alongside
     `compute_readiness.py`: `_bump_last_updated` (`:349-368`) is a targeted field
     replacement whose docstring guarantees extra keys survive.
  3. `memory/repo/EXAMPLE/MEMORY.md` — replace the `overview` bullet with the
     generator's output:
     `- [overview](overview.md) — EXAMPLE repo memory note — copy the pattern into memory/repo/<your-repo>/ and delete EXAMPLE/`

  **Do NOT** edit `overview.md`'s frontmatter to match the old bullet. The
  frontmatter is the source of truth; the index line is the stale artefact.

  **Files**: `memory/repo/nescio/adr/MEMORY.md`,
  `memory/repo/EXAMPLE/readiness.md`, `memory/repo/EXAMPLE/MEMORY.md`,
  `tests/fixtures/example_readiness.md`

  **Amended during execution (revision 3).** A fourth file is required.
  `tests/test_compute_readiness.py:458-472` asserts
  `tests/fixtures/example_readiness.md` is **byte-identical** to
  `memory/repo/EXAMPLE/readiness.md` — the fixture copy exists because `memory/`
  is outside `FRAMEWORK_PATHS`, so a synced downstream test cannot read the real
  file. Edit 2 trips that guard, whose own failure message prescribes the remedy
  ("re-copy one onto the other"). Revision 2 missed this: it named the fixture
  zero times, which made the original acceptance criteria (green suite AND
  exactly 3 files) mutually unsatisfiable.

  **Expected diff** (verified at plan time):
  ```
  memory/repo/nescio/adr/MEMORY.md   1 line touched — "\ No newline at end of file"
                                     disappears. NOT content loss.
  memory/repo/EXAMPLE/readiness.md   +1 frontmatter line
  memory/repo/EXAMPLE/MEMORY.md      overview bullet description replaced;
                                     readiness bullet UNCHANGED
  memory/concepts/MEMORY.md          untouched (already rc 0)
  ```

  **Acceptance criteria**:
  - With `scripts/wiki_index.py` **unchanged**, all three exit rc 0:
    `PYTHONPATH=scripts python scripts/wiki_index.py --dir memory/concepts --check`
    and the same for `memory/repo/EXAMPLE` and `memory/repo/nescio/adr`.
  - `git ls-files --eol memory` shows `w/lf` for all three.
  - No `MEMORY.md` line is deleted other than the `overview` description
    replacement. In particular the `readiness` bullet keeps its description.
  - `PYTHONPATH=scripts python -m unittest discover -s tests` — green.

  **QA Scenario**: `git diff --stat` shows exactly 4 files, ≤5 changed lines.

### Wave 2 — the generator (SEQUENTIAL, single agent, all `scripts/wiki_index.py`)

- [ ] **2. Markers, block rendering, marker classifier, `compose()`**

  **What to do**:
  - Add `GENERATED_BEGIN` / `GENERATED_END` per D4, with a comment mirroring
    `compute_readiness.py:93-96`.
  - Add `render_block(body: str) -> str` producing the D4 block: markers, blank
    line, the two-line explanatory HTML comment, blank line, `body` (or a
    placeholder per D13/D15), blank line, end marker, trailing newline.
    Deterministic in `body` alone — nothing reads the clock.
  - Add `_classify_markers(text) -> tuple[str, str]` returning
    `("none" | "ok" | "malformed", reason)` per D7. Count with `text.count(...)`;
    take positions with `.index()` only after the counts prove exactly one each.
  - Add `compose(existing_text: str | None, block: str, *, replaceable: bool)
    -> tuple[str | None, str]` returning `(new_text_or_None, disposition)` where
    disposition ∈ `created` / `spliced` / `migrated` / `appended` /
    `malformed:<reason>`. `None` means "write nothing".
  - `build_index()` is **unchanged** (D3 deferred — `readiness.md` is still
    indexed).

  **Files**: `scripts/wiki_index.py`

  **Acceptance criteria**:
  - `_classify_markers` returns `malformed` for each of the 5 bad rows in D7 and
    `ok` only for exactly-one-each-in-order.
  - `compose(text_with_begin_only, block, replaceable=False)` →
    `(None, "malformed:...")`. **The regression guard against the
    `compute_readiness.compose()` duplicate-block bug.**
  - Splicing preserves prefix and suffix byte-for-byte.
  - Same input twice through `compose` → identical output (no growth).

  *Suite is red from here until Task 4 — see Execution Strategy.*

- [ ] **3. Line-identity predicate (D6) and de-duplication (D13/D14)**

  **What to do**:
  - Add `_is_safely_replaceable(existing_text: str, emitted_lines: set[str]) -> bool`:
    `True` iff every non-blank line of `existing_text.splitlines()` is in
    `emitted_lines`. No regex.
    The docstring must state, in this order: (a) why shape matching is
    insufficient, quoting the
    `- [START HERE — read before touching sessions](auth-model.md) — ask Markus first`
    counter-example; (b) that `ai-os#138`'s `repo/soulsgate-payment` was pure
    bullets with no prose and is saved only by line identity; (c) that hand-curated
    ordering is **not** preserved and this is an accepted, stated loss.
    **This is the single most important comment in the PR.**
  - Add `_LINKED_TARGET_RE = re.compile(r"\]\(([^)]+\.md)\)")` with a comment
    noting it duplicates `wiki_lint._MDLINK_RE:25` because D3 is deferred.
  - Add `_linked_targets(text: str) -> set[str]` — matches, with a leading `./`
    stripped.
  - Add `dedupe_body(lines: list[str], preserved: str) -> list[str]` dropping any
    bullet whose target is in `_linked_targets(preserved)`. Document both failure
    directions as safe (miss → duplicate bullet; spurious hit → omitted bullet for
    a note the file already links).
  - Wire de-duplication into **both** the append and the splice paths per D14, in
    each case with `preserved` = everything outside the markers.

  **Files**: `scripts/wiki_index.py`

  **Acceptance criteria**:
  - The `START HERE` line makes a file non-replaceable.
  - A pure-bullet file whose bullets link `adr/0001-x.md` is non-replaceable
    (the `soulsgate-payment` shape).
  - A file whose lines are exactly the emitted lines, reordered, **is** replaceable.
  - Full overlap → block body is the "already linked above" placeholder.
  - Append then re-run → `read_bytes()` identical (D14; fails if de-dup is
    append-only).

- [ ] **4. Rewrite `regenerate()`, the CLI, the stdout guard, and the stale test**

  **What to do**:
  - Rewrite `regenerate(dir_path, *, check=False) -> tuple[int, list[str]]`.
    **Keep the signature and return shape** — `promote_learnings.py:479` unpacks
    two values. Flow: build body → read existing with `newline=""` (or `None`) →
    D15 empty-folder short-circuit → classify markers → compute `replaceable` →
    de-duplicate → `compose` → unchanged ⇒ rc 0 → `check` ⇒ rc per D9 → else write
    with `newline=""` per D10 and emit the D9 message plus, on the curated path,
    the D13 `⚠` line.
  - Add the stdout guard at the top of `main()`, **before** the `_resolve_dir`
    call so it also covers the existing error `print` at `:67`, copying
    `compute_readiness.py:539-543`:
    ```python
    # Summary lines carry — and ⚠; a legacy Windows console defaults to cp1252 and
    # would raise UnicodeEncodeError. Guarded — a redirected StringIO in tests has
    # no reconfigure.
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass
    ```
    Add `import sys`.
  - Rewrite the module docstring: it currently claims whole-file replacement. It
    must describe the owned block, the line-identity migration rule, the
    de-duplication behaviour, and exit codes 0/1/2.
  - **Repair `tests/test_wiki_index.py:35-46`** (`test_write_then_check_clean`) in
    this same commit: assert the file *contains* the bullet and both markers, and
    that a second `regenerate` leaves `read_bytes()` unchanged. Do not weaken it to
    a bare `assertTrue`.

  **Files**: `scripts/wiki_index.py`, `tests/test_wiki_index.py`

  **Acceptance criteria**:
  - `grep -n "read_text\|write_text" scripts/wiki_index.py` shows `newline=""` on
    **every** hit.
  - `PYTHONPATH=scripts python -m unittest discover -s tests` — **green again.**
  - After a write run, a `--check` run on the same directory is rc 0.
  - `scripts/wiki_index.py` remains stdlib-only (ADR 0001).

### Wave 3 — tests (parallel, 3 agents, distinct files)

- [ ] **5. The test matrix in `tests/test_wiki_index.py`**

  **What to do**: expand to the full matrix below. Keep the existing `_note()`
  helper and `tempfile.TemporaryDirectory()` style; add a
  `_write_bytes(path, text, *, crlf=False)` helper so line endings are controlled
  exactly. Assert with `read_bytes()` wherever idempotency or line endings are the
  subject.

  **Files**: `tests/test_wiki_index.py`

  **Acceptance criteria**: every matrix row has at least one named test method; no
  test reads the repo's real `memory/` tree.

- [ ] **6. Pin the stdout guard in `tests/test_console_encoding_guard.py`**

  **What to do**: add a `WikiIndexGuardTest` using the existing
  `_run_with_cp1252_stdout` helper. Drive `wiki_index.main()` with
  `["wiki_index.py", "--dir", "no-such-directory-xyz"]` — the resolve failure at
  `wiki_index.py:66-68` is the early, side-effect-free error path this module's
  docstring says these tests target. Assert `rc == 1`, that `stream.encoding`
  normalises to `utf8`, and write `"⚠\n"` to the stream. Add `import wiki_index`.

  **Files**: `tests/test_console_encoding_guard.py`

  **Acceptance criteria**: depends on Task 4's guard; fails without it.

- [ ] **7. Promote-path regression test**

  **What to do**: add to `tests/test_promote_learnings.py`: (a) a curated
  `MEMORY.md` with prose in the target directory survives a real promote — the
  end-to-end reproduction of `ai-os#138` **through the actual unattended call
  site** at `promote_learnings.py:479`, which is where the damage happened; (b) a
  target directory with malformed markers is left byte-identical, the `⚠ malformed`
  line appears in the promote summary, and the promote's own rc stays 0.

  **Files**: `tests/test_promote_learnings.py`

  **Acceptance criteria**: (a) fails against `main`'s generator and passes after
  Wave 2. Existing assertions at `tests/test_promote_learnings.py:429-455` still
  pass unchanged (they are `assertIn`-style on the child index and the
  `would reindex` line — both still true).

### Wave 4 — repo content and docs

- [ ] **8. Migrate the repo's indexes with the new code; document the markers**

  **What to do**:
  - Run `PYTHONPATH=scripts python scripts/wiki_index.py --dir <d>` for
    `memory/concepts`, `memory/repo/EXAMPLE`, `memory/repo/nescio/adr`. After
    Task 1 all three are line-identical to generator output, so **all three must
    migrate silently** — no `⚠` on any of them. A warning here means Task 1 was
    incomplete; stop and fix Task 1 rather than accepting the append.
  - Add a **"Folder indexes"** subsection to `memory/CONVENTIONS.md` — the file
    that already documents the wiki's rules. Cover: the two markers; that edits
    between them are overwritten and everything outside is preserved; that a
    marker-less file is adopted only when every line is one the generator would
    emit, and appended-to otherwise; that hand-curated ordering is not preserved
    in the adopt case; and that the generated block omits notes the surrounding
    text already links.
  - Add a comment at `scripts/promote_learnings.py:472-482` recording that
    `regenerate` now returns rc 2 for a malformed index, that the rc is
    deliberately still discarded, and that the condition surfaces as a `⚠` summary
    line rather than an exception. **No behaviour change to this file.**

  **Files**: `memory/concepts/MEMORY.md`, `memory/repo/EXAMPLE/MEMORY.md`,
  `memory/repo/nescio/adr/MEMORY.md`, `memory/CONVENTIONS.md`,
  `scripts/promote_learnings.py`

  **Acceptance criteria**:
  - The diff on all three index files is **purely additive**: the marker block
    wraps the existing bullets. No bullet text changes. (Task 1 already absorbed
    every content change; if a bullet moves here, something is wrong.)
  - `--check` on all three → rc 0.
  - `python scripts/wiki_lint.py --dir memory --check` → same finding count as
    before the PR (run it on `main` first and compare).
  - `git ls-files --eol memory` → `w/lf` throughout.
  - Full suite green.

  **Do NOT** hand-edit `CHANGELOG.md`; release-please owns it
  (`release-please-config.json`).

---

## Test Matrix

All cases synthetic. `tests/test_wiki_index.py` unless noted. Cut rows from
revision 1 (subfolder linking, subfolder-only folder, `--recursive` exit codes,
parent chain, droppable non-note) move to the follow-up issue with D2/D3/D5/D8/D11.

| # | Case | Setup | Assert |
|---|---|---|---|
| 1 | Prose above block | `# Orientation\n\nprose\n\n` + block with stale bullets | prose byte-identical; block replaced; rc 0 |
| 2 | Prose below block | block + `\n## Hand notes\n\nprose\n` | suffix byte-identical; block replaced |
| 3 | Marker-less, line-identical → migrates | exactly `build_index()`'s output | becomes block only; **no `⚠`** in summary |
| 4 | Marker-less, reordered generated lines → migrates | same lines, shuffled | replaced in generator order; documents the accepted ordering loss |
| 5 | **`START HERE` annotation** | `- [START HERE — read before touching sessions](auth-model.md) — ask Markus first` where `auth-model.md` is a real note | **not** replaceable → appended. The hole shape+containment missed. |
| 6 | **`soulsgate-payment` shape** | pure bullets, no prose, targets `adr/0001-x.md` | **not** replaceable → appended. A genuine `ai-os#138` regression guard — but it does **not** make the case for line identity: mutation testing showed the rejected shape+containment predicate rejects it too, because containment catches `adr/0001-x.md` unaided. Row 5 is the only row that discriminates between the two predicates. |
| 7 | Marker-less, curated prose → appends + warns | `# Index\n\nHand-written orientation.\n\n- [a](a.md) — d\n` | original text is a byte-exact **prefix** of the result; summary contains `⚠ appended` |
| 8 | **Append, full overlap** | curated file links every note in the folder | block body is the "already linked above" placeholder; no bullet duplicated |
| 9 | **Append, partial overlap** | curated file links 1 of 3 notes | block lists exactly the other 2 |
| 10 | **Append, no overlap** | curated prose links nothing | block lists all notes |
| 11 | **Splice de-duplicates too** (D14) | run case 9 twice | `read_bytes()` identical; block still lists exactly 2. Fails if de-dup is append-only. |
| 12 | Missing end marker → refuse | begin marker, no end | byte-identical; rc 2; `⚠ malformed`; **run twice → still byte-identical** (the `compute_readiness` duplicate bug) |
| 13 | Missing begin marker → refuse | end marker only | byte-identical; rc 2 |
| 14 | Reversed markers → refuse | end textually before begin | byte-identical; rc 2 |
| 15 | Duplicate markers → refuse | two begin markers; separately, two end markers | byte-identical; rc 2, both variants |
| 16 | Empty folder, no file | dir with only `.gitkeep` | no `MEMORY.md` created; rc 0; `skipped (no notes)` |
| 17 | Emptied folder | `MEMORY.md` exists, all notes deleted | block written with `_(no notes yet)_`; file not deleted |
| 18 | Idempotency | run twice on cases 1, 2, 3, 7, 9 | `read_bytes()` identical between runs |
| 19 | CRLF input | pure-generated file written `\r\n`; and a marked file with CRLF prose above the block | run 1 migrates/splices without raising; run 2 `--check` rc 0; the CRLF prose keeps its `\r\n` bytes |
| 20 | `--check` never writes | every case 1–17 under `check=True` | `read_bytes()` unchanged in **all** of them, malformed included |
| 21 | cp1252 stdout *(`test_console_encoding_guard.py`)* | `main()` on an unresolvable `--dir` | rc 1; encoding utf-8; `⚠` writable |
| 22 | Prose survives a real promote *(`test_promote_learnings.py`)* | curated `MEMORY.md`, then a real promote | prose survives — the unattended path that caused `ai-os#138` |
| 23 | Malformed survives a real promote *(`test_promote_learnings.py`)* | malformed markers, then a real promote | file byte-identical; `⚠ malformed` in summary; promote rc 0 |

---

## Success Criteria

1. `PYTHONPATH=scripts python -m unittest discover -s tests -v` — green on Windows
   and ubuntu CI.
2. `--check` on `memory/concepts`, `memory/repo/EXAMPLE`, `memory/repo/nescio/adr`
   → rc 0 at branch head.
3. `python scripts/wiki_lint.py --dir memory --check` → same finding count as `main`.
4. No `MEMORY.md` loses a line across the whole branch except the single
   `overview` description correction in Task 1, which is a staleness fix toward the
   frontmatter source of truth.
5. Every `read_text` / `write_text` in `scripts/wiki_index.py` passes `newline=""`.
6. `scripts/wiki_index.py` stays stdlib-only (ADR 0001).
7. `scripts/_wiki_common.py` and `scripts/wiki_lint.py` are **unmodified**;
   `scripts/promote_learnings.py` changes by comment only.
8. `wiki_index.regenerate()` keeps its `(int, list[str])` contract. A malformed file
   makes `promote_learnings` warn — never raise, never duplicate a block, never lose
   a byte.

---

## Deferred to the follow-up issue

Reference by decision number: **D2** (`## Subfolders`), **D3** (`NON_NOTE_NAMES`
→ `_wiki_common`, `readiness.md` reconciliation), **D5** (indexable-directory
definition), **D8** (`--recursive` tree mode), **D11** (parent-chain reindex in
`promote_learnings`), **D12** (CI wiring into `.github/workflows/tests.yml`), and
the three new root index files (`memory/MEMORY.md`, `memory/repo/MEMORY.md`,
`memory/repo/nescio/MEMORY.md`).

Two smaller items to carry over:

- `_LINKED_TARGET_RE` in `wiki_index.py` duplicates `wiki_lint._MDLINK_RE:25`.
  Consolidate when D3 moves shared vocabulary into `_wiki_common.py`.
- `scripts/assess_repo_readiness.py:88` holds a **third** independent definition of
  "not a note" (`_EXCLUDED = {"MEMORY.md", "readiness.md"}`). It is a different set
  with a different purpose, so folding it in would be a behaviour change to the
  autonomy-dial input, not a refactor. Three files now encode "what counts as a
  note" and only two of them agree.

---

## Open questions I am flagging rather than guessing

1. **D14's prose-mention suppression.** De-duplicating on the splice path is forced
   by idempotency, but it means a note mentioned once in prose
   (`see [alpha](a.md) for context`) is permanently absent from the generated
   block. I judge this acceptable — the file links it, so the index is not lying,
   and `wiki_lint` still counts it as referenced. The alternative (de-dup only on
   the first append) needs state in the file and re-doubles on run 2. **If you want
   suppression limited to bullet-shaped links only**, say so before Task 3: it is a
   one-line change to `_linked_targets` (require the match to start at a line's
   `- [`), and it narrows the suppression to genuine list entries at the cost of
   missing a curated list written with a different bullet character.

2. **The double em dash in `EXAMPLE/MEMORY.md` after Task 1.** `overview.md`'s
   frontmatter description itself contains an em dash, so the corrected bullet
   reads `- [overview](overview.md) — EXAMPLE repo memory note — copy the
   pattern…`. Cosmetically poor. The clean fix is to tighten `overview.md`'s
   `description` to an index-appropriate one-liner — which is editing the source of
   truth, legitimately, rather than the artefact. I did not fold that in because it
   changes a template file's documented content and is a judgement call about
   wording, not correctness. Line-identity holds either way.

3. **Task 1's `readiness.md` frontmatter addition versus deferred D3.** Adding a
   `description` to `readiness.md` makes the generator emit the good line today. If
   D3 later lands, `readiness.md` stops being indexed entirely and that description
   becomes unused (though still meaningful metadata). This does not prejudge D3 in
   either direction, but it does mean the follow-up will delete a line Task 1 just
   made correct. I think that is fine and strictly better than deleting the
   hand-written description now; flagging it so it is not a surprise later.
