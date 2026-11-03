---
name: module-gate wants its verdict before the first CI run
description: why the module gate keeps failing on PRs that changed no oversized code, and the cheap fix
type: convention
---
<!-- promoted:begin -->
`module_gate.py` demands a **recorded verdict** for every file it sees over the tripwire — not a split. It reads both commit messages and the PR body, and it counts **added** lines, so a file already over the limit on `main` trips the gate when a PR makes it one line longer.

This failed five PRs in six days (#214, #219, #221, #222, #223), every time on a file the PR barely touched: a workflow that gained a `permissions:` block, a test module that gained a checksum update, a newly committed plan or QA report over 400 lines. Each was fixed by editing the PR description — **no code change at all** — because GitHub re-runs the gate when the description is edited.

Two consequences worth internalising:

- **Put the `Module-check:` line in the PR body when you open the PR.** #226 did, and the gate passed on its first run; the others paid a failed check plus an edit-retrigger round trip. The cost of the upfront line is one sentence.
- **The ack must be on one line.** A verdict wrapped across two lines does not match the gate's pattern, which expects the path and the verdict text on a single line separated by a dash or colon.

Also: the gate compares **commits**, not the working tree. Running it before committing reports "no over-tripwire file grew" and tells you nothing.

Files that recur here: `.github/workflows/tests.yml`, `brand/make_diagrams.py`, `docs_site/test_site_content.py`, and any committed plan or audit report under `.sisyphus/` or `docs/reports/`.
[Source: empirical — 2026-10-30]
<!-- promoted:end -->
