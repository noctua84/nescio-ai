#!/usr/bin/env python3
"""PreToolUse hook: stop the CI-gate agent editing the files that define the checks.

``agents/qa-guard.md`` tells the CI-gate agent (``qa-guard``, or ``cato`` under
the philosopher theme) that it may never edit or create the files that define
the checks: CI workflows, pre-commit config, linter and type-checker settings,
``conftest.py``, the ``[tool.*]`` tables of ``pyproject.toml``, the ``scripts``
block of ``package.json``. A prompt rule is not enforcement; this hook is the
enforcement. It denies the tool call before it runs.

What it is, and is not
----------------------

A **tripwire**, not a sandbox. File tools (``Edit``/``Write``/``MultiEdit``/
``NotebookEdit``) are judged exactly: the path is classified and, for the two
section-protected files, the edit is *simulated* so a change to ``[project]``
is allowed while a change under ``[tool.ruff]`` is not. Shell tools (``Bash``,
``PowerShell``) are judged best-effort: known write forms (redirects, ``tee``,
``sed -i``, ``cp``/``mv``/``rm``...) are parsed for their targets, and any
other command that merely *mentions* a protected file is denied unless its
command word is on a read-only allowlist. That is deliberately conservative: a
command we cannot prove harmless gets denied with a reason telling the agent to
read the file with the Read tool, or to name the file and return BLOCKED.

The orchestrator's ``git status --porcelain`` audit after the agent returns is
the backstop for everything this hook misses. The hook makes the honest path
cheap and the dishonest path loud; it does not make the dishonest path
impossible.

Known bypasses (why this is a tripwire)
---------------------------------------

- variables:       ``f=ruff.toml; echo x > $f`` (the name never appears literally
                   next to the write)
- globs:           ``echo x > ruff.t*ml``
- indirection:     write a script file, then execute it (the script body is only
                   inspected at the moment it is written, if at all)
- directory hops:  ``cd .github && echo x > workflows/ci.yml`` (the segment that
                   writes does not name the protected path)
- encoding:        ``echo ... | base64 -d > $(...)``, ``printf`` octal escapes
- autofixers:      ``ruff check --fix``, ``npm pkg set scripts.x=y`` and friends
                   that rewrite config as a side effect, without naming it
- heredoc bodies and multi-line strings are parsed as if they were commands

Scope decisions
---------------

- ``Makefile`` is protected as a whole file. The agent prompt says "check
  targets in a Makefile"; targets cannot be reliably separated from the rest of
  a Makefile by a hook, so the guard is stricter than the prompt.
- Whole-file protection also covers *creating* a new check-config file.
- ``pyproject.toml`` is protected only in its ``tool`` table and
  ``package.json`` only in its ``scripts`` object. A change that leaves the
  protected section equal is allowed; a result that does not parse is denied
  (fail closed: we cannot show the section is untouched).
- Both theme names are guarded, because the runtime ``agent_type`` is whichever
  theme is installed. ``tests/test_check_file_guard.py`` pins ``GUARDED_AGENTS``
  against ``scripts/_crew_common.PAIRS`` so a rename cannot silently disarm it.

Failure mode
------------

A user-level PreToolUse hook runs for **every** agent in **every** session. The
very first thing ``evaluate`` does is return ``None`` for any agent that is not
guarded, so that path is a dict lookup and nothing else — it must not be able
to crash. Everything after the guarded check fails **closed**: any internal
error, or malformed stdin, exits 2 (which blocks the tool call), even on Claude
Code versions that predate the ``onFailure: "block"`` hook option. The price is
that a bug here blocks every agent's tool calls; that is the intended
trade-off, and the reason the non-guarded path is kept so small.

Contract: stdin is the hook-input JSON (``agent_type``, ``cwd``, ``tool_name``,
``tool_input``...). To deny, print one ``hookSpecificOutput`` JSON object to
stdout and exit 0. To allow, print nothing and exit 0. Stdlib only.
"""
from __future__ import annotations

import json
import re
import shlex
import sys
import tomllib
from pathlib import Path, PurePosixPath

# Runtime agent_type is the functional name or the philosopher name, depending
# on the installed theme (scripts/_crew_common.PAIRS: ("qa-guard", "cato")).
GUARDED_AGENTS = frozenset({"qa-guard", "cato"})

FILE_TOOLS = frozenset({"Edit", "Write", "MultiEdit", "NotebookEdit"})
SHELL_TOOLS = frozenset({"Bash", "PowerShell"})

# Basenames (lowercase) of files that exist only to define checks.
WHOLE_FILE_BASENAMES = frozenset({
    "azure-pipelines.yml", ".gitlab-ci.yml", ".pre-commit-config.yaml",
    "conftest.py", "pytest.ini", "ruff.toml", ".ruff.toml", ".flake8",
    "mypy.ini", ".mypy.ini", "setup.cfg", "tox.ini", ".pylintrc", "pylintrc",
    ".coveragerc", "makefile", "gnumakefile",
})
# Files protected only in one section; value = the top-level key that is guarded.
SECTION_FILES = {"pyproject.toml": "tool", "package.json": "scripts"}

