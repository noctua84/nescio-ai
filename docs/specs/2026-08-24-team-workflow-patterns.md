# Team Workflow Patterns — Contribution Proposal

Status: draft

## Background

This spec proposes six patterns for integration into nescio, drawn from running
Claude Code daily as a team tool across multiple production codebases over several
months. The team context matters: unlike solo use, team use surfaces failure modes
that only emerge when multiple people share the same agent setup, commit into the
same branches, and hand half-finished sessions to each other. The patterns here
are the places where the crew — as shipped in 1.0 — needed supplementing.

Nothing here conflicts with nescio's core design. Several patterns sharpen
existing concepts (the reviewer, the builder output contract, the orchestrator's
parallelism rule). Others introduce roles the crew currently leaves to
`general-purpose` or to the user: test authorship, documentation maintenance,
CI-gate iteration.

All patterns are company- and tech-stack-agnostic as specified here. Each has
been running in a language-specific form for several months; this spec describes
the generalised form that belongs in the framework.

---

## Pattern 1 — `test-writer`: a dedicated test-authorship agent

### The problem

`builder` writes the implementation and covers it with tests. This works well
for small, self-contained tasks. It breaks in two ways at team scale:

1. **Scope pressure.** When a task is large or complex, `builder` completes the
   implementation and writes minimal tests to satisfy the DoD, rationalising that
   "reviewer will catch issues." Tests written under deadline pressure by the same
   agent that wrote the implementation tend to test the implementation's current
   behaviour rather than its intended contract.

2. **Bug laundering.** If `builder` finds a bug while writing tests, the temptation
   is to fix it in the same commit — a small, well-intentioned scope creep that
   blurs the audit trail. The fix belongs in a `builder` task; the test belongs in
   a `test-writer` task; mixing them makes both harder to review.

### The solution

A `test-writer` agent with a hard file boundary: it may only write or modify files
inside the project's test directories. It cannot touch implementation files under
any circumstances — not even "trivial fixes." When it finds a bug, it documents
it and returns `BLOCKED` with a precise description. The fix is a separate task
for `builder`.

This separation has a second benefit: `test-writer` can run in parallel with
subsequent `builder` tasks on separate branches, because it never touches
production files. On a shared branch, they must remain sequential — git conflicts
arise from concurrent commits regardless of which files each agent touches.

### Key behaviours

