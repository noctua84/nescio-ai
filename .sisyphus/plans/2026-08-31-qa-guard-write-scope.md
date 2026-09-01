# qa-guard write scope: detection over prevention

## Objective

Give `qa-guard` a declared, tested file boundary, and a detection control that
actually works — without pretending prevention is possible.

## The finding that shapes this plan

`qa-guard` holds `Bash` and cannot not hold it: its core instruction is "Run
every discovered check and capture the complete output" (`agents/qa-guard.md:35`).
`sed -i`, `python <<EOF`, `>>`, `ruff --fix` all mutate files without passing
through `Edit`/`Write`. An LLM denied `Edit` will routinely retry with the tool
it still has — normal recovery, not evasion.

**Therefore no tool-level or path-level mechanism is a control here.** A
PreToolUse deny guards the polite path only. Diff-based detection is
tool-agnostic; permission-based prevention is not. That asymmetry is why this
plan drops the hook and invests in the diff.

Rejected after verification, recorded so it is not re-proposed:

| Rejected | Why |
|---|---|
| PreToolUse path-deny hook | Bash bypass (above); `install.py:71` `PART_KEYS` filters a `hooks` key out of the settings overlay, so root `settings.json` reaches no user; `install.py:537` builds hook entries with no `matcher`, so it would fire on every tool call in every session; `hooks/` is symlinked to `~/.claude/hooks`, making it machine-global; `apply_theme` never rewrites `hooks/`, so a name-keyed hook silently fails open after theming. |
| `disallowedTools: Write` | Same Bash bypass. Honest only as behavioural narrowing, never as enforcement. User declined. |
| `git log --grep` gate | `qa-guard` has no commit convention and the orchestrator never asks it to commit. The gate would pass vacuously — green by construction. |

## Tasks

### T1 — `agents/qa-guard.md`: boundary sentence + dependency reclassification

Add to the charter body, as ONE sentence with no internal `. `. The block below
is indented for display only - insert it FLUSH LEFT, or Markdown renders it as a
code block:

    **Hard file boundary: you may never edit the files that define the checks —
    CI workflows, pre-commit config, linter and type-checker settings, or build
    scripts.**

CRITICAL — do not put `[tool.*]`, `.github/workflows/`, or any bare
`.ext` token inside that sentence. `_boundary_sentence`
(`tests/test_agent_definitions.py:130`, regex `BOUNDARY_SENTENCE_END_RE` at `:61`) truncates at the first `[.!?]` followed
by optional markup then whitespace. `[tool.*]` matches: `.` + `*]` + backtick +
space. Verified empirically — the sentence silently truncates to
`Hard file boundary: never edit the ` + backtick + `[tool.*]` + backtick and the
rest of the scope vanishes with the lint still green. Put the concrete path list
in the FOLLOWING paragraph, which the agent reads and the lint does not parse.

Also mirror the phrase into `description:` for routing parity with `test-writer`
and `doc-writer` (the lint strips frontmatter, so the body copy is the one that
counts).

Then reclassify dependencies:
- REMOVE `missing dependencies` from the fix list at line 46.
- ADD to the `Return BLOCKED when:` list: adding a dependency changes the
  project's supply chain to make a check pass; that is a decision for a human,
  not a mechanical fix.

Surgical edits only. Do not restructure the charter.

### T2 — `scripts/_crew_common.py`: move qa-guard, add a negation-bearing term

- `CODE_WRITERS`: remove `"qa-guard"`.
- `BOUNDED_WRITERS`: add `"qa-guard"`.
  (MOVE, not add. Adding to both fails the disjointness assertion at
  `tests/test_agent_definitions.py:329-332`. The union stays 6, so the pinned count
  at :284 stays green.)
- `BOUNDARY_SCOPE_TERMS`: add `"qa-guard": ("may never edit",)`.