KIND_WHOLE = "whole"
WORKFLOWS = (".github", "workflows")

# Names looked for by the shell "mention" fallback (substring, lowercase).
MENTION_NAMES = tuple(sorted(
    WHOLE_FILE_BASENAMES | set(SECTION_FILES) | {".github/workflows"}
))

BOUNDARY = (
    "qa-guard may not edit check definitions; "
    "if a check is wrong, name it and return BLOCKED"
)

_BASH_READONLY = frozenset({
    "cat", "head", "tail", "less", "more", "grep", "egrep", "fgrep", "rg",
    "ls", "wc", "diff", "cmp", "stat", "file", "echo", "test", "[", "find",
    "git",
})
_PS_READONLY = frozenset({
    "get-content", "gc", "type", "select-string", "sls", "get-childitem",
    "gci", "dir", "ls", "test-path", "get-item", "git",
})
_GIT_READONLY_SUBCOMMANDS = frozenset({
    "diff", "status", "log", "show", "blame", "ls-files", "grep",
})
_FIND_WRITE_FLAGS = frozenset({
    "-delete", "-exec", "-execdir", "-fprint", "-fprint0", "-fprintf", "-fls",
    "-ok", "-okdir",
})
# Words that run another command; the real command word follows.
_WRAPPERS = frozenset({"sudo", "env", "command", "nohup", "time", "exec", "nice", "builtin"})
_PUNCT = frozenset("();<>|&")


# --------------------------------------------------------------------------
# Path classification
# --------------------------------------------------------------------------

def _norm(path: str) -> str:
    return path.replace("\\", "/")


def classify(path: str, cwd: str | None = None) -> str | None:
    """Return ``"whole"``, ``"tool"``, ``"scripts"`` or None for ``path``.

    ``"tool"``/``"scripts"`` name the guarded section of a section-protected
    file (``pyproject.toml`` / ``package.json``). Basenames compare
    case-insensitively; a path under ``cwd`` is made relative to it first.
    """
    p = _norm(path)
    if cwd:
        c = _norm(cwd).rstrip("/")
        if c and p.lower().startswith(c.lower() + "/"):
            p = p[len(c) + 1:]
    parts = [s.lower() for s in p.split("/") if s and s != "."]
    if not parts:
        return None
    for i in range(len(parts) - 1):
        if (parts[i], parts[i + 1]) == WORKFLOWS:
            return KIND_WHOLE
    base = parts[-1]
    if base in WHOLE_FILE_BASENAMES:
        return KIND_WHOLE
    return SECTION_FILES.get(base)


def _deny_reason(path: str, detail: str = "") -> str:
    extra = f" ({detail})" if detail else ""
    return f"Refusing to modify {path}{extra}: {BOUNDARY}."


# --------------------------------------------------------------------------
# File tools
# --------------------------------------------------------------------------

def _read_current(path: str, cwd: str | None) -> str:
    p = Path(path)
    if not p.is_absolute() and cwd:
        p = Path(cwd) / p
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""  # missing file == empty: this call may be creating it


def _apply_edit(text: str, old: str, new: str, replace_all: bool) -> str | None:
    """Apply one replacement; None when ``old`` is not found (Claude Code rejects it)."""
    if old == "":
        return new if text == "" else None
    if old not in text:
        return None
    return text.replace(old, new) if replace_all else text.replace(old, new, 1)


def _simulate(tool: str, tool_input: dict, current: str) -> str | None:
    """Return the file content after the tool call, or None when it would not apply."""
    if tool == "Write":
        content = tool_input.get("content")
        return content if isinstance(content, str) else None
    if tool == "Edit":
        edits = [tool_input]
    else:  # MultiEdit
        edits = tool_input.get("edits")
        if not isinstance(edits, list):
            return None
    text = current
    for e in edits:
        if not isinstance(e, dict):
            return None
        old, new = e.get("old_string"), e.get("new_string")
        if not isinstance(old, str) or not isinstance(new, str):
            return None
        text = _apply_edit(text, old, new, bool(e.get("replace_all")))
        if text is None:
            return None
    return text


_PARSE_ERRORS = (ValueError, tomllib.TOMLDecodeError)  # JSONDecodeError is a ValueError


def _section(kind: str, text: str) -> object:
    """The guarded section of ``text``; raises on unparsable content."""
    data = tomllib.loads(text) if kind == "tool" else json.loads(text)
    return data.get(kind) if isinstance(data, dict) else None


