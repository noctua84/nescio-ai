# Roadmap

Where Nescio is going. This is **directional, not dated**. Each item links a
tracking issue; the [open issues](https://github.com/noctua84/nescio-ai/issues)
are always the source of truth.

Tags map an item to a [milestone](https://github.com/noctua84/nescio-ai/milestones):
`loop`, `readiness`, `cross-repo`. `parked` means the *Parked* milestone —
deliberately held. Untagged items aren't milestoned yet.

## Learning loop & memory — [Epic #43](https://github.com/noctua84/nescio-ai/issues/43)

The memory subsystem, end to end: capture → harvest → promote → generalize.

- `loop` [#53](https://github.com/noctua84/nescio-ai/issues/53) — learning-log: retain full promotion history as a generalization dataset
- `readiness` [#35](https://github.com/noctua84/nescio-ai/issues/35) — confidence-decay & re-validation for stale promoted memory
- `cross-repo` [#10](https://github.com/noctua84/nescio-ai/issues/10) — cross-repo generalization tier (learning-path step 2)
- [#29](https://github.com/noctua84/nescio-ai/issues/29) — adapter layer so the crew can also drive OpenAI Codex CLI
- **A2 — section-level `CLAUDE.md` import** (`CLAUDE.d/`) — adopt individual instruction sections, not the whole brief. *(Planned; spec drafted.)*
