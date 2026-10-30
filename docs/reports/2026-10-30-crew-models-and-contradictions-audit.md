# QA Audit Report: crew model bump, contradiction fixes, trio roles, ADR rationale

**Date:** 2026-10-30
**Auditor:** Pyrrho
**Scope:** `git diff origin/main...HEAD` on `claude/agent-crew-review-7243d7` — 9 commits, merge-base `6347961` .. `6e1c263`, audited against `.sisyphus/plans/2026-10-30-crew-models-and-contradictions.md` (T1–T7).
**Pinned refs:** `BASE_SHA = 6347961feef881ad25a29f53989ded50997d8108`, `HEAD_SHA = 6e1c263ed249849647d789b912bcc80b6fbe97e6`
**Severity Summary:** 0 Critical | 3 Major | 11 Minor | 6 Info

## Executive Summary

The mechanical half of the plan is done and well covered: all 17 charters are on
the pinned 5.5 IDs with exactly the effort levels the plan decided, the catalog
regenerates clean, and the suite is green (1702 passed, 1 skipped). The judgement
half is where it leaks. Three findings matter: the builder charters' authoritative
`### Verdicts` definition of `BLOCKED` was never widened to match the new two-way
routing it is supposed to feed (T2); the new `$HOME/.claude/scripts/...` call sites
resolve to nothing on an already-installed machine until `install.py` is re-run,
with no fallback and no detection (T6 — verified broken in this very environment);
and adding `scripts/` to `LINKS` turns a pre-existing real `~/.claude/scripts` into
a conflict the default install path can never clear, which also silently suppresses
settings/CLAUDE.md integration and hook wiring.

Beyond those, the trio sharpening (T4) is half-applied: scout's new "use the class
you were handed" charter sits directly above an output contract that still demands
it emit its own `Type` + `Confidence`, and the orchestrator still dispatches and
synthesises scout as risk triage. No `<deviations>` note was recorded for the
orchestrator-side work T4 explicitly told the implementer to report.

## Findings

### [MAJOR] Builder `### Verdicts` still defines `BLOCKED` as decision-only — the new routing rule has nothing to classify

**Category:** Bug / Regression (contradiction between agent files)
**File(s):** `agents/builder.md:145-146`, `agents/builder-standard.md`, `agents/builder-simple.md` (byte-identical from `## Your Purpose` onward), `agents/orchestrator.md:458-465`, `agents/orchestrator.md:539-540`
**Confidence:** VERIFIED
**Status:** New

**Description:**
T2 made the orchestrator the classifier of record and split `BLOCKED` two ways:
"missing decision or fact" → user, "harder than this tier" → one tier up. The
builder tier paragraph was updated to say so. The **output contract's own
definition of the verdict** — the part the builder actually reads when deciding
what to write — was not. It still describes only the decision case.

**Evidence:**
Tier paragraph at `HEAD_SHA`, `agents/builder.md:18-22`:
```
You are the `complex` tier: design judgment — architectural decisions,
cross-system impact, or genuine ambiguity. If the task proves harder than this
tier or needs a decision the plan has not settled, return `BLOCKED` naming
which: the orchestrator routes decisions and difficulty alike to the user —
there is nowhere higher to escalate.
```
Verdict definition, 125 lines later, `agents/builder.md:145-146` (unchanged by
this PR, identical in all three tiers):
```
- **BLOCKED** — could not proceed. Name the decision or information needed. This
  is a respected outcome, not a failure.
```
The orchestrator's rule it is meant to feed, `agents/orchestrator.md:458-465`:
```
   - `BLOCKED` → read the named blocker and classify it yourself; the builder's
     own framing is input, not the verdict. A missing **decision or fact** →
```
And the user-facing progress template, `agents/orchestrator.md:539-540`, also
carries only the narrow framing:
```
### Blocked — needs your decision
- [!] Task 4: [title] — [the decision or missing information `builder` named]
```

**Impact:**
Two of the three places that define what a `BLOCKED` contains say "a decision or
missing information". A builder that blocks on difficulty has no prescribed shape
for saying so and is most likely to phrase it as a missing decision — which routes
it to the user instead of one tier up, i.e. the exact failure T2 set out to fix,
now with the doctrine documented as fixed. Nothing in the suite catches it: the
new orchestrator tests assert only on orchestrator prose.

**Reproduction Steps:**
1. Read `agents/builder-simple.md:18-21` — told to return `BLOCKED` naming
   difficulty *or* a missing decision.
2. Read the same file's `### Verdicts` entry for `BLOCKED` — only "name the
   decision or information needed".
3. Expected: the verdict definition enumerates both branches. Actual: only one.

**Recommended Fix:**
Widen the shared `### Verdicts` bullet to name both branches explicitly, e.g.
"Name which: the decision or fact that is missing, **or** what proved harder than
this tier." Add the difficulty case to the orchestrator's progress-update template
(see also the related Minor finding on the missing escalation slot). A test
asserting both phrases appear in each tier's shared body would pin it.

---

### [MAJOR] `$HOME/.claude/scripts/` does not exist on an already-installed machine — six prompt call sites now point at nothing

**Category:** Bug / Regression
**File(s):** `agents/builder.md:64`, `agents/builder-standard.md:64`, `agents/builder-simple.md:63`, `agents/planner.md:147,150`, `agents/orchestrator.md:449`, `install.py:57-69`
**Confidence:** VERIFIED
**Status:** New

**Description:**
T6 repointed every script invocation at `"$HOME/.claude/scripts/<name>.py"` and
added `("scripts", "scripts")` to `install.py`'s `LINKS`. The link is only created
by running `install.py`; nothing in the prompts detects its absence, and no
fallback to the repo-relative path remains. On any machine installed before this
commit — including this audit's own environment — the path resolves to nothing.