The term MUST carry the negation. A positive term such as `("check",)` would
certify `Hard file boundary: you may edit the checks freely.` as compliant —
the exact bug `test_a_revoked_boundary_does_not_satisfy_the_lint` exists to
prevent, reappearing in a shape that test cannot catch. Verified: with
`"may never edit"`, the inverted sentence fails the lint.

Update the comments above both constants so they still describe what the sets
mean after the move.

### T3 — `tests/test_agent_definitions.py`: update pins, add polarity regression

- `:321` `BOUNDED_WRITERS == {"test-writer","doc-writer"}` -> add `"qa-guard"`.
- `:326` `CODE_WRITERS == {...,"qa-guard"}` -> remove it.
- `:365` `set(BOUNDARY_SCOPE_TERMS) == BOUNDED_WRITERS | WRITE_BOUNDED` — derived,
  passes once T2 lands. Verify, do not edit.
- NEW test, sibling to `test_a_revoked_boundary_does_not_satisfy_the_lint`:
  assert the INVERTED negative sentence fails the lint, i.e. that
  `Hard file boundary: you may edit the files that define the checks freely.`
  does NOT contain `qa-guard`'s scope term while the real sentence does.
  Docstring must explain that an exclusion-shaped boundary needs a
  negation-bearing term, because substring presence alone cannot see polarity.
  Use PURE LITERALS in the test, exactly as the sibling at `:386-399` does. Do
  NOT read `agents/*.md` from disk — that would duplicate
  `test_bounded_writers_declare_their_boundary`.

Do NOT weaken or delete any existing assertion. The pinned-literal docstrings
(:293-302, :311-312) say a red "is not an invitation to update the literal" —
the commit message must carry the architectural justification.

### T4 — `agents/orchestrator.md`: CI Gate Audit

Add a section modelled on the existing Regression Gate (~:371-391), placed near
the `qa-guard` dispatch (~:417-433). It MUST run against the working tree, not
the log, and must say why:

    ### CI Gate Audit (after a `qa-guard` wave)

    `qa-guard` does not commit — it leaves fixes in the working tree and PHASE 6
    commits them wholesale. A `git log --grep` gate would therefore pass
    vacuously. Audit the diff instead.

    ```bash
    git diff --name-only
    ```
    ```bash
    git diff -U0 -- '*test*' | grep -E '^-\s*(assert|self\.assert|expect|it\()'
    ```

    Reject a `PASSED` verdict when the diff shows: any path under
    `.github/workflows/`; `.pre-commit-config.yaml`; a `[tool.*]` section of
    `pyproject.toml` or `setup.cfg`; a `Makefile` or `package.json` scripts
    target; a removed assertion or deleted test function; or a new entry under
    `[project.dependencies]`. Name the file, ask for a revert, re-dispatch.

This catches edits made via Bash, which no permission rule can see.

### T5 — `README.md:121-125`: correct the prose

Currently: "Six may also *edit* existing ones: `builder` and its two tiers plus
`qa-guard` change production code, while `test-writer` and `doc-writer` are held
to their declared file boundaries."

NOTE: the sentence does not end at :123 — it runs to :125, ending
"...their charters - frontmatter has no path-scoped form, so the boundary is
prose, not enforcement." Rewrite the WHOLE sentence, not the quoted fragment.

That becomes false with T2. `qa-guard` is now a bounded writer. No test guards
this prose — it goes stale silently. Rewrite so the three bounded writers are
grouped and the count still reads correctly.

## Verification

```bash
PYTHONPATH=scripts python -m unittest discover -s tests
```
Do NOT use pytest — the local wrapper uses an out-of-contract interpreter and
reports a spurious `Path.read_text() ... newline` TypeError (`CONTRIBUTING.md`).

Then confirm the theme round-trip still holds:
```bash
python scripts/apply_theme.py --dry-run philosophers
```

## Out of scope

- Any hook. Recorded above with reasons.
- A commit convention for `qa-guard` (would be needed only for a log-based gate).
- The same audit for other writers.
