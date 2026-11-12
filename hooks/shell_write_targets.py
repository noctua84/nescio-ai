"""Best-effort shell command parsing for PreToolUse guards: splits a command into
segments, finds the files a segment writes, and recognises read-only commands.
Knows nothing about which files are protected — that policy lives in the guard
that imports it.
"""

from __future__ import annotations

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
