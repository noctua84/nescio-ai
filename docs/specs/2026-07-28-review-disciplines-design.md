# Review disciplines — ref-pinning + confidence tags for `reviewer`

Status: draft — awaiting review

> Adapted (idea only, written fresh) from a generic multi-agent PR-review pattern.
> Two disciplines fold into the single `reviewer` agent; the heavier status-first
> synthesis and incremental re-review live with the opt-in fan-out (#20).

## Purpose

Sharpen `agents/reviewer.md` with two review disciplines that operationalize
nescio's existing (but softer) evidence ethos:

1. **Head-ref-only ref-pinning** for PR review — never read the default branch
   "for context," which contaminates a review with fixes that landed *after* the
   PR.
2. **Confidence tags** (`[VERIFIED]` / `[INFERRED]` / `[UNVERIFIED]`) with a
   **verbatim-quote-per-citation** rule — every finding declares how well it's
   evidenced, and every `file:line` carries a quote of that line.

Scope is deliberately narrow: `reviewer.md` only. Status-first synthesis and
incremental stability-bar are multi-agent/re-review concerns owned by the fan-out
issue (#20).

## Why this design

- **It's a sharpening, not a bolt-on.** `reviewer` already says "every finding
  must have evidence — a file, a line, a trace," "mark 'Needs Investigation' if
  unconfirmed," and "never assume behavior from names." Confidence tags make that
  a fixed vocabulary; the quote rule makes "a line" mean *the actual quoted line*.
  This is nescio's principled-refusal ethos, operationalized.
- **Ref-pinning closes a real hole.** `reviewer`'s mission includes "a PR under
  review," but nothing stops it reading `main` mid-review and citing a post-merge
  fix as if the PR contained it — the single most common review-contamination
  failure. Pinning HEAD/BASE and forbidding default-branch reads removes it.
- **Weave in, don't restructure.** The rules land inside `reviewer`'s existing
  sections (Scope Definition, Report Format, Behavioral Guidelines), next to the
  methodology they sharpen — not as a bolt-on section that duplicates context.
- **Confidence is orthogonal to severity.** Keep CRITICAL/MAJOR/MINOR/INFO for
  *impact*; the tag conveys *how sure*. A finding can be CRITICAL and
  `[INFERRED]`; the reader treats those differently.

## The change — `agents/reviewer.md` only

### 1. Ref-pinning → §1 Scope Definition

Add a rule: when the audit target is a **PR**, resolve and pin the refs up front —
`HEAD_SHA` = `headRefOid`, `BASE_SHA` = `baseRefOid` (via `gh pr view --json
headRefName,headRefOid,baseRefName,baseRefOid`). Read code **only** at `HEAD_SHA`
or `BASE_SHA`.

> **Never read the default branch (`main`/`master`) or any other mutable ref
> "for context."** Default-branch reads contaminate the review with fixes that
> landed *after* the PR, producing confidently-wrong "already handled"
> conclusions. If you need context beyond the PR's two refs, record it as an
> `[UNVERIFIED]` open question — do not fetch it. Other/sibling files may be read
> only at a named commit SHA, never at a branch name.

For non-PR targets (worktree, landed commit range) the rule degrades naturally:
pin to the commit range under audit; don't wander to a moving branch.

### 2. Confidence tags + verbatim quote → Report Format + Behavioral Guidelines

Every finding carries a **Confidence** tag, defined in a new "Confidence
Definitions" block beside the existing "Severity Definitions":

- **`[VERIFIED]`** — you quoted a line at a named ref (`HEAD_SHA`/`BASE_SHA` or a
  pinned SHA) that proves the claim.
- **`[INFERRED]`** — you reasoned from quoted code to a downstream consequence you
  cannot directly quote. State the consequence.
- **`[UNVERIFIED]`** — you could not reach the evidence (no access, unresolved
  transitive call, source not visible from the pinned refs). State what would
  resolve it.

Rules added to the finding template and Behavioral Guidelines:

- Every `file:line` citation MUST be accompanied by a **verbatim quote** of that
  line. A citation without a quote is not a finding — downgrade it to
  `[UNVERIFIED]`.
- **Never ship-block on an `[UNVERIFIED]` finding alone**; `[INFERRED]` findings
  are down-weighted relative to `[VERIFIED]`.
- The finding template gains a `**Confidence:** [VERIFIED|INFERRED|UNVERIFIED]`
  line alongside `**Severity:**`.

### 3. Reconcile the existing vocabulary

`reviewer`'s current bullet — *"If you cannot fully confirm an issue, mark it
'Needs Investigation' and state what additional information would resolve it"* —
is folded into `[UNVERIFIED]` so there is **one** vocabulary, not two overlapping
ones. The "No material issues found is legitimate" and "never manufacture
findings" bullets stay — they're the same ethos and reinforce the tags.

Everything else in `reviewer.md` is unchanged.

## Testing

Prompt/markdown — no `pytest` surface (consistent with the `critic` and
`code-navigation` specs). Two layers:

- **Mechanical:** `reviewer.md` contains the ref-pinning rule (HEAD/BASE pinning +
  the "never read default branch" prohibition) and the three confidence-tag
  definitions + the verbatim-quote rule. A grep-level check.
- **Behavioral (golden scenarios via `prompt-testing-plan` + `agent-evaluation`):**
  1. Reviewing a PR, the agent resolves HEAD/BASE and **never cites
     default-branch code**; a "this is handled upstream" claim it cannot quote at
     a pinned ref is tagged `[UNVERIFIED]`, not asserted.
  2. Every `file:line` in the report carries a verbatim quote.
  3. A reasoned-but-unquotable consequence is tagged `[INFERRED]` with the
     consequence stated.
  4. A report with only `[UNVERIFIED]` items does not gate a merge as BLOCKING.

  Behavioral, verified via the Task tool at VERIFY; not CI-asserted. Stated openly.

## Deliverables

- `agents/reviewer.md` — the two disciplines woven into §1, Report Format, and
  Behavioral Guidelines; "Needs Investigation" reconciled into `[UNVERIFIED]`.
- Issue #20 — a one-line note correction: ref-pinning + confidence tags come from
  this work; status-first synthesis + incremental stability-bar are #20's own.
- This spec; behavioral scenarios verified at VERIFY.

## Out of scope

- Status-first CLEAN/CONCERNS/BLOCKING synthesis and the multi-agent fan-out (#20).
- Incremental re-review with prior-review marker comments and the stability bar
  (#20).
- Propagating confidence tags to `critic` / `explore` (considered; deferred as
  YAGNI — reviewer is where PR/code evidence discipline bites hardest).
- Any change to the `secure-code-review` / `security-architecture-review` skills.

## Open risks / notes

- **Tag discipline is behavioral, not enforced.** Nothing mechanically rejects an
  untagged finding; the prompt makes it the default and the golden scenarios
  check it. Acceptable for a prompt-level agent (same limitation as every other
  nescio agent).
- **Ref-pinning depends on `gh`.** When reviewing a local worktree rather than a
  GitHub PR, "pin the refs" means the commit range under audit; the rule is
  written to degrade to that, not to hard-require `gh`.