def _check_section_file(path, kind, tool, tool_input, cwd) -> str | None:
    current = _read_current(path, cwd)
    new = _simulate(tool, tool_input, current)
    if new is None:
        return None  # the edit will not apply; Claude Code rejects it
    try:
        after = _section(kind, new)
    except _PARSE_ERRORS:
        return _deny_reason(path, f"the result would not parse, so the `{kind}` "
                                  "section cannot be verified unchanged")
    try:
        before = _section(kind, current) if current.strip() else None
    except _PARSE_ERRORS:
        before = None  # unparsable current file: its section counts as absent
    if before != after:
        return _deny_reason(path, f"it changes the `{kind}` section")
    return None


def _check_file_tool(event: dict) -> str | None:
    tool = event.get("tool_name")
    ti = event.get("tool_input")
    if not isinstance(ti, dict):
        return None
    path = ti.get("file_path") or ti.get("notebook_path")
    if not isinstance(path, str) or not path:
        return None
    cwd = event.get("cwd") if isinstance(event.get("cwd"), str) else None
    kind = classify(path, cwd)
    if kind is None:
        return None
    if kind == KIND_WHOLE:
        return _deny_reason(path)
    if tool in ("Edit", "Write", "MultiEdit"):
        return _check_section_file(path, kind, tool, ti, cwd)
    return _deny_reason(path)  # NotebookEdit on a non-notebook: cannot simulate


# --------------------------------------------------------------------------
# Shell tools (best effort)
# --------------------------------------------------------------------------

def _split_segments(command: str, *, powershell: bool) -> list[str] | None:
    """Split on unquoted newline, ``;``, ``&&``, ``||``, ``|``, ``&`` (and, for
    bash, ``(``, ``)`` and backticks). None when quotes are unbalanced.

    ``&`` directly after ``>``/``<`` or before ``>`` belongs to a redirect
    (``2>&1``, ``&>file``) and does not split.
    """
    esc = "`" if powershell else "\\"
    seps = "\n;|&" if powershell else "\n;|&()`"
    segs: list[str] = []
    cur: list[str] = []
    quote = ""
    i, n = 0, len(command)
    while i < n:
        ch = command[i]
        if quote:
            cur.append(ch)
            if ch == esc and quote == '"' and i + 1 < n:
                cur.append(command[i + 1])
                i += 1
            elif ch == quote:
                quote = ""
        elif ch == esc and i + 1 < n:
            cur.append(ch)
            cur.append(command[i + 1])
            i += 1
        elif ch in "'\"":
            quote = ch
            cur.append(ch)
        elif ch in seps:
            if ch == "&" and (
                (i > 0 and command[i - 1] in "<>")
                or (i + 1 < n and command[i + 1] == ">")
            ):
                cur.append(ch)
            else:
                segs.append("".join(cur))
                cur = []
        else:
            cur.append(ch)
        i += 1
    if quote:
        return None
    segs.append("".join(cur))
    return [s for s in segs if s.strip()]


def _is_option(tok: str) -> bool:
    return tok.startswith("-") and len(tok) > 1


def _in_place_flag(tool: str, tok: str) -> bool:
    """True if ``tok`` is a sed/perl switch cluster that turns on in-place edit."""
    if tok.startswith("--"):
        return tok == "--in-place" or tok.startswith("--in-place=")
    if not tok.startswith("-"):
        return False
    stop = "efl" if tool == "sed" else "eEMmIxXdDVCF"
    for c in tok[1:]:
        if c == "i":
            return True
        if c in stop:
            return False
    return False


def _redirect_targets(tokens: list[str]) -> tuple[list[str], list[str]]:
    """Split off redirections: (remaining words, write-redirect targets)."""
    words: list[str] = []
    targets: list[str] = []
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if t and all(c in _PUNCT for c in t):
            if ">" in t and i + 1 < len(tokens):
                nxt = tokens[i + 1]
                if not all(c in _PUNCT for c in nxt):
                    targets.append(nxt)
                i += 1
            elif "<" in t:
                i += 1  # input redirect or heredoc delimiter: not a write
        else:
            words.append(t)
        i += 1
    return words, targets


def _command_index(words: list[str]) -> int:
    """Index of the real command word: past ``VAR=x`` prefixes and wrappers."""
    i = 0
    while i < len(words):
        w = words[i]
        base = PurePosixPath(_norm(w)).name.lower()
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", w) or base in _WRAPPERS or (
            _is_option(w) and i > 0
        ):
            i += 1
            continue
        break
    return i


def _write_targets(cmd: str, args: list[str]) -> list[str]:
    """Paths the command (already normalised to a bare lowercase name) writes."""
    positional = [a for a in args if not _is_option(a)]
    if cmd == "tee":
        return positional
    if cmd in ("sed", "perl"):
        return positional if any(_in_place_flag(cmd, a) for a in args if _is_option(a)) else []
    if cmd in ("cp", "install", "ln"):
        return positional[-1:]
    if cmd in ("mv", "rm", "unlink", "touch", "truncate", "chmod"):
        return positional  # mv/rm also destroy their sources
    if cmd == "dd":
        return [a[3:] for a in args if a.startswith("of=")]
    return []


