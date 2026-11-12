# Tool-call guards: enforcing crew boundaries with hooks

**Status:** exploration + one prototype (`hooks/check_file_guard.py`).
**Question:** which of the boundaries the agent prompts state can Claude Code
hooks enforce in code, and how reliably?

## Verdict

| Boundary (prompt text today) | Enforceable by a `PreToolUse` hook? | Reliability |
|---|---|---|
| `planner` may spawn only `explore`, `librarian` | **Yes** — match `Agent`, read `tool_input.subagent_type` | Structural: exact, no parsing |
| `qa-guard` never edits check definitions — file tools | **Yes** — path check, plus a before/after diff of `[tool.*]` / `scripts` | Exact for `Edit`/`Write`/`MultiEdit` |
| `qa-guard` never edits check definitions — shell | **Partly** — parse obvious write forms, deny ambiguous mentions | Tripwire, not a sandbox (see [Shell limits](#shell-parsing-limits)) |
| `test-writer` touches only test directories — file tools | **Yes, with config** — needs a per-repo test-path list | Exact once paths are known |
| `doc-writer` must not touch implementation files — file tools | **Yes, with config** — allowlist doc paths/extensions | Exact for paths; docstrings in code stay a judgment call |
| `test-writer` / `doc-writer` — shell | **Partly** — same limits as `qa-guard` | Tripwire |
| "Don't weaken assertions", "don't scope-creep", "verify before claiming done" | **No** — semantic, not a tool-call shape | Prompt + orchestrator audits only |

Rule of thumb: a boundary is enforceable when it is a property of **one tool
call's structured input** — a path, a `subagent_type`. It is not
enforceable when the effect has to be inferred from free-form text, which is
what a shell command is.

The prototype guards `qa-guard` because its boundary is the most precise and the
orchestrator already names the Bash bypass. The `planner` spawn guard is the
cheapest next step: it is exact, and the docs confirm the frontmatter allowlist
does nothing when `planner` runs as a subagent.

## What the hooks docs establish

Source: <https://code.claude.com/docs/en/hooks> and
<https://code.claude.com/docs/en/sub-agents>, read 2026-11-12. Headings named
so a reader can re-check.

**Which agent is calling? Yes.** *Common input fields* lists `agent_id` and
`agent_type`. `agent_type` is present "when the session uses `--agent` or the
hook fires inside a subagent"; inside a subagent the subagent's type wins over
`--agent`. *Configuration* says settings-level hooks also run inside subagents
and carry both fields. Consequence: in the main thread under
`"agent": "orchestrator"` (this repo's `settings.json`) `agent_type` is
`orchestrator`, not absent. A guard must key on the agent it guards, never on
"`agent_type` is present".

The value is the **installed** name, which depends on the theme:
`qa-guard` or `cato`, `planner` or `plato`. The guard accepts both. A test pins
that set against `scripts/_crew_common.py` `PAIRS`, so a rename cannot quietly
disarm it.

**Can `PreToolUse` on `Agent` deny a spawn? Yes.** The spawning tool is `Agent`.
Its `tool_input` holds `prompt`, `description`, `subagent_type` and an optional
`model` (*PreToolUse input → Agent*). `PreToolUse` matches every tool except
`EndConversation`, and a `deny` decision blocks the call as for any other
tool. A missing `subagent_type` should be denied too, because it falls back to
a general-purpose agent.

**Deny format.** Print one JSON object on stdout and exit 0:
`{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision":
"deny", "permissionDecisionReason": "..."}}`. The reason is shown to Claude, so
it doubles as the agent's instruction ("name it and return BLOCKED"). Exit
code 2 also blocks, with stderr as the reason, even when the JSON says
`allow`. **Every other exit code, a crash or a timeout fails open by default**
(*Other exit codes*, *Timeouts*).

**`onFailure: "block"`** (command and http hooks, v2.1.295+, values
`continue` | `block`, default `continue`) turns those failures into
"what exit code 2 does on that event". Failures include: cannot start, an exit
code other than 0 or 2, a timeout, and invalid output. It has no effect on
`async` hooks or on `Stop`/`SubagentStop`. A guard therefore has to be
synchronous. The prototype also fails closed on its own: any internal exception
exits 2. That covers versions older than 2.1.295, which ignore the key.

**Windows.** *Failed hooks on Windows without Git Bash*: without Git Bash,
only exit 0 or 2 count for `PreToolUse`. The changelog records the fail-open
bugs behind this: 2.1.309 fixed `"shell": "powershell"` hooks failing open
without Git for Windows, and 2.1.310 fixed `PreToolUse`/`PermissionRequest`
letting the call through when Git Bash is missing. The docs' recommendation is
`onFailure: "block"` plus `"shell": "powershell"`. This repo sidesteps the shell
entirely, as the next point explains. `tool_input.file_path` arrives with
backslashes on Windows, so the guard normalises `\` to `/`.

**`shell` and `args`.** `"shell"` accepts `bash` or `powershell`. It defaults to
`bash`, or to `powershell` on Windows when Git Bash is absent, and is
**ignored when `args` is set**. With `args`, `command` is resolved as an
executable and spawned directly, with no shell and no tokenisation. On
Windows that requires a real `.exe`. `install.py` already wires every hook
in this exec form: `command` is the resolved `python.exe` and `args` is the
absolute script path. So the Git Bash / PowerShell fail-open class does
not apply to it, and quoting cannot break it. Keep it that way.

**Latency.** The default command timeout is 600 s. The prototype sets 10 s, so
a hung guard blocks quickly instead of stalling the session for ten minutes.
The docs give no `PreToolUse` latency guidance. The real cost is one Python
process spawn per matched call, for **every** agent, because a settings hook
cannot be filtered by agent. Measured cost of the non-guarded path is in
[Prototype](#prototype). The `if` field (one permission-rule pattern such as
`Bash(git *)`) filters by tool input, not by agent, and is best-effort: when
Claude Code can't tell what a Bash command runs, the hook runs anyway. It
can narrow a guard, never replace one.

**Matcher syntax.** A matcher made only of letters, digits, `_`, `-`, spaces,
`,` and `|` is an **exact-name list**, not a regex. So
`Edit|Write|MultiEdit|NotebookEdit|Bash|PowerShell` matches exactly those six
tools. Any other character turns it into an unanchored JavaScript regex, where
`Edit.*` would also catch `NotebookEdit`. `MultiEdit` is not in the
`tool_input` tables I read. Listing it costs nothing if the tool doesn't
exist.

**The docs' own caveat.** *Common fields* says to "use the permission system
rather than a hook to enforce a hard allow or deny". Permission rules are
global, not per agent, and a global `deny Edit(ruff.toml)` would also block
the builder. A per-agent boundary therefore needs a hook. The caveat is a
reason to keep the hook a tripwire, not a reason to skip it.

## Hooks in agent frontmatter

The sub-agents page documents a `hooks:` frontmatter key: "Lifecycle hooks
scoped to this subagent. Ignored for plugin subagents." Claude Code runs them
only while that subagent runs, and converts a `Stop` hook to `SubagentStop`.
Project-level agents run them only after the workspace-trust dialog, and a
`-p` session does not count as trust. This crew is installed as
**user-level** agents (`~/.claude/agents`, symlinked), not a plugin, so
frontmatter hooks **would be honoured**.

That makes frontmatter the cleaner placement in principle. The hook fires only
for `qa-guard`, costs other agents nothing, and needs no `agent_type` check.
The prototype still wires at settings level, for three reasons:

1. **No install-time path.** Frontmatter is tracked, so it cannot hold the
   absolute interpreter and script paths `install.py` resolves. It would need
   shell form, e.g. `python "$HOME/.claude/hooks/check_file_guard.py"`. That
   reintroduces the shell (Git Bash vs PowerShell, and the Windows fail-open
   class above) and depends on whichever `python` is first on `PATH` (the
   failure that #144 hit with a rebuilt venv). With `onFailure: "block"` a bad
   `PATH` would block `qa-guard` entirely: safe, but a broken agent.
2. **Themes rewrite agent files.** `apply_theme.py` regenerates `agents/*.md`,
   and `tests/test_agent_definitions.py` pins their frontmatter. A hook block
   there is more surface to keep in sync across both themes.
3. **`install.py --check` can see settings hooks**, so a dead guard is
   visible. A frontmatter hook that never spawns is silent.

Revisit if `install.py` grows a step that renders frontmatter with resolved
paths at install time. The settings guard keys on `agent_type`, so moving it
later is a wiring change, not a rewrite.

## Shell parsing limits

`hooks/check_file_guard.py` treats a shell command in three tiers:

1. **Recognised write forms** — redirections (`>`, `>>`, `>|`, `&>`, `n>`),
   `tee`, `sed -i` / `perl -i`, `cp`/`mv`/`install`/`ln` destinations,
   `rm`/`unlink`/`touch`/`truncate`/`chmod`, `dd of=`. If the target is a
   protected file, the call is denied.
2. **Ambiguous mention** — the segment names a protected file and its command is
   not on a short read-only allowlist (`cat`, `grep`, `git diff`, …;
   `Get-Content`, `Select-String`, … for PowerShell). Denied, with the reason
   telling the agent to use the `Read` tool. Inline interpreters (`python -c`,
   `node -e`, `bash -c`, `pwsh -Command`) are never allowlisted.
3. **Everything else** is allowed.

**Where it stops.** Each bypass below is out of reach of any static parse, not
just this one:

- indirection: `f=ruff.toml; echo x > "$f"`, globs (`ruff.t*ml`), `cd .github && …`;
- encoded or generated code: `base64 -d | sh`, a script written to `/tmp` and then run;
- tools that edit config as a side effect: an autofixer's `--fix`, `npm pkg set scripts.x=…`, `poetry`/`uv` subcommands;
- any interpreter reading its program from a file the guard never sees.

The tests pin one known bypass (the variable form) as **not** caught, so the
limit is visible in the suite rather than discovered later.

**So the shell guard is a tripwire, and the orchestrator's existing *CI Gate
Audit* (`git status --porcelain` plus the net-assertion count, after every
`qa-guard` wave) stays the backstop.** The guard catches the obvious path at
call time and tells the agent why. The audit catches everything that reached
the working tree, however it got there. Neither replaces the other.

A real sandbox would need the OS: a read-only bind mount of the check files,
or Claude Code's sandboxed Bash with a write deny-list. Both apply to every
agent, not per agent. Out of scope here.

## Mods (JS/TS `tool.check`) — what they would add

Mods are plugin-packaged JavaScript functions that Claude Code calls in its
own process. `tool.check` runs "after the PreToolUse hooks run, and before the
permission prompt", and returns `allow` / `ask` / `deny` or defers via
`next(e)`. Compared with a Python command hook:

- **No process spawn per call.** This removes the latency tax on non-guarded agents.
- **`e.isReadOnly` (v2.1.304+).** Claude Code's own read-only classification of
  the call. Tier 2 above could ask Claude Code instead of keeping a homegrown
  allowlist, which is the weakest part of the shell guard.
- **Fail-open by default**: a mod that throws or times out is skipped, unless it
  catches and denies itself. That is a step back from `onFailure: "block"`.
- **Ordering:** non-managed settings `PreToolUse` hooks run *after* the mod chain
  for `tool.call`. Mods are a separate layer, not a replacement.

The 2.1.287 version for `tool.check` named in the review was not found in the
part of the changelog I read. The `e.isReadOnly` / 2.1.304 pairing is from the
mods events page. Not adopted: the user does not want JS/TS in this repo now,
and nothing above is blocked on it.

## Prototype

- `hooks/check_file_guard.py` — `PreToolUse` guard for `qa-guard`/`cato`.
  Whole-file protection for workflow and check-config files (including
  *creating* them). `pyproject.toml` and `package.json` are checked by
  simulating the edit and comparing the `[tool]` table / `scripts` object
  before and after, so `[project]` or `dependencies` edits pass. Shell
  handling is the three tiers above. Every other agent returns immediately.
- `install.py` — `wire_check_file_guard_hook` wires it as a synchronous
  `PreToolUse` hook with matcher `Edit|Write|MultiEdit|NotebookEdit|Bash|PowerShell`,
  `"onFailure": "block"` and `"timeout": 10`. `_wire_command_hook` gained an
  `extra` keyword for those entry keys and treats a mismatch as drift to repair.
- Tests: `tests/test_check_file_guard.py` (hook-input JSON fixtures under
  `tests/fixtures/check_file_guard/`) and new cases in
  `tests/test_install_hooks.py`.

**Scope comes from `agent_type` alone.** The settings hook fires for every
agent's matched calls, and the first check in `evaluate` is what keeps it out
of everyone else's way. Because `main()` fails closed, a bug *before* that
check would block every agent. That is why the path is a dictionary lookup
and nothing more.

**Measured cost** (Windows 11, Python 3.13, median of 15 spawns via
`subprocess`): the guard costs about **55 ms per matched call**, both for a
non-guarded agent and for a guarded `Bash` call. A bare `python -c pass` costs
about 24 ms. So roughly half the cost is interpreter start-up, and the rest is
imports. Over a session with a few hundred `Edit`/`Write`/`Bash` calls, that is
tens of seconds spread across the whole crew. It is acceptable for one guard. It
is the reason for the single-dispatcher step below, not one spawn per guard.

**Known false positives** (the mention fallback over-denies; the agent is told
to name the file and return `BLOCKED`):

- `ruff check --config pyproject.toml .`, `pytest -c pytest.ini`, `mypy --config-file mypy.ini`
- a quoted `|` or `>` inside an argument (`grep "|" ruff.toml`)
- a heredoc body that names a protected file

A per-linter allowlist for `--config <file>` would remove the first group. It
was not added, to keep the prototype's allowlist small enough to audit.
`git add` / `git commit` naming a check file would also be denied. That costs
nothing, because `qa-guard` does not commit.

## Next steps (not done here)

1. **`planner` spawn guard.** Deny `Agent` when `agent_type ∈ {planner, plato}`
   and `subagent_type ∉ {explore, librarian}` (or is missing). Exact, small,
   and closes the gap the review found.
2. **`test-writer` / `doc-writer` path guards.** Both need a per-repo notion of
   "test paths" / "doc paths". Read it from a small config, with a
   conservative default (`tests/`, `test_*.py`, `*_test.*`, `*.spec.*` /
   `docs/`, `*.md`, `*.rst`). Without that config the guard would be either
   useless or wrong.
3. **One dispatcher, not N hooks.** Each guard as its own settings hook means one
   Python spawn per guard per call. When there is more than one, route by
   `agent_type` inside a single `crew_guard.py`.
4. **Read-only agents.** #240 forbade destructive shell commands in the
   read-only agents by prompt. The same tier-1 parser could back that.
