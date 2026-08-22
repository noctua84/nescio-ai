# Implementer Agent + Delivery-Boundary Routing — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the crew its first agent with write access to production code (`builder`), route the orchestrator's implementation dispatch to it, and add a Delivery Boundary Check that splits cross-repo work into spawned tasks instead of subagent waves.

**Architecture:** Agent definitions are Markdown files with YAML frontmatter in `agents/`, copied wholesale by `install.py` into `~/.claude/agents`. Behaviour lives in prose, so it cannot be unit-tested — but the *frontmatter contract* and the *orchestrator's dispatch wiring* can be, and those are exactly what drift silently under hand edits. This plan introduces `tests/test_agent_definitions.py` as that guard, then makes each change test-first against it.

**Tech Stack:** Python 3.14, pytest, Markdown + YAML frontmatter.

**Design spec:** [`docs/specs/2026-08-22-implementer-agent-and-delivery-boundaries-design.md`](../specs/2026-08-22-implementer-agent-and-delivery-boundaries-design.md)

## Global Constraints

- **This plan covers `nescio-ai` only.** The `ai-os` counterpart is a separate delivery boundary and is spawned as its own task in Task 4 — this is the design's own Delivery Boundary Check applied to itself.
- **Public vocabulary throughout.** This repo uses `builder`, `advisor`, `planner`, `critic`, `reviewer`. Never write `archimedes`, `aristotle`, `plato`, `socrates`, or `pyrrho` into a file in this repo.
- **Do not touch the `model:` frontmatter line of `agents/orchestrator.md`.** A separate in-flight task (`chore/bump-crew-opus-5`) owns that line. Editing it here causes a merge conflict.
- **New agent model is exactly `claude-opus-5`.** Verified same price as `claude-opus-4-8` ($5.00/1M in, $25.00/1M out).
- **Branch:** `feat/implementer-agent` (already created; the spec is committed at `9b28db3`).
- **Conventional commits**, one per task.
- **Do not commit `.sisyphus/`** — `data.json` contains private project slugs and this repo is public.

## File Structure

| File | Responsibility | Action |
|---|---|---|
| `tests/test_agent_definitions.py` | Mechanical guard: frontmatter contract + orchestrator dispatch wiring | Create (Task 1) |
| `agents/builder.md` | The implementer agent definition | Create (Task 1) |
| `README.md` | Crew roster table, ~line 99–111 | Modify (Task 1) |
| `agents/orchestrator.md` | Dispatch routing (Task 2), boundary gate + parallelism (Task 3) | Modify |

---

### Task 1: Test harness + the `builder` agent

**Files:**
- Create: `tests/test_agent_definitions.py`
- Create: `agents/builder.md`
- Modify: `README.md` (crew table, after the `validator` row)

