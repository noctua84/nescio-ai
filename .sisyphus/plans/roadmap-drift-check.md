# Roadmap drift check — reconcile `ROADMAP.md` against **roadmap-labelled** open issues (#60)

## Revision log

**Revision 2** — after `validator` (executability: BLOCKED ×2) and `critic` (red-team: material
objections ×2). The core shape — *assert rather than generate, never write, hermetic tests,
tri-state exit* — survived the red team unchanged and is not revisited here.

| # | Change | Why |
|---|---|---|
| **R2-1** | **Deny-list → allow-list.** The check no longer asserts a bijection against *all* open issues. It asserts against the subset labelled **`roadmap`**. | The premise "31↔31 is a known-good baseline" was **false as an invariant**. Verified: all 31 open issues are authored by `noctua84`; the repo is public, MIT, and carries `good first issue` + `help wanted`. The bijection was an artefact of solo authorship. The first outside bug report would have redded the build with no escape hatch. Owner policy: *"the roadmap is essentially planned features… work with labels to distinguish planned work from new one."* |
| **R2-2** | The symmetric `check_bijection` is **split into two checks with different severities** (§ *Direction semantics*), and referenced-but-unlabelled is **advisory (exit 0)**. | The three directions have different evidence quality and different remedy locations. Treating them symmetrically was the error. |
| **R2-3** | New **Task 0** — classify all 31 currently-referenced issues *planned / maintenance / ambiguous*, owner-approved **before** any labelling. New **Task 0b** — create + apply the label and, if the owner reclassifies, **amend the unpushed commit `07779cb`**. | Applying the owner's rule strictly, ≥5 entries already committed in `07779cb` are maintenance, not planned features. That must be an explicit decision, not a silent one. |
| **R2-4** | New **Task 10** — issue-template work: migrate to **issue forms** (`.yml`) and document *what earns a roadmap line*. | Owner explicitly asked for it. It is the intake half of the allow-list. |
| **R2-5** | **Trigger split.** Offline checks on `pull_request`; network reconciliation on **push-to-`main` + `schedule` + `workflow_dispatch`** only, via a job-level `if:`. Added an explicit precondition: **this job must not be added to required status checks.** | `critic` HIGH. Finding 1's drift is caused by issue open/close events, which produce no PR. Verified aggravator: PRs #89/#91/#93/#94 use no closing keywords, so issues close out-of-band. Verified: `main`'s protection requires only `["tests"]` — that is the sole reason R9 is defensible, and it was undocumented. |
| **R2-6** | **B1 fixed at all five sites** — `PATH=/nonexistent python …` → `PY=$(command -v python); PATH=/nonexistent PYTHONPATH=scripts "$PY" …`. | `validator` BLOCKER, reproduced here: the old form exits **127** (`python: command not found`), never the expected 2 or 0. The line called "the hermeticity proof" proved nothing while looking like a pass. The fixed form was run and verified to work *and* to still hide `gh` (`shutil.which("gh")` → `None`). |
| **R2-7** | **B2 fixed** — the self-contradicting `grep -c "open_issues" … # → 0` is replaced with a check that expresses the real intent. | `validator` BLOCKER: `grep -c` counts comment lines, and lines 303 / 388-390 *require* `open_issues` to be named in a comment and the docstring. |
| **R2-8** | **Cut the legend-text half of `check_tag_vocabulary`**; dropped fixture `legend_missing_tag.md` (7 → 6 fixtures, acceptance count updated). | String-matching backticked tags against a hand-written legend paragraph is exactly the brittleness rejected for README two sections earlier. Keep `tag ∈ TAG_TO_MILESTONE`. |
| **R2-9** | **One primary reference per bullet.** Further links in a bullet's prose are commentary, exempt from uniqueness / membership / closed-ref. Plus a **required code comment** stating the narrow `[#N](url)` anchor is load-bearing. | `critic`. Verified traps: `ROADMAP.md:59` *"(in tension with **#53**…)"* and `:90` *"fixed in **#83**"* — and **#83 is a MERGED PR, not an issue** (`gh pr view 83` → MERGED). Both are bare `#N`, so today the narrow anchor already saves us; the comment stops a later "simplification" of the regex from re-opening it. |
| **R2-10** | **gh pagination fixed** — explicit page loop, not `--paginate`. `--slurp` **rejected with evidence**. | Verified empirically at `per_page=20`: `gh api … --paginate --jq '[…]'` emitted **two separate JSON arrays**, one per page — `json.loads` raises, and R2 converts that into a false exit 2. Silent at 31 issues, breaks at 101. Also verified: `gh` 2.87.3 refuses `--slurp` with `--jq` (*"the `--slurp` option is not supported with `--jq` or `--template`"*), so `critic`'s first suggested fix does not compile. |
| **R2-11** | README guard: docstring softened to what it actually does; named escape `<!-- roadmap-check: allow -->` added. | It guards one section of one file, not "the drift class". |
| **R2-12** | Noted **scheduled-workflow rot** (GitHub auto-disables cron workflows after 60 days of repo inactivity) and added `workflow_dispatch` as the manual re-arm. | The check would die silently exactly when nobody is watching. |
| **R2-13** | Added a required code comment: the narrow `--jq` projection **is** the privacy control. | Widening to `--jq '.'` while debugging would dump issue bodies into a public CI log. |
| **R2-14** | Task 7's acceptance criterion no longer imports **PyYAML**. | This repo is deliberately dependency-free; the criterion was not runnable as written. |
| **R2-15** | Fixed stale counts: "all five checks" → nine; R7's "four offline checks" → "three after Task 1, four after Task 5". Removed the hardcoded `31 18 2` parse assertion in favour of a parser **self-consistency** invariant. | The hardcoded counts become wrong the moment Task 0b removes an entry. |
| **R2-16** | Added § *Upheld under red team* so three decisions are not re-litigated. | `critic` explicitly upheld them; a "material objections" verdict is not licence to discard what survived. |