def _mentions(text: str) -> str | None:
    t = _norm(text).lower()
    for name in MENTION_NAMES:
        if name in t:
            return name
    return None


def _cannot_verify(name: str) -> str:
    return (f"Refusing this command: cannot verify this command does not modify {name}; "
            f"read it with the Read tool, or name the file and return BLOCKED. "
            f"{BOUNDARY}.")


def _bash_readonly(cmd: str, args: list[str], raw: str, has_redirect: bool) -> bool:
    if "$(" in raw or "`" in raw:
        return False  # command substitution can hide a write inside a "read"
    if cmd not in _BASH_READONLY:
        return False
    if cmd == "echo" and has_redirect:
        return False
    if cmd == "find" and any(a in _FIND_WRITE_FLAGS for a in args):
        return False
    if cmd == "git":
        return _git_readonly(args)
    return True


def _git_readonly(args: list[str]) -> bool:
    sub = next((a for a in args if not _is_option(a)), None)
    return sub in _GIT_READONLY_SUBCOMMANDS and not any(
        a.startswith("--output") for a in args
    )


def _check_bash_segment(raw: str, cwd: str | None) -> str | None:
    try:
        # posix shlex eats a backslash before an ordinary character, which turns
        # a Windows-style `.github\workflows\x.yml` into one meaningless word.
        # Read such backslashes as path separators (conservative: it can only
        # make a protected path easier to recognise).
        lexable = re.sub(r"\\(?=[A-Za-z0-9._-])", "/", raw)
        lex = shlex.shlex(lexable, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        tokens = list(lex)
    except ValueError:
        name = _mentions(raw)
        return _cannot_verify(name) if name else None
    words, redirects = _redirect_targets(tokens)
    for target in redirects:
        if classify(target, cwd):
            return _deny_reason(target, "shell redirect")
    idx = _command_index(words)
    if idx >= len(words):
        return None
    cmd = PurePosixPath(_norm(words[idx])).name.lower()
    if cmd.endswith(".exe"):
        cmd = cmd[:-4]
    args = words[idx + 1:]
    for target in _write_targets(cmd, args):
        if classify(target, cwd):
            return _deny_reason(target, f"`{cmd}` target")
    name = _mentions(raw)
    if name and not _bash_readonly(cmd, args, raw, bool(redirects)):
        return _cannot_verify(name)
    return None


def _check_powershell_segment(raw: str) -> str | None:
    name = _mentions(raw)
    if not name:
        return None
    stripped = raw.strip().lstrip("&.").strip()
    first = stripped.split(None, 1)[0].strip("'\"").lower() if stripped else ""
    if (
        first in _PS_READONLY
        and ">" not in raw
        and "$(" not in raw
        and (first != "git" or _git_readonly(stripped.split()[1:]))
    ):
        return None
    return _cannot_verify(name)


def _check_shell_tool(event: dict) -> str | None:
    ti = event.get("tool_input")
    command = ti.get("command") if isinstance(ti, dict) else None
    if not isinstance(command, str) or not command.strip():
        return None
    cwd = event.get("cwd") if isinstance(event.get("cwd"), str) else None
    powershell = event.get("tool_name") == "PowerShell"
    segments = _split_segments(command, powershell=powershell)
    if segments is None:  # unbalanced quotes: nothing can be parsed reliably
        name = _mentions(command)
        return _cannot_verify(name) if name else None
    for seg in segments:
        reason = (_check_powershell_segment(seg) if powershell
                  else _check_bash_segment(seg, cwd))
        if reason:
            return reason
    return None


# --------------------------------------------------------------------------
# Entry points
# --------------------------------------------------------------------------

def evaluate(event: dict) -> str | None:
    """Return a deny reason for this PreToolUse event, or None to stay silent."""
    agent = event.get("agent_type")
    if not isinstance(agent, str) or agent not in GUARDED_AGENTS:
        return None  # every other agent: nothing below this line may run
    tool = event.get("tool_name")
    if tool in FILE_TOOLS:
        return _check_file_tool(event)
    if tool in SHELL_TOOLS:
        return _check_shell_tool(event)
    return None


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        sys.stdin.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass
    # Fail closed (exit 2 blocks the tool call) on *any* error after this
    # point, including malformed stdin. That also blocks every non-guarded
    # agent when the hook itself is broken: the intended trade-off, and why the
    # non-guarded path in evaluate() is a single dict lookup.
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
        print(f"check_file_guard: internal error, failing closed: {exc!r}",
              file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
