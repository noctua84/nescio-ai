---
name: a hooks sibling imported two ways is two module objects
description: why patching hooks.record_stop silently no-ops, and how it hid a vacuous test
type: regression
---
<!-- promoted:begin -->
`hooks/__init__.py` inserts the package directory onto `sys.path`, because the hook modules are also run as standalone scripts and import their siblings by **bare name** (`import record_stop as rs`).

The consequence is a trap: `import record_stop` and `from hooks import record_stop` create **two separate entries in `sys.modules` from one file**. Patching one leaves the other untouched. A test that patches the `hooks.`-qualified module patches an object the hook under test never consults — the fault is never injected, and the test goes on passing.

That is not hypothetical. `tests/test_harvest_nudge.py` patched `hooks.record_stop.git_roots` with a function that raises, then asserted `rc == 0` and empty stdout. Those assertions also hold for an untouched empty session, so the test proved nothing. Run against a mutation that narrowed `main()`'s `except`, the original test **passed** — it would have missed a real regression in exactly the behaviour its name described. Fixed in PR #227 by importing `record_stop` by bare name.

Two rules follow:

- In tests that patch a `hooks/` sibling, import it by **bare name**, never `hooks.`-qualified. The `from hooks import ...` line must come first — that is what runs `hooks/__init__.py` and puts the directory on `sys.path`.
- **Assert the fault was injected**, before asserting the outcome. A call counter is what stops the test going silently vacuous again.

Verify with identity, not reasoning: `rs is harvest_nudge.rs` was `False` before the fix and `True` after.
[Source: empirical — 2026-11-01]
<!-- promoted:end -->
