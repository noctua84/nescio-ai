---
name: assess-repo
description: Read-only readiness scan of a target repo on two axes — brain memory depth and the repo's own AI-friendliness — producing the signal Phase 3's autonomy dial consumes.
user-invocable: true
---

# /assess-repo

The **read-only "freshman orientation" gate**. Before the brain works
autonomously in a repo, this scans how ready that repo is and reports it on two
axes. It writes nothing — to the target repo or anywhere — and executes nothing
in the target; detection is purely by filesystem presence.

## The two axes

- **Memory depth** — how much durable, version-controlled knowledge the brain
  already holds about this repo under `memory/repo/<name>/` (content notes +
  ADRs, excluding the `MEMORY.md` index). Levels: `none` / `thin` / `moderate` /
  `deep`. A repo the brain has never learned about is `none`.
- **AI-friendliness** — how much the *target repo itself* helps an agent work
  safely: tests, CI, typechecking, ADRs, `CLAUDE.md` conventions, and a project
  manifest. Levels: `high` / `medium` / `low`.

The combined signal is what **Phase 3's autonomy dial** reads to set this repo's
autonomy cap — richer memory and a more AI-friendly repo raise the cap.

## Invocation

```bash
python scripts/assess_repo_readiness.py [repo-path]     # markdown report
python scripts/assess_repo_readiness.py [repo-path] --json
```

`repo-path` defaults to the current directory. `--memory-root <path>` overrides
where the brain's `memory/` tree lives (defaults to this repo's `memory/`). The
report ends with a **What's missing** list of actionable gaps for each absent
signal.

Read `scripts/assess_repo_readiness.py` for the exact thresholds and detection
rules.