**Evidence:**
`agents/builder.md:64` at `HEAD_SHA`:
```
`python "$HOME/.claude/scripts/module_scan.py" --json --tripwire <N>` gives you
```
`agents/orchestrator.md:449` at `HEAD_SHA`:
```
   python "$HOME/.claude/scripts/verify_commit_position.py" <reported-sha> <branch> --base origin/main
```
Observed on the audit host:
```
$ ls -ld ~/.claude/scripts
/usr/bin/ls: cannot access 'C:/Users/marku/.claude/scripts': No such file or directory
```
(`~/.claude/agents`, `commands`, `hooks` are present as symlinks, so the install
is otherwise live — only `scripts` is missing.)

The `$HOME` form itself is sound; I probed both shells with a throwaway script:
Git Bash `python "$HOME/.claude/tmp-probe/p.py"` → `ok`, and
`powershell -NoProfile -Command 'python "$HOME/.claude/tmp-probe2/p.py"'` →
`ok-ps`. Both scripts are stdlib-only and operate on `cwd` (`module_scan.py` uses
`git ls-files`), so running them by absolute path from a product checkout is
correct — *once the link exists*.

**Impact:**
`module_scan.py` is the input to the module-size tripwire that builders and the
planner are required to report on, and `verify_commit_position.py` is the
orchestrator's guard against orphaned detached-HEAD commits. Both now fail with
"No such file or directory" on every pre-existing install until the user re-runs
`install.py`. The builder has `wc -l` as a stated alternative; the orchestrator's
commit-position check has none, so a real safety check degrades to a shell error
the agent may well narrate past.

**Reproduction Steps:**
1. On a machine where `~/.claude` was installed before `6e1c263`, do not re-run
   `install.py`.
2. Run `python "$HOME/.claude/scripts/verify_commit_position.py" HEAD main --base origin/main`.
3. Expected: the exit-1/exit-0 verdict the charter describes. Actual: file not found.

**Recommended Fix:**
Either (a) have the charters state the precondition and a fallback — "if
`~/.claude/scripts` is missing, re-run `python install.py` from the brain checkout;
in the brain checkout itself `python scripts/<name>.py` also works" — or (b) add a
`--check`-style warning to `install.py` and a line to the release notes /
CHANGELOG telling existing users to re-link. Note the themed downstream (`ai-os`,
which is what `~/.claude` points at on this host) is carried out of scope, so for
that deployment the path stays broken until the sync lands.

---

### [MAJOR] A pre-existing real `~/.claude/scripts` becomes an unclearable install conflict that also suppresses settings and hook wiring

**Category:** Bug (installer regression on upgrade)
**File(s):** `install.py:63-69`, `install.py:958-1019`, `scripts/adopt_existing_config.py:49-52`
**Confidence:** VERIFIED
**Status:** New

**Description:**
`scripts` is now a `LINKS` target, so a user who already keeps personal helpers in
`~/.claude/scripts` hits `is_conflict()` on it. The default install path treats
*any* conflict as a gate: it skips `install_settings`, `install_claude_md` and the
hook wiring entirely, then tells the user to review with `/adopt-config`. But
`adopt_existing_config.SOURCES` has no entry for `scripts`, so the scan stages
nothing, the content hash never reaches `memory/adoption-log.md`, and `is_done()`
stays false forever. Every subsequent `python install.py` repeats the same message
and performs no integration.

**Evidence:**
`install.py:63-69` at `HEAD_SHA`:
```
LINKS = [
    ("memory", "memory"),
    ("skills", "skills"),
    ("agents", "agents"),
    ("commands", "commands"),
    ("hooks", "hooks"),
    ("scripts", "scripts"),
]
```
`install.py:986-1016` — the conflict gate:
```
    if not conflicts:
        cleanup_dead_user_local(dry_run)
        install_settings(parts, dry_run)
        install_claude_md(claudemd_choice, dry_run)
...
    undone = [c for c in conflicts if not is_done(sha8(c), ledger)]
...
    if undone:
        print("\nStaging the not-yet-adopted ones for review:")
        stage_conflicts(dry_run)
```
`scripts/adopt_existing_config.py:49-52` — what staging actually scans:
```
    ("claude-code/agents", CLAUDE_DIR / "agents"),
    ("claude-code/commands", CLAUDE_DIR / "commands"),
    ("claude-code/skills", CLAUDE_DIR / "skills"),
    ("claude-code/memory", CLAUDE_DIR / "memory"),
```

**Impact:**
For an affected user, `python install.py` becomes a no-op that prints a review
instruction which cannot be satisfied — and silently stops merging `settings.json`
and wiring the Stop/SessionStart hooks, which previously worked. The documented
escape (`--relink`) exists and is printed, but it backs up and replaces their
`scripts` directory. `hooks` has the same gap today, so the mechanism is
pre-existing; `scripts` is a far more likely name for a user to already own, which
is what makes this PR the trigger. No test covers `do_default` with a `scripts`
conflict (the new test exercises `do_relink` only).

**Reproduction Steps:**
1. `mkdir ~/.claude/scripts && touch ~/.claude/scripts/mine.py` on an otherwise
   clean home.
2. Run `python install.py` from the brain checkout.
3. Expected: links created, settings merged, hooks wired, conflict reported.
   Actual: "1 existing real file(s) block symlinking", nothing staged for
   `scripts`, settings/CLAUDE.md/hooks all skipped; repeat runs behave identically.

**Recommended Fix:**
Add `("claude-code/scripts", CLAUDE_DIR / "scripts")` to
`adopt_existing_config.SOURCES` so the conflict can actually be adopted and
ledgered, and add a `do_default` test with a real `~/.claude/scripts` asserting
the message and that the user has a path forward. Separately consider whether the
all-or-nothing conflict gate should still suppress `install_settings` /
hook wiring for a link target that has nothing to do with either.

