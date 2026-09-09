# Modular design doctrine — cohesion tripwire, split procedure, opt-in layering

Status: draft — awaiting review

> The crew has no concept of module boundaries. A grep of `agents/`, `skills/`,
> `CLAUDE.md`, `README.md` and `ROADMAP.md` for cohesion / file-size / split
> language returns nothing but false positives. Files grow without limit because
> nothing in the crew is ever obliged to notice.

## Purpose

Give the crew a defensible answer to "this file has gotten too big" — one that
prevents god-files at write time, remediates the ones that already exist, and
surfaces the rest as tracked debt. Plus an **opt-in** layered-service shape for
projects that want it, delivered as a worked example rather than a crew default.

Five deliverables:

1. `skills/modular-design/SKILL.md` — the rule, the tripwire, the split procedure
2. `skills/layered-api-design/SKILL.md` — endpoints / manager / repository, gated
3. `scripts/module_scan.py` — read-only size report
4. Instruction edits to `planner`, `builder` (×3 tiers), `reviewer`
5. An optional `## Architecture` section in the `CLAUDE.md` project brief

## Why this design

- **No new agent.** Modularization is not a job the way planning or auditing is —
  it is a property of how `planner` decomposes and how `builder` writes. An agent
  would have to be invoked by someone who already noticed the problem, which is
  precisely the failure being fixed.
- **Line count prompts, cohesion decides.** A pure line threshold is enforceable
  and wrong: it rewards splitting for its own sake, and ten 50-line files with
  circular imports score better than one cohesive 500-line file. The tripwire
  obliges an agent to *ask the question and record the answer*, nothing more.
- **Two of the three tests exist to block bad splits.** This is the part most
  "keep files small" guidance omits, and the reason such guidance backfires.
- **Architecture is declared, never inferred.** `endpoints/manager/repository` is
  standard for CRUD-over-HTTP and actively wrong for a CLI, a data pipeline, a
  game loop, or this repo. A public framework that imposes it has the same defect
  as one that imposes hexagonal.
- **Reuse the existing delivery path.** `builder` already reports `<out-of-scope>`
  findings and `orchestrator` already carries them to DELIVER as candidate spawned
  tasks. Boundary findings ride that machinery. No orchestrator changes.

## 1. The rule — stated once, in `skills/modular-design/`

A unit does one thing, can be named without "and", and hides how it does it.

Three tests, applied in order:

| Test | Question | Fails when |
|---|---|---|
| **Reasons to change** | How many distinct reasons would make someone edit this file? | 3+ → split along those reasons |
| **Shared private state** | Would the two halves share mutable private state? | Yes → they are one unit, **do not split** |
| **Name test** | Can each half be named without "and", "Utils", "Helpers", "Manager"? | No → the boundary is wrong; find another |

**Split by reason-to-change, never by line count.**

Tests 2 and 3 are veto gates. Test 1 can say "split"; either of the others can
overrule it. A file that fails test 1 but whose only available split would share
private state stays whole, and the agent says so.

### The tripwire

Default **400 physical lines**, overridable per project (§5).

Crossing it does not mandate a split. It mandates *running the three tests and
stating the outcome*. A cohesive 900-line file passes and is left alone; the
agent records why. Physical lines, not logical — the number is a prompt to look,
so precision buys nothing, and blank/comment-stripping only adds argument surface.

## 2. Prevention — agent instruction edits

Surgical. Each edit lands inside the section it sharpens, not as a bolt-on.

### `agents/planner.md`

- **Task decomposition** (existing "one task = one module/concern = 1-3 files"):
  when a task would add to a file already over the tripwire, plan the extraction
  as its own *preceding* task, tiered `standard` or `complex`.
- **Plan Structure → Context**: record the project's declared architecture (§5)
  if it has one, so builders inherit it without re-deriving it.

### `agents/builder.md`, `builder-standard.md`, `builder-simple.md`

- New line in **Anti-Patterns**: *appending to a file already over the tripwire
  without running the cohesion test*.
- Explicit in **You DO NOT**: the split is **never performed mid-task**. That is
  scope expansion, which builder is already forbidden. It goes in `<out-of-scope>`
  with the proposed boundary named — which is more useful than a line count,
  because it is a scopeable task.
- **Exception**: when the plan's task *is* the split, execute it per §3.

### `agents/reviewer.md`

- Module boundaries become a review dimension, subject to the existing confidence
  tags and quote-per-citation rules. A finding names the file, the count of
  reasons-to-change found, and the proposed boundary.

### `agents/orchestrator.md` — unchanged

Deliberately. Its `<out-of-scope>` collection during EXECUTE and the findings
section in DELIVER already route boundary findings to spawned tasks. Adding a
file-size rule to the crew's largest file would be a poor advertisement for the
doctrine.

## 3. Remediation — the procedure in `skills/modular-design/`

1. Target a file — from `module_scan.py` (§4) or named directly.
2. Inventory every top-level symbol; group by reason-to-change.
3. Apply the shared-state and name guards. **This step may legitimately conclude
   "do not split"** — record the reasoning and stop.
4. Propose the split: new file names, what moves to each, resulting import edges.
   **Stop and get approval before touching anything.**
5. Execute as **pure moves** — no logic edits, no signature changes, no
   opportunistic cleanup. Tests green after each move.
