#!/usr/bin/env python3
"""PreToolUse hook: stop the planner spawning any subagent except explore/librarian.

``agents/planner.md`` declares ``tools: ... Agent(explore, librarian)`` in its
frontmatter, an allowlist of the subagent types the planner may spawn. Claude
Code only honours that allowlist when the agent runs as the **main thread**
(``claude --agent planner``). When the planner runs as a *subagent* (the normal
case: the orchestrator spawns it) the allowlist does nothing, and the planner
could spawn a builder, a reviewer, or a general-purpose agent. A prompt rule is
not enforcement; this hook is the enforcement. It denies the ``Agent`` tool
call before it runs.

What it is, and is not
----------------------

Exact, not best-effort. The decision reads one structured field,
``tool_input.subagent_type``, so there is no command parsing and no bypass by
quoting or indirection. The spawn is allowed only when that field is a string
naming ``explore`` or ``librarian`` (neither is themed: both names are the same
under every theme). A missing, empty, blank or non-string ``subagent_type``
falls back to a general-purpose agent in Claude Code, so it is denied.

Both theme names are guarded, because the runtime ``agent_type`` is whichever
theme is installed (``scripts/_crew_common.PAIRS``: ``("planner", "plato")``).

Failure mode
------------

A user-level PreToolUse hook runs in every session. ``evaluate`` first returns
``None`` for any agent that is not guarded, so that path is a dict lookup and
nothing else; it cannot crash. Everything after fails **closed**: any internal
error, or malformed stdin, exits 2 (which blocks the tool call), even on Claude
Code versions that predate the ``onFailure: "block"`` hook option.

Contract: stdin is the hook-input JSON (``agent_type``, ``tool_name``,
``tool_input``...). To deny, print one ``hookSpecificOutput`` JSON object to
stdout and exit 0. To allow, print nothing and exit 0. Stdlib only.
"""
from __future__ import annotations

import json
import sys

# Runtime agent_type is the functional name or the philosopher name, depending
# on the installed theme (scripts/_crew_common.PAIRS: ("planner", "plato")).
GUARDED_AGENTS = frozenset({"planner", "plato"})

# Mirrors `Agent(explore, librarian)` in agents/planner.md.
ALLOWED_SUBAGENTS = frozenset({"explore", "librarian"})


def evaluate(event: dict) -> str | None:
    """Return a deny reason for this PreToolUse event, or None to stay silent."""
    agent = event.get("agent_type")
    if not isinstance(agent, str) or agent not in GUARDED_AGENTS:
        return None  # every other agent: nothing below this line may run
    if event.get("tool_name") != "Agent":
        return None
    tool_input = event.get("tool_input")
    raw = tool_input.get("subagent_type") if isinstance(tool_input, dict) else None
    subagent = raw.strip() if isinstance(raw, str) else ""
    if subagent in ALLOWED_SUBAGENTS:
        return None
    rejected = repr(subagent) if subagent else "(none; this falls back to general-purpose)"
    allowed = ", ".join(sorted(ALLOWED_SUBAGENTS))
    return (
        f"The planner may only spawn {allowed}; refusing to spawn {rejected}. "
        "Name the work you wanted delegated in your plan and return it to the "
        "orchestrator rather than spawning it yourself."
    )


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        sys.stdin.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass
    # Fail closed (exit 2 blocks the tool call) on *any* error after this
    # point, including malformed stdin. That also blocks every non-guarded
    # agent's spawns when the hook itself is broken: the intended trade-off.
    try:
        event = json.loads(sys.stdin.read())
        if not isinstance(event, dict):
            raise ValueError("hook input is not a JSON object")
        reason = evaluate(event)
        if reason:
            print(json.dumps({"hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }}))
    except Exception as exc:
        print(f"planner_spawn_guard: internal error, failing closed: {exc!r}",
              file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