---

### [MINOR] scout's output contract still demands the classification its new Phase 0 told it not to make

**Category:** Maintainability (self-contradicting charter)
**File(s):** `agents/scout.md:19-25`, `agents/scout.md:56-61`, `agents/scout.md:82`
**Confidence:** VERIFIED
**Status:** New

**Description:**
T4 softened scout's mandatory intent classification into "use the class you were
handed". The OUTPUT FORMAT block 35 lines below was not touched and still requires
scout to emit its own `Type` and a `Confidence` rating — the artefact of the
behaviour that was removed.

**Evidence:**
`agents/scout.md:21-25` at `HEAD_SHA`:
```
You are handed a triage class from the orchestrator. Use it as given; do not
re-classify by default. Only override it if it is clearly wrong for the
```
`agents/scout.md:59-61` at `HEAD_SHA`:
```
## Intent Classification
**Type**: [Refactoring | Build | Mid-sized | Collaborative | Architecture | Research]
**Confidence**: [High | Medium | Low]
```
`agents/scout.md:82` still reasons about scout's own classification confidence:
```
**WHEN UNCLASSIFIABLE**: if intent stays genuinely ambiguous even after exploring, say so and ask — a Low-confidence classification must be surfaced as a guess, never presented as settled.
```

**Impact:**
The mandatory output block is the strongest instruction in a charter of this shape.
An agent told "do not re-classify" but required to fill in `Type` and `Confidence`
will re-classify — restoring the duplication of the orchestrator's triage table
that T4 existed to remove, while the charter now reads as if it were fixed.

**Reproduction Steps:**
1. Read `agents/scout.md` Phase 0, then its OUTPUT FORMAT.
2. Expected: the output block echoes the handed class, or records an override.
   Actual: it asks for an independent `Type` + `Confidence`.

**Recommended Fix:**
Relabel the block to `## Triage class` with `**Class (as handed)**: …` and an
optional `**Override**: <what I think it is, and why>`; fold the Low-confidence
sentence into the override case.

---

### [MINOR] The orchestrator still dispatches and synthesises scout as risk triage; no `<deviations>` note was recorded

**Category:** Regression (plan item not completed)
**File(s):** `agents/orchestrator.md:162`, `agents/orchestrator.md:190-191`, `agents/scout.md:3,11-13`
**Confidence:** VERIFIED
**Status:** New

**Description:**
T4's last bullet: "Check orchestrator.md references to advisor interrogate mode /
scout classification and fix any (read-only otherwise — T2 owns orchestrator edits;
if an orchestrator change is needed, report it in `<deviations>` rather than
editing)." The orchestrator's scout dispatch and synthesis headings still describe
the pre-sharpening scout, and no deviation was recorded in any commit message on
this branch.

**Evidence:**
`agents/orchestrator.md:162` at `HEAD_SHA`:
```
Agent(subagent_type: "scout", prompt: "Analyze this request for hidden risks and ambiguities.
```
`agents/orchestrator.md:190` at `HEAD_SHA`:
```
### Risk Assessment (from scout)
```
Against the new charter, `agents/scout.md:11-13`:
```
Before a plan exists, your question is: **did we forget something specific to
this task?** You surface unstated requirements, edge cases, scope gaps, and
hidden intent — not a plan, not a design, and not a critique of one.
```
`git log 6347961..HEAD` bodies contain no `<deviations>` or deviation note for
this (checked all 9 commit messages).

**Impact:**
The dispatch prompt is what the subagent actually receives; it overrides the
charter's framing in practice. The sharpening therefore lands in the catalog and
the charter but not in the one place that drives behaviour. Low blast radius — the
two framings overlap heavily — but the plan item is unfinished and undeclared.

**Recommended Fix:**
A one-line orchestrator edit ("Analyze this request for what the plan would miss —
unstated requirements, edge cases, scope gaps") plus renaming the synthesis heading
to `### Completeness check (from scout)`. If the owner wants the file untouched in
this PR, record it as a carried deviation.

---

### [MINOR] Triage vocabularies don't match, and scout is now told to depend on them matching

**Category:** Maintainability (contradiction, partly acknowledged)
**File(s):** `agents/orchestrator.md:36-43`, `agents/scout.md:21-32`, `agents/scout.md:38`
**Confidence:** VERIFIED
**Status:** New

**Description:**
The orchestrator's TRIAGE table produces `{Trivial, Bug Fix, Research/Question,
Mid-sized Task, Build from Scratch, Architecture}`. Scout's Phase 0 list is
`{Refactoring, Build from Scratch, Mid-sized Task, Collaborative, Architecture,
Research}`. Before this PR scout classified independently, so the two taxonomies
were merely parallel; now scout is told to use the handed class, which makes the
mismatch load-bearing.

**Evidence:**
`agents/orchestrator.md:38-39` at `HEAD_SHA`:
```
| **Trivial** (typo, config change, one-liner) | → EXECUTE → VERIFY → DELIVER |
| **Bug Fix** | → DISCOVER → EXECUTE → VERIFY → DELIVER |
```
`agents/scout.md:27,30` at `HEAD_SHA`:
```
- **Refactoring**: changes to existing code - SAFETY: regression prevention, behavior preservation
- **Collaborative**: wants dialogue - INTERACTIVE: incremental clarity through dialogue
```
The git-archaeology directive the plan explicitly preserved lives only under the
unreachable class, `agents/scout.md:38`:
```
Directives: Define pre-refactor verification. Verify after EACH change. Don't change behavior while restructuring. MUST: request a git-archaeology pass (via `explore`) on the code to be changed before planning — establish *why* it's shaped this way so the plan preserves intent, not just behavior.
```

**Impact:**
Bounded in practice: PHASE 2 (the only place the orchestrator dispatches scout) is
reached only for **Build from Scratch** and **Architecture** per the triage table,
and scout has branches for both. The real cost is that `Refactoring`,
`Collaborative`, `Mid-sized` and `Research` are dead paths via the designed route,
so the refactor git-archaeology MUST can only fire on an ad-hoc dispatch. The plan
carries "refactor triage class" in its Out-of-scope list, so this is a known gap —
but T4 made scout depend on the taxonomy while the taxonomy fix stayed deferred.

**Recommended Fix:**
Nothing in this PR. When the carried item is picked up, align the two lists in one
change and add a test that scout's class list is a superset of the orchestrator's
table rows.

---

### [MINOR] `create-adr` Common mistakes still prescribes the "four-section format" after a fifth section became mandatory

**Category:** Maintainability (doc self-contradiction)
**File(s):** `skills/create-adr/SKILL.md:58`, `skills/create-adr/SKILL.md:121`
**Confidence:** VERIFIED
**Status:** New

**Description:**
T5 changed Step 4's lead-in from "four core sections" to "core sections" because
`## Options considered` is now required, but the Common mistakes table still tells
the author to use "the brain's four-section format".

