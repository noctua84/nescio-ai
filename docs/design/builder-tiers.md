# Builder tiers: one contract, three models

> Status: implemented with `scripts/render_tiers.py`. The tier-specific sections
> listed under "Recommendation" are approved and live in the template.

## The question

The three builder charters (`builder` on Opus, `builder-standard` on Sonnet,
`builder-simple` on Haiku) were ~230-line copies. A prompt audit flagged the
duplication. The fix chosen was to keep three agent names, because routing,
telemetry and evals key on them, and to generate the three files from one
source. That raised a prior question: should the three briefs be identical at
all, or should each be tuned to its model?

## What the orchestrator relies on

`agents/orchestrator.md` (Per-Task Dispatch) states the design the tiers serve:

- The tiers "carry an **identical contract**: same method, same verification
  bar, same output block, same anti-patterns. They differ only in the model they
  run on." Over-tiering is therefore a cost mistake, never a quality one.
- "When in doubt between two tiers, choose the **lower** one; the escalation
  path below is cheap and exists precisely to catch a mis-tier."
- `BLOCKED` is routed by its content: a missing decision or fact goes to the
  user, difficulty goes one tier up, and from `builder` difficulty also goes to
  the user.
- After each wave it parses the report: the `COMPLETE` / `PARTIAL` / `BLOCKED`
  verdict, the `Inverted pin:` and `Deferred red:` labels in `<deviations>`,
  and the `<out-of-scope>` and `<deviations>` lists it carries to delivery.

`tests/test_agent_definitions.py` pins the same design. `TestBuilderTierParity`
requires byte-identical text from `## Your Purpose` onward and identical
frontmatter apart from `name`, `description` and `model`. Its effort test says
why `effort` stays out of the per-tier set: "The tiers are a cost ladder, not a
rigour ladder." A lower effort on `builder-simple` would make a mis-tier cost
quality as well as money, and no reader of the charters could see it.

## The contract: identical in every tier

Everything from `## Your Purpose` to the end of the file:

| Part | Why it can't vary |
|---|---|
| You DO / You DO NOT | Defines what a `BLOCKED` means. Escalation assumes the next tier blocks on the same things. |
| Method steps 1–7: orientation, blast-radius search, test first, implement, verify, commit prefixes, report | This is the verification bar. Step 5 produces the `Inverted pin:` and `Deferred red:` labels the orchestrator confirms with the user. |
| Output Contract block (`<verdict>`, `<changed>`, `<blast-radius>`, `<verification>`, `<module-check>`, `<deviations>`, `<out-of-scope>`) | Parsed by the orchestrator after every wave. |
| Verdict definitions | Both `BLOCKED` branches (missing decision, harder than this tier) are what the routing rule switches on. |
| Anti-patterns | The "same anti-patterns" in the orchestrator's promise. |

These frontmatter fields are also shared: `tools`, `effort`, `autoCompactWindow`.

## Per-tier assessment

### Could `builder-simple` use a shorter brief with an explicit step list?

**No to shorter. Yes to one small addition.**

- The brief is already a numbered step list (Method 1–7). The sections that look
  like judgment work, such as the blast-radius search, red-test attribution and
  the pin rule, are the verification bar and feed labels the orchestrator
  parses. Taking them out of the Haiku tier breaks "identical contract".
  Escalation would then hand `standard` a task whose first attempt was checked
  to a lower bar.
- Simple-tier tasks are often broad mechanical changes, such as a rename across
  many files. Those have the widest blast radius in the crew, so the readers
  and callers search matters most here.
- No eval in this repo compares a shortened Haiku brief with the full one. The
  only Haiku data on record, in CONTRIBUTING's effort notes, is about effort,
  not brief length. Cutting the brief would rest on a general belief about
  small models, not on evidence.

**Addition: stop signals.** The routing policy sends doubtful tasks to the
cheapest tier on purpose and counts on that tier to block early. The charter
gave Haiku only the abstract test "proves harder than this tier". The added
section turns the orchestrator's own classification question ("does this task
require a decision the plan … [has] not already settled?") into four concrete
checks. It also says these are *difficulty* blocks, not missing decisions.
Without that, an unsettled local choice reported by `builder-simple` reads as a
missing decision, and the orchestrator's routing table sends it to the user
instead of one tier up.

