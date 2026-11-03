---
name: readiness is uncomputable here — memory/repo/nescio vs trail key nescio-ai
description: the naming mismatch that makes compute_readiness skip this repo entirely
type: context
---
<!-- promoted:begin -->
`scripts/compute_readiness.py` keys each repo off the **learning-trail basename**, which for this repo is `nescio-ai`. The repo's own memory lives at `memory/repo/nescio/`. The script never creates directories, so it reports:

    skip nescio-ai  (no memory/repo/nescio-ai/ — skipped; directories are never created)

So step 8 of `/harvest-memory` — update readiness — **cannot run for the repo the skill most often runs in.** There is no `readiness.md` under `memory/repo/nescio/` and none will be generated.

This is a live inconsistency, not a quirk to route around. The filing convention is deliberate and documented: ADR 0005's own reasoning is that `memory/repo/<name>/` is repo-scoped, so `memory/repo/nescio/adr/0005` declares itself a decision *about* `nescio-ai`. The short name `nescio` was chosen; the trail key is derived from the clone directory name and is not.

Fixing it means picking one: rename `memory/repo/nescio/` to `nescio-ai/` (touches every ADR cross-reference and the ADR index), or give `compute_readiness.py` an explicit alias map. Do not "fix" it by creating an empty `memory/repo/nescio-ai/` — that splits one repo's memory across two directories, which is worse than the skip.

Related: `repo-registry.toml` is absent from this repo, which is the suite's one remaining skip.
[Source: empirical — 2026-11-02]
<!-- promoted:end -->