6. Only then thin the wrappers, as separate commits.

The 5/6 separation is the safety property: a move that changes no behaviour is
reviewable by inspection, and a behaviour change not tangled with 600 lines of
motion is reviewable at all. Reviewing them together is reviewing neither.

Commits use a new **`[refactor]`** prefix, joining the existing
`[impl]` / `[fix]` / `[test]` / `[docs]` / `[chore]` phase brackets, and coexisting
with conventional-commit format — `refactor: [refactor] extract billing pricing`.

The doubling in `refactor: [refactor] …` is accepted, exactly as `fix: [fix] …`
already is. The conventional type is a release-tooling necessity; the bracket is
the phase-scoped review paper trail. Two audiences, not one redundant label — do
not "clean this up."

### Shape catalogue

Two to three lines each. Pointers, not doctrine. Applied only when the project
declares the shape (§5) or already visibly uses it:

- **layered service** → `skills/layered-api-design/`
- **pipeline** — one stage per transform; an explicit data contract between stages
- **plugin / registry** — thin dispatching core, one module per capability
- **library** — a public surface file over private internals

## 4. `scripts/module_scan.py`

Read-only report. Mirrors the established `repo_hygiene_scan.py` precedent:
detection is a separate program from anything that changes files.

- Enumerates via `git ls-files`, so `.gitignore` is respected for free and the
  tool is correct inside a worktree.
- Default exclusions: migrations, lockfiles, generated sources (`*_pb2.py` and
  similar), minified assets, vendored trees.
- Flags: `--tripwire N` (default 400), `--top N`, `--json` for agent consumption.
- **Always exits 0.** It is a report, not a gate. A non-zero exit would make it a
  CI blocker by accident the first time someone pipes it into a workflow.
- Non-UTF-8 files are counted by byte-newlines rather than skipped or crashed on.

Output:

```
  over tripwire (>400 lines)
  ------------------------------------
   1180  src/api/handlers.py
    612  src/models/user.py
    418  src/services/billing.py

  3 files over, 247 scanned
  run the modular-design skill on any of these to get a proposed split
```

## 5. `skills/layered-api-design/` and the opt-in gate

The skill opens with an explicit gate:

> Applies only when the project declares layered-service architecture in its
> `CLAUDE.md`, or already visibly uses it. Never inferred from "this is an HTTP
> API." If the project has not declared a shape, use `modular-design` and follow
> the structure that is already there.

Each layer is a thin wrapper over focused submodules — e.g. `managers/billing/`
containing `pricing.py` and `invoicing.py` behind a thin `__init__.py` surface.

| Layer | Owns | Never touches |
|---|---|---|
| **endpoints** | parse, validate input, call one manager function, format output, map errors to status codes | business rules, SQL |
| **manager** | business rules, orchestration across repositories, the transaction boundary | HTTP types in *or* out, SQL |
| **repository** | persistence; accepts and returns domain types | business rules |

Named anti-patterns, each with its tell and its fix:

- **fat controller** — branching business logic in the handler
- **SQL in the handler** — the repository layer bypassed entirely
- **anemic manager** — a pure pass-through that adds nothing; the tell that this
  project does not need the layer, and the honest fix is to delete it
- **leaky repository** — ORM rows returned upward, coupling managers to the schema
- **logic in the serializer** — business decisions hidden in output formatting
- **handler orchestrating multiple managers** — the signal that a manager function
  is missing, not that the handler should coordinate

### The declaration

A new optional section in the `CLAUDE.md` project brief, documented in `README.md`:

```markdown
## Architecture

Layered service. HTTP handlers validate and format only; managers own the
business rules and the transaction boundary; repositories own SQL.

Module tripwire: 500 lines.
```

Absent this section, the crew follows existing structure and imposes nothing.

## Testing

`scripts/module_scan.py` is tested alongside the other scripts in `tests/`:

- a file exactly at, one under, and one over the tripwire (boundary conditions)
- `--tripwire` override honoured
- excluded categories (migrations, lockfiles, generated, vendored) omitted
- untracked and gitignored files omitted
- a non-UTF-8 file counted, not crashed on
- empty repository → clean report, exit 0
- `--json` output shape is stable and parseable

The skills and agent edits are prose; they are verified by review, not by tests.

## Out of scope

- Splitting `agents/orchestrator.md` (24.4KB — the largest file in the crew, and
  a god-file by the rule written here). Real, tracked separately, not this change.
- A blocking commit hook. Considered and rejected: it would fire on anyone with a
  legitimate mid-task reason to grow a file, and the cost of being wrong is much
  higher than the cost of a missed detection.
- Language-aware logical-line counting, cyclomatic complexity, import-graph
  analysis. All defensible; none needed for a tripwire whose only job is to
  prompt a human-legible judgment.
- Retrofitting the doctrine across the existing `skills/` tree.

## Success criteria

- A builder that appends to an over-tripwire file reports the boundary it would
  draw, in `<out-of-scope>`, without splitting mid-task.
- A planner that sees an over-tripwire file in a task's path schedules the
  extraction ahead of the work.
- `module_scan.py` runs clean on this repo and names `agents/orchestrator.md`.
- `modular-design` can conclude "do not split" on a cohesive long file and say why.
- A project with no `## Architecture` section gets no layering imposed on it.