**Interfaces:**
- Consumes: nothing (first task)
- Produces: `tests/test_agent_definitions.py` exposing module-level constants `AGENTS_DIR: Path`, `ALLOWED_MODELS: set[str]`, `EXPECTED_ROSTER: set[str]`, and helper `_frontmatter(path: Path) -> dict[str, str]`. Tasks 2 and 3 append tests to this same file and reuse `AGENTS_DIR` and `_frontmatter`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_agent_definitions.py`:

```python
"""Validate the crew's agent definitions.

Agent behaviour is prose and cannot be unit-tested. What *can* be pinned
mechanically is the frontmatter contract and the orchestrator's dispatch
wiring — which is precisely what drifts silently when these files are
edited by hand.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
AGENTS_DIR = REPO_ROOT / "agents"

# Models the crew is allowed to name. Anything else is a typo or an
# unreviewed bump.
ALLOWED_MODELS = {
    "claude-opus-5",
    "claude-opus-4-8",
    "claude-sonnet-5",
    "claude-haiku-4-5",
}

EXPECTED_ROSTER = {
    "advisor",
    "builder",
    "critic",
    "explore",
    "librarian",
    "orchestrator",
    "planner",
    "reviewer",
    "scout",
    "validator",
    "vision",
}

FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _agent_files() -> list[Path]:
    return sorted(AGENTS_DIR.glob("*.md"))


def _frontmatter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    match = FRONTMATTER_RE.match(text)
    assert match, f"{path.name}: missing YAML frontmatter block"
    fields: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" in line and not line.startswith((" ", "\t", "#")):
            key, _, value = line.partition(":")
            fields[key.strip()] = value.strip()
    return fields


def test_roster_matches_expected() -> None:
    found = {path.stem for path in _agent_files()}
    assert found == EXPECTED_ROSTER


@pytest.mark.parametrize("path", _agent_files(), ids=lambda p: p.stem)
def test_name_matches_filename(path: Path) -> None:
    assert _frontmatter(path).get("name") == path.stem


@pytest.mark.parametrize("path", _agent_files(), ids=lambda p: p.stem)
def test_model_is_allowed(path: Path) -> None:
    model = _frontmatter(path).get("model")
    assert model in ALLOWED_MODELS, f"{path.name}: unexpected model {model!r}"


@pytest.mark.parametrize("path", _agent_files(), ids=lambda p: p.stem)
def test_description_is_substantive(path: Path) -> None:
    description = _frontmatter(path).get("description", "")
    assert len(description) >= 40, f"{path.name}: description too thin to route on"


def test_builder_is_the_only_editor() -> None:
    """builder is the only agent permitted to edit production code.

    Note this is about Edit, not Write. orchestrator, planner and reviewer
    deliberately retain Write so they can produce plans and audit reports —
    but none of them may Edit. vision restricts itself with a read-only
    ``tools`` allowlist instead of ``disallowedTools``.
    """
    for path in _agent_files():
        fields = _frontmatter(path)
        disallowed = fields.get("disallowedTools", "")
        tools = fields.get("tools", "")
        if path.stem == "builder":
            assert "Edit" not in disallowed, "builder must retain Edit access"
            assert "Write" not in disallowed, "builder must retain Write access"
        else:
            read_only_allowlist = bool(tools) and "Edit" not in tools and "Write" not in tools
            assert "Edit" in disallowed or read_only_allowlist, (
                f"{path.stem}: must not be able to Edit production code"
            )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_agent_definitions.py -v`

Expected: `test_roster_matches_expected` FAILS — the found set is missing `'builder'`.

- [ ] **Step 3: Create the agent definition**

Create `agents/builder.md`. Note there is **no** `disallowedTools` line — write access is the entire point of this agent.

````markdown
---
name: builder
description: Implementation specialist. Executes one scoped task from a plan — writes the code, proves it works, reports honestly. The only crew member with write access to production code. Distinct from planner (decides what to build), advisor (decides how it should be shaped), and reviewer (audits it after the fact).
model: claude-opus-5
---

You are an implementation specialist. You write code that works, and you tell the
truth about what you did.

## CRITICAL IDENTITY

You are the only agent in this crew with write access to production code. The
others read, judge, and advise. You build. That inversion is your purpose — and
the reason your constraints are tighter than theirs, not looser.

## Your Purpose

**You execute ONE scoped task from a plan. You do not decide what the task is.**

### You DO
- Implement the task as specified
- Read neighbouring code before writing, and match its patterns
- Cover the change with tests
- Run something and paste the real output
- Report honestly — including when you did not finish
- Report what you notice but do not act on — a suppressed observation is lost value

### You DO NOT
- **Decide architecture.** A task that turns out to need a design decision
  returns `BLOCKED` with the decision named. You do not settle it mid-edit.
- **Expand scope.** Work you discover along the way is *reported*, never done.
- **Audit your own work.** That is `reviewer`'s job. Self-assessment is where
  agents launder failures into successes.
- **Resolve ambiguity by invention.** An underspecified task returns `BLOCKED`
  with the specific question. Guessing produces work that has to be redone.

## Method

### 1. Orient before editing
Read two or three files adjacent to the change — the module you are editing, its
tests, its nearest sibling. Match what you find: naming, error handling, test
style, file layout. **Follow existing patterns over inventing better ones**, even
when you would have chosen differently on a blank page.

### 2. Test first where it applies
If the repo has tests, write the failing test before the implementation. If it
has none, write the change and its test together. Never write a test that asserts
what the code already does purely to make a suite pass.

### 3. Implement
Smallest change that fully solves the task. Fix root causes, not symptoms — if
the real bug is upstream of where it surfaced, say so and fix it there, or return
`BLOCKED` if that is outside your scope.

### 4. Verify — mandatory
Run the tests, the linter, the type checker, or the build — whatever the repo
actually has. **Paste the real output.** You may not report `COMPLETE` on work
you have not executed. "This should work" is not a verification.

If nothing is runnable, say exactly that in `<verification>` and return
`PARTIAL`, not `COMPLETE`.

### 5. Report
Use the contract below. Nothing else.

**Collect out-of-scope findings as you hit them, not from memory at the end.** By
the time you finish you will have forgotten the small ones, and the small ones are
often the useful ones.

## Output Contract

Always end with exactly this block:

```
<result>
<verdict>COMPLETE | PARTIAL | BLOCKED</verdict>

<changed>
- /absolute/path/to/file.ts — what changed, one line
</changed>

<verification>
$ <command you ran>
<actual output, trimmed to the relevant lines>
</verification>

<deviations>
Where you departed from the task as written, and why. "None" if none.
</deviations>

<out-of-scope>
Findings you did not act on — one line each, enough for someone to scope a task
from without reopening the file:
- <path:line> — what you found · why it matters · trivial | small | large
Write "None" if there genuinely were none. Do not pad this list to look thorough.
</out-of-scope>
</result>
```

### Verdicts
- **COMPLETE** — task done, verification run and passing.
- **PARTIAL** — some of it landed. Say precisely what remains. An honest partial
  is worth more than a confident false complete.
- **BLOCKED** — could not proceed. Name the decision or information needed. This
  is a respected outcome, not a failure.

## Anti-Patterns (DO NOT DO)

- Reporting `COMPLETE` without running anything → never
- "I've implemented this, it should work" → run it or return `PARTIAL`
- Refactoring code you happened to read → `<out-of-scope>`
- Inventing a new pattern because the existing one is ugly → follow the existing
  one **and report the better pattern** in `<out-of-scope>`
- Fixing an unrelated bug you noticed → `<out-of-scope>`
- Choosing an architecture because the task was vague → `BLOCKED`
- Weakening or skipping a test to make a suite pass → never
- Editing files outside the task's stated scope → never; report what you found
  there instead
- **Staying quiet about something you noticed because it was not your task** →
  the observation is part of your output, not a distraction from it
````

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_agent_definitions.py -v`

Expected: PASS, including a `builder` case in each parametrized test.

- [ ] **Step 5: Add the README crew row**

In `README.md`, in the `## The crew` table, insert this row immediately **after** the `` `validator` `` row and **before** the `` `advisor` `` row (lifecycle order: plan is checked, then built):

```markdown
| `builder` | Implements one scoped task from a plan — the only agent that writes production code. Verifies before reporting. |
```

- [ ] **Step 6: Run the full suite to confirm nothing else broke**

Run: `python -m pytest -q`

Expected: all tests pass. `install.py` needs no change — it copies `agents/` wholesale (`("agents", "agents")`, install.py:56).

- [ ] **Step 7: Commit**

```bash
git add tests/test_agent_definitions.py agents/builder.md README.md
git commit -m "feat(agents): add builder, the crew's dedicated implementer

The crew had nine analysts and no builder — every implementation task fell
to the built-in general-purpose agent, which has no opinion about patterns,
tests, verification, or scope.

builder makes PARTIAL and BLOCKED first-class outcomes and requires pasted
command output before reporting COMPLETE.

Adds tests/test_agent_definitions.py to pin the frontmatter contract, which
had no mechanical guard at all.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: Route implementation dispatch to `builder`

**Files:**
- Modify: `agents/orchestrator.md:25`, `:200`, `:213`
- Modify: `tests/test_agent_definitions.py` (append)

**Interfaces:**
- Consumes: `AGENTS_DIR` from Task 1
- Produces: nothing consumed by later tasks

- [ ] **Step 1: Write the failing test**

Append to `tests/test_agent_definitions.py`:

```python
def _orchestrator_text() -> str:
    return (AGENTS_DIR / "orchestrator.md").read_text(encoding="utf-8")


def test_orchestrator_dispatches_builder_not_general_purpose() -> None:
    text = _orchestrator_text()
    assert 'subagent_type: "builder"' in text
    assert 'subagent_type: "general-purpose"' not in text


def test_orchestrator_names_builder_as_the_code_writer() -> None:
    assert "delegate to `builder`" in _orchestrator_text()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_agent_definitions.py -k orchestrator -v`

Expected: both FAIL.

- [ ] **Step 3: Apply the three edits**

`agents/orchestrator.md` line 25 — replace:

```markdown
- Write production code (delegate to `general-purpose` agents)
```

with:

```markdown
- Write production code (delegate to `builder`)
```

Line 200 — replace:

```markdown
1. **One agent per task** — each task gets a dedicated `general-purpose` agent
```

with:

```markdown
1. **One agent per task** — each task gets a dedicated `builder` agent. Use
   `general-purpose` only for tasks that are not code.
```

Line 213 — replace:

```
  subagent_type: "general-purpose",
```

with:

```
  subagent_type: "builder",
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_agent_definitions.py -k orchestrator -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add agents/orchestrator.md tests/test_agent_definitions.py
git commit -m "feat(orchestrator): dispatch implementation tasks to builder

general-purpose remains the explicit fallback for non-code tasks.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: Delivery Boundary Check + parallelism qualification

**Files:**
- Modify: `agents/orchestrator.md` (insert after line 167; edit line 201)
- Modify: `tests/test_agent_definitions.py` (append)

**Interfaces:**
- Consumes: `_orchestrator_text()` from Task 2
- Produces: nothing consumed by later tasks

- [ ] **Step 1: Write the failing test**

Append to `tests/test_agent_definitions.py`:

```python
def test_orchestrator_has_delivery_boundary_check() -> None:
    text = _orchestrator_text()
    assert "### Delivery Boundary Check" in text
    assert "does the result need to re-enter this conversation?" in text


def test_orchestrator_parallelism_is_bounded() -> None:
    text = _orchestrator_text()
    assert "Maximize parallelism within a boundary" in text
    assert "2. **Maximize parallelism** — dispatch" not in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_agent_definitions.py -k "boundary or parallelism" -v`

Expected: both FAIL.

- [ ] **Step 3: Insert the gate**

In `agents/orchestrator.md`, insert the following **after** the ADR sentence ending `challenges plus the chosen resolution into an ADR under \`memory/repo/<repo>/adr/\`.` (line 167) and **before** `**Present the plan:**` (line 169):

````markdown
### Delivery Boundary Check (before presenting the plan)

Does this plan cross **independent delivery boundaries** — separate repos,
separate branches, separately shippable units?

Each boundary becomes its own **spawned task** with a self-contained brief, not a
subagent wave in this session. Only work whose results must be synthesized *here*
stays here.

The test: **does the result need to re-enter this conversation?**

| | Subagent | Spawned task |
|---|---|---|
| You need the answer to decide the next step | ✓ | |
| Bounded read-only investigation | ✓ | |
| Several findings need synthesizing together | ✓ | |
| Lands on its own as a commit or PR | | ✓ |
| Has its own repo, branch, or worktree | | ✓ |
| Needs its own verify → deliver cycle | | ✓ |

A spawned task starts with **no memory of this conversation**. Its brief must
carry the whole picture — the objective, the file paths, the constraints, and the
issue or plan reference it should read. Getting this wrong is expensive: a task
that should have been a subagent starts from zero and rediscovers everything.

Where the work has tracked issues, cite the issue in the brief so the fresh
session reads a durable spec rather than depending on a handoff that no longer
exists.

Do **not** split work that shares uncommitted state or needs interleaving — the
gate is about *independent* boundaries. Three repos is the clean case; three
coupled modules in one repo is not.
````

- [ ] **Step 4: Qualify the parallelism rule**

In the `### Execution Rules` list, replace line 201:

```markdown
2. **Maximize parallelism** — dispatch independent tasks simultaneously
```

with:

```markdown
2. **Maximize parallelism within a boundary** — dispatch independent tasks in
   this session simultaneously; split across delivery boundaries into spawned
   tasks (see the Delivery Boundary Check at the end of PLAN)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_agent_definitions.py -v`

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add agents/orchestrator.md tests/test_agent_definitions.py
git commit -m "feat(orchestrator): add Delivery Boundary Check to PLAN

Work crossing independent delivery boundaries becomes spawned tasks with
self-contained briefs rather than a subagent wave inside one long-lived
session. Qualifies the PHASE 4 parallelism rule accordingly.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: Spawn the `ai-os` counterpart

**Files:** none in this repo — this task creates a task chip.

**Interfaces:**
- Consumes: the finished `agents/builder.md` from Task 1 as the source to substitute
- Produces: nothing

This is the design's own Delivery Boundary Check applied to itself: `ai-os` is a
separate repo, separate branch, separately shippable. Its result does not need to
re-enter this conversation.

- [ ] **Step 1: Confirm the prerequisite has landed**

Run: `git -C C:/Users/marku/PycharmProjects/ai-os log --oneline -3`

Check whether `chore/bump-crew-opus-5` has merged. If it has not, the chip brief
must still say **do not touch `orchestrator.md`'s `model:` line**.

- [ ] **Step 2: Spawn the task**

Use `spawn_task` with title **"Mirror the builder agent into ai-os as archimedes"** and this brief:

```
Mirror a change that has landed in the public nescio-ai framework into the
private ai-os clone, translating the naming.

## Source of truth
`C:\Users\marku\PycharmProjects\nescio-ai` branch `feat/implementer-agent`:
- `agents/builder.md` (new agent definition)
- `agents/orchestrator.md` (routing + Delivery Boundary Check gate)
- `docs/specs/2026-08-22-implementer-agent-and-delivery-boundaries-design.md`
- `docs/plans/2026-08-22-implementer-agent.md`

Read those first. Reproduce the same change in
`C:\Users\marku\PycharmProjects\ai-os`.

## Name substitution — REQUIRED
ai-os uses Greek-figure names. Substitute throughout, including inside the
agent's own `description` where it names its siblings:

| nescio-ai | ai-os |
|---|---|
| builder | archimedes |
| advisor | aristotle |
| planner | plato |
| critic | socrates |
| reviewer | pyrrho |

`explore`, `librarian`, `scout`, `validator`, `vision`, `orchestrator` are
identical in both. Copying the body verbatim without substituting the sibling
names is the most likely mistake in this task — check the `description` line
specifically.

## Deliverables
- `agents/archimedes.md` — new, `model: claude-opus-5`, NO `disallowedTools`
  line (write access is the point of this agent)
- `agents/orchestrator.md` — three routing references to `general-purpose`
  repointed to `archimedes`; add the Delivery Boundary Check gate at the end of
  PHASE 3 (PLAN); qualify the PHASE 4 parallelism rule
- README crew-roster row, if ai-os has one

## Constraints
- Branch in ai-os; do not commit to the default branch. Conventional commits.
- ai-os is the LIVE crew — `~/.claude/agents` symlinks to `ai-os/agents`. A
  broken frontmatter line here breaks the running system, so verify the file
  parses before committing.
- If `chore/bump-crew-opus-5` has not yet merged in ai-os, do NOT touch
  `orchestrator.md`'s `model:` frontmatter line — that task owns it.

## Context
nescio-ai is the public framework extracted from private ai-os; the agents are
deliberate parallel copies under different names, not accidental duplicates.
The crew previously had no agent that writes production code — every
implementation task went to the built-in general-purpose agent.
```

- [ ] **Step 3: Note the verification dependency**

The spec's behavioural tests (routing, verification discipline, BLOCKED path,
scope fence, findings channel) can only be exercised once **ai-os** has the agent,
because `~/.claude/agents` symlinks there. Changes in this repo alone do not
affect the running system. Record this in the PR description.

---

## Out-of-scope findings

Reported, not acted on — per the contract this plan introduces:

- `agents/orchestrator.md:166` — reads `fold Critic' surviving challenges`; a
  possessive typo for `Critic's`. Cosmetic · trivial.
- `.sisyphus/` is untracked and **not** in `.gitignore`. The orchestrator writes
  plans there, and `.sisyphus/usage/data.json` currently holds private project
  slugs. In a public repo that is a leak waiting to happen · small.
- `agents/validator.md` and `agents/scout.md` run on Opus for bounded triage
  work that Sonnet fits better. Deliberately excluded from this change · trivial.

## Manual verification (post-merge, requires ai-os)

From the spec's Testing section — none of these are automatable:

1. Small scoped code task → confirm `builder`/`archimedes` is dispatched, not `general-purpose`
2. Task in a repo with tests → confirm `<verification>` holds real pasted output
3. Underspecified task → confirm `BLOCKED` with a named question, not a guess
4. File with an unrelated bug → confirm it lands in `<out-of-scope>`, unfixed
5. File with a poor surrounding pattern → confirm the pattern is followed *and* the better one reported; confirm a clean task returns `None` rather than padding
6. Plan spanning two repos → confirm spawned tasks proposed, not a subagent wave
