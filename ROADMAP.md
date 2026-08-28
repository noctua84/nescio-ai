# Roadmap

Where Nescio is going. This is **directional, not dated** — priorities shift, and
"I don't know when" is a valid answer here too. Each item links a tracking issue;
the [open issues](https://github.com/noctua84/nescio-ai/issues) are always the
source of truth.

Tags map an item to a [milestone](https://github.com/noctua84/nescio-ai/milestones):
`loop`, `readiness`, `cross-repo`. `parked` means the *Parked* milestone —
deliberately held, for one of three distinct reasons (blocked on evidence, blocked
on tooling that isn't built yet, or a taste call to revisit later), so check the
issue before assuming which. Held is **not** neglected. Untagged items aren't
milestoned yet.

## Shipped

Capabilities, not releases — this section is deliberately coarse so it doesn't
need rewriting every time a version goes out.

- The crew + lifecycle (triage → discover → analyze → plan → execute → verify → deliver).
- Principled refusal and the pre-build `critic` red-team pass.
- A dedicated implementer (`builder`) and the Delivery Boundary Check that routes
  work to it, so deciding *what* to build stays separate from building it.
- The learning loop's core: session-trail capture (Stop hook), `/harvest-memory`
  distillation, human-gated promotion into version-controlled `memory/`, and
  harvest-aware pruning so un-harvested learnings can't age out.
- A write path through that loop you can actually trust: a harvest watermark, a
  promotion receipt, and stamp rollback when a promotion doesn't land
  ([ADR 0003](memory/repo/nescio/adr/0003-learning-loop-write-path-verified.md)).
- Repo-readiness assessment (`assess_repo_readiness`) and the SessionStart harvest nudge.
- Readiness computed deterministically from the learning trail
  (`scripts/compute_readiness.py`) — a measured signal, not a self-report.
- Overlay-sync for downstream instances (`sync_from_upstream`, with a `--diff` preview).
- A dependency-free, cross-platform installer that deep-merges into your existing
  Claude config, adopts **just the parts you want** (`--settings agent,plugins`),
  and never destroys a working setup.
- A documentation site (`docs_site/`, with the agent catalogue generated from
  frontmatter) and a brand package (`brand/`).

Per-release detail lives in [CHANGELOG.md](CHANGELOG.md).

## Learning loop & memory — [Epic #43](https://github.com/noctua84/nescio-ai/issues/43)

The memory subsystem, end to end: capture → harvest → promote → generalize → measure.

- `loop` [#53](https://github.com/noctua84/nescio-ai/issues/53) — learning-log: retain full promotion history as a generalization dataset (retire the 150-line compaction)
- `cross-repo` [#10](https://github.com/noctua84/nescio-ai/issues/10) — cross-repo generalization tier (learning-path step 2)
- `cross-repo` [#11](https://github.com/noctua84/nescio-ai/issues/11) — knowledge ingest + query + capture bridge (step 3)
- `cross-repo` [#34](https://github.com/noctua84/nescio-ai/issues/34) — learning-store bridge: CI review-learnings ↔ brain (phase 2.2)
- `readiness` [#35](https://github.com/noctua84/nescio-ai/issues/35) — confidence-decay & re-validation for stale promoted memory
- `parked` [#36](https://github.com/noctua84/nescio-ai/issues/36) — diversity-weighted promotion + same-condition inversion
- `parked` [#38](https://github.com/noctua84/nescio-ai/issues/38) — consolidation cadence: scheduled "sleep" reflection over memory
- `readiness` [#40](https://github.com/noctua84/nescio-ai/issues/40) — orchestrator PR-observation retro + automatic harvest
- `readiness` [#70](https://github.com/noctua84/nescio-ai/issues/70) — derive a clean-vs-flagged session verdict from the transcript, replacing `readiness.md`'s insufficient-data state
- `loop` [#2](https://github.com/noctua84/nescio-ai/issues/2) — wiki-engine lint hygiene follow-ups
- `parked` [#41](https://github.com/noctua84/nescio-ai/issues/41) — evaluate Obsidian as a read-only view over `memory/`

## Earned autonomy — [Epic #33](https://github.com/noctua84/nescio-ai/issues/33)

Unattended action is deliberately **not** on by default. It's gated behind a
readiness signal the learning loop produces, and rolled out per-repo.

- `parked` [#32](https://github.com/noctua84/nescio-ai/issues/32) — earned per-repo autonomy dial + charter evolution (phase 3)
- `parked` [#39](https://github.com/noctua84/nescio-ai/issues/39) — mid-task checkpoint / resume (+ fork) for the orchestrator lifecycle
- `parked` [#37](https://github.com/noctua84/nescio-ai/issues/37) — a gradual "Confidence & gaps" signal on specialist agents

## Interoperability

- [#29](https://github.com/noctua84/nescio-ai/issues/29) — adapter layer so the crew can also drive OpenAI Codex CLI (hooks / agents / skills / MCP)

## Installer & onboarding

- **A2 — section-level `CLAUDE.md` import** (`CLAUDE.d/`) — adopt individual instruction sections, not the whole brief. *(Planned; spec drafted.)*
- **Layer B — LLM-assisted config reconciliation** — a post-install skill that reads your existing `settings.json`/`CLAUDE.md` and the framework's and proposes a *conscious merge*, flagging conflicts instead of clobbering. The differentiator. *(Planned; explored.)*

## Ergonomics & workflow

- `loop` [#59](https://github.com/noctua84/nescio-ai/issues/59) — dispatch template: branch from the fetched remote ref (the detached-HEAD guard itself has shipped; this is the remaining follow-up)
- `loop` [#52](https://github.com/noctua84/nescio-ai/issues/52) — review pipeline: parity check vs downstream + close the `claude-code-action` freshness gap
- `loop` [#60](https://github.com/noctua84/nescio-ai/issues/60) — automatic drift check: reconcile this file against open issues + milestones
- [#58](https://github.com/noctua84/nescio-ai/issues/58) — a `postmortem` skill for multi-repo incident write-ups
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
