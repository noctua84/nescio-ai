---
name: a pure move is a claim an agent can make cheaply
description: line counts cannot distinguish a pure extraction from smuggled logic
type: convention
---
<!-- promoted:begin -->
`modular-design` requires a split to execute as pure moves — no logic edits, no signature changes, no opportunistic cleanup — with the thinning of wrappers as a **separate commit**. That makes "it is a pure move" the load-bearing claim, and it is one an implementer can assert for free.

Line counts do not check it. Splitting the ADR 0002 trigger reminder out of `hooks/harvest_nudge.py` (411 → 202 lines) produced a diff of +863/−763 — a net +100 that is equally consistent with import scaffolding *or* with logic smuggled in on the way. The net number carries no signal either way.

What does check it: compare the extracted content directly against its original, and confirm the generated or dependent output is byte-identical where it should be. The docs-site lifecycle split was accepted on exactly that basis — "the generated page is byte-identical before and after."

The same discipline applies to test-only phases. `euclid` may not touch implementation files, and that is verifiable rather than trustable: `git diff origin/main -- scripts/` empty on PR #228, `hooks/harvest_nudge.py` byte-identical to `main` on #227. Check the boundary; do not accept the report of it.
[Source: empirical — 2026-11-01]
<!-- promoted:end -->