### Does `builder` (Opus) need guidance the others don't?

**Yes, because the shared text contradicts the tier's own definition.** The
orchestrator classifies a task as `complex` when it needs "an architectural
decision, cross-system impact, genuine ambiguity about what correct means, or a
new pattern with no precedent". The shared DO NOT list tells the same agent
that a task needing a design decision "returns `BLOCKED`", and so does
resolving ambiguity. Read literally, every correctly tiered `complex` task
should block on arrival.

**Addition:** a section that says which decision the tier was sent to make
(a pattern with no precedent, the shape of a cross-module change), and that it
should make it within scope and record it in `<deviations>` as
`Design choice:` with the rejected alternative. It also says what still blocks:
what to build, any interface or contract outside the plan's scope, and
ambiguity about what correct means. That last case stays with the user, which
matches the shared rule. `standard` gets the same section scoped to local
choices, because the orchestrator sends it tasks with "one or two *local*
decisions" and the same DO NOT list applies.

The `Design choice:` entries change no contract field. They go in the existing
`<deviations>` section, which the orchestrator already collects and carries to
delivery. Its two special labels (`Inverted pin:`, `Deferred red:`) are
unaffected.

### `effort` and `autoCompactWindow`

- **`effort`: keep identical (`high`).** The tests and the orchestrator both
  rely on the tiers being a cost ladder, as quoted above.
- **`autoCompactWindow`: keep identical (`400000`).** All three models have a
  1M-token context window (CONTRIBUTING records `claude-haiku-5-5` reporting
  `contextWindow: 1000000`), so the one value means the same on each.
- **Option, not implemented:** Haiku 5.5 input above 100K tokens is billed at
  5x the base rate ($0.50 vs $0.10 per MTok). Compacting `builder-simple` at
  `100000` would avoid that tier of pricing for API-billed runs. The cost of
  doing so, losing context mid-task on a tier whose tasks are usually short, has
  not been measured. The generator already supports per-tier frontmatter if
  this is wanted later. `TestBuilderTierParity` would need to add
  `autoCompactWindow` to its per-tier identity set.

## Recommendation

1. Generate the three charters from `agents/_src/tiers.md.tmpl` (done). Every
   edit to the shared contract lands once.
2. Allow tier-specific text only above `## Your Purpose`: frontmatter identity,
   the tier paragraph, and the sections below. `tests/test_render_tiers.py`
   enforces this in the template, and `TestBuilderTierParity` enforces it on
   the committed files.
3. Add these tier-specific sections (approved):
   - `builder-simple`: **Say early when a task is not `simple`.** Four stop
     signals, routed as *harder than this tier*.
   - `builder-standard`: **Make the decisions you were dispatched to make.**
     Local choices: make them and record them as `Design choice:`. A
     cross-module interface change blocks as harder than this tier.
   - `builder`: **Make the decision you were dispatched to make.** Design
     choices within scope, recorded as `Design choice:`. What to build,
     out-of-scope contracts and ambiguity about what correct means still block.
4. Keep `effort` and `autoCompactWindow` shared.

## Follow-up outside this change

The orchestrator's `complex` row includes "genuine ambiguity about what correct
means". The builder contract sends that case to the user. One of the two should
change so they agree: drop it from the row, or say it means ambiguity the plan
asks the implementer to resolve. This change leaves `agents/orchestrator.md`
alone, because a concurrent branch is editing it.

## How the generator works

- `agents/_src/tiers.md.tmpl` holds the source with functional names. A
  `<!-- tier: a b -->` marker opens a block kept only for the named tiers, the
  next `tier:` marker or `<!-- end tier -->` closes it, and `<!-- note: -->`
  lines are dropped. Text outside blocks reaches every tier.
- `python scripts/render_tiers.py` writes the charters, and `--check` exits 1 if
  any is stale. On a philosopher-themed tree it renames through
  `apply_theme.theme_text` and writes `archimedes*.md`. The output is the same
  bytes that `apply_theme.py`, and so the sync script, produce from the
  functional charter.
- The template stays functional in a themed instance. `apply_theme.py` rewrites
  only top-level `agents/*.md`, and the sync copies `agents/` recursively, so
  `_src/` arrives unchanged. The template and the script are named without the
  word `builder`, so the theme rename never rewrites the path that the
  generated frontmatter comment points at.
