---
name: modular-design
description: Use when a file has grown large, when deciding how to split a module, or when a task would add code to an already-oversized file. Applies a cohesion test rather than a line limit, and refuses splits that would separate shared state. Triggers on "this file is too big", "split this module", "god class", "refactor into modules", "where should this code live", "module boundaries".
user-invocable: true
---

# Modular design

## Overview

Files grow because nothing is ever obliged to notice. This skill supplies the
obligation and, more importantly, the judgment — because "keep files small" on
its own is worse than no rule at all. It produces ten fifty-line files with
circular imports and calls that an improvement.

The rule this skill enforces is not about size. It is:

> A unit does one thing, can be named without "and", and hides how it does it.

## When this applies

- A file crossed the tripwire (below) and someone has to decide what that means.
- A task would add code to a file that is already over it.
- A module's responsibilities feel tangled and you want a defensible boundary.
- Someone asked for a split and you need to check whether it is the right one.

## The tripwire

Default **400 physical lines**. A project may override it in its `CLAUDE.md`
`## Architecture` section (`Module tripwire: 500 lines.`).

Get the numbers instead of guessing at them:

```bash
python scripts/module_scan.py
python scripts/module_scan.py --tripwire 500 --top 10
python scripts/module_scan.py --json          # for programmatic use
```

**Crossing the tripwire does not mandate a split.** It mandates running the
three tests below and stating the outcome. A cohesive 900-line file passes and
is left alone. Say so explicitly — an unstated "I looked and it was fine" is
indistinguishable from not looking, and the next agent re-litigates it.

## The three tests

Apply in order. **Tests 2 and 3 are veto gates**: test 1 can say "split", and
either of the others can overrule it.

### 1. Reasons to change

How many distinct reasons would make someone edit this file?

Count causes, not functions. "The pricing rules changed", "we moved to a new
payment provider", and "the invoice PDF layout changed" are three reasons. Ten
functions that all change when the pricing rules change are one reason.

- **1 reason** → cohesive. Leave it, whatever its length.
- **2 reasons** → borderline. Split only if the halves are genuinely independent.
- **3+ reasons** → split along those reasons.

### 2. Shared private state (veto)

Would the two halves share mutable private state — a cache, a connection, a
counter, an accumulated buffer, an initialization order?

**If yes, they are one unit. Do not split them.** A split here does not remove
the coupling; it makes it invisible, converts a local variable into a
cross-module contract, and turns a bug you could see into one you cannot.

Read-only shared *constants* do not trigger this veto. Shared *mutable* state
does.

### 3. Name test (veto)

Can each proposed half be given a name that says what it does, without "and",
and without falling back to `utils`, `helpers`, `common`, `misc`, `core`,
`base`, or a bare `manager`?

**If the best name you can find is `utils.py`, the boundary is wrong.** That name
is what a leftover pile is called. Find a different cut, or leave the file whole.

## Deciding, and recording the decision

State the outcome in one of three forms:

- **"Cohesive — one reason to change (<the reason>). Left whole at N lines."**
- **"Split declined — <k> reasons to change, but <veto 2|veto 3>: <why>. Left
  whole at N lines."**
- **"Split along <k> reasons: <name> (<reason>), <name> (<reason>). Boundary
  passes the state and name tests."**

The second form is the one people forget. A file can fail test 1 and still be
correct to leave whole; reporting that as "cohesive" hides the veto and
guarantees the next agent re-litigates it.

Where it goes, if you are an agent implementing a task: a **proposed boundary**
is a scopeable task and belongs in `<out-of-scope>`. A **declined split or a
cohesive verdict is not a task** — state it in your report body instead, so the
findings list stays a list of work and not a log of non-findings.

## The split procedure

Only run this when splitting *is* the assigned task.

1. **Target one file.** From `module_scan.py` or named directly.
2. **Inventory.** List every top-level symbol — function, class, constant — and
   group them by reason-to-change. Write the groups down before judging them.
3. **Apply the veto gates.** Shared private state, then the name test. **This
   step may legitimately conclude "do not split"** — record the reasoning and
   stop. That is a successful outcome of this skill, not a failure of it.
4. **Propose.** New file names, what moves to each, and the resulting import
   edges — including any new cycle, which is a sign the boundary is wrong.
   **Stop here and get approval before touching anything.** When the split is
   already an approved task in a work plan, the plan *is* the approval: record
   the boundary in your report and continue to step 5. Return `BLOCKED` only if
   the boundary you found differs materially from the one the task assumed.
5. **Execute as pure moves.** Move code with no logic edits, no signature
   changes, no renames, no opportunistic cleanup. Run the tests after each move.
6. **Only then thin the wrappers**, as separate commits.

**Steps 5 and 6 must not share a commit.** A move that changes no behaviour is
reviewable by inspection. A behaviour change that is not tangled with six
hundred lines of motion is reviewable at all. Together they are neither, and
"the refactor broke something" becomes unbisectable.

Commit moves with the `[refactor]` phase bracket:

```bash
git commit -m "refactor: [refactor] extract pricing rules from billing"
```

## Shape catalogue

If the project declares an architecture in its `CLAUDE.md` `## Architecture`
section, or visibly already uses one, follow it. **Otherwise impose nothing** —
follow the structure that is there.

- **Layered service** — endpoints / manager / repository. See the
  `layered-api-design` skill for the full treatment.
- **Pipeline** — one module per transform stage, with an explicit data contract
  between stages. The contract, not the stage, is the unit that must stay stable.
- **Plugin / registry** — a thin dispatching core plus one module per capability.
  The core must not know any capability by name.
- **Library** — a public surface module over private internals. Everything not
  named in the surface is free to change.

Each layer, stage, or plugin is itself a **thin wrapper over focused
submodules**. A "layer" that is one 2,000-line file has not been decomposed; it
has been labelled.

## Who does what

- **An implementer** that notices an over-tripwire file **does not split it
  mid-task** — that is scope expansion. It runs the three tests and reports the
  proposed boundary in `<out-of-scope>`. A named boundary is a scopeable task; a
  line count is not.
- **A planner** that sees an over-tripwire file in a task's path schedules the
  extraction as its own preceding task.
- **A reviewing agent** raises boundaries as a maintainability finding with the
  count of reasons-to-change it found.

## Anti-patterns

- **Splitting by line count.** Produces even-sized files with arbitrary seams.
- **Splitting by technical layer when the project has no layers.** `models.py`,
  `views.py`, `utils.py` in a project that thinks in features means every feature
  change touches every file.
- **A `utils.py` that survives the split.** It is the pile of everything the
  boundary could not explain, and it will grow faster than what you split.
- **Splitting a file whose halves share a cache.** See veto 2.
- **Renaming and moving in one commit.** The diff shows deletion and creation;
  nobody can see that nothing changed.
- **"I'll clean this up while I'm in here."** That is the change nobody reviewed.
- **Declaring a file cohesive without saying why.** Unfalsifiable, and the next
  agent starts over.