**Evidence:**
`skills/create-adr/SKILL.md:58` at `HEAD_SHA` (changed by this PR):
```
Match the existing files exactly. Frontmatter + core sections:
```
`skills/create-adr/SKILL.md:121` at `HEAD_SHA` (unchanged):
```
| Importing a heavy multi-section corporate template | Use the brain's four-section format; match the existing files. |
```

**Impact:**
The one row in the table that pushes back on template bloat now cites a section
count the skill no longer uses, and the row immediately below it demands the fifth
section. An author resolving the conflict by section count drops Options considered.

**Recommended Fix:**
"Use the brain's five-section format" — or better, drop the count: "Use the
sections in Step 4 and nothing else; match the existing files."

---

### [MINOR] qa-guard's boundary lists `setup.cfg` twice, at two different scopes

**Category:** Maintainability (ambiguous boundary)
**File(s):** `agents/qa-guard.md:15-19`
**Confidence:** VERIFIED
**Status:** New

**Evidence:**
`agents/qa-guard.md:15-19` at `HEAD_SHA`:
```
Concretely, that is anything under `.github/workflows/`, `azure-pipelines.yml`,
`.pre-commit-config.yaml`, the `[tool.*]` sections of `pyproject.toml` and
`setup.cfg`, check targets in a `Makefile`, and the `scripts` block of
`package.json`, plus check-configuration files such as `conftest.py`,
`pytest.ini`, `ruff.toml`, `.flake8`, `mypy.ini`, `setup.cfg`, and `tox.ini`.
```

**Impact:**
The first mention forbids only `setup.cfg`'s `[tool.*]` sections; the second
forbids the file. An agent reading for permission can pick either. The
orchestrator's audit (`agents/orchestrator.md:616`) rejects "a `[tool.*]` section
of `pyproject.toml` or `setup.cfg`" — the narrow reading — so a `[flake8]` or
`[metadata]` edit to `setup.cfg` passes the gate while arguably violating the
charter.

**Recommended Fix:**
Drop `setup.cfg` from the second list and widen the first to "`pyproject.toml` and
`setup.cfg`" without the section qualifier, then mirror the wording in the
orchestrator's reject list.

---

### [MINOR] "May never **edit**" does not plainly forbid **creating** a check-config file, and the prohibition is absent from "You may not"

**Category:** Maintainability (incomplete boundary vs. the audit that enforces it)
**File(s):** `agents/qa-guard.md:11-13`, `agents/qa-guard.md:76-77`, `agents/qa-guard.md:79-85`, `agents/orchestrator.md:613-618`
**Confidence:** VERIFIED
**Status:** New

**Description:**
T3 asked for new check-config files to be added "to the forbidden boundary". What
landed forbids *editing* them and adds one `BLOCKED` trigger scoped to the missing-
fixture case. The explicit "You may not:" list — the enumerated prohibitions — says
nothing about creating one, even though the orchestrator's CI Gate Audit rejects
"a new check-config file of any kind".

**Evidence:**
`agents/qa-guard.md:11-13` at `HEAD_SHA`:
```
**Hard file boundary: you may never edit the files that define the checks — CI
workflows, pre-commit config, linter and type-checker settings, build scripts,
or check-configuration files.**
```
`agents/qa-guard.md:76-77` — the only creation-aware rule, narrowed to fixtures:
```
- A missing fixture cannot be fixed without creating a new check-configuration
  file (conftest.py, pytest.ini, etc.) — name the file you would need to create
```
`agents/qa-guard.md:79-85` — the "You may not" list, with no creation clause:
```
You may not:

- Add `# noqa`, `# type: ignore`, `--no-verify`, `skip`, `xfail`, or any
  inline disable to silence a check — the check must pass, not be suppressed