- Hard file boundary enforced in the agent prompt ("you may not write to any file
  outside the test directories — not even once, not even a one-line fix")
- Bug escalation path: document in `<blocked-on>`, return `BLOCKED`, never patch
- Test contract: tests assert the intended interface, not the implementation's
  current output. If those differ, that is a bug — escalate it.
- No test weakening: removing an assertion or adding an exception to make a suite
  pass is forbidden; `BLOCKED` is the correct outcome
- Output contract: same `<result>` block as `builder`, with `<verdict>` and
  `<verification>` carrying the actual test run output

### Fit with nescio

`test-writer` is a peer of `builder`, not a sub-role. The orchestrator dispatches
them to separate phases. The pattern aligns with nescio's existing hard-file
restrictions (see `reviewer`'s read-only constraint, `critic`'s and `advisor`'s
`disallowedTools: Write, Edit`) — `test-writer` extends the same principle to
production implementation files.

---

## Pattern 2 — Phase-scoped audit trail via typed commits

### The problem

The crew produces one unbroken stream of commits with conventional messages. The
`reviewer` reads the current working tree and recent diff. When a session spans
multiple phases (implement → test → fix → docs), the reviewer has no structural
handle to scope its audit to exactly one phase's worth of changes. It either
over-reads (reviewing tests when it was asked to review implementation) or
under-reads (missing a fix commit that snuck in a behaviour change).

### The solution

A typed commit convention — a short bracketed prefix on every commit produced by
the crew — combined with a `reviewer` discipline that pins its diff to a single
prefix type:

| Prefix | Author | What it covers |
|---|---|---|
| `[impl]` | `builder` | Production code changes |
| `[test]` | `test-writer` | Test additions and modifications |
| `[fix]` | `builder` | Bug fixes surfaced by test-writer |
| `[docs]` | documentation agents | Documentation only |
| `[chore]` | any | Config, tooling, scaffolding |

`reviewer` is invoked per-phase. After an `[impl]` phase, it runs `git log
--oneline --grep='\[impl\]'` to identify the relevant commits, then `git diff
<oldest-impl-sha>^..HEAD -- <impl-paths>` to scope its read. It does not look
at `[test]` commits unless reviewing a `[test]` phase.

The second benefit: the orchestrator can enforce a **regression gate** after
`[test]` phases. Before accepting a `[test]` verdict, it verifies that no
`[impl]` files changed in the `[test]` commits. If they did, it rejects the
verdict and re-dispatches with an explicit boundary reminder. This catches the
failure mode where `test-writer` "just fixed one small thing" in an impl file.

### Key behaviours for `reviewer`

- Determine phase from the commit prefix being reviewed
- Resolve the exact set of commits belonging to that phase via `git log --grep`
- Scope the diff to those commits and their affected paths
- Do not read commits from other phases for "context" — record any cross-phase
  question as `[UNVERIFIED]` rather than fetching

### Key behaviours for `orchestrator`

- After every `[test]` wave: verify that no implementation file paths appear in
  the diff for those commits — the exact check depends on the project's directory
  structure, but the principle is: if `test-writer`'s commits touch any file
  outside the project's test tree, reject the verdict and re-dispatch with an
  explicit boundary reminder
- Expose the commit prefix for each phase to `builder` and `test-writer` so they
  know what to use, rather than leaving it to convention

### Relationship to conventional commits

Nescio already uses conventional commits (`feat(agents): ...`, `fix: ...`,
`chore: ...`). The typed prefix is a complementary layer, not a replacement:
the conventional type describes *what kind of change* it is; the bracketed prefix
describes *which workflow phase produced it*. They coexist in the same message:
`feat: [impl] add authentication handler`. The bracketed prefix is what
`reviewer` and the regression gate grep for; the conventional prefix is what
release-please and changelogs consume.

### Fit with nescio

This extends nescio's existing reviewer ref-pinning discipline
(spec: `2026-07-28-review-disciplines-design.md`). The confidence-tag and
verbatim-quote rules remain; the typed-commit targeting is an additional scoping
layer on top of the existing evidence framework.

---

## Pattern 3 — Cost-tiered implementation routing

### The problem

`builder` runs on `claude-opus-5` for all tasks regardless of complexity. For a
solo user working on one codebase, this is reasonable — most tasks benefit from
the reasoning depth. In a team context running dozens of tasks per day, a
significant fraction of those tasks are genuinely mechanical: adding a config key,
updating a constant, writing a one-function wrapper, adding a new test case to an
existing suite. Running Opus for these is both slow and expensive relative to
what the task requires.

### The solution

Complexity classification at plan time, model routing at dispatch time.

The `planner` classifies every task with one of three tiers when it writes the
plan. The orchestrator uses the tier to select the builder variant:

| Tier | Description | Model |
|---|---|---|
| `simple` | Mechanical — no design judgment, no ambiguity, &lt;50 lines, well-understood pattern | `claude-haiku-4-5` |
| `standard` | Moderate — some judgment, 50–200 lines, one or two design decisions | `claude-sonnet-5` |
| `complex` | High reasoning load — architecture decisions, cross-system impact, significant ambiguity | `claude-opus-5` |

The tier lives in the plan file alongside each task's DoD. It is **planner's
estimate, not orchestrator's judgment** — the orchestrator reads and routes, it
does not reclassify. If `builder` hits ambiguity that makes a `simple` task
actually `complex`, it returns `BLOCKED` with the question rather than upgrading
its own model.

The practical effect: in a day of 20 tasks, perhaps 8 are `simple`, 8 `standard`,
4 `complex`. Running the right model saves significant wall-clock time and cost
with no quality reduction on the simple tasks.

### Fit with nescio

This is an additive capability. The existing `builder` agent is unchanged and
maps to the `complex` tier. The `simple` and `standard` tiers are new agent
variants (`builder-simple`, `builder-standard`) with identical prompts but
different `model:` frontmatter. The orchestrator's dispatch table gains a
tier-to-agent mapping.

An alternative is to pass the model tier as a parameter in the plan and have
a single `builder` agent read it at dispatch time, rather than maintaining three
separate agent files. The trade-off: three files make the model selection visible
in the agent roster and testable via `test_agent_definitions.py`; a single
parameterised agent is simpler to maintain but the tier routing is less
transparent.

---

## Pattern 4 — Documentation agent pair

### The problem

Code-implementing agents drift into writing documentation. This produces
technically accurate docs that are inconsistently structured, use different
terminology from the rest of the project's docs, and are often in the wrong
place. Conversely, leaving docs entirely to the user means documentation falls
behind the code.

The second failure mode is more subtle: when an agent that writes code is also
responsible for documentation, it tends to document what it built rather than
what users need to know. These are different things.

### The solution

Two agents with a strict read/write boundary:

**`doc-researcher`** — read-only access to documentation directories. No `Write`,
no `Edit`, no `Bash` that creates files. Navigates existing project docs and
returns structured findings: what exists, where gaps are, what a doc-writing agent
would need to update. Consumes documentation, does not produce it. The key
usefulness: it can be dispatched in parallel with an implementation wave, mapping
the doc landscape while `builder` works, so the documentation phase has a complete
map ready when the code is done.

**`doc-writer`** — write access restricted to documentation directories (`docs/`,
`*.md` root files). Cannot touch implementation files. Consumes `doc-researcher`
findings and a description of what changed. Produces documentation that uses the
project's existing vocabulary and structure, because it read the existing docs
first. Works from templates where the project provides them.

The division mirrors the `builder`/`reviewer` split: one agent reads the world,
the other changes it, and mixing them produces agents that do both poorly.

### Key behaviours

`doc-researcher`:
- Entry point: the project's documentation index (README, a `docs/` root index,
  or a CLAUDE.md section that describes the doc structure)
