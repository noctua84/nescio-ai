---
name: nescio-adr-0006-lint-suppressions-are-documentation
description: E402 is deliberately not enforced and the sys.path.insert-then-import pattern is recorded here once; a `# noqa` carrying prose rationale is documentation before it is a directive, so RUF100 is never cleared with `ruff --fix`.
type: adr
status: proposed
---

# ADR 0006: Lint suppressions are documentation, and the gate may not delete documentation

## Status

Proposed. Supersedes nothing.

**Reconciles with [ADR 0001](0001-no-agent-frameworks-in-nescio.md)**, which keeps
the runtime install path dependency-free — see *Is a linter a dependency?* below.
Touches a structure established by
[ADR 0003](0003-learning-loop-write-path-verified.md) (`_trail_scope.py` and its
re-exports) without changing it.

Tracked as [#175](https://github.com/noctua84/nescio-ai/issues/175); arises from
the static-analysis rollout in [#162](https://github.com/noctua84/nescio-ai/issues/162),
[#171](https://github.com/noctua84/nescio-ai/issues/171) and
[#174](https://github.com/noctua84/nescio-ai/issues/174).

## Context

A ruff gate is being added to `.github/workflows/tests.yml` one rule family per
PR. Phase 1 selected `E9,F63,F7,F82` (0 findings, green on day one); phase 2
collapsed that to `["E9", "F"]`. The ruleset is authoritative in `pyproject.toml`
and the job reads it rather than repeating `--select`, so a local run and CI
cannot diverge.

`#162` planned `RUF100` (unused-noqa) as the next, cheapest, "mechanical" phase:
delete the stale directives, 93 of them, all auto-fixable. **That plan is wrong,
and measuring it is what shows why.** Against phase 2's config:

```
$ uvx ruff@0.16.10 check --extend-select RUF100 --statistics .
115  RUF100  [*] unused-noqa
```

| Count | Code the dead directive names | Sites |
|---|---|---|
| **103** | `E402` module-import-not-at-top-of-file | 57 files |
| 6 | `BLE001` blind-except | 3 files |
| 3 | `PLC0415` import-outside-top-level | |
| 1 each | `S310`, `ANN001`, `E731` | |

A `# noqa` is "unused" when the rule it names is not selected. So `RUF100`'s
count is **not a backlog of stale cruft** — it is a list of the places where this
repository wrote down a deliberate deviation for a rule the gate has not (yet)
turned on. `ruff check --fix` deletes all 115 without reading them.

### The two patterns at stake

**1. `sys.path.insert(...)` then import — 103 markers.** The framework is
stdlib-only and has no installed package, so a script or test reaches its
siblings by putting the directory on `sys.path` first and importing after:

```python
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import install_github_action as gha  # noqa: E402
```

These 103 markers are **homogeneous**. Every one says the same thing, and the
reason is reconstructible from the `sys.path.insert` three lines above it. Their
information density is near zero *per site*; what matters is that the pattern is
recorded **once**, somewhere a reader will find it.

**2. Deliberate broad `except` — 6 markers.** These are the opposite: each
carries its own distinct, non-reconstructible reason.

| Site | Inline rationale |
|---|---|
| `scripts/promote_learnings.py:687` | reindex is best-effort |
| `scripts/repo_hygiene_scan.py:245`, `:265`, `:325` | one bad row → needs-review, not abort |
| `scripts/repo_hygiene_scan.py:503` | deliberate: guarantee exit 0 |
| `tests/test_roadmap_drift.py:1577` | the assertion is "never" |

`repo_hygiene_scan.py:503` is load-bearing in the same way the `roadmap` job's
exit codes are: it guarantees exit 0 so a scan failure cannot red a build it was
never meant to gate. Nothing outside that comment says so. Delete the comment and
the next reader sees an unexplained bare `except Exception` and tidies it into a
narrow one, and the guarantee is gone.

### Selecting the rule is not a general escape

The obvious way to keep a marker is to select the rule it names, which makes the
suppression live. Phase 2 already did this by accident and it worked: selecting
`F` turned the four `# noqa: F401` re-export markers into real suppressions —
including `scripts/compute_readiness.py:97`, which re-exports `_trail_scope`'s
scoping helpers because ADR 0003 put them there and callers import them through
this module. One directive there covers two names, which is why four directives
account for five findings.

But that only works where the rule is cheap to turn on. Measured:

| Code | Markers preserved | Unsuppressed findings if selected |
|---|---|---|
| `S310` | 1 | 1 |
| `E731` | 1 | 2 |
| `E402` | 103 | 3 |
| `BLE001` | 6 | **9** |
| `PLC0415` | 3 | **29** |
| `ANN001` | 1 | **354** |

Selecting `ANN001` to save one comment would import 354 findings. The mechanism
does not generalise, so a rule is needed that does.

### Is a linter a dependency?

ADR 0001 keeps `[project] dependencies` empty and protects a precise property:
*clone, run `install.py`, working system — no virtualenv, no dependency
resolution.* A reader could reasonably ask whether a linter violates it.

It does not, and the reasons should be on the record rather than rediscovered:

- ruff runs **only in CI**, invoked as `uvx ruff@0.16.10`. Nothing in the
  framework imports it, and no installed artefact gains a dependency.
- It was deliberately **not** added to `[dependency-groups]`. That would have
  rewritten `uv.lock`, which release-please owns and the `lockfile` job checks,
  and would have put a linter in the dependency surface for no gain.
- `pyproject.toml` gains a `[tool.ruff.lint]` table only. `[project]
  dependencies` stays `[]`.

This is the same shape of reconciliation ADR 0005 made for the retrieval
service: the boundary (there a network call, here a CI-only tool) is what keeps
the decision compatible with ADR 0001 rather than a reversal of it. It should not
be collapsed later by "just adding ruff to the dev group" for convenience.

## Decision

**1. `E402` is not enforced, and the pattern it would flag is recorded here.**
The `sys.path.insert(...)`-then-import shape in `scripts/`, `tests/` and
`brand/` is intentional: it is how a stdlib-only, non-installed framework
reaches its own modules. `E402` is not selected, and is not expected to be. This
paragraph is the durable record those 103 inline markers were carrying.

**2. A `# noqa` that carries prose is documentation first and a directive
second.** When the directive goes inert, the prose survives. The marker is
rewritten to a plain comment, keeping the reason and dropping the dead
machinery:

```python
except Exception as exc:  # noqa: BLE001 - deliberate: guarantee exit 0
except Exception as exc:  # broad except, deliberate: guarantee exit 0
```

**3. `RUF100` is never cleared with `ruff --fix`.** Whenever it is enabled, it is
cleared by hand, per site, with each directive triaged into exactly one of:

- **select the rule** — where the rule is cheap to turn on and wanted anyway
  (the `F401` re-exports, already done in phase 2);
- **convert to a plain comment** — where the directive is inert but the prose is
  worth keeping (all 12 non-`E402` markers);
- **delete** — where the marker is homogeneous and its reason is recorded
  elsewhere (the 103 `E402` markers, whose reason is Decision 1).

**4. A rule is never selected for the purpose of silencing `RUF100`.** Turning on
`ANN001` to preserve one comment would be the tail wagging the dog. The rule's
own merits decide whether it is selected; `RUF100` never does.

## Options considered

| Option | Verdict |
|---|---|
| **Do nothing** — never select `RUF100` | Rejected, but it is the status quo and it is *safe*. 115 inert directives keep accumulating and teach each reader that a line was once flagged when it was not. The cost is confusion, not breakage, which is why this is a low-priority phase rather than a blocked one. |
| **`ruff check --fix --select RUF100`** | Rejected. Deletes all 115 markers unread, including the six distinct broad-`except` justifications and the `exit 0` guarantee. This is the option the "93, fixable" framing in #162 invites, and it is information loss presented as a lint fix. |
| **Select every code a marker names** | Rejected. Preserves all 115 markers at a cost of 9 + 29 + 354 + 1 + 2 + 3 = ~398 new findings, most of them `ANN001` annotations nobody asked for. Lets the suppression list dictate the ruleset. |
| **Select `E402`, keep its 103 markers** | Rejected by the repo owner: the pattern is deliberate and is not to be enforced. Worth recording that this option was *cheap* — only 3 unsuppressed findings — so if the decision is ever revisited, the cost is known and small. |
| **Hand-triage per site (chosen)** | Accepted. ~115 edits across ~60 files, mechanical but attentive, and lossless. |

## Consequences

**Negative, and the main cost:** clearing `RUF100` becomes a hand-written change
touching roughly 60 files instead of one `--fix` invocation. That is tedious, it
is harder to review than an auto-fix, and it is the reason this phase should come
last rather than first. A future session under time pressure will be tempted to
run `--fix` anyway; Decision 3 exists to be cited when that happens.

**Negative:** Decision 1 trades 103 local markers for one paragraph in a file
that lives outside the code. A reader looking at
`brand/make_brand.py:56` after the deletion sees an import that is not at the top
of the file and nothing at all explaining it. The record is more durable but less
discoverable, and that is a real loss, accepted deliberately.

**Negative:** `status: proposed`. Decision 1 encodes a preference about `E402`
that has been stated once. If the `sys.path.insert` pattern is ever replaced by
making the framework installable, Decision 1 becomes stale and this ADR needs
revisiting rather than quietly ignoring.

**Positive:** the six broad-`except` justifications, including the `exit 0`
guarantee at `scripts/repo_hygiene_scan.py:503`, survive a rule family being
enabled. That guarantee has the same character as the `roadmap` job's
deliberate exit-2 handling, which `.github/workflows/tests.yml` protects with a
comment of its own — the two should stay consistent.

**Positive:** the gate's ruleset is decided on each rule's merits rather than by
what happens to be suppressed, and `RUF100`'s count stops being mistaken for a
backlog.

**To re-verify:** every count here is a measurement against ruff 0.16.10 and the
phase 2 config, and all of them drift. `RUF100` was 93 when #162 was filed, 107
a day later, and 115 at the time of writing; `UP017` moved 55 → 57 and `I001`
22 → 26 over the same period. Re-measure with `--extend-select`, never
`--select`, which replaces the config and reported 119 for the same tree.