- Weaken a test to make it pass
- Add functionality or change behaviour to satisfy a type checker
- Run `git commit --no-verify`
```
What enforces it, `agents/orchestrator.md:616-617`:
```
`package.json` scripts target; a new check-config file of any kind; a net
removal of assertions or a deleted test function; or a new entry under
```

**Impact:**
A qa-guard that needs a `ruff.toml` or `mypy.ini` for something other than a
fixture can read its charter as permitting creation (it is not an "edit", and not
in the prohibition list) and then be rejected by the orchestrator's audit — a
wasted wave, and the charter is the document the agent trusts.

**Recommended Fix:**
Change the boundary verb to "edit **or create**", and add a bullet to "You may
not": "Create a new check-configuration file of any kind — if a check cannot pass
without one, name the file and return `BLOCKED`."

---

### [MINOR] "Same contract" tier doctrine deleted from all three builder charters; the new parity test's rationale quotes prose that no longer exists

**Category:** Regression (content removal) / test rationale
**File(s):** `agents/builder.md:18-22`, `agents/builder-standard.md:18-22`, `agents/builder-simple.md:18-21`, `tests/test_agent_definitions.py:1533-1546`
**Confidence:** VERIFIED
**Status:** New

**Description:**
The T2 rewrite of the tier paragraphs dropped the doctrine sentences that stated
the tiers are one contract at three prices — including builder.md's anti-inflation
line. The doctrine now survives only in the two dispatcher charters. The new
`TestBuilderTierParity` docstring justifies itself by quoting that removed prose
as if it were still in the files it tests.

**Evidence:**
Removed at `BASE_SHA` → `HEAD_SHA` (from the diff of `agents/builder.md`):
```
-cross-system impact, or genuine ambiguity. The `simple` and `standard` tiers
-carry this identical contract on cheaper models, so you are here because the task
-needs *reasoning*, not because it is long or important.
```
and from `agents/builder-standard.md`:
```
-existing pattern that needs adapting rather than copying. The `complex` tier
-carries this same contract at higher cost; size alone does not justify it.
```
`grep -n "same contract\|identical contract\|differ only in\|size alone" agents/builder*.md` at
`HEAD_SHA` returns nothing; the phrases now appear only at
`agents/orchestrator.md:384-385` and `agents/planner.md:128-129`.
`tests/test_agent_definitions.py:1536` at `HEAD_SHA`:
```
    Their own prose says so: "same contract", "they differ only in the model
```

**Impact:**
Modest behaviourally — builders do not pick their own tier. But the charters no
longer tell a `complex`-tier agent that it is there for reasoning rather than
importance, which was a named guard against tier inflation, and a reader of the new
test is pointed at a quotation they cannot find. The parity test itself is sound.

**Recommended Fix:**
Restore one clause to the shared tier paragraph ("the other tiers carry this same
contract on cheaper models — size alone does not justify a higher one") and reword
the test docstring to cite `orchestrator.md:384-385` / `planner.md:128-129`, which
is where the promise now lives.

---

### [MINOR] `docs/design/agent-design-principles.md` still cites advisor's removed `interrogate` mode as its canonical example

**Category:** Maintainability (doc drift to a deleted feature)
**File(s):** `docs/design/agent-design-principles.md:100-101`, `agents/advisor.md`
**Confidence:** VERIFIED
**Status:** New

**Evidence:**
`docs/design/agent-design-principles.md:100-101` at `HEAD_SHA`:
```
applies. `advisor`'s `interrogate` mode is a named outcome for the situation
where giving an answer before asking questions would be dishonest.
```
`grep -n interrogate agents/advisor.md` at `HEAD_SHA` returns nothing; the
`<modes>` block was deleted by `ef7608b`.

**Impact:**
This is the repo's living doctrine document for "every honest outcome must be a
named outcome", and its worked example now points at a mode that does not exist.
A future charter author follows the reference and finds nothing. (Two dated
historical specs — `docs/specs/example-critic-devils-advocate.md:73-75`, which also
still describes critic dispatching `explore`/`librarian` — are archival and I would
leave them.)

**Recommended Fix:**
Swap the example for one that still exists: advisor's "insufficient basis to
recommend" line (`agents/advisor.md`, `<guiding_principles>`), or critic's "nothing
material" verdict.

---

### [MINOR] `README.md` still describes scout as intent triage

**Category:** Maintainability (doc drift)
**File(s):** `README.md:105`
**Confidence:** VERIFIED
**Status:** New

**Evidence:**
`README.md:105` at `HEAD_SHA`:
```
| `scout` | Pre-plan risk/intent triage — surfaces assumptions and likely failure points. |
```
versus the new description at `agents/scout.md:3`. The generated catalog
(`docs_site/docs/agents.md`) was regenerated and is correct; the hand-maintained
README table was not updated. No test compares the two.

**Impact:**
The README is the project's front door and now advertises the behaviour T4
removed ("intent triage"). Cosmetic, but it is the drift the plan's focus list
asked about.

**Recommended Fix:**
"Pre-plan completeness check — did we forget something specific to this task?"

---

### [MINOR] `tests/test_agent_definitions.py` now carries ADR-skill assertions at 2013 lines, against the repo's own per-concern test convention

**Category:** Maintainability (cohesion)
**File(s):** `tests/test_agent_definitions.py:1977-2009`
**Confidence:** VERIFIED
**Status:** New

**Description:**
`TestAdrOptionsConsidered` asserts on `skills/create-adr/SKILL.md` and
`adr-template.md` from a module named for agent definitions. The file now has five
distinct reasons to change: agent frontmatter contracts, orchestrator charter prose,
`modular-design` doctrine, `create-adr` skill content, and unit cover for two
parsing helpers. The repo otherwise splits aggressively per concern
(`test_module_scan.py`, `test_adr_transform.py`, `test_publish_adrs.py`,
and eight separate `test_sync_theme_*.py` files).

**Evidence:**
`tests/test_agent_definitions.py:1977-1979` at `HEAD_SHA`:
```
ADR_SKILL_DIR = ROOT / "skills" / "create-adr"


class TestAdrOptionsConsidered(unittest.TestCase):
```
`python scripts/module_scan.py --json` at `HEAD_SHA` reports it as the largest
file in the repo:
```
    { "path": "tests/test_agent_definitions.py", "lines": 2013 },