- Follows references rather than exhaustive directory scans — if the project has
  a doc index, use it; `find` is a fallback for unindexed projects
- Returns: existing coverage map, gap list, path-to-topic mapping, suggested
  update targets

`doc-writer`:
- Reads `doc-researcher` output before writing anything
- Matches vocabulary and structure of the nearest existing doc to the new one
- Hard file boundary: if a documentation update requires a code change, that is a
  scope error — document the gap and return `BLOCKED`
- Commits with `[docs]` prefix

### Fit with nescio

Nescio's `memory/` subsystem handles durable cross-session facts. This pattern
handles in-project documentation — the README, a `docs/` tree, inline comments,
API documentation. These are distinct layers that should stay distinct.

The doc-researcher/doc-writer split also fits the crew's existing read-before-write
discipline: `explore` reads the codebase; `librarian` reads external sources;
`doc-researcher` reads project documentation. The pattern is consistent.

---

## Pattern 5 — QA iteration loop (`qa-guard`)

### The problem

`reviewer` finds issues. `builder` fixes them. But "CI passes" is not the same as
"reviewer approved" — CI is a mechanical bar (linter, type checker, test suite)
that runs deterministically and must be at 100% before a branch can merge. The
crew has no dedicated mechanism for reaching that bar. Currently the orchestrator
loops manually: dispatch builder, check if tests pass, dispatch again if not.

This is error-prone. The orchestrator does not know the project's CI configuration.
It does not know which hooks run, which linters are configured, what the test
command is, or how to interpret a partial failure. A dedicated agent that knows how
to discover and run CI tools, interpret failures, and iterate until they pass
eliminates this loop from the orchestrator and handles it more reliably.

### The solution

A `qa-guard` agent that has one job: make the CI-equivalent checks pass.

On entry it reads the project's CI configuration (`.pre-commit-config.yaml`,
`pyproject.toml`, `package.json`, `.github/workflows/`, Makefile targets, or
whatever the project uses) to discover the actual checks. It then runs them,
reads the output, fixes the failures, and runs again — iterating until everything
passes or it has exhausted its repair mandate.

The repair mandate is narrow by design:

- Fix formatting, import order, type annotation, and linting errors
- Fix test setup errors (missing fixtures, wrong imports)
- Do **not** add new functionality, change behaviour, or modify API contracts
- Do **not** weaken or skip failing tests — if a test reveals a real bug, return
  `BLOCKED` with the test name and failure message

This constraint matters: `qa-guard` is a mechanical pass, not a design agent.
The line between "fixing a linter error" and "changing what the code does" is
sometimes thin; `qa-guard` stays firmly on the mechanical side and returns
`BLOCKED` whenever the fix would require a judgment call.

### Key behaviours

- Discover CI tools from config files rather than assuming a stack
- Run tools and capture full output before attempting any fix
- Fix one failure category at a time and re-run to confirm the fix landed
- Never use `--no-verify`, `--skip`, `noqa`, or inline disable comments to
  silence a check — the check must pass, not be suppressed
- If a check fails consistently after two fix attempts, return `BLOCKED` with
  the raw output and the attempted fix
- Output contract: final state is "all checks pass" or `BLOCKED` with a precise
  description of what is failing and what was tried

### Fit with nescio

`qa-guard` runs between the `[test]` phase and the `reviewer`'s final pass. The
orchestrator dispatches it after `test-writer` commits. It sits downstream of
`builder` and `test-writer`, upstream of `reviewer`. Its existence removes the
"run tests, fix issues, run again" loop from the orchestrator's phase management,
letting the orchestrator describe phases rather than managing CI retry logic.

---

## Pattern 6 — Agent design principles as a first-class reference

### The problem

As nescio grows — new agents, new skills, community contributions — there is no
single document that describes *how* to design an agent for this crew. Individual
agent prompts encode the principles implicitly (the evidence requirement in
`reviewer`, the scope fence in `builder`, the approval-bias in `validator`), but
there is no place a contributor can read to understand why agents are designed the
way they are and how to design a new one consistently.