**Correction to a premise handed down with the review.** The review states *"every issue must come
through a template — that's a strong lever."* That is true **only of the web UI**.
`blank_issues_enabled: false` does not govern `gh issue create --title --body`, which bypasses
templates entirely. Direct evidence in this repo: **11 of 31 open issues carry no labels at all**
(#19, #20, #21, #22, #52, #53, #58, #71, #72, #81, #84) — proof that issues here are routinely
created outside the template path. The template is therefore a strong lever on *outside*
contributors and no lever at all on the maintainer. Task 10 is designed around that, and the
allow-list does not depend on the template holding.

---

## TL;DR

> Build **one script** (`scripts/check_roadmap_drift.py`) with a tri-state exit convention
> (`0` pass / `1` drift / `2` could-not-check), consumed by **two callers**: a hermetic,
> fully-offline `tests/test_roadmap_drift.py` that runs in the existing `tests` job, and a new
> dedicated `roadmap` job in `.github/workflows/tests.yml` that runs the live reconciliation on
> **push-to-main, a weekly cron, and manual dispatch — never on `pull_request`**. The check is an
> **allow-list**: only issues labelled **`roadmap`** are expected to appear in the file, so an
> outside bug report cannot red the build. It **asserts** on membership and tags; it **never
> rewrites** `ROADMAP.md`, so the file's editorial prose survives intact. A companion issue-form
> migration makes the intake side of that policy legible to contributors.

## Context

### What #60 asks for

`ROADMAP.md` duplicates state GitHub owns (which issues are open, which milestone each belongs to)
with nothing detecting divergence. #60 proposes a scheduled workflow and offers three shapes
without resolving between them: **check-and-PR**, **check-and-report**, and **generate the tagged
bullet list into a marked block**.

### What the audit found (verified, do not re-derive)

A full reconciliation audit was completed and `ROADMAP.md` hand-fixed in commit `07779cb` on this
branch (verified: `07779cb` is the **only** commit ahead of `origin/main` — it is unpushed and
amendable). Findings:

1. **The failure mode is OMISSION, not tag rot.** After 68 commits and three releases of drift,
   every milestone tag in the file was still correct. The actual drift was 2 issues
   closed-but-still-listed (#42, #54) and 7 open issues never added (#64, #69, #70, #71, #72, #81,
   #84). **#60 proposes policing tags; tags are not what rots. Membership is.** Any design that
   optimises for tag correctness at the cost of membership detection is aimed at the wrong target.

2. ~~**The file is at a perfect baseline**~~ — **RETRACTED in revision 2.** The 31↔31 bijection is
   real *today* but is **not an invariant**. Re-verified:

   ```
   open issues (PRs filtered): [2,10,11,19,20,21,22,29,32,33,34,35,36,37,38,39,40,41,43,
                                52,53,58,59,60,64,69,70,71,72,81,84]   # 31
   roadmap-referenced:          identical set                          # 31
   authors:                     noctua84 × 31  (100%)
   repo:                        PUBLIC, MIT, labels include `good first issue`, `help wanted`
   ```

   The bijection is a **coincidence of solo authorship**. The repo actively solicits outside
   issues. The first one breaks it. **This is why the check is an allow-list, not a bijection.**

3. **Live milestone vocabulary** (verified):

   | # | Title | `open_issues` (API, PR-inflated) | roadmap tag | tagged bullets |
   |---|-------|------|-----|----|
   | 1 | Loop integrity | 5 | `loop` | 5 (#2 #52 #53 #59 #60) |
   | 2 | Readiness signal | 4 | `readiness` | 4 (#35 #40 #69 #70) |
   | 3 | Cross-repo knowledge | 3 | `cross-repo` | 3 (#34 #10 #11) |
   | 4 | Parked | 6 | `parked` | 6 (#32 #36 #37 #38 #39 #41) |

   **Note the trap:** `open_issues` matches the filtered count *today* only because no PR is
   currently milestoned. The #60 gotcha is silent right now and will bite the first time a PR is
   assigned to a milestone.

4. **Epics are referenced from headings, not bullets.** `## Learning loop & memory — [Epic
   #43](...)` and `## Earned autonomy — [Epic #33](...)`. Both #43 and #33 are **unmilestoned**
   (verified), so the "milestoned ⇒ tagged" rule holds cleanly today — but the parser must count
   heading references toward membership while exempting them from the tag rule.

5. **In-repo precedent for the marked-block approach exists** — `scripts/compute_readiness.py`
   (markers, only-between-markers rewriting, deterministic render). Its docstring records that this
   discipline was a response to a real data-loss bug (#25, fixed in #45). Relevant as evidence that
   the repo takes generator-destroys-human-prose seriously, and as the reason shape C is rejected
   below rather than adopted.

6. **In-repo precedent for offline degradation exists** — `scripts/_hygiene_common.py` has `run()`,
   `gh_available()`, and a tri-state result that keeps `False` ("consulted, answer is no") distinct
   from `None` ("could not consult"), with the reason string `"unconfirmed-offline"`.
   `scripts/verify_commit_position.py` has the exit convention `EXIT_PASS=0 / EXIT_CHECK_FAILED=1 /
   EXIT_ERROR=2` with "could not check" explicitly separated from "check failed". **Both are house
   patterns to follow, not reinvent.**

7. **Hard conventions.** All 24 files in `scripts/` have a matching `tests/test_<name>.py` (10–35 KB
   each) — a test file is not optional. `.github/workflows/tests.yml` runs `PYTHONPATH=scripts
   python -m unittest discover -s tests -v`; its `lockfile` job is the house idiom for "turn silent
   drift into a loud failure". Tests are stdlib `unittest`, `tempfile.TemporaryDirectory`,
   `sys.path.insert(0, ROOT / "scripts")`.

8. **`ROADMAP.md` is currently covered by no test, no lint, no link check.**

9. **#64 constraint:** every release PR in this repo stalls at `action_required` pending manual
   workflow approval. Any auto-opened PR inherits that friction.

### What revision 2 verified additionally

10. **Label inventory** (`gh label list`): `bug`, `documentation`, `duplicate`, `enhancement`,
    `good first issue`, `help wanted`, `invalid`, `question`, `wontfix`, `deferred`,
    `autorelease: pending`, `autorelease: tagged`. **There is no planned-work label, and no
    collision with the name `roadmap`.**

11. **`enhancement` is useless as the predicate** — 19 of 31 open issues carry it, spanning genuine
    features (#10, #29, #32) and pure chores (#2, #64). Confirmed by direct enumeration.

12. **Label application is already maintainer-gated by GitHub.** Applying a label requires the
    *triage* role or above; an outside contributor cannot self-apply `roadmap`. This is a real
    permission property, not a convention — and it is the reason the template must **not**
    auto-stamp `roadmap` (see Task 10).

13. **Branch protection on `main`** (`gh api …/branches/main/protection`):
    `required_status_checks.contexts == ["tests"]`, `strict: true`. **Only `tests` is required.**

14. **`gh api --paginate --jq '[…]'` emits one array per page.** Reproduced at `per_page=20`
    against this repo: two separate `[…]` documents on stdout. And **`--slurp` is rejected when
    combined with `--jq`** in gh 2.87.3.

15. **`PATH=/nonexistent python …` exits 127**, not 2. `PY=$(command -v python); PATH=/nonexistent
    "$PY" …` runs correctly and still hides `gh` from the child process.

16. **No bullet in `ROADMAP.md` currently carries two `[#N](url)` links.** The primary-reference
    rule (R2-9) is forward-protection, not a fix for a present failure. It costs one line of
    parsing.

---

## The policy inversion: allow-list, not bijection

### The owner's rule

> *"The roadmap is essentially planned features for the software. Work with labels to distinguish
> planned work from new one. Also add an issue template that describes what an issue should contain
> and be labeled with in order to fit in."*

Formally: the roadmap is not *"every open issue, minus exemptions"*. It is *"every issue the
maintainer has declared to be planned work."* Membership is **opt-in and maintainer-asserted**, not
inferred.

### Label choice: **`roadmap`**

**Decided.** No collision (finding 10). Rationale:

- It reads correctly in the only sentence that matters — *"this issue is on the roadmap"* — and
  names the exact artefact it governs. A reader needs no glossary.
- **Rejected `planned`**: `deferred` already exists, and `planned` would imply a mutually-exclusive
  state machine with it. It is not one — #32, #36, #37, #38, #39, #41 are *simultaneously*
  `deferred` and on the roadmap (the *Parked* milestone). `roadmap` is **orthogonal to `deferred`
  by design**, and that must be stated in the label description: *"Planned direction for the
  project; expected to appear in ROADMAP.md. Orthogonal to `deferred` — parked work is still
  planned."*
- **Rejected `roadmap: planned`**: the namespaced form only earns its colon when there is a second
  value in the namespace. There isn't one.
- **Rejected reusing `enhancement`**: finding 11 — 19/31 carry it, including chores.

### Direction semantics — **justified per direction, deliberately asymmetric**

Let **L** = open issues labelled `roadmap`. Let **R** = primary issue references in `ROADMAP.md`
(§ *primary reference* below), excluding `## Shipped`.

| Direction | Condition | Severity | Justification |
|---|---|---|---|
| **D1 — labelled but missing** | `n ∈ L`, `n ∉ R` | **exit 1 (hard)** | The maintainer made an explicit, machine-readable declaration and the file contradicts it. Zero policy judgement, zero ambiguity. The wrong thing is the file, and **the remedy is one line in this repo**, in the same commit-space as the check. This is finding 1's actual failure mode. |
| **D2 — referenced but not an open issue** | `n ∈ R`, issue closed / not found / is a PR | **exit 1 (hard)** | The file asserts *planned future work* that GitHub says is finished, abandoned, or never existed. Depends on issue **state**, not on metadata anyone has to remember to apply — so it is the one direction that stays meaningful even if the labelling policy is later dropped. Remedy is again one line in this repo. Sub-cases are reported distinctly (*closed* vs *not found or is a PR*) so #83-class traps read correctly. |
| **D3 — referenced but unlabelled** | `n ∈ R`, open, `roadmap ∉ labels` | **exit 0 (advisory, printed)** | **Different in kind: nothing here is necessarily wrong.** The file may be right and the label merely un-applied. Critically, **the remedy is not in the repo** — it is a GitHub metadata change that no commit can make and no PR can carry. *A check whose red cannot be cleared by editing the tree blocks the wrong person.* It is also the only direction that fires *en masse* during the policy migration, and the only one an ordinary editorial act can trigger. Report it loudly — named issue numbers plus the literal `gh issue edit <N> --add-label roadmap` command — and exit 0. |
| **D4 — open, unlabelled, unreferenced** | `n ∉ L`, `n ∉ R` | **silent (no finding)** | **This is the escape hatch the old design lacked.** The outside bug report, the chore, the CI plumbing issue: not declared planned work, not in the file, nothing to reconcile. Under the old bijection this was a hard failure. It is now a non-event. |

**On D3's residual hole, stated honestly.** Because D3 is advisory, a bullet added without the label
is invisible to D1 forever after. That hole is *mitigated, not closed*: D3 prints the issue number
on every push to `main` and every weekly run, so it is loud but not blocking. **Promoting D3 to
exit 1 is a follow-up gated on evidence** — if the advisory is demonstrably ignored for a quarter,
file an issue with that evidence and promote it. Do not promote it speculatively now.

### Consequence: entries already committed in `07779cb` may not belong

Applying the rule strictly, several entries added by the audit are maintenance, not planned
features. **This is not decided silently — it is Task 0, and the owner approves the table before any
label is applied.** If the owner removes entries, **Task 0b amends `07779cb`** (unpushed, on this
branch) rather than only changing the checker.

---

## Upheld under red team — do not re-litigate

`critic` examined and **explicitly upheld** three decisions. They are recorded here so a later
reviewer does not reopen them:

1. **Deleting the duplicated state loses.** `README.md:260-271` already ran that experiment and
   drifted anyway. Removing `ROADMAP.md` converts *detectable* drift into *undetectable* drift.
2. **The weekly cron is the most valuable trigger, not theatre.** It is the only trigger that fires
   on GitHub-side events that produce no push — which is precisely finding 1's failure mode.
3. **The privacy posture is clean.** The narrow projection stays narrow (see R11).

---

## The design decision

### Recommendation: **shape D (a check, run as a test + a dedicated CI job), triggered per § *Trigger design*.**

- **One script**, `scripts/check_roadmap_drift.py`, holding the parser, all nine checks, and the
  single network call site. Tri-state exit `0/1/2` per the `verify_commit_position.py` convention.
- **One test file**, `tests/test_roadmap_drift.py`, exercising the parser and every check with
  **injected** issue state — never live network. Runs in the existing `tests` job. Passes on a
  machine with no network and no `gh`.
- **One new CI job**, `roadmap`, in `.github/workflows/tests.yml`, mirroring the `lockfile` job's
  shape, running the live reconciliation on push-to-`main`, `schedule`, and `workflow_dispatch`.

### Why the other three lose

**Shape C — generate the tagged bullet list into a marked block: rejected on editorial voice.**

This is the fatal one. The roadmap's bullets carry hand-written clauses deliberately trimmed from
the issue titles. Issue #53's title is *"Learning-log: retain full promotion history as a
generalization dataset; retire the 150-line compaction policy"*; the roadmap reads *"learning-log:
retain full promotion history as a generalization dataset (retire the 150-line compaction)"*. #72's
bullet carries an editorial judgement that appears in no issue title at all — *"(in tension with
#53, which would retire the cap outright — settling that first may moot this)"*. #59's carries
*"(the detached-HEAD guard itself has shipped; this is the remaining follow-up)"*.

A generator emitting raw titles would replace all of that with more verbose, less considered text.
#60 itself names the file as *"a file whose prose is editorial judgement rather than generated
content."* **Eliminating drift by destroying the editorial voice is a net regression.** Preserving
the prose inside a generated block would require a side-file of per-issue prose overrides — strictly
more machinery than the checker, with the same failure surface, and the override file itself would
then be the thing that drifts.

Secondary: the marked-block scheme rewrites the file, so it inherits the data-loss risk class that
`compute_readiness.py`'s marker discipline exists to contain. A checker that writes nothing has no
such class.

**Shape A — check-and-PR: rejected on #64, and on voice.**

It carries C's voice problem (it must author the corrected bullet text) *plus* #64's friction: an
auto-opened roadmap PR would sit at `action_required` awaiting manual workflow approval exactly as
every release PR does. A fix mechanism that requires the same manual intervention as the manual fix,
while additionally producing worse prose, has negative value. It also needs `contents: write` +
`pull-requests: write` on a token, widening the workflow's blast radius for a check that only needs
read.

**Shape B — check-and-report as a standalone scheduled workflow: not wrong, but strictly dominated.**

B preserves the voice perfectly and sidesteps #64. Its cron trigger is retained wholesale (see
*Upheld*, item 2); what B loses is that a *cron-only* check never fires on the diff that introduced
an editorial error. The offline half of shape D catches those on the PR itself. **So the
recommendation is D, with B's trigger, sharing one implementation and one workflow file.**

### The counter to shape D, and how it is answered

The stated counter is that a test needing the GitHub API makes the suite network-dependent and
hostile to offline and fork runs. The plan answers it by **splitting the check by whether it needs
the network, and putting only the offline half in the test suite**:

| # | Check | Needs network? | Where it runs | Severity |
|---|---|---|---|---|
| 1 | `check_unique_references` (no primary reference appears twice) | no | `tests` job | 1 |
| 2 | `check_tag_vocabulary` (tag ∈ `TAG_TO_MILESTONE`) | no | `tests` job | 1 |
| 3 | `check_link_wellformed` (displayed `#N` == URL `issues/N`, correct host/repo) | no | `tests` job | 1 |
| 4 | `check_readme` (README `## Roadmap` carries no enumerable issue state) | no | `tests` job | 1 |
| 5 | `check_labelled_present` — **D1** | **yes** | `roadmap` job | 1 |
| 6 | `check_reference_resolves` — **D2** | **yes** | `roadmap` job | 1 |
| 7 | `check_reference_labelled` — **D3** | **yes** | `roadmap` job | **0 (advisory)** |
| 8 | `check_tag_agreement` (milestone ↔ tag, both directions, over **L** only) | **yes** | `roadmap` job | 1 |
| 9 | `check_milestone_vocabulary` (new/renamed milestone holding roadmap-labelled work) | **yes** | `roadmap` job | 1 |

The *logic* of all nine lives in the script and is unit-tested with injected fixtures. Only the
*live invocation* of the five network checks lives in the separate job. `python -m unittest discover
-s tests` therefore stays 100% hermetic: no socket, no `gh`, no token. Fork runs and offline runs
are unaffected.

### Primary reference vs. commentary

**A bullet contributes exactly one issue reference: the first `[#N](https://github.com/noctua84/nescio-ai/issues/N)`
link on the line** (for a heading, the first such link in the heading text). Any further issue link
later in the same bullet is **commentary** — exempt from checks 1, 5, 6, and 7.

Rationale (`critic`): linking a cross-reference is an ordinary editorial act. Without this rule it
trips uniqueness, membership, and closed-ref simultaneously. Verified traps already in the file:
`ROADMAP.md:59` *"(in tension with **#53** …)"* and `:90` *"fixed in **#83**"* — where **#83 is a
merged PR, not an issue.** Both are currently *bare* `#N`, so the narrow `[#N](url)` anchor already
exempts them; the primary-reference rule is what keeps that true if someone later links one.

**Required code comment**, adjacent to the reference regex — its absence is a review failure:

> `# The narrow [#N](.../issues/N) anchor is LOAD-BEARING, not incidental. ROADMAP.md contains bare`
> `# "#N" in prose (see :59 "in tension with #53", :90 "fixed in #83" — and #83 is a merged PR, not`
> `# an issue). Loosening this to a bare r"#(\d+)" would make ordinary editorial prose fail three`
> `# checks at once. Do not "simplify" it.`

### A committed snapshot of issue state was considered and rejected

Committing a JSON snapshot of open issues so the test could reconcile offline would make the
snapshot itself the thing that drifts — a fourth copy of GitHub-owned state with nothing keeping it
fresh. That is precisely the defect #60 was filed about, relocated. **Rejected.** The reconciliation
must read live state or not run at all; the tri-state exit is how "did not run" stays honest.

### README scope decision — in scope, but not as a prose check

#60 says the fix *"should cover `README.md`'s roadmap summary too… otherwise the same drift just
relocates."* The audit confirmed README's summary is **currently accurate**, and it is **prose-level
with no issue numbers** (`README.md:260-271`).

There is nothing there to reconcile mechanically. Verifying *"earned per-repo autonomy is parked"*
against milestone 4 would require string-matching prose against section headings — brittle, high
false-positive, and it would fail the moment someone rewords a sentence correctly.

**So the README requirement is inverted: rather than policing the prose, prevent the class of
duplication from re-forming.** The check asserts that README's `## Roadmap` section contains a link
to `ROADMAP.md` and contains **zero** `issues/<N>` references. That is mechanically checkable, cheap,
and a direct answer to "otherwise the same drift just relocates".

**Scope, stated accurately (R2-11):** this guard covers **one section of one file**. It is not a
guard against "the drift class" in general, and the docstring must not claim to be. It carries a
named escape — a line containing `<!-- roadmap-check: allow -->` inside the section suppresses the
finding — so a future legitimate exception is a documented opt-out rather than a reason to delete
the check.

README's prose summary remains a human responsibility. **Stated plainly as a limitation, not
silently dropped.**

---

## Trigger design (revised — `critic` HIGH)

**The problem.** Finding 1's drift is caused by issue **open/close events**, which produce no PR.
Network checks on `pull_request` therefore catch **none** of the diagnosed failure mode while
inheriting all of its false positives. Verified aggravator: recent PRs (#89, #91, #93, #94) use **no
closing keywords**, so issues close out-of-band — under the old design every such close would red
the *next unrelated push or PR*.

**The split:**

| Trigger | What runs | Why |
|---|---|---|
| `pull_request` | **offline checks only** (via the `tests` job) | These are genuinely diff-caused: someone edited `ROADMAP.md` or `README.md` in the PR. Fast, hermetic, zero false positives from GitHub-side events. Works on forks with no token. |
| `push` to `main` | full reconciliation | The maintainer is present; the fix is one line. |
| `schedule` (weekly) | full reconciliation | **The only trigger that fires on issue open/close with no push.** This is the highest-value trigger, not theatre (see *Upheld*, item 2). |
| `workflow_dispatch` | full reconciliation | Manual re-arm; also the remedy for cron rot below. |

Implemented as a **job-level `if:`**, not a workflow-level trigger filter — adding
`push: branches: [main]` to `on:` would silently change when `tests` and `lockfile` run.

### Precondition — **`roadmap` must NOT be a required status check**

**Verified:** `main`'s branch protection requires exactly `["tests"]` (`strict: true`). **That is
the sole reason R9 (exit 2 fails the job) is defensible**: a rate-limit or `gh` outage produces a
red job that is *visible* but does not block merges.

> **If someone later adds `roadmap` to required status checks, R9 becomes indefensible** — an
> upstream GitHub incident would block every merge in the repo. Either keep it non-required, or
> change R9 to swallow exit 2 first. **Do not do both.** State this in the job's comment block.

### Scheduled-workflow rot

GitHub **auto-disables cron workflows after 60 days of repository inactivity**. The weekly check
would die *silently*, exactly when nobody is watching — which is the same class of failure #60 was
filed about. Mitigations, all cheap:

- `workflow_dispatch` is present so the workflow can be re-armed with one click.
- The job's comment block states the 60-day rule explicitly, so the next person reading a
  mysteriously-quiet check finds the answer in the file.
- Accepted residual risk: this repo has not been inactive for 60 days in its history. Not worth a
  keepalive workflow now. Named as a limitation, not engineered around.

---

## Offline / network-failure behaviour (a requirement, not an afterthought)

This section is normative. Tasks 3 and 7 both implement against it.

**R1 — single network call site.** `fetch_issue_state()` is the only function in the script that
touches the network. Every check function takes already-fetched state as a parameter. This is what
makes the test suite hermetic.

**R2 — never raises.** `fetch_issue_state()` returns `(state, None)` on success and `(None, reason)`
on any failure. It catches at minimum: `FileNotFoundError`/`OSError` (no `gh` binary), non-zero `gh
auth status` (unauthenticated), non-zero `gh api` (network down, 5xx, 403 rate-limit, 404 repo),
`json.JSONDecodeError` (truncated or multi-document body), and `subprocess.TimeoutExpired`. Follow
`scripts/_hygiene_common.py`: use `run()`-style `capture_output`, branch on `returncode`, keep
"answer is no" distinct from "could not ask".

**R3 — bounded.** Every `gh` invocation carries `timeout=30`. The script cannot hang a CI job.

**R4 — one retry.** A non-zero `gh api` exit is retried once after a 5s sleep before being declared
unreachable. This absorbs the common transient 502 without masking a real outage. Rate-limit (403
with a `rate limit` body) is **not** retried — it is reported immediately, since retrying makes it
worse.

**R5 — exit code semantics.**

| Condition | Exit |
|---|---|
| all checks pass (advisories may still print) | `0` |
| **only** advisory (D3) findings | `0` — printed, never fatal |
| any **hard** check reports drift (offline or network) | `1` |
| offline checks pass, fetch failed | `2` |
| offline checks report drift **and** fetch failed | `1` (a definite finding outranks an unknown) |

**R6 — offline checks always run first and always run.** A fetch failure never suppresses the
offline findings. The report prints what it *could* determine before it prints what it could not.

**R7 — `--offline` flag.** Skips `fetch_issue_state()` entirely, runs only the offline checks
(**three after Task 1, four after Task 5**), exits `0` or `1`, **never** `2`. This is what a
contributor with no `gh` and no token runs locally, and it is what `pull_request` runs in CI. It
must be documented as such.

**R8 — the `tests` job never reaches the network path.** All reconciliation tests pass a hand-built
state object. Adding `-p no:network`-style guards is unnecessary because there is no call to guard;
the seam is the injection point.

**R9 — CI treats exit `2` as a job failure.** Rationale: the `roadmap` job is dedicated, so its red
does not contaminate the `tests` signal, and "the drift check could not run" is exactly the kind of
silence #60 exists to eliminate. Swallowing exit 2 would let a rate-limit silently disable the
check — reintroducing the defect. **This is contingent on the precondition above: `roadmap` is not a
required status check.** With `GITHUB_TOKEN`'s 1000 req/hr/repo budget against this check's small
request count, flakiness is not expected in practice.

**R10 — the report names the reason.** On exit 2, stderr says e.g. `roadmap: could not check — gh
unavailable` / `— not authenticated` / `— api error (403, rate limited)`. Never a bare traceback,
never a bare "failed".

**R11 — the projection is the privacy control.** The `gh api --jq` projection requests **only**
`{number, milestone.title, labels[].name}`. This is not a performance micro-optimisation — it is the
reason issue *bodies* never enter a process whose stdout lands in a **public** CI log. **Required
code comment** adjacent to the `--jq` string:

> `# This narrow projection IS the privacy control. This repo is public and CI logs are public;`
> `# widening to --jq '.' "just to debug" would dump every open issue body into a public log.`
> `# Debug by printing the projected dicts, never the raw API payload.`

**R12 — pagination is explicit.** **Do not use `--paginate`.** Verified (finding 14): `gh api
--paginate --jq '[…]'` emits **one JSON array per page**, so `json.loads` raises and R2 converts
that into a false exit 2 — silent at 31 issues, broken at 101. Verified likewise: **`--slurp` is
rejected when combined with `--jq`** in gh 2.87.3, so that workaround does not compile.

The implementation loops pages explicitly:

```
page = 1
while True:
    rows = gh_json(f"repos/{repo}/issues?state=open&per_page=100&page={page}", jq=PROJECTION)
    accumulate(rows)
    if len(rows) < 100: break
    page += 1
    if page > MAX_PAGES: return (None, "too many pages")   # bounded; MAX_PAGES = 20
```

Each page is a single well-formed array, so `json.loads` is safe, the narrow projection (R11) is
preserved, and the loop is bounded. **A comment must record why `--paginate` and `--slurp` were both
rejected**, so nobody "simplifies" it back.

---

## Verification strategy

Every task's acceptance criterion is a command a reviewer can paste. Two commands recur:

```bash
# targeted
PYTHONPATH=scripts python -m unittest tests.test_roadmap_drift -v

# full suite, exactly as CI runs it
PYTHONPATH=scripts python -m unittest discover -s tests -v
```

**The hermeticity idiom** (revision 2, B1 — this exact form, at every site):

```bash
PY=$(command -v python); PATH=/nonexistent PYTHONPATH=scripts "$PY" <rest>
```

The naive `PATH=/nonexistent python …` **removes `python` itself** and exits **127** —
verified — so it proves nothing while looking like a pass. The corrected form was executed during
planning: it runs the interpreter *and* still hides `gh` (`shutil.which("gh")` → `None` inside the
child). Any acceptance criterion that drops `PY=$(command -v python)` is broken.

`ROADMAP.md` after Task 0b is the **reference state**: every check must report clean against it.
Synthetic drift fixtures (Task 2) prove each check actually fires. **Counts are deliberately not
hardcoded** — Task 0b may change them — so the baseline test asserts a parser *self-consistency*
invariant plus "all offline checks clean" (see Task 4).

---

## Execution strategy

Seven waves. Wave 0 gates everything: no code is worth writing until the owner has settled which
issues are planned work.

| Wave | Tasks | Parallel? |
|---|---|---|
| **0** | T0 (classification table — **owner approval gate**) | no — blocks all |
| **0b** | T0b (create + apply label; amend `07779cb` if reclassified) | no |
| 1 | T1 (script core), T2 (fixtures), T10 (issue forms) | yes — different files |
| 2 | T3 (fetch layer + network checks), T4 (offline tests) | yes — different files |
| 3 | T5 (README guard), T6 (reconciliation tests) | yes — different files |
| 4 | T7 (CI job), T8 (docs) | yes — different files |
| 5 | T9 (live end-to-end verification) | no |

Waves 2–4 serialise on shared files (`check_roadmap_drift.py`, `test_roadmap_drift.py`) — deliberate
rather than split into artificial helper modules. This repo reserves `scripts/_*_common.py` for
genuinely shared code (2+ consumers), and this feature has one consumer.

---

## TODOs

### Wave 0 — the policy gate

- [ ] **0. Classify every currently-referenced issue: planned feature / maintenance / ambiguous**

  **What to do**: No code, no labels, no file edits. Produce the table below as the task's output,
  **and get the owner's explicit approval on it before Task 0b runs.** The proposed classification
  is filled in as a starting position to react to, not a decision already taken.

  Criteria applied:
  - **Planned feature** — a *capability the project intends to have*. Someone reading the line
    learns where the project is going. Includes parked/deferred work (held ≠ abandoned) and
    evaluative spikes whose outcome is a capability decision.
  - **Maintenance** — a *defect in, or upkeep of, a capability that already shipped*: bugs, CI
    plumbing, docs debt, housekeeping. Tracked as issues, shipped normally, **no roadmap line**.
  - **Ambiguous** — genuinely reads both ways; the owner decides.

  | # | Title (short) | Labels today | Milestone | Proposed | Rationale |
  |---|---|---|---|---|---|
  | 43 | Epic: the learning loop | `enhancement` | — | **planned** | Epic; the roadmap's organising heading |
  | 33 | Epic: earned per-repo autonomy | `enhancement` | — | **planned** | Epic; the roadmap's organising heading |
  | 10 | cross-repo generalization tier | `enhancement` | Cross-repo | **planned** | New capability, learning-path step 2 |
  | 11 | knowledge ingest + query + capture bridge | `enhancement` | Cross-repo | **planned** | New capability, step 3 |
  | 34 | learning-store bridge (phase 2.2) | `enhancement` | Cross-repo | **planned** | New capability |
  | 35 | confidence-decay & re-validation | `enhancement` | Readiness | **planned** | New capability |
  | 40 | orchestrator retro + auto harvest | `enhancement` | Readiness | **planned** | New capability |
  | 70 | clean-vs-flagged session verdict | `enhancement` | Readiness | **planned** | New signal, replaces a placeholder state |
  | 53 | retain full promotion history; retire the cap | — | Loop | **planned** | Deliberate data-model change, not a fix |
  | 60 | roadmap drift check | `enhancement` | Loop | **planned** | New tooling capability (this work) |
  | 58 | `postmortem` skill | — | — | **planned** | New skill |
  | 29 | OpenAI Codex CLI adapter | `enhancement` | — | **planned** | New capability; named in README as a direction |
  | 20 | heavyweight `/pr-review` fan-out | — | — | **planned** | New opt-in capability |
  | 21 | machine-local statusline | — | — | **planned** | New opt-in capability |
  | 22 | headless action for `dependency-pr-ci-fix` | — | — | **planned** | New opt-in capability |
  | 32 | phase-3 autonomy dial + charter evolution | `enhancement`,`deferred` | Parked | **planned** | Parked ≠ unplanned |
  | 36 | diversity-weighted promotion | `enhancement`,`deferred` | Parked | **planned** | Parked ≠ unplanned |
  | 37 | "Confidence & gaps" signal | `enhancement`,`question`,`deferred` | Parked | **planned** | Evaluative spike toward a capability |
  | 38 | consolidation cadence ("sleep") | `enhancement`,`deferred` | Parked | **planned** | Parked ≠ unplanned |
  | 39 | mid-task checkpoint / resume | `enhancement`,`deferred` | Parked | **planned** | Parked ≠ unplanned |
  | 41 | evaluate Obsidian as a view layer | `enhancement`,`question`,`deferred` | Parked | **planned** | Evaluative spike toward a capability |
  | **64** | release-please stalls at `action_required` | `enhancement` | — | **maintenance** | CI plumbing defect in a shipped release process |
  | **69** | `compute_readiness` Windows name bucketing | `bug` | Readiness | **maintenance** | Labelled `bug`; a defect in shipped behaviour |
  | **71** | `promote_learnings.py` cp1252 crash | — | — | **maintenance** | Crash in a shipped script |
  | **72** | learning-log over the 150-line cap | — | — | **maintenance** | Housekeeping; and #53 may moot it entirely |
  | **84** | audit `write_text` sites for the CRLF class | — | — | **maintenance** | Defect-class audit following a shipped fix |
  | *2* | wiki-engine "cosmetic follow-ups" | `enhancement` | Loop | *ambiguous* | Title says cosmetic/hygiene → chore; but milestoned `Loop integrity` |
  | *19* | decide on empty scaffolding dirs | — | — | *ambiguous* | A decision, not a capability; a valid outcome is "drop it" |
  | *52* | review pipeline parity + freshness gap | — | Loop | *ambiguous* | The parity check is a capability; closing the freshness gap is upkeep |
  | *59* | dispatch template: branch from fetched ref | `enhancement` | Loop | *ambiguous* | Fast-follow hardening of a guard that already shipped |
  | *81* | docs site: `builder` + Delivery Boundary Check | — | — | *ambiguous* | Documentation debt for shipped capability; leans maintenance |

  **Proposed totals: 21 planned / 5 maintenance / 5 ambiguous = 31.**

  **Flag prominently for the owner:** if the 5 maintenance rows (and any ambiguous rows the owner
  resolves as maintenance) are accepted, **`07779cb` must be amended** — those bullets were added by
  the audit to reach the (now-retracted) bijection and should not have been. The commit is unpushed
  and amendable (verified). This reaches back into work already committed; it is not only a
  checker change.

  **Files**: none. Output is the approved table, recorded in the PR description.

  **Acceptance criteria**:
  ```bash
  # Confirm the input set is still exactly the 31 issues classified above:
  gh issue list --state open --limit 100 --json number --jq '[.[].number] | sort | length'
  # → 31   (if this differs, re-run the classification for the delta before proceeding)
  ```
  Plus: an explicit written approval from the owner naming, for each ambiguous row, whether it is
  planned or maintenance. **No label is created or applied until that exists.**

- [ ] **0b. Create the `roadmap` label, apply it, and reconcile `07779cb`**

  **What to do**: Gated on T0 approval.

  1. Create the label:
     ```bash
     gh label create roadmap \
       --description "Planned direction for the project; expected in ROADMAP.md. Orthogonal to 'deferred'." \
       --color 0e8a16
     ```
     Verified: no existing label named `roadmap` (finding 10). Do **not** reuse `enhancement`
     (finding 11) and do **not** replace `deferred` — the two coexist.
  2. Apply `roadmap` to every issue the owner classified **planned**:
     `gh issue edit <N> --add-label roadmap`.
  3. **Do not** apply it to maintenance issues. **Do not** remove any existing label.
  4. For every issue the owner reclassified as maintenance that currently has a bullet in
     `ROADMAP.md`: remove that bullet and **amend `07779cb`** (`git commit --amend`), keeping the
     original commit message intent. The commit is unpushed, so no force-push to a shared branch is
     involved. Do not create a second "revert part of the audit" commit — the audit commit was never
     published; amending keeps history honest.
  5. Record in the amended commit body which issues were dropped and why, citing the owner's policy.

  **Files**: `ROADMAP.md` (bullet removals only — **no bullet text is rewritten**; GitHub labels,
  which are not files).

  **Acceptance criteria**:
  ```bash
  gh label list --limit 100 | grep -c "^roadmap"      # → 1
  # every roadmap-labelled open issue is referenced in the file, and vice versa:
  gh issue list --state open --label roadmap --limit 100 --json number --jq '[.[].number]|sort|join(" ")'
  # NOTE: the parser does not exist yet here, so this is a coarse stand-in. It counts every
  # issues/<N> link in the file, INCLUDING any inside `## Shipped`. `## Shipped` carries no
  # issue links today (verified), so the comparison is exact right now -- if you add one
  # there first, subtract it by hand rather than trusting this line.
  grep -oE 'issues/[0-9]+' ROADMAP.md | cut -d/ -f2 | sort -n | uniq | tr '\n' ' '
  # → the two lists agree (this is the state the checker will later assert automatically)
  git log --oneline origin/main..HEAD    # → still exactly one commit; 07779cb amended, not stacked
  git diff origin/main -- ROADMAP.md | grep -c '^+- '   # → only additions the owner approved
  ```

### Wave 1

- [ ] **1. Script core: parser, offline checks, CLI exit convention**

  **What to do**: Create `scripts/check_roadmap_drift.py`. Module docstring in the house style (see
  `compute_readiness.py`) stating: what it reconciles, that it **never writes**, the
  membership-not-tags finding, **the allow-list policy and why it is not a bijection** (public repo,
  outside contributors), and the `open_issues`-counts-PRs gotcha.

  Implement:
  - `ROADMAP_LABEL = "roadmap"` — with a comment that membership is **maintainer-asserted opt-in**,
    that GitHub already restricts labelling to triage-and-above (finding 12), and that this is why
    an outside bug report cannot force a roadmap line.
  - `TAG_TO_MILESTONE = {"loop": "Loop integrity", "readiness": "Readiness signal",
    "cross-repo": "Cross-repo knowledge", "parked": "Parked"}` — declared, with a comment that
    Task 3's `check_milestone_vocabulary` is what keeps it honest.
  - Exit constants `EXIT_PASS = 0`, `EXIT_DRIFT = 1`, `EXIT_ERROR = 2` (mirror
    `verify_commit_position.py:56-60`).
  - `parse_roadmap(text) -> tuple[list[Entry], list[str]]` where `Entry` carries `number`,
    `tag | None`, `kind` (`"bullet"` | `"heading"`), `line_no`. Must handle:
    tagged bullet `` - `loop` [#53](https://github.com/noctua84/nescio-ai/issues/53) — text ``;
    untagged bullet `- [#29](.../issues/29) — text`; heading reference
    `## Learning loop & memory — [Epic #43](.../issues/43)`; bullets with **no** issue link at all
    (Installer & onboarding's *A2* / *Layer B*, Under consideration's *Crew benchmarking*) — these
    are tolerated and ignored, never flagged.
  - **Primary reference rule**: exactly one `Entry` per line — the **first** `[#N](…/issues/N)` link.
    Later issue links on the same line are commentary and are discarded. Carry the required
    load-bearing-anchor comment verbatim from § *Primary reference vs. commentary*.
  - **Section scoping**: the `## Shipped` section and the intro/legend paragraph are excluded from
    all issue-reference checks. Shipped is a history section that may legitimately cite a closed
    issue; the legend's bare `https://github.com/noctua84/nescio-ai/issues` link carries no `/N` and
    must not be mistaken for a reference. Encode this as an explicit `EXCLUDED_SECTIONS =
    {"Shipped"}` with a comment, not as an accident of the regex.
  - Offline checks, each returning a list of human-readable finding strings:
    - `check_unique_references` — no primary reference appears more than once across all entries.
    - `check_tag_vocabulary` — every tag used is a `TAG_TO_MILESTONE` key. **The legend-text half is
      deliberately omitted** (R2-8): string-matching backticked tags against a hand-written prose
      paragraph is the same brittleness rejected for README. Record that omission in a comment so it
      is not "restored" as an oversight.
    - `check_link_wellformed` — the displayed `#N` equals the `issues/N` in the URL, and the URL
      host/repo is `github.com/noctua84/nescio-ai`.
  - `main(argv=None) -> int` with `argparse`: `--roadmap PATH` (default repo `ROADMAP.md`),
    `--offline`, `--json`. Wire R5/R6/R7, including the **advisory channel** — findings carry a
    severity so D3 can print without affecting the exit code. Leave `fetch_issue_state` as a
    module-level function returning `(None, "not implemented")` — Task 3 fills it in.

  **Files**: `scripts/check_roadmap_drift.py` (new)

  **Acceptance criteria**:
  ```bash
  PYTHONPATH=scripts python scripts/check_roadmap_drift.py --offline; echo "exit=$?"
  # → exit=0, and output names the four milestone tags it knows

  # parser self-consistency: one Entry per primary link, and no bare-#N false positives.
  # (Counts are NOT hardcoded -- Task 0b may change them.)
  PYTHONPATH=scripts python - <<'PY'
  import re, check_roadmap_drift as c
  text = open('ROADMAP.md', encoding='utf-8').read()
  entries, _ = c.parse_roadmap(text)
  # every parsed entry maps to a distinct source line
  assert len({e.line_no for e in entries}) == len(entries), "two entries share a line"
  # every entry's number appears in a well-formed link on its own line
  lines = text.splitlines()
  for e in entries:
      assert f"/issues/{e.number}" in lines[e.line_no - 1], e
  assert sum(1 for e in entries if e.kind == "heading") == 2, "expected the two epic headings"
  assert all(e.tag in c.TAG_TO_MILESTONE for e in entries if e.tag)
  print("entries:", len(entries), "tagged:", sum(1 for e in entries if e.tag))
  PY
  # → assertions pass; the printed counts are informational, not asserted
  ```

- [ ] **2. Drift fixtures**

  **What to do**: Create `tests/fixtures/roadmap/` containing minimal `ROADMAP.md`-shaped files,
  each isolating exactly one condition. Keep each under ~30 lines — they exist to make a single
  assertion legible, not to mirror the real file.
  - `clean.md` — legend + one section + 3 tagged bullets + 1 untagged + 1 prose-only bullet + 1 epic
    heading reference. All checks pass.
  - `duplicate_reference.md` — `#53` is the **primary** reference of two different bullets.
  - `unknown_tag.md` — a bullet tagged `` `v2` ``, not in the vocabulary.
  - `mismatched_link.md` — `[#53](.../issues/35)`.
  - `shipped_section_closed_ref.md` — a closed-issue reference inside `## Shipped`; asserts the
    exclusion works and this is **not** flagged.
  - `prose_only.md` — a section whose bullets carry no issue links at all, **plus** a bullet with a
    bare `#83` in prose and a bullet whose prose contains a *second* `[#N](url)` link after its
    primary one. Asserts zero findings — this is the R2-9 regression fixture.

  ~~`legend_missing_tag.md`~~ — **dropped in revision 2** with the legend-text check (R2-8).

  **Files**: `tests/fixtures/roadmap/clean.md`, `duplicate_reference.md`, `unknown_tag.md`,
  `mismatched_link.md`, `shipped_section_closed_ref.md`, `prose_only.md`

  **Acceptance criteria**:
  ```bash
  ls tests/fixtures/roadmap/*.md | wc -l   # → 6
  grep -L "Tags map an item" tests/fixtures/roadmap/*.md   # → empty; every fixture has a legend
  grep -c '#83' tests/fixtures/roadmap/prose_only.md       # → ≥1; the bare-#N trap is represented
  ```

  **QA scenario**: open `clean.md` beside `ROADMAP.md` — the bullet grammar must be identical
  character-for-character in structure (backtick tag, space, `[#N](url)`, space, em-dash, space).

- [ ] **10. Issue templates: migrate to issue forms, and document what earns a roadmap line**

  **What to do**: This is the intake half of the allow-list, and the part the owner explicitly asked
  for. It is **documentation first, YAML second.**

  **Decision: migrate `.md` → issue forms (`.yml`).** Justification:
  - Forms support `required: true`. A markdown template's headings are *suggestions* an author can
    delete; a form's required field cannot be submitted empty. That is the difference between
    enforcing structure and merely proposing it.
  - Forms support `dropdown`, so "is this planned work?" becomes a structured field a maintainer can
    triage from the issue list rather than free prose.
  - Forms keep `labels:` frontmatter, so existing `bug` / `enhancement` stamping is preserved.
  - **Cost, stated honestly:** forms are web-UI-only. `gh issue create --title --body` bypasses them
    entirely, and `blank_issues_enabled: false` does not change that. Direct evidence: **11 of 31
    open issues carry no labels at all**, which is only possible via the CLI path. So the form is a
    lever on outside contributors and **no lever at all on the maintainer** — the allow-list is
    designed not to depend on it.

  **The critical design call — the template must NOT auto-stamp `roadmap`.** If a public template
  stamped it, any outside contributor could force a line onto `ROADMAP.md` and hard-fail D1. That
  re-creates exactly the vulnerability the allow-list closes. Instead the form asks a *question*
  (`dropdown`: "Is this a new capability, or a defect/chore in something that already ships?") and
  the maintainer applies `roadmap` at triage. GitHub already enforces this: labelling requires the
  triage role (finding 12).

  Deliverables:
  1. `.github/ISSUE_TEMPLATE/bug_report.yml` — replaces `bug_report.md`. `labels: [bug]`. Required:
     what happened, expected, steps, environment. A `- type: markdown` note: *bugs are fixed and
     shipped normally, and do not get a roadmap line.*
  2. `.github/ISSUE_TEMPLATE/feature_request.yml` — replaces `feature_request.md`.
     `labels: [enhancement]` (**not** `roadmap`). Required: problem/use case, proposed idea,
     alternatives considered. A `dropdown` "What kind of change is this?" with options *new
     capability* / *improvement to something that ships* / *defect or chore* / *not sure*. Plus a
     `- type: markdown` block reproducing the roadmap criteria below.
  3. `.github/ISSUE_TEMPLATE/config.yml` — keep `blank_issues_enabled: false`. Add a
     `contact_links` entry pointing at `ROADMAP.md` so someone asking "is this already planned?"
     is answered before they file.
  4. Delete `bug_report.md` and `feature_request.md` in the same commit (having both a `.md` and a
     `.yml` for the same purpose shows two choices in the picker).

  **The documentation the owner asked for — "what an issue should contain and be labeled with in
  order to fit in."** This exact text goes in the feature-request form's markdown block, in
  `CONTRIBUTING.md` (Task 8), and in condensed form in `ROADMAP.md`'s legend (Task 8):

  > **What earns a roadmap line.** `ROADMAP.md` lists *planned features* — capabilities the project
  > intends to have. An issue gets a line when a maintainer applies the **`roadmap`** label, which
  > happens at triage, not at filing.
  >
  > **Gets a line:** a new capability, skill, agent, or subsystem; a deliberate change to how an
  > existing capability is designed; an evaluative spike whose outcome is a capability decision.
  > Work in the *Parked* milestone still gets a line — `deferred` means held, not abandoned, and the
  > two labels coexist.
  >
  > **Does not get a line:** bugs and crashes; CI, release, and packaging plumbing; documentation
  > debt; housekeeping and audits. These are tracked as issues and shipped normally — the roadmap is
  > about direction, not about the backlog.
  >
  > **To be roadmap-ready an issue needs:** a title that reads as a capability (not a symptom); the
  > problem or use case in one paragraph; the proposed shape; and what you considered instead. If a
  > maintainer cannot write a one-line roadmap bullet from your issue, it is not ready for one.

  **Files**: `.github/ISSUE_TEMPLATE/bug_report.yml` (new), `feature_request.yml` (new),
  `config.yml` (modify), `bug_report.md` (delete), `feature_request.md` (delete)

  **Acceptance criteria**:
  ```bash
  ls .github/ISSUE_TEMPLATE/          # → bug_report.yml  config.yml  feature_request.yml  (no .md)
  grep -c "blank_issues_enabled: false" .github/ISSUE_TEMPLATE/config.yml   # → 1
  grep -c "roadmap" .github/ISSUE_TEMPLATE/feature_request.yml   # → ≥1  (the criteria prose)
  # the label-stamping frontmatter must NOT include the roadmap label:
  grep -nE '^labels:' .github/ISSUE_TEMPLATE/*.yml
  # → bug_report: [bug]; feature_request: [enhancement].  Neither contains "roadmap".
  grep -c "required: true" .github/ISSUE_TEMPLATE/feature_request.yml   # → ≥3
  ```
  **QA scenario**: after merge, open `https://github.com/noctua84/nescio-ai/issues/new/choose` and
  confirm exactly two templates appear, no "blank issue" option, and that the feature form refuses
  to submit with the required fields empty. If GitHub reports a form-schema parse error, the
  template silently disappears from the picker — **check the picker, not just the file.**

### Wave 2

- [ ] **3. Network layer: `gh` fetch, PR filter, tri-state degradation, the five reconciliation checks**

  **What to do**: In `scripts/check_roadmap_drift.py`, implement `fetch_issue_state()` and the five
  network-dependent checks.

  `fetch_issue_state(repo="noctua84/nescio-ai") -> tuple[IssueState | None, str | None]`:
  - Guard with a `gh_available()` equivalent (`gh auth status` returncode == 0, `OSError` →
    unavailable), per `scripts/_hygiene_common.py:172-180`.
  - Issues, **paginated explicitly per R12** (no `--paginate`, no `--slurp`):
    ```
    repos/<repo>/issues?state=open&per_page=100&page=<n>
      --jq '[.[] | select(.pull_request | not)
                 | {number, milestone: (.milestone.title // null), labels: [.labels[].name]}]'
    ```
  - Milestones (single page is sufficient, but use the same loop):
    ```
    repos/<repo>/milestones?state=open&per_page=100&page=<n>  --jq '[.[] | {number, title}]'
    ```
  - **The #60 gotcha**: `select(.pull_request | not)` is mandatory on the issues call. Add an inline
    comment saying why (the milestones API's `open_issues` counts PRs; without the filter the check
    reports false drift whenever a PR is milestoned). **Do not** use the milestone `open_issues`
    count as a source of truth anywhere — derive per-milestone counts from the filtered issue list
    only.
  - Carry the **R11 privacy comment** and the **R12 pagination comment** verbatim.
  - Satisfy R2, R3, R4 (`timeout=30`, one 5s-backoff retry on non-rate-limit failure, rate-limit
    reported without retry).

  Checks, each taking `(entries, state)` and returning findings tagged with a severity:
  - `check_labelled_present` (**D1, hard**) — every open issue carrying `roadmap` appears as a
    primary reference. Wording: *"labelled `roadmap` but not on the roadmap: #N — add a bullet, or
    drop the label."*
  - `check_reference_resolves` (**D2, hard**) — every primary reference resolves to an **open
    issue**. For each referenced number absent from the open set, resolve it individually:
    ```
    repos/<repo>/issues/<N>  --jq '{number, state, is_pr: (has("pull_request"))}'
    ```
    Report distinctly: *"referenced but closed: #N — move to Shipped or remove"* vs *"referenced but
    not an open issue: #N (not found, or is a pull request)"*. **Bound this**: if more than 20
    numbers need individual resolution, skip the per-issue calls and report them in bulk without
    state, to keep the request budget honest. Comment why the bound exists.
  - `check_reference_labelled` (**D3, ADVISORY — never affects the exit code**) — a primary
    reference to an open issue lacking `roadmap`. Wording must include the literal remedy:
    *"on the roadmap but not labelled: #N — `gh issue edit N --add-label roadmap` (advisory; the
    remedy is GitHub metadata, which no commit can carry)."* Add a comment explaining the severity
    choice, citing § *Direction semantics*, so it is not "fixed" into a hard failure by someone who
    reads the asymmetry as a bug.
  - `check_tag_agreement` (**hard**) — over **roadmap-labelled issues only**, both directions: an
    issue with milestone M must carry the tag mapping to M; an issue with **no** milestone must
    carry **no** tag. Heading-kind entries (epics #43, #33) are exempt from the tag rule but still
    count for D1/D2.
  - `check_milestone_vocabulary` (**hard**) — every open milestone holding ≥1 open
    **roadmap-labelled** issue has a `TAG_TO_MILESTONE` entry; every `TAG_TO_MILESTONE` value
    resolves to an existing open milestone title. Restricting to labelled issues means a
    maintenance-only milestone does not demand a roadmap tag.

  Wire all five into `main()` behind R5/R6, with the advisory channel separate from the hard one.

  **Files**: `scripts/check_roadmap_drift.py` (modify)

  **Acceptance criteria**:
  ```bash
  PYTHONPATH=scripts python scripts/check_roadmap_drift.py; echo "exit=$?"
  # → exit=0 against ROADMAP.md as of Task 0b (advisories may print; they do not change the exit)

  # B1-corrected hermeticity probe: interpreter survives, gh does not.
  PY=$(command -v python); PATH=/nonexistent PYTHONPATH=scripts "$PY" scripts/check_roadmap_drift.py; echo "exit=$?"
  # → exit=2, stderr names "gh unavailable"; no traceback

  grep -c "select(.pull_request | not)" scripts/check_roadmap_drift.py   # → ≥1

  # B2-corrected: the intent is "open_issues is named only in prose that warns against it,
  # never in an expression that consumes it". Assert that directly:
  grep -n "open_issues" scripts/check_roadmap_drift.py
  # → every hit is inside a comment (#) or the module docstring; NO hit assigns from it,
  #   indexes it, or compares it (no `["open_issues"]`, no `.open_issues`, no `== open_issues`).
  grep -nE '\["open_issues"\]|\.open_issues|open_issues *[=<>!]' scripts/check_roadmap_drift.py
  # → no match.  This is the executable form of the rule; the grep -c above is human-read.

  # R12: --paginate and --slurp are both rejected, with the reason recorded.
  grep -c -- "--paginate" scripts/check_roadmap_drift.py   # → hits are in the comment only
  grep -nE '^\s*#.*(paginate|slurp)' scripts/check_roadmap_drift.py   # → ≥1; the rationale is present
  ```

- [ ] **4. Tests: parser and offline checks**

  **What to do**: Create `tests/test_roadmap_drift.py` in the house style (`# tests/…` header
  comment, stdlib `unittest`, `ROOT = Path(__file__).resolve().parent.parent`,
  `sys.path.insert(0, str(ROOT / "scripts"))`, `import check_roadmap_drift`).

  Cover:
  - `parse_roadmap` against each fixture: entry counts, tags, `kind`, `line_no`.
  - Each offline check fires on its fixture and stays silent on `clean.md`.
  - `shipped_section_closed_ref.md` produces **zero** findings — the exclusion regression test.
  - `prose_only.md` produces zero findings — covers both the no-link bullets **and** the R2-9
    traps: a bare `#83` in prose, and a second `[#N](url)` link after a bullet's primary one.
    Name it `test_prose_commentary_is_not_a_reference` and cite `ROADMAP.md:59` / `:90` and the fact
    that **#83 is a merged PR** in the docstring.
  - **Baseline test** against the real `ROADMAP.md`: all offline checks report clean, and the parser
    is self-consistent (one entry per source line; each entry's number present in a well-formed link
    on that line; exactly 2 heading entries; every tag ∈ `TAG_TO_MILESTONE`). **Do not hardcode the
    total entry count** — Task 0b may change it, and a magic number would turn an approved editorial
    decision into a red test. Record that reasoning in a comment.
  - `--offline` never returns `EXIT_ERROR`, asserted by invoking `main(["--offline"])`.

  **Files**: `tests/test_roadmap_drift.py` (new)

  **Acceptance criteria**:
  ```bash
  PYTHONPATH=scripts python -m unittest tests.test_roadmap_drift -v   # all pass

  PY=$(command -v python); PATH=/nonexistent PYTHONPATH=scripts "$PY" -m unittest tests.test_roadmap_drift -v
  # still all pass
  ```
  The second command is the hermeticity proof and is not optional. **Note the corrected form** — the
  naive `PATH=/nonexistent python …` exits 127 (`python: command not found`) and proves nothing.
  `command -v python` is resolved *before* `PATH` is clobbered; the child still cannot see `gh`.

### Wave 3

- [ ] **5. README structural guard**

  **What to do**: Add `check_readme(readme_text)` to `scripts/check_roadmap_drift.py` and wire it
  into the offline set. It asserts, over the `## Roadmap` section of `README.md` only:
  - the section links to `ROADMAP.md`;
  - the section contains **zero** `github.com/noctua84/nescio-ai/issues/<N>` references.

  **Named escape (R2-11):** a line containing `<!-- roadmap-check: allow -->` inside the section
  suppresses the finding. Document it in the finding message itself, so the person hitting the
  failure learns the opt-out without reading source.

  The finding message must explain the intent, e.g.
  *"README's roadmap summary must stay prose-level — enumerated issue state here becomes a third
  copy that drifts (#60). Move it to ROADMAP.md, or add `<!-- roadmap-check: allow -->` to this
  section if the duplication is deliberate."*

  Add `--readme PATH` (default repo `README.md`) and a docstring paragraph recording the decision —
  **worded to what it actually does (R2-11)**: this guards the `## Roadmap` section of one file
  against acquiring enumerable issue state. It is *not* a guard against drift in general, and it
  makes no claim about whether the prose is accurate; that stays a human judgement.

  **Files**: `scripts/check_roadmap_drift.py` (modify)

  **Acceptance criteria**:
  ```bash
  PYTHONPATH=scripts python scripts/check_roadmap_drift.py --offline; echo "exit=$?"   # → exit=0
  ```
  **QA scenario**: append `- [#99](https://github.com/noctua84/nescio-ai/issues/99) — x` under
  README's `## Roadmap`, re-run `--offline`, confirm exit 1 with the explanatory message; then add
  `<!-- roadmap-check: allow -->` to that section and confirm exit 0; then `git checkout README.md`.
  Do not commit either edit.

- [ ] **6. Tests: reconciliation, injected state, and the PR-filter regression**

  **What to do**: Extend `tests/test_roadmap_drift.py`. A `_state(...)` helper builds an
  `IssueState` from a literal dict — **no network, no `gh`, no mocking of `subprocess` for the check
  tests.** The helper must accept per-issue `labels`, since the allow-list depends on them.

  Cover:
  - `check_labelled_present` (D1): labelled-but-missing fires; labelled-and-present is silent.
  - `check_reference_resolves` (D2): a closed issue still listed; a reference to a number that is a
    PR; a reference to a number that does not exist. Each reported with its own wording.
  - `check_reference_labelled` (D3): fires as an **advisory** — assert both that the finding is
    produced *and* that `main()` returns `EXIT_PASS` when it is the only finding. This is the test
    that stops someone silently promoting it to a hard failure.
  - **`test_unlabelled_unreferenced_issue_is_silent`** — the escape hatch, and the reason revision 2
    exists. Feed an open issue with no `roadmap` label that appears nowhere in the file (the outside
    bug report). Assert **zero findings of any severity**. Docstring must record that the old
    bijection design hard-failed on this, and that 100% solo authorship was what hid it.
  - `check_tag_agreement`: wrong tag; missing tag on a milestoned labelled issue; a tag on an
    unmilestoned labelled issue; heading-kind entry exempt from the rule but present in D1/D2; an
    **unlabelled** issue's milestone is ignored entirely.
  - `check_milestone_vocabulary`: a fifth milestone holding roadmap-labelled issues and no tag; a
    milestone holding only *unlabelled* issues produces **no** finding; a renamed milestone breaking
    a `TAG_TO_MILESTONE` value.
  - **The #60 gotcha, as a named regression test** — `test_pull_requests_do_not_count_as_issues`:
    feed `fetch_issue_state`'s parsing seam a raw payload containing an entry with a `pull_request`
    key assigned to milestone "Loop integrity", and assert it is absent from the parsed state and
    produces no finding. Docstring must cite #60 and #57's PR #56.
  - **`test_multi_page_response_is_accumulated`** (R12 regression): drive the paginated fetch with a
    stubbed `run` returning a full 100-item page then a short page, and assert both pages land in
    the state. Docstring must record the verified defect: `gh api --paginate --jq '[…]'` emits **one
    array per page**, so `json.loads` raises and R2 turns it into a false exit 2 — reproduced at
    `per_page=20` against this repo; and `--slurp` is rejected when combined with `--jq`.
  - **Degradation tests** (`unittest.mock.patch` on the `run`/subprocess seam only):
    `gh` missing → `(None, reason)` and `main()` → `EXIT_ERROR`; unauthenticated → same; `gh api`
    non-zero → retried once then `(None, reason)`; rate-limit → **not** retried; `TimeoutExpired` →
    `(None, reason)`; malformed JSON → `(None, reason)`. Each asserts no exception escapes.
  - **R5 precedence test**: offline drift **and** a failed fetch → `EXIT_DRIFT` (1), not 2.

  **Files**: `tests/test_roadmap_drift.py` (modify)

  **Acceptance criteria**:
  ```bash
  PY=$(command -v python); PATH=/nonexistent PYTHONPATH=scripts "$PY" -m unittest tests.test_roadmap_drift -v
  # all pass — proves zero live-network dependency

  PYTHONPATH=scripts python -m unittest discover -s tests -v   # full suite green

  grep -c "def test_pull_requests_do_not_count_as_issues" tests/test_roadmap_drift.py      # → 1
  grep -c "def test_unlabelled_unreferenced_issue_is_silent" tests/test_roadmap_drift.py   # → 1
  grep -c "def test_multi_page_response_is_accumulated" tests/test_roadmap_drift.py        # → 1
  grep -c "def test_prose_commentary_is_not_a_reference" tests/test_roadmap_drift.py       # → 1
  ```

### Wave 4

- [ ] **7. CI job**

  **What to do**: Add a `roadmap` job to `.github/workflows/tests.yml`, modelled on the `lockfile`
  job — including a comment block in the same voice explaining what silent drift it turns into a
  loud failure, and citing #60.

  - Add to the workflow's `on:` block:
    ```yaml
    on:
      push:
      pull_request:
      schedule:
        - cron: "17 6 * * 1"     # weekly Monday; offset minute avoids the top-of-hour queue
      workflow_dispatch:
    ```
    Note in the comment that `tests` and `lockfile` will also fire on that schedule and that this is
    acceptable — they are cheap, and a weekly independent confirmation is a feature.
  - Job body:
    ```yaml
    roadmap:
      # Network reconciliation runs on push-to-main, the weekly cron, and manual dispatch --
      # NOT on pull_request.  The drift this catches is caused by issue open/close events, which
      # produce no PR at all; and this repo's PRs close issues out-of-band (no closing keywords),
      # so every close would otherwise red the next unrelated PR.  The offline half of the same
      # check already runs on every PR inside the `tests` job.
      #
      # PRECONDITION: this job must NOT be added to main's required status checks.  Protection
      # currently requires only ["tests"].  This job exits 2 ("could not check") on a gh outage or
      # rate limit and that is deliberate -- silence is the defect #60 was filed about -- but it is
      # only safe while a red here does not block merges.  If you make it required, change the
      # exit-2 handling first.  Do not do both.
      #
      # NOTE: GitHub auto-disables cron workflows after 60 days of repo inactivity.  If the weekly
      # run stops appearing, that is why; workflow_dispatch re-arms it.
      if: >-
        github.event_name == 'schedule' ||
        github.event_name == 'workflow_dispatch' ||
        (github.event_name == 'push' && github.ref == 'refs/heads/main')
      runs-on: ubuntu-latest
      permissions:
        contents: read
        issues: read
      steps:
        - uses: actions/checkout@v4
        - uses: actions/setup-python@v5
          with:
            python-version: "3.13"
        - env:
            GH_TOKEN: ${{ github.token }}
          run: PYTHONPATH=scripts python scripts/check_roadmap_drift.py
    ```
  - Do **not** add `continue-on-error`. Per R9, exit 2 fails this job deliberately.
  - Do **not** grant write permissions. This job never opens a PR (see: shape A rejected).

  **Files**: `.github/workflows/tests.yml` (modify)

  **Acceptance criteria** — **no PyYAML** (R2-14); this repo is deliberately dependency-free:
  ```bash
  grep -cE '^  roadmap:'            .github/workflows/tests.yml   # → 1
  grep -cE '^  schedule:'           .github/workflows/tests.yml   # → 1
  grep -cE '^  workflow_dispatch:'  .github/workflows/tests.yml   # → 1
  grep -n  'continue-on-error'      .github/workflows/tests.yml   # → no match
  grep -nE '(contents|issues|pull-requests): *write' .github/workflows/tests.yml   # → no match
  grep -n  "github.event_name == 'schedule'" .github/workflows/tests.yml           # → 1 match
  grep -n  "required status checks" .github/workflows/tests.yml   # → 1 match (the precondition comment)

  # jobs are exactly the three expected, read without a YAML parser:
  # (Job keys live below the `jobs:` line; the `on:` block also uses two-space keys, so slice first.)
  sed -n '/^jobs:/,$p' .github/workflows/tests.yml | grep -cE '^  [a-z_-]+:$'
  sed -n '/^jobs:/,$p' .github/workflows/tests.yml | grep -oE '^  [a-z_-]+:$'
  # → 3, and exactly:  tests:  lockfile:  roadmap:

  # the precondition still holds on the live repo:
  gh api repos/noctua84/nescio-ai/branches/main/protection --jq '.required_status_checks.contexts'
  # → ["tests"]   -- if "roadmap" ever appears here, R9 must be revisited
  ```
  **QA scenario**: after merge to `main`, confirm the `roadmap` job runs on the push and that its
  log shows the five reconciliation checks reporting clean. Then open a throwaway PR touching only a
  comment and confirm the `roadmap` job is **skipped**, not run — that is the `critic` HIGH being
  fixed, and it is only visible on a real PR.

- [ ] **8. Documentation**

  **What to do**:
  - `README.md`: add a short subsection near the `verify_commit_position.py` block documenting the
    check, both invocations (`--offline` for contributors without `gh`, plain for the full
    reconciliation), the `0/1/2` exit meanings, and **that advisories print without failing**. Match
    the surrounding tone — matter-of-fact, no marketing.
  - `ROADMAP.md`: **bullet content is not to be changed by this task.** Edit only the legend
    paragraph, to (a) note the file is machine-checked by `scripts/check_roadmap_drift.py`, and (b)
    state the allow-list policy in one or two sentences — *this file lists planned features; an item
    appears here when a maintainer applies the `roadmap` label; bugs, plumbing, and housekeeping are
    tracked as issues but do not get a line; `parked`/`deferred` items are held, not dropped.* Link
    to `CONTRIBUTING.md` for the full criteria.
  - `CONTRIBUTING.md`: add a **"What goes on the roadmap"** subsection carrying the full criteria
    text from Task 10 verbatim (single source of wording, two rendering sites), plus one line under
    the existing check/test guidance: when you open or close an issue that carries the `roadmap`
    label, update `ROADMAP.md`; the `roadmap` CI job will tell you if you forgot.

  **Files**: `README.md`, `ROADMAP.md` (legend paragraph only), `CONTRIBUTING.md`

  **Acceptance criteria**:
  ```bash
  # No bullet was touched by THIS task.  Compare against the post-Task-0b tree, not origin/main,
  # since 0b legitimately removed bullets:
  git diff HEAD -- ROADMAP.md | grep '^[-+]- '   # → empty
  git diff HEAD -- ROADMAP.md | grep -c '^+'     # → small (the legend sentences only)

  grep -c "roadmap" CONTRIBUTING.md                            # → ≥1
  grep -c "What goes on the roadmap" CONTRIBUTING.md           # → 1
  grep -c "check_roadmap_drift" README.md ROADMAP.md           # → ≥1 each
  PYTHONPATH=scripts python scripts/check_roadmap_drift.py --offline; echo "exit=$?"   # → 0
  ```

### Wave 5

- [ ] **9. Live end-to-end verification**

  **What to do**: No new code. Prove the check does what it claims against the real repo.

  1. **Baseline:** `python scripts/check_roadmap_drift.py` → exit 0.
  2. **D1 — omission detection** (the actual failure mode, finding 1): delete a bullet for a
     `roadmap`-labelled issue from a **scratch copy**, run `--roadmap <scratch>`, confirm exit 1
     with *"labelled `roadmap` but not on the roadmap: #N"*. Restore.
  3. **D2 — closed-ref detection:** add a bullet for `#54` (verified closed) to the scratch copy,
     confirm exit 1 naming it as **closed**, distinctly from a not-found. Then add a bullet for
     `#83` (verified **merged PR**, not an issue) and confirm it reports *"not an open issue (not
     found, or is a pull request)"* — different wording, same exit.
  4. **D3 — advisory, not fatal:** add a bullet for an open issue that does **not** carry `roadmap`
     (e.g. one of the maintenance issues from T0). Confirm the advisory prints, names the
     `gh issue edit` remedy, and **exit is 0**. This is the single most important step in this
     task — it is the property the whole revision turns on.
  5. **D4 — the escape hatch:** confirm that the maintenance issues left unlabelled and unreferenced
     produce **no output at all** in the baseline run. This is what the old design would have
     hard-failed on, and what an outside bug report will hit on day one.
  6. **Tag rot detection:** retag a labelled issue's bullet to the wrong milestone tag in the
     scratch copy, confirm exit 1 naming the expected milestone.
  7. **PR-filter live proof:** temporarily assign an open PR to milestone 1 via
     `gh pr edit <n> --milestone "Loop integrity"`, re-run, confirm **still exit 0**, then
     `gh pr edit <n> --remove-milestone`. This is the only way to prove the #60 gotcha is actually
     handled against the live API. **Ask before mutating repo state** — if that is not acceptable,
     the Task 6 unit regression stands as the proof and this step is skipped and recorded as
     skipped.
  8. **Degradation:**
     ```bash
     PY=$(command -v python); PATH=/nonexistent PYTHONPATH=scripts "$PY" scripts/check_roadmap_drift.py; echo "exit=$?"
     ```
     → exit 2, reason named, no traceback. (The naive form without `PY=$(command -v python)` exits
     127 and proves nothing — see the Verification strategy note.)

  **Files**: none modified. Use the scratchpad for scratch copies; `ROADMAP.md` is never edited
  during this task.

  **Acceptance criteria**: all eight steps produce the stated exit codes, recorded in the PR
  description as a verification log. Step 7 either passes or is explicitly marked skipped with its
  reason.

---

## Explicitly NOT covered

- **Auto-fixing `ROADMAP.md`.** No PR-opening, no marked block, no write path of any kind. The
  script is read-only against every file it inspects. Shapes A and C are rejected, not deferred.
  (Task 0b's amendment is a one-time human editorial act, not a code path.)
- **Auto-applying the `roadmap` label.** Neither the script nor the issue template applies it. It is
  a maintainer triage decision, and GitHub's permission model already enforces that (finding 12).
  Auto-stamping it from a public template would let any outside contributor force a roadmap line.
- **Promoting D3 to a hard failure.** Deliberately advisory (§ *Direction semantics*). Promotion is
  a follow-up gated on evidence that the advisory is being ignored, not a speculative tightening.
- **Verifying README's roadmap *prose*.** README's summary carries no enumerable state; the guard
  prevents it from acquiring any (Task 5), but "is this paragraph still an accurate
  characterisation" stays a human judgement. Named as a limitation.
- **Bullet text vs. issue title agreement.** Deliberate — the divergence is the editorial value (see
  the #53/#72/#59 examples). Checking it would manufacture failures for correct prose.
- **The legend-paragraph tag check.** Cut in revision 2. Matching backticked tags against
  hand-written prose is the brittleness already rejected for README.
- **Section placement.** Whether an item belongs under *Ergonomics* or elsewhere is editorial. The
  check verifies membership and tags, not taxonomy.
- **Enforcing that maintainers file through the issue form.** Not possible — `gh issue create`
  bypasses templates, and 11 of 31 current issues prove it happens routinely. The allow-list is
  designed not to depend on the template.
- **A keepalive workflow against 60-day cron auto-disable.** Noted as a limitation with
  `workflow_dispatch` as the manual remedy. Not engineered around on zero evidence of inactivity.
- **`CHANGELOG.md` and `docs_site/`.** Neither duplicates issue-set state; out of scope.
- **Closed-issue archival.** The check reports a closed issue still listed; it does not decide
  whether it should move to *Shipped* or be deleted. Human call.
- **Issue-opening or commenting on drift.** A failing job plus GitHub's own notification is the
  reporting mechanism. No extra token scope, no bot identity.
- **Rate-limit backoff beyond R4's single retry.** A handful of requests per run against a 1000/hr
  budget does not justify more machinery. If it ever becomes flaky, that is a follow-up issue with
  evidence, not speculative complexity now.
- **The milestone-placement question #60 raises about itself.** A triage call for the maintainer —
  though note the check passes either way, since untagged is legal.

---

## Success criteria

1. **The owner has approved the Task 0 classification table**, and every issue classified *planned*
   carries the `roadmap` label while no issue classified *maintenance* does.
2. If any entry was reclassified as maintenance, **`07779cb` is amended** (still exactly one commit
   ahead of `origin/main`), not stacked with a corrective commit.
3. `PYTHONPATH=scripts python -m unittest discover -s tests -v` is green, **and stays green under
   `PY=$(command -v python); PATH=/nonexistent PYTHONPATH=scripts "$PY" -m unittest discover -s
   tests -v`** — no network, no `gh`.
4. `python scripts/check_roadmap_drift.py` exits 0 against `ROADMAP.md` and `README.md`.
5. **An open issue that is neither labelled `roadmap` nor referenced in the file produces no
   finding of any severity** — the outside-bug-report escape hatch, proven by a named unit test and
   by Task 9 step 5.
6. **A referenced-but-unlabelled issue prints an advisory and exits 0** — proven by a named unit
   test and by Task 9 step 4.
7. Deleting any single `roadmap`-labelled bullet from a scratch copy produces exit 1 naming the
   omitted issue — finding 1's omission class is provably caught.
8. A milestoned PR does not produce a finding — #60's gotcha is handled, with a named unit
   regression test.
9. A multi-page issue response is accumulated correctly — the `--paginate` defect cannot recur,
   with a named unit regression test.
10. A bullet whose prose contains a bare `#N` or a second `[#N](url)` link produces no finding, and
    the load-bearing-anchor comment is present in the source.
11. `gh` unavailable produces exit 2 with a named reason and no traceback; `--offline` never
    produces exit 2.
12. **`ROADMAP.md`'s surviving bullets are byte-identical to their pre-plan state** — no bullet was
    *rewritten*; the only bullet-level change permitted is Task 0b's owner-approved *removals*. The
    editorial voice is provably untouched.
13. `.github/workflows/tests.yml` has a `roadmap` job with read-only permissions, no
    `continue-on-error`, `push`/`pull_request`/`schedule`/`workflow_dispatch` triggers, and a
    job-level `if:` that **skips it on `pull_request`**.
14. `main`'s required status checks are still exactly `["tests"]` — the `roadmap` job was not added
    to them, and the workflow comment records why that matters.
15. `.github/ISSUE_TEMPLATE/` contains two issue **forms** and a `config.yml`, no `.md` templates,
    and **neither form stamps the `roadmap` label**.
16. The "what earns a roadmap line" criteria appear in the feature-request form, `CONTRIBUTING.md`,
    and (condensed) `ROADMAP.md`'s legend.
17. `scripts/check_roadmap_drift.py` has a matching `tests/test_roadmap_drift.py`, satisfying the
    repo's one-test-per-script convention.
