# Roadmap

Where Nescio is going. This is **directional, not dated** — priorities shift, and
"I don't know when" is a valid answer here too. Each item links a tracking issue;
the [open issues](https://github.com/noctua84/nescio-ai/issues) are always the
source of truth.

## Shipped in 1.0

- The crew + lifecycle (triage → discover → analyze → plan → execute → verify → deliver).
- Principled refusal and the pre-build `critic` red-team pass.
- The learning loop's core: session-trail capture (Stop hook), `/harvest-memory`
  distillation, human-gated promotion into version-controlled `memory/`, and
  harvest-aware pruning so un-harvested learnings can't age out.
- Repo-readiness assessment (`assess_repo_readiness`) and the SessionStart harvest nudge.
- Overlay-sync for downstream instances (`sync_from_upstream`, with a `--diff` preview).
- A dependency-free, cross-platform installer that deep-merges into your existing
  Claude config, adopts **just the parts you want** (`--settings agent,plugins`),
  and never destroys a working setup.

## Learning loop & memory — [Epic #43](https://github.com/noctua84/nescio-ai/issues/43)

The memory subsystem, end to end: capture → harvest → promote → generalize → measure.

- [#42](https://github.com/noctua84/nescio-ai/issues/42) — compute `readiness.md` deterministically from the learning-trail (2.1a)
- [#10](https://github.com/noctua84/nescio-ai/issues/10) — cross-repo generalization tier (learning-path step 2)
- [#11](https://github.com/noctua84/nescio-ai/issues/11) — knowledge ingest + query + capture bridge (step 3)
- [#34](https://github.com/noctua84/nescio-ai/issues/34) — learning-store bridge: CI review-learnings ↔ brain (phase 2.2)
- [#35](https://github.com/noctua84/nescio-ai/issues/35) — confidence-decay & re-validation for stale promoted memory
- [#36](https://github.com/noctua84/nescio-ai/issues/36) — diversity-weighted promotion + same-condition inversion
- [#38](https://github.com/noctua84/nescio-ai/issues/38) — consolidation cadence: scheduled "sleep" reflection over memory
- [#40](https://github.com/noctua84/nescio-ai/issues/40) — orchestrator PR-observation retro + automatic harvest
- [#2](https://github.com/noctua84/nescio-ai/issues/2) — wiki-engine lint hygiene follow-ups
- [#41](https://github.com/noctua84/nescio-ai/issues/41) — evaluate Obsidian as a read-only view over `memory/`

## Earned autonomy — [Epic #33](https://github.com/noctua84/nescio-ai/issues/33)

Unattended action is deliberately **not** on by default. It's gated behind a
readiness signal the learning loop produces, and rolled out per-repo.

- [#32](https://github.com/noctua84/nescio-ai/issues/32) — earned per-repo autonomy dial + charter evolution (phase 3)
- [#39](https://github.com/noctua84/nescio-ai/issues/39) — mid-task checkpoint / resume (+ fork) for the orchestrator lifecycle
- [#37](https://github.com/noctua84/nescio-ai/issues/37) — a gradual "Confidence & gaps" signal on specialist agents

## Interoperability

- [#29](https://github.com/noctua84/nescio-ai/issues/29) — adapter layer so the crew can also drive OpenAI Codex CLI (hooks / agents / skills / MCP)

## Installer & onboarding

- **A1 — per-part settings adoption** — merge just the parts you want. *(In review.)*
- **A2 — section-level `CLAUDE.md` import** (`CLAUDE.d/`) — adopt individual instruction sections, not the whole brief. *(Planned; spec drafted.)*
- **Layer B — LLM-assisted config reconciliation** — a post-install skill that reads your existing `settings.json`/`CLAUDE.md` and the framework's and proposes a *conscious merge*, flagging conflicts instead of clobbering. The differentiator. *(Planned; explored.)*
- [#19](https://github.com/noctua84/nescio-ai/issues/19) — decide on the empty scaffolding dirs (adopt as a memory tier, or drop)

## Ergonomics & workflow

- [#20](https://github.com/noctua84/nescio-ai/issues/20) — heavyweight `/pr-review` multi-agent fan-out (opt-in)
- [#21](https://github.com/noctua84/nescio-ai/issues/21) — optional machine-local statusline (model / context / repo / PR / work-item)
- [#22](https://github.com/noctua84/nescio-ai/issues/22) — optional headless GitHub Action to auto-run `dependency-pr-ci-fix` on a red bump PR

## Under consideration

- **Crew benchmarking** — turn the shipped evaluation skills (`agent-evaluation`,
  `prompt-evaluation-harness`) inward: a fixed scenario suite scored by an
  LLM-as-judge, measuring routing correctness, `critic` catch-rate, and
  refusal-when-appropriate. Not yet tracked as an issue.

---

*Want something prioritized, or think a direction is wrong? Open an issue — challenging the plan is on-brand here.*