```
The plan (T7) asked for the ADR test "if cheap" but did not name a location.

**Impact:**
Not a defect in the assertions — they are real and would fire. It is the file's
third unrelated concern, it crosses the 400-line tripwire (module-gate needs
PR-body acknowledgement, per the brief), and it makes the ADR contract hard to
find from `skills/create-adr/`.

**Recommended Fix:**
Move `TestAdrOptionsConsidered` to a new `tests/test_create_adr_skill.py`. The
boundary I would draw: `test_agent_definitions.py` keeps `agents/*.md` frontmatter
and roster/permission contracts; orchestrator prose assertions and skill-content
assertions each get their own module.

---

### [MINOR] CONTRIBUTING's new note reports 1M native context next to a paragraph whose rationale assumes a 200K cap

**Category:** Maintainability (doc coherence)
**File(s):** `CONTRIBUTING.md:126-138`, `tests/test_agent_definitions.py:85-88`
**Confidence:** VERIFIED
**Status:** New

**Evidence:**
`CONTRIBUTING.md:126-127` at `HEAD_SHA` (pre-existing):
```
No agent here carries the suffix by default. The coordinator is the one that can
exceed 200K — it accumulates every subagent report in a single context, while
```
`CONTRIBUTING.md:134-135` at `HEAD_SHA` (added by this PR, immediately after):
```
Claude Code CLI 2.1.312 (two runs per arm, so directional): `claude-haiku-5-5`
resolves and reports `contextWindow: 1000000` with no `[1m]` suffix.
```
The same assumption is embedded in the test module's comment,
`tests/test_agent_definitions.py:85-86`:
```
# No agent in this repo carries it by default: the coordinator is the one that
# accumulates every subagent report in a single context and so the one that can
```

**Impact:**
A reader cannot tell whether the `[1m]` apparatus and its "opt in rather than
inheriting it" policy still apply to the 5.5 crew. The measurement is recorded
faithfully (T1's requirement) but not reconciled with the policy paragraph it
undercuts.

**Recommended Fix:**
One sentence after the measurement: "If the 5.5 IDs carry 1M natively, the suffix
policy above is moot for this crew — re-verify per model before relying on either."
The note also mixes two topics (context window and effort) under an effort heading;
splitting them would help.

---

### [MINOR] The Escalate section asks for an escalation note the progress-update template has no slot for

**Category:** Maintainability
**File(s):** `agents/orchestrator.md:395-396`, `agents/orchestrator.md:530-546`
**Confidence:** VERIFIED
**Status:** New

**Evidence:**
`agents/orchestrator.md:395-396` at `HEAD_SHA`:
```
in the wave's progress update.
```
(preceded by "The task keeps its original tier in the plan; note the escalation").
The template at `agents/orchestrator.md:533-545` has `### Completed`,
`### In Progress`, `### Blocked — needs your decision`, `### Remaining` and a
trailing `[Any issues encountered and how they were resolved]` — no escalation
line. The `### Blocked` heading is decision-only, so a difficulty escalation has
nowhere structured to go.

**Impact:**
Tier escalations — the signal the doctrine says is the self-correcting feedback for
mis-tiering downward — land in free prose or not at all, which is the same
invisibility the doctrine criticises in upward mis-tiering.

**Recommended Fix:**
Add `### Escalated — one tier up` to the template, or widen the Blocked heading to
`### Blocked — needs your decision / escalated`.

---

### [INFO] The effort mapping itself is unpinned, and `ALLOWED_MODELS` can no longer catch a half-reverted bump

**Category:** Maintainability (test coverage gap, deliberate tradeoff)
**File(s):** `tests/test_agent_definitions.py:45-56`, `tests/test_agent_definitions.py:478-504`
**Confidence:** VERIFIED
**Status:** New

Plan T1 kept the superseded IDs on purpose ("a model revert is a one-line change")
and its accept criterion "no frontmatter still names a superseded ID" was checked by
hand, not by a test. The new effort test asserts only allowlist membership plus
builder-tier equality. Net: a crew left half on `claude-opus-5` and half on
`claude-opus-5-5`, or `explore` silently promoted to `max`, passes CI.

`tests/test_agent_definitions.py:45-56` at `HEAD_SHA`:
```
ALLOWED_MODELS = {
    "claude-opus-5",
    "claude-opus-5-5",
    "claude-sonnet-5",
...
# Superseded IDs are kept so a model revert is a one-line change.
```
I verified the mapping by hand at `HEAD_SHA`: all 17 agents match the plan's lists
exactly (11 high, 5 medium, 1 low; models per role as specified).

Suggestion, if cheap: a single test asserting the generation is uniform — every
`model:` ends in `-5-5` — which keeps the revert one line (edit the suffix) while
making a partial bump fail.

---

### [INFO] `orchestrator.md`'s own `effort: high` is dead config by this PR's measurement, and the new test's docstring says otherwise

**Category:** Maintainability
**File(s):** `agents/orchestrator.md:5`, `CONTRIBUTING.md:136-138`, `tests/test_agent_definitions.py:478-487`
**Confidence:** VERIFIED
**Status:** New

The PR records that frontmatter `effort` is ignored when an agent runs as the main
session (`CONTRIBUTING.md:136-138`: "frontmatter `effort` showed no effect while
`--effort low/high` moved output 283 → 507 tokens, so the session effort … governs
the orchestrator"). The new test's docstring nonetheless asserts the general claim
"An omitted `effort:` silently inherits the host's default, so the same crew
behaves differently on two machines" — which is true for subagents and false for the
one agent that is normally the session. Harmless (the orchestrator declaring `high`
costs nothing), but a short note in `agents/orchestrator.md` or the test docstring
would stop the next reader from treating it as effective.

---

### [INFO] `TestAdrOptionsConsidered`'s rationale misstates what `adr-template.md` is for

**Category:** Maintainability
**File(s):** `tests/test_agent_definitions.py:1989-1990`, `skills/create-adr/SKILL.md:103`, `scripts/publish_adrs.py:349-355`
**Confidence:** VERIFIED
**Status:** New

The test docstring at `HEAD_SHA` reads:
```
        """The template is the only part of the skill an author actually copies."""
```
But nothing directs an author to copy it — `SKILL.md` Step 4 contains its own inline
block, and the same PR adds `SKILL.md:103` saying the template "uses the *published*
form frontmatter (`title`/`status`/`source_repo`)", i.e. the wrong frontmatter for a
brain ADR. `scripts/publish_adrs.py:349-355` confirms its real role: it is copied to
`TEMPLATE.md` in the docs checkout. I verified the frontmatter claim against
`scripts/_adr_transform.py:171-173`, which emits exactly `title`/`status`/
`source_repo` — so the note is accurate and T5's "say so in a comment" option was
exercised correctly. Only the test's stated reason is wrong.

---

### [INFO] `skills/modular-design` and `skills/layered-api-design` still use the repo-relative `python scripts/module_scan.py`

**Category:** Maintainability (incomplete fix, outside T6's stated scope)
**File(s):** `skills/modular-design/SKILL.md:35-37`, `skills/layered-api-design/SKILL.md:133`, `scripts/module_scan.py:35-37`
**Confidence:** VERIFIED
**Status:** New

T6's accept criterion (`grep -rn "python scripts/" agents/` empty) is met. But the
builder charter sends the agent to `~/.claude/skills/modular-design/SKILL.md` for
the three tests, and that skill — which is itself symlinked into `~/.claude` and so
read from product checkouts — still says:
```
python scripts/module_scan.py
python scripts/module_scan.py --tripwire 500 --top 10
python scripts/module_scan.py --json          # for programmatic use
```
Same in `skills/layered-api-design/SKILL.md:133` and the script's own usage
docstring. Low impact (the builder prompt gives the absolute form two lines later),
but the relative form is the bug T6 fixed, still live on the path the prompt routes
through.

---

### [INFO] `ef7608b`'s commit message overclaims "What you are NOT" sections

**Category:** Maintainability
**Confidence:** VERIFIED
**Status:** New

The commit body states: "All three descriptions and \"What you are NOT\" sections
now state each role's distinct one-line question." Only `agents/critic.md` has such
a section (`## What you are NOT`, lines 30-40 at `HEAD_SHA`); `scout.md` and
`advisor.md` have none. The descriptions were all three updated, so the user-visible
outcome is as planned — the message is just wrong about the mechanism, which matters
only for someone reading the log as the record of what changed.

---

### [INFO] `advisor` has no explicit hand-off line to critic

**Category:** Maintainability
**Confidence:** INFERRED
**Status:** New

Removing the `interrogate` mode leaves advisor with no statement that plan
stress-testing is critic's job; the boundary exists only in critic's "Not `advisor`"
bullet and in advisor's description. Consequence: a caller who asks advisor to
"stress-test this plan" gets a recommendation rather than a redirect, where
previously it got the question arc. Low impact — the orchestrator only dispatches
advisor for architecture decisions — but a one-line `<scope_discipline>` addition
("stress-testing an existing plan belongs to `critic`; say so rather than
re-opening the decision") would close it.

---

### [INFO] `scout.md:38` tells scout to "request a git-archaeology pass (via `explore`)" with no dispatch rights

**Category:** Maintainability
**File(s):** `agents/scout.md:6`, `agents/scout.md:38`
**Confidence:** INFERRED
**Status:** New

`agents/scout.md:6` is `tools: Read, Bash, Grep, Glob` — no `Agent(...)`. This is
the same defect class the PR deliberately fixed in critic.md ("You cannot dispatch
other agents"). It reads as survivable because the directive sits under "Directives
for Planner", so "request" plausibly means "tell the planner to ask for one". Worth
one clarifying word ("ask the orchestrator to dispatch `explore` for a
git-archaeology pass") while the file is open, since scout was already edited here.

---

## Regression Check Results

| Feature/Contract | Status | Notes |
|---|---|---|
| T1 — 17 charters on pinned 5.5 IDs | Pass | Verified file by file at `HEAD_SHA`; no frontmatter names a superseded ID. |
| T1 — per-agent `effort` matches the plan's lists | Pass | 11 high / 5 medium / 1 low, role for role as decided. |
| T1 — `ALLOWED_MODELS` adds 5.5, keeps superseded + comment | Pass | `tests/test_agent_definitions.py:45-56`. |
| T1 — CONTRIBUTING probe note | Pass | `CONTRIBUTING.md:130-138`; see Minor on coherence with the preceding paragraph. |
| T1 — catalog regenerated | Pass | `python docs_site/gen_catalog.py --check` → "verified 17 agents and 36 skills", rc 0. |
| T2 — orchestrator classifies every BLOCKED | Pass | `agents/orchestrator.md:387-402, 454-465`. |
| T2 — builders name the blocker; verdict definition agrees | **Fail** | Major finding 1: `### Verdicts` still decision-only in all three tiers. |
| T2 — planner wording aligned | Pass | `agents/planner.md:128-135`. |
| T2 — tiers differ only in frontmatter + tier paragraph | Pass | Enforced byte-for-byte by the new `TestBuilderTierParity`. |
| T3 — qa-guard no-commit rule | Pass | `agents/qa-guard.md:84-85`; consistent with `orchestrator.md:582-584`. |
| T3 — check-config files in the boundary | Warning | Present, but "edit"-only verb, absent from "You may not", `setup.cfg` double-scoped. |
| T3 — "missing fixtures" narrowed | Pass | `agents/qa-guard.md:61` + BLOCKED trigger at 76-77. |
| T3 — `BOUNDARY_SCOPE_TERMS` preserved | Pass | Suite green; no terms removed. |
| T4 — scout reframed as completeness, class handed | Warning | Charter yes; output contract and orchestrator dispatch still classify/triage risk. |
| T4 — advisor `interrogate` removed | Pass | Gone from `agents/advisor.md`; one stale reference left in `docs/design/`. |
| T4 — critic lens 8 + research fix | Pass | `agents/critic.md:68-71, 86-93, 147-148`; no dispatch claim remains. |
| T4 — "no criticism for its own sake" in all three | Pass | `scout.md:83`, `advisor.md` guiding_principles, `critic.md` (pre-existing). |
| T4 — orchestrator references checked / deviation recorded | **Fail** | Minor finding: not fixed and not reported. |
| T5 — Options considered required, as-built exempt | Pass | `SKILL.md:83-88`, `adr-template.md`; rationale added to Decision. |
| T5 — Common mistakes updated | Warning | New rows correct; "four-section format" row now contradicts them. |
| T5 — frontmatter mismatch resolved by note | Pass | `SKILL.md:103`; claim verified against `scripts/_adr_transform.py:171-173`. |
| T5 — `test_publish_adrs` / `test_adr_transform` green | Pass | Full suite green. |
| T6 — `scripts` in `LINKS` + comment | Pass | `install.py:57-69`. |
| T6 — `grep "python scripts/" agents/` empty | Pass | Verified empty. |
| T6 — `$HOME` form works in bash and PowerShell | Pass | Probed both: `ok` / `ok-ps`. |
| T6 — path resolves on an installed machine | **Fail** | Major finding 2: `~/.claude/scripts` absent on this host. |
| T6 — install behaviour for an existing real `~/.claude/scripts` | **Fail** | Major finding 3: unclearable conflict, suppresses settings + hooks. |
| T6 — `tests/test_install.py` updated | Pass | Two new tests; the relink one is discriminating (rc 1 only if `scripts` is a link target). |
| T7 — effort allowlist test | Pass | Substantive; mapping itself unpinned (Info). |
| T7 — tier effort + body parity tests | Pass | Includes a guard against parity-by-deletion. |
| T7 — stale BLOCKED docstring updated | Pass | `tests/test_agent_definitions.py:1929-1940`. |
| T7 — ADR template test | Warning | Correct assertion, wrong stated rationale, wrong module. |
| Full suite | Pass | 1702 passed, 1 skipped. |
| Repo memory (`~/.claude/memory/repo/nescio-ai/`) | Pass | Three recorded failure modes (roadmap-drift GitHub inputs, merge-commit CHANGELOG duplication, single required check) — none reintroduced. Note the third: only `tests` is a required check, so "CI passed" covers lint/module-gate/docs-tests advisorily. |

## Recommendations

Priority order:

1. Widen the shared builder `### Verdicts` definition of `BLOCKED` to both branches
   (decision/fact **and** harder-than-tier), and add the escalation case to the
   orchestrator's progress-update template. Without this, T2's mechanism is not
   actually wired. Pin it with a test on each tier's shared body.
2. Decide the deployment story for `~/.claude/scripts`: state the precondition and
   a fallback in the charters, or gate on it. Right now the orchestrator's
   commit-position check silently degrades on every pre-existing install.
3. Add `("claude-code/scripts", CLAUDE_DIR / "scripts")` to
   `adopt_existing_config.SOURCES` and a `do_default` test for a real
   `~/.claude/scripts`, so an affected user is not stuck in the conflict branch
   with settings and hooks unwired.
4. Finish T4 on the scout side: rework the OUTPUT FORMAT block to echo the handed
   class, and either fix the orchestrator's dispatch prompt / "Risk Assessment"
   heading or record the carried deviation.
5. Small doc/boundary cleanups, cheap and independent: the "four-section" row in
   `create-adr`; `setup.cfg` double-scoping and the edit-vs-create verb in
   qa-guard; the `interrogate` reference in `docs/design/agent-design-principles.md`;
   the scout row in `README.md`.
6. Housekeeping: move `TestAdrOptionsConsidered` to its own module and fix its
   docstring; restore one "same contract" clause to the builder tier paragraphs and
   re-point the parity test's docstring; reconcile the 1M-context paragraph in
   CONTRIBUTING; consider a one-line test that every `model:` is on the same
   generation.

Nothing here is a merge blocker on its own evidence except finding 1, which is a
two-line prose fix. Findings 2 and 3 are deployment/upgrade issues that need a
decision more than code.

## Files Reviewed

Read at `HEAD_SHA` (`6e1c263`) unless noted:

- `.sisyphus/plans/2026-10-30-crew-models-and-contradictions.md`, `.sisyphus/discovery/2026-10-30-crew-models-and-contradictions.md`
- `agents/advisor.md`, `agents/builder.md`, `agents/builder-standard.md`, `agents/builder-simple.md`, `agents/critic.md`, `agents/orchestrator.md`, `agents/planner.md`, `agents/qa-guard.md`, `agents/scout.md`; frontmatter of the remaining 8 charters
- `install.py`, `scripts/adopt_existing_config.py`, `scripts/_adopt_common.py`, `scripts/module_scan.py`, `scripts/verify_commit_position.py`, `scripts/publish_adrs.py`, `scripts/_adr_transform.py`
- `skills/create-adr/SKILL.md`, `skills/create-adr/adr-template.md`, `skills/modular-design/SKILL.md`, `skills/layered-api-design/SKILL.md`
- `tests/test_agent_definitions.py`, `tests/test_install.py`
- `README.md`, `CONTRIBUTING.md`, `docs_site/docs/index.md`, `docs_site/docs/agents.md`, `settings.json`
- `docs/design/agent-design-principles.md`, `docs/specs/example-critic-devils-advocate.md`, `brand/make_diagrams.py` (context only)
- `~/.claude/memory/repo/nescio-ai/MEMORY.md`
- Diff of all 28 changed files, `BASE_SHA`..`HEAD_SHA`
