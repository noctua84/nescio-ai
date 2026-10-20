"""Recognise what a session's tool calls touched: shell intent and file paths.

Pure functions over the strings a transcript records for a tool call -- a
``Bash`` command, a ``file_path`` -- with no shared mutable state. Extracted
from ``session_anatomy.py``, which re-imports ``classify_shell``,
``normalize_path`` and ``_shell_path_args`` and is the only caller.

Deliberate design decisions, each of which has a failure mode behind it:

  * **``normalize_path`` makes a path comparable across agents' own
    worktrees, not absolute.** Two subagents that each run in their own git
    worktree read the "same" file at two different absolute paths; relativizing
    to each transcript's own ``cwd`` is what lets ``hot_files`` recognise
    that both of them read it. When a path is *not* under the transcript's
    own ``cwd`` -- a tool result naming a path in a sibling worktree of the
    same repository -- a ``.claude/worktrees/<name>/`` segment anywhere in
    the path is stripped up through and including that segment, falling
    back to the repo-relative remainder. This is narrow by design: it
    recognises exactly one directory convention, and two genuinely
    *different* repositories that happen to share a relative path (both
    having ``src/index.ts``, say) would incorrectly collapse into one
    ``hot_files`` entry under this rule. Accepted because the common case
    this script exists to serve is several agents sharing one repository
    across worktrees, not cross-repository analysis.

  * **Classifying a shell command strips a leading ``cd ... &&`` and env
    assignments before matching the first word.** Agents routinely prefix a
    ``Bash`` call with ``cd <dir> &&`` to run from a specific directory, or
    with a ``VAR=x`` environment override; matching against the unstripped
    string would file nearly every such call under "other" instead of its
    real intent.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Shell command classification
# ---------------------------------------------------------------------------

_READ_CMDS = {"sed", "cat", "head", "tail", "less", "more", "type", "get-content", "gc"}
_SEARCH_CMDS = {"grep", "rg", "egrep", "find", "ls", "wc", "select-string", "dir", "get-childitem"}
_TEST_MARKERS = (
    "pytest", "unittest", "vitest", "jest", "npm test", "npm run test",
    "pnpm test", "yarn test", "tox", "go test", "cargo test",
)

# `cd <dir> &&` / `cd <dir>;` (POSIX or PowerShell), possibly repeated, and a
# leading `VAR=value` environment assignment, possibly repeated.
_CD_PREFIX_RE = re.compile(r"^\s*cd\s+\S+\s*(?:&&|;)\s*", re.IGNORECASE)
_ENV_ASSIGN_RE = re.compile(r"^\s*[A-Za-z_][A-Za-z0-9_]*=\S*\s+")


def _strip_prefixes(command: str) -> str:
    """Strip repeated leading ``cd ... &&``/``;`` segments and env assignments."""
    changed = True
    while changed:
        changed = False
        new = _CD_PREFIX_RE.sub("", command)
        if new != command:
            command = new
            changed = True
        new = _ENV_ASSIGN_RE.sub("", command)
        if new != command:
            command = new
            changed = True
    return command


def classify_shell(command: str) -> str:
    """Classify a shell command into "git", "test", "read", "search", or "other".

    Precedence is git, then test, then read, then search, then other: a
    command containing a test-runner invocation (e.g. ``cd pkg && npm test``)
    is "test" even if its first word would otherwise read as something else,
    and a bare ``git`` invocation is never miscategorised as a test just
    because its arguments happen to mention one.
    """
    if not command:
        return "other"
    stripped = _strip_prefixes(command)
    words = stripped.split()
    first = words[0].lower() if words else ""

    if first == "git":
        return "git"

    lowered = stripped.lower()
    if any(marker in lowered for marker in _TEST_MARKERS):
        return "test"

    if first in _READ_CMDS:
        return "read"
    if first in _SEARCH_CMDS:
        return "search"
    return "other"


# ---------------------------------------------------------------------------
# Path normalization
# ---------------------------------------------------------------------------


# See the module docstring's `normalize_path` bullet for why this exists and
# its accepted cross-repository limitation.
_WORKTREE_SEGMENT_RE = re.compile(r"\.claude/worktrees/[^/]+/(.*)$")


def normalize_path(path: str, cwd: str | None) -> str:
    """Normalize ``path`` to forward slashes, relative to ``cwd`` when under it.

    Comparison is case-insensitive for the Windows-drive-letter prefix only
    (``C:`` vs ``c:``), matching how Windows paths from different shells
    describe the same location without over-folding case for the rest of the
    path (which matters on case-sensitive filesystems too).

    When the path is not under ``cwd``, a ``.claude/worktrees/<name>/``
    segment anywhere in it is treated as a second normalization anchor (see
    the module docstring for the tradeoff): the remainder after that segment
    is returned, repo-relative, so the same file read from two different
    worktrees of one repository still compares equal.
    """
    norm_path = path.replace("\\", "/")
    if not cwd:
        match = _WORKTREE_SEGMENT_RE.search(norm_path)
        return match.group(1) if match else norm_path
    norm_cwd = cwd.replace("\\", "/").rstrip("/")
    if not norm_cwd:
        match = _WORKTREE_SEGMENT_RE.search(norm_path)
        return match.group(1) if match else norm_path

    def _drive_fold(s: str) -> str:
        if len(s) >= 2 and s[1] == ":":
            return s[0].lower() + s[1:]
        return s

    folded_path = _drive_fold(norm_path)
    folded_cwd = _drive_fold(norm_cwd)

    if folded_path == folded_cwd:
        return "."
    prefix = folded_cwd + "/"
    if folded_path.startswith(prefix):
        return norm_path[len(prefix):]

    match = _WORKTREE_SEGMENT_RE.search(norm_path)
    if match:
        return match.group(1)
    return norm_path


# Shell metacharacters that mean a token is not a path argument at all, but a
# redirect, pipe, or command separator (`2>/dev/null`, `| head`, `; rm -rf`).
# Checked before the path-like test below, since `2>/dev/null` would
# otherwise pass it (it contains "/").
_SHELL_METACHARS = frozenset(">|<&;")


def _is_path_like(token: str) -> bool:
    """True when a shell-command token looks like a file path argument.

    A flag (``-n``, ``--color``) is never a path, nor is a redirect, pipe, or
    separator token (``2>/dev/null``, ``2>&1``, ``|``) or the literal device
    path ``/dev/null`` itself. Anything else containing a path separator, or
    ending in a dot-extension, is treated as a path -- deliberately
    permissive, since missing a real path costs more (a file silently absent
    from ``files_read``) than an occasional false positive (a non-path token
    with a dot in it, which is rare for the commands this classifies).
    """
    if not token or token.startswith("-"):
        return False
    if any(ch in _SHELL_METACHARS for ch in token):
        return False
    if token.strip("'\"") == "/dev/null":
        return False
    return "/" in token or "\\" in token or bool(re.search(r"\.[A-Za-z0-9]{1,10}$", token))


# A bare redirect operator as its own token (`>`, `>>`, `<`, `2>`, `&>`,
# `&>>`) -- the shell splits `cat a.py > out.txt` this way, so the token
# right after it (`out.txt`) is a redirect *target*, not something the
# command read. A glued-on form (`>out.txt`, `2>err.log`) is a single token
# and is already rejected by `_SHELL_METACHARS` in `_is_path_like`.
_REDIRECT_OP_RE = re.compile(r"^\d*(>>?|<|&>>?)$")


def _shell_path_args(command: str) -> list[str]:
    stripped = _strip_prefixes(command)
    tokens = [tok.strip("'\"") for tok in stripped.split()]
    # Skip the command word itself.
    args: list[str] = []
    skip_next = False
    for tok in tokens[1:]:
        if skip_next:
            skip_next = False
            continue
        if _REDIRECT_OP_RE.match(tok):
            skip_next = True
            continue
        if _is_path_like(tok):
            args.append(tok)
    return args