This produces gradual design drift. A contributed agent that seems reasonable in
isolation may violate principles the existing agents follow consistently: it may
give "helpful" advice the user didn't ask for, expose tools it doesn't need,
write a 600-word system prompt, or define success as an output rather than a
behaviour.

### The solution

A reference document at `docs/design/agent-design-principles.md` that codifies
the design decisions already embedded in the existing agents. It is descriptive,
not prescriptive — it explains what the existing agents do and why, in terms that
transfer to new agent design.

Proposed principles, drawn from observing what works and what doesn't in
production crew use:

**1. Trust model capability**
Write the agent to use the model's full reasoning. Don't over-specify mechanical
steps — specify outcomes, constraints, and the problem the agent is solving.
Over-specified prompts produce agents that follow steps even when the steps are
wrong for the specific situation.

**2. Lead with positive identity**
Define what the agent does before what it avoids. An agent whose opening
statement is a list of prohibitions has no clear identity — it will follow the
rules without understanding why. Define the role first; add anti-pattern clauses
only where a real failure has been observed. New constraint sections are evidence,
not speculation: if you have not seen the failure, do not write the rule.

**3. Scope the tools, scope the role**
The tool list is part of the role definition. An agent with `Write` is a different
agent from one without it — not the same agent with a constraint. Assign only the
tools the agent needs for its role; additional tools expand what the model
considers doing, not just what it's allowed to do.

**4. First-class outcomes**
Every outcome the agent can honestly produce must be named and respected. For the
crew's agents: `COMPLETE`, `PARTIAL`, `BLOCKED`, "no findings", "plan holds",
"not found". An agent that can only succeed in one way will rationalize its way
into that outcome when it shouldn't. The epistemic refusal — "I don't know / no
competent path" — must be a named outcome, not an implicit fallback.

**5. Output contracts over prose conventions**
Structured output blocks (`<result>`, `<verdict>`, `<changed>`) are more reliable
than prose conventions ("end your response with a summary"). The structure makes
the contract inspectable, testable, and parseable by the orchestrator. Prose
conventions drift under context pressure; structured contracts hold.

**6. Minimal prompt length**
A well-focused 200-word prompt outperforms an exhaustive 800-word one. Long
prompts bury the core identity in qualification and edge-case handling. Write the
core in 100–200 words; add constraint sections only where real failures have
occurred. A new section added to prevent a known failure is evidence, not
speculation.

**7. Role separation with explicit non-overlap**
Each agent should define what it is not, briefly. This is not redundant — it is
the only mechanism for preventing role confusion when the orchestrator dispatches.
The "you are not X" clause is read when the agent is uncertain whether a task is
in scope. Keep it short: one sentence per role that might be confused.

### Fit with nescio

This document lives in `docs/design/`, alongside the existing design documents.
It is not an agent spec and does not gate any implementation. It is a reference
for contributors and for the orchestrator's own design reviews.

A secondary use: the `critic` agent's lens 7 (compliance) already runs
unconditionally. A comparable "design review" lens — "does this proposed new agent
violate any of the design principles?" — could be added to `planner` for tasks
that create new agents. That is out of scope for this spec but follows naturally.

---

## Summary: proposed additions

| Pattern | New agents | New docs | Changed agents |
|---|---|---|---|
| 1. `test-writer` | `test-writer` | — | `orchestrator` (dispatch), `planner` (phase guidance) |
| 2. Typed commits | — | — | `builder`, `test-writer`, `reviewer`, `orchestrator` |
| 3. Cost-tiered routing | `builder-simple`, `builder-standard` | — | `orchestrator` (tier routing), `planner` (complexity field) |
| 4. Doc agent pair | `doc-researcher`, `doc-writer` | — | `orchestrator` (post-build phase) |
| 5. `qa-guard` | `qa-guard` | — | `orchestrator` (CI phase before reviewer) |
| 6. Design principles | — | `docs/design/agent-design-principles.md` | — |

All six patterns are independent. They can be implemented and shipped in any
order. Patterns 1 and 2 are the highest-value starting point: `test-writer`
closes the test-authorship gap and the typed-commit convention enables phase-scoped
review — both of which interact with every other pattern.

## Implementation sequencing recommendation

1. **Agent design principles doc** (Pattern 6) — no code, establishes design
   language for the other five
2. **Typed commit convention** (Pattern 2) — modifies existing agents, low risk,
   enables reviewer improvements
3. **`test-writer`** (Pattern 1) — new agent, integrates with typed commits
4. **`qa-guard`** (Pattern 5) — new agent, completes the implement → test → CI
   pass → review chain
5. **Cost-tiered routing** (Pattern 3) — two new builder variants, orchestrator
   dispatch change
6. **Doc agent pair** (Pattern 4) — two new agents, most self-contained of the six
