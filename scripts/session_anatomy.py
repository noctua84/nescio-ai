#!/usr/bin/env python3
"""Report where a multi-agent Claude Code session's context went.

Reads a session's transcript JSONL files -- the main transcript and every
subagent transcript under ``subagents/`` -- and reports, per agent type: how
many requests ran, how much input context each one carried, how much of that
was the dispatch prompt versus accumulated tool output, and which files got
read the most. It answers one question: *when a change is made to an agent's
definition (its tool allowlist, its dispatch prompt shape, whether it reads
``CLAUDE.md``), where would the context savings actually come from?* A
one-off analysis of a single session found the dispatch prompt itself is a
rounding error (~0.5% of subagent input) while the first request's baseline
context (everything loaded before the agent does anything) is 38-54%, with
the remainder dominated by tool output -- mostly ``Read`` and the shell
read/search commands agents use instead of it. This script makes that
analysis repeatable instead of one-off.

Deliberate design decisions, each of which has a failure mode behind it:

  * **Stream line by line, never load a whole transcript into memory.** Real
    sessions run 160+ subagents with transcripts well over 100MB combined; a
    ``json.load`` of the whole file (or even ``.readlines()`` before
    parsing) would multiply peak memory by the file count instead of staying
    bounded by the single largest line.

  * **A malformed JSON line is counted and skipped, never fatal.** A
    transcript is an operational log, not a validated format -- a single
    truncated line (from an interrupted write) must not blank out every
    agent's numbers that follow it in the same file.

  * **Dedupe assistant usage by ``message.id``, keeping the last.** The same
    assistant message is re-emitted across multiple JSONL entries as its
    tool-use blocks resolve; summing every occurrence of ``usage`` would
    double- or triple-count that request's tokens. The *last* occurrence
    carries the final usage for that message, not the first.

  * **Theme-agnostic grouping by the literal ``agentType`` string.** This
    script has no fixed notion of what agents exist -- a crew is a project
    convention, not something to hardcode here. An agent whose
    ``meta.json`` is missing or unreadable is grouped under the literal
    string ``"unknown"`` rather than dropped, so its context usage is still
    visible in the totals.

  * **Tokens only, never cost.** Pricing changes by model and by date; a
    script that converts tokens to dollars goes stale the moment a price
    does, and silently misleads whoever trusts the number after that. This
    stays a token-accounting tool.

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

Usage:
    python scripts/session_anatomy.py <session-id-or-dir>
    python scripts/session_anatomy.py <session-id> --json
    python scripts/session_anatomy.py <id1> <id2> --top-files 15
    python scripts/session_anatomy.py --projects-root ~/.claude/projects <id>
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterator

# ---------------------------------------------------------------------------
# Transcript parsing
# ---------------------------------------------------------------------------


def iter_entries(path: Path) -> Iterator[tuple[dict, bool]]:
    """Yield ``(entry, ok)`` for each line of a JSONL transcript.

    ``ok`` is False for a line that failed to parse as a JSON object; the
    caller tallies those rather than this function raising, so one damaged
    line in a 100MB+ transcript does not blank out everything after it.
    """
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                yield {}, False
                continue
            if not isinstance(entry, dict):
                yield {}, False
                continue
            yield entry, True


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


# ---------------------------------------------------------------------------
# Content helpers
# ---------------------------------------------------------------------------


def _content_len(content: Any) -> int:
    """Character length of a message/tool-result ``content`` field."""
    if isinstance(content, str):
        return len(content)
    total = 0
    for block in content or []:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            total += len(block.get("text", "") or "")
        elif block.get("type") == "tool_result":
            total += _content_len(block.get("content"))
    return total


def _content_text(content: Any) -> str:
    """Flattened text of a message's ``content`` field (str or block list)."""
    if isinstance(content, str):
        return content
    parts = []
    for block in content or []:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", "") or "")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Per-transcript analysis
# ---------------------------------------------------------------------------


def analyze_transcript(path: Path, agent_type: str) -> dict:
    """Analyze a single transcript (main or subagent) and return its stats.

    Returns a dict with keys: agent_type, transcript, prompt_chars,
    prompt_tokens_est, requests, context_first, context_last, context_peak,
    input_processed, output_tokens, tool_calls, tool_output_chars,
    shell_output_chars, shell_calls, file_reads, duplicate_reads,
    files_read, malformed_lines.

    ``duplicate_reads`` counts only repeated *file-read* calls -- a Read
    tool call or a shell call classified "read" by `classify_shell` -- whose
    tool name and input JSON are identical to one already seen earlier in
    this transcript (each repeat beyond the first counts once). Any other
    repeated call (a second identical `Grep`, a re-run `git status`) is not
    counted here.
    """
    prompt_chars = 0
    prompt_seen = False
    malformed_lines = 0

    usage_by_id: dict[str, dict] = {}
    usage_order: list[str] = []

    tool_name_by_use_id: dict[str, str] = {}
    tool_input_by_use_id: dict[str, Any] = {}
    tool_calls: dict[str, int] = {}
    tool_output_chars: dict[str, int] = {}
    shell_calls: dict[str, int] = {}
    shell_output_chars: dict[str, int] = {}

    file_reads = 0
    seen_call_signatures: set[str] = set()
    duplicate_reads = 0
    files_read: set[str] = set()

    for entry, ok in iter_entries(path):
        if not ok:
            malformed_lines += 1
            continue

        message = entry.get("message") or {}
        cwd = entry.get("cwd")
        entry_type = entry.get("type")

        if entry_type == "user" and not prompt_seen:
            content = message.get("content")
            if content is not None:
                prompt_chars = len(_content_text(content)) if not isinstance(content, str) else len(content)
                prompt_seen = True

        if entry_type == "assistant":
            mid = message.get("id")
            usage = message.get("usage")
            if mid and usage:
                if mid not in usage_by_id:
                    usage_order.append(mid)
                usage_by_id[mid] = usage

            for block in message.get("content") or []:
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue
                name = block.get("name", "?")
                use_id = block.get("id")
                tool_input = block.get("input", {}) or {}
                if use_id:
                    tool_name_by_use_id[use_id] = name
                    tool_input_by_use_id[use_id] = tool_input

                tool_calls[name] = tool_calls.get(name, 0) + 1

                # A "file-read call" is a Read tool call or a shell call
                # classified as the "read" family -- the same set that feeds
                # `file_reads`. Duplicate-call detection is scoped to just
                # these: a repeated `Grep` or `Bash git status` is not what
                # `duplicate_reads` means to flag, only re-reading a file
                # (identical tool name + identical input JSON) already seen
                # in this transcript.
                command = ""
                family = None
                is_file_read_call = name == "Read"
                if name in ("Bash", "PowerShell"):
                    command = str(tool_input.get("command", "") or "")
                    family = classify_shell(command)
                    is_file_read_call = family == "read"

                if is_file_read_call:
                    try:
                        sig = name + "\0" + json.dumps(tool_input, sort_keys=True, default=str)
                    except TypeError:
                        sig = name + "\0" + repr(tool_input)
                    if sig in seen_call_signatures:
                        duplicate_reads += 1
                    else:
                        seen_call_signatures.add(sig)

                if name == "Read":
                    file_reads += 1
                    file_path = tool_input.get("file_path")
                    if file_path:
                        files_read.add(normalize_path(str(file_path), cwd))
                elif name in ("Bash", "PowerShell"):
                    shell_calls[family] = shell_calls.get(family, 0) + 1
                    if family == "read":
                        file_reads += 1
                        for arg in _shell_path_args(command):
                            files_read.add(normalize_path(arg, cwd))

        if entry_type == "user" and isinstance(message.get("content"), list):
            for block in message["content"]:
                if not isinstance(block, dict) or block.get("type") != "tool_result":
                    continue
                use_id = block.get("tool_use_id")
                name = tool_name_by_use_id.get(use_id, "?")
                length = _content_len(block.get("content"))
                tool_output_chars[name] = tool_output_chars.get(name, 0) + length
                if name in ("Bash", "PowerShell"):
                    tool_input = tool_input_by_use_id.get(use_id, {}) or {}
                    command = str(tool_input.get("command", "") or "")
                    family = classify_shell(command)
                    shell_output_chars[family] = shell_output_chars.get(family, 0) + length

    context_values = []
    output_tokens = 0
    for mid in usage_order:
        usage = usage_by_id[mid]
        context_values.append(
            (usage.get("input_tokens", 0) or 0)
            + (usage.get("cache_read_input_tokens", 0) or 0)
            + (usage.get("cache_creation_input_tokens", 0) or 0)
        )
        output_tokens += usage.get("output_tokens", 0) or 0

    requests = len(context_values)
    context_first = context_values[0] if context_values else 0
    context_last = context_values[-1] if context_values else 0
    context_peak = max(context_values) if context_values else 0
    input_processed = sum(context_values)

    return {
        "agent_type": agent_type,
        "transcript": path.name,
        "prompt_chars": prompt_chars,
        "prompt_tokens_est": prompt_chars // 4,
        "requests": requests,
        "context_first": context_first,
        "context_last": context_last,
        "context_peak": context_peak,
        "input_processed": input_processed,
        "output_tokens": output_tokens,
        "tool_calls": tool_calls,
        "tool_output_chars": tool_output_chars,
        "shell_output_chars": shell_output_chars,
        "shell_calls": shell_calls,
        "file_reads": file_reads,
        "duplicate_reads": duplicate_reads,
        "files_read": sorted(files_read),
        "malformed_lines": malformed_lines,
    }


# ---------------------------------------------------------------------------
# Session-level aggregation
# ---------------------------------------------------------------------------

MAIN_AGENT_TYPE = "(main)"


def _share(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def analyze_session(session_dir: Path) -> dict:
    """Analyze every transcript in a session directory and aggregate by agent type."""
    session_id = session_dir.name
    transcripts: list[dict] = []

    main_path = session_dir / f"{session_id}.jsonl"
    if main_path.exists():
        transcripts.append(analyze_transcript(main_path, MAIN_AGENT_TYPE))

    subagents_dir = session_dir / "subagents"
    if subagents_dir.is_dir():
        for jsonl_path in sorted(subagents_dir.glob("agent-*.jsonl")):
            meta_path = jsonl_path.with_suffix("").with_suffix(".meta.json")
            agent_type = "unknown"
            if meta_path.exists():
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                    agent_type = meta.get("agentType") or "unknown"
                except (OSError, json.JSONDecodeError):
                    agent_type = "unknown"
            transcripts.append(analyze_transcript(jsonl_path, agent_type))

    by_type: dict[str, dict] = {}
    grouped: dict[str, list[dict]] = {}
    for result in transcripts:
        grouped.setdefault(result["agent_type"], []).append(result)

    for agent_type, results in grouped.items():
        agents = len(results)
        with_requests = [r for r in results if r["requests"] > 0]
        requests = sum(r["requests"] for r in results)
        input_processed = sum(r["input_processed"] for r in results)
        prompt_weighted = sum(r["prompt_tokens_est"] * r["requests"] for r in results)
        baseline_weighted = sum(r["context_first"] * r["requests"] for r in results)
        file_reads = sum(r["file_reads"] for r in results)
        duplicate_reads = sum(r["duplicate_reads"] for r in results)

        mean_context_first = (
            sum(r["context_first"] for r in with_requests) / len(with_requests)
            if with_requests else 0.0
        )
        mean_context_last = (
            sum(r["context_last"] for r in with_requests) / len(with_requests)
            if with_requests else 0.0
        )

        by_type[agent_type] = {
            "agents": agents,
            "requests": requests,
            "input_processed": input_processed,
            "prompt_share": _share(prompt_weighted, input_processed),
            "baseline_share": _share(baseline_weighted, input_processed),
            "mean_context_first": mean_context_first,
            "mean_context_last": mean_context_last,
            "file_reads": file_reads,
            "duplicate_reads": duplicate_reads,
        }

    subagent_results = [r for r in transcripts if r["agent_type"] != MAIN_AGENT_TYPE]
    sub_requests = sum(r["requests"] for r in subagent_results)
    sub_input_processed = sum(r["input_processed"] for r in subagent_results)
    sub_prompt_weighted = sum(
        r["prompt_tokens_est"] * r["requests"] for r in subagent_results
    )
    sub_baseline_weighted = sum(
        r["context_first"] * r["requests"] for r in subagent_results
    )
    sub_with_requests = [r for r in subagent_results if r["requests"] > 0]
    subagent_totals = {
        "agents": len(subagent_results),
        "requests": sub_requests,
        "input_processed": sub_input_processed,
        "prompt_share": _share(sub_prompt_weighted, sub_input_processed),
        "baseline_share": _share(sub_baseline_weighted, sub_input_processed),
        "mean_context_first": (
            sum(r["context_first"] for r in sub_with_requests) / len(sub_with_requests)
            if sub_with_requests else 0.0
        ),
        "mean_context_last": (
            sum(r["context_last"] for r in sub_with_requests) / len(sub_with_requests)
            if sub_with_requests else 0.0
        ),
        "file_reads": sum(r["file_reads"] for r in subagent_results),
        "duplicate_reads": sum(r["duplicate_reads"] for r in subagent_results),
    }

    tool_output_chars: dict[str, int] = {}
    shell_output_chars: dict[str, int] = {}
    for result in subagent_results:
        for name, chars in result["tool_output_chars"].items():
            tool_output_chars[name] = tool_output_chars.get(name, 0) + chars
        for family, chars in result["shell_output_chars"].items():
            shell_output_chars[family] = shell_output_chars.get(family, 0) + chars

    file_agents: dict[str, set[str]] = {}
    for result in subagent_results:
        agent_key = f"{result['agent_type']}:{result['transcript']}"
        for file_path in result["files_read"]:
            file_agents.setdefault(file_path, set()).add(agent_key)
    hot_files = sorted(
        ({"path": path, "agents": len(agents)} for path, agents in file_agents.items()),
        key=lambda entry: (-entry["agents"], entry["path"]),
    )

    malformed_lines = sum(r["malformed_lines"] for r in transcripts)

    return {
        "by_type": by_type,
        "subagent_totals": subagent_totals,
        "tool_output_chars": tool_output_chars,
        "shell_output_chars": shell_output_chars,
        "hot_files": hot_files,
        "malformed_lines": malformed_lines,
    }


def resolve_session(arg: str, projects_root: Path) -> Path:
    """Resolve a session argument (a directory, or a bare session id) to a directory.

    An existing directory is returned as-is. Otherwise ``arg`` is treated as
    a session id and globbed for under every project directory; exactly one
    match resolves, zero or more than one raises ``ValueError`` naming what
    was found (or not found) so the caller can report it clearly.
    """
    candidate = Path(arg)
    if candidate.is_dir():
        return candidate

    matches = sorted(projects_root.glob(f"*/{arg}")) if projects_root.is_dir() else []
    matches = [m for m in matches if m.is_dir()]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise ValueError(
            f"no session directory found for {arg!r} under {projects_root}"
        )
    joined = ", ".join(str(m) for m in matches)
    raise ValueError(f"ambiguous session id {arg!r}: multiple matches under {projects_root}: {joined}")


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------


def _fmt_pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _fmt_k(value: float) -> str:
    return f"{value / 1000:.1f}k"


def format_report(result: dict, top_files: int) -> str:
    """Format one or more ``analyze_session`` results as a human-readable report."""
    lines: list[str] = []
    for session in result["sessions"]:
        session_id = session["session_id"]
        agents = sum(entry["agents"] for entry in session["by_type"].values())
        main_entry = session["by_type"].get(MAIN_AGENT_TYPE, {})
        main_processed = main_entry.get("input_processed", 0)
        sub_processed = session["subagent_totals"]["input_processed"]
        total_processed = main_processed + sub_processed

        lines.append("")
        lines.append(f"session {session_id}")
        lines.append(
            f"  {agents} agents, {total_processed / 1e6:.1f}M input tokens processed"
        )
        if session["malformed_lines"]:
            lines.append(
                f"  {session['malformed_lines']} malformed transcript line(s) skipped"
            )
        lines.append("")

        header = (
            f"  {'agent type':<22} {'n':>3} {'reqs':>6} {'prompt%':>8} "
            f"{'base%':>7} {'first':>7} {'last':>7} {'reads':>6} {'dup reads':>9}"
        )
        lines.append(header)
        lines.append("  " + "-" * (len(header) - 2))
        for agent_type, entry in sorted(
            session["by_type"].items(), key=lambda kv: -kv[1]["input_processed"]
        ):
            lines.append(
                f"  {agent_type:<22} {entry['agents']:>3} {entry['requests']:>6} "
                f"{_fmt_pct(entry['prompt_share']):>8} {_fmt_pct(entry['baseline_share']):>7} "
                f"{_fmt_k(entry['mean_context_first']):>7} {_fmt_k(entry['mean_context_last']):>7} "
                f"{entry['file_reads']:>6} {entry['duplicate_reads']:>9}"
            )

        totals = session["subagent_totals"]
        lines.append("")
        lines.append(
            f"  subagents (excl. main): {totals['agents']} agents, "
            f"{totals['requests']} requests, "
            f"prompt share {_fmt_pct(totals['prompt_share'])}, "
            f"baseline share {_fmt_pct(totals['baseline_share'])}"
        )

        # Rows below 0.1% share are omitted from the printed report -- a long
        # tail of one-off tool names (an MCP tool called once) adds noise
        # without adding signal here. The JSON output is unfiltered; this
        # trims only the human-readable rendering.
        total_tool_chars = sum(session["tool_output_chars"].values())
        if total_tool_chars:
            shown = [
                (name, chars)
                for name, chars in session["tool_output_chars"].items()
                if chars / total_tool_chars >= 0.001
            ]
            if shown:
                lines.append("")
                lines.append("  tool output share (subagents):")
                for name, chars in sorted(shown, key=lambda kv: -kv[1]):
                    lines.append(
                        f"    {name:<14} {chars / 1e6:>7.2f}M chars  "
                        f"{_fmt_pct(chars / total_tool_chars):>6}"
                    )

        total_shell_chars = sum(session["shell_output_chars"].values())
        if total_shell_chars:
            shown_shell = [
                (family, chars)
                for family, chars in session["shell_output_chars"].items()
                if chars / total_shell_chars >= 0.001
            ]
            if shown_shell:
                lines.append("")
                lines.append("  shell output share by family (subagents):")
                for family, chars in sorted(shown_shell, key=lambda kv: -kv[1]):
                    lines.append(
                        f"    {family:<14} {chars / 1e6:>7.2f}M chars  "
                        f"{_fmt_pct(chars / total_shell_chars):>6}"
                    )

        hot_files = session["hot_files"][:top_files]
        if hot_files:
            lines.append("")
            lines.append(f"  top {len(hot_files)} hot files (by distinct subagents):")
            for entry in hot_files:
                lines.append(f"    {entry['agents']:>3}  {entry['path']}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    # A non-ASCII path or agent-type string would appear verbatim in the
    # report; a legacy Windows console (cp1252) would raise UnicodeEncodeError
    # on it. Reconfigure to UTF-8 up front, before any print (guarded -- a
    # redirected StringIO in tests has no reconfigure).
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass

    parser = argparse.ArgumentParser(
        description="Report where a multi-agent Claude Code session's context went.",
    )
    parser.add_argument(
        "sessions", nargs="+", help="session id(s) or session directory path(s)"
    )
    parser.add_argument(
        "--projects-root",
        type=Path,
        default=Path.home() / ".claude" / "projects",
        help="root under which session ids are searched (default ~/.claude/projects)",
    )
    parser.add_argument(
        "--json", action="store_true", help="emit machine-readable JSON"
    )
    parser.add_argument(
        "--top-files", type=int, default=8, help="how many hot files to list (default 8)"
    )
    args = parser.parse_args(argv)

    if args.top_files < 1:
        parser.error("--top-files must be at least 1")

    sessions = []
    for session_arg in args.sessions:
        try:
            session_dir = resolve_session(session_arg, args.projects_root)
        except ValueError as exc:
            parser.error(str(exc))
            return 2  # unreachable; parser.error exits, but keeps type-checkers happy
        result = analyze_session(session_dir)
        result["session_id"] = session_dir.name
        sessions.append(result)

    if args.json:
        print(json.dumps({"schema_version": 1, "sessions": sessions}, indent=2))
    else:
        print(format_report({"sessions": sessions}, args.top_files))
    return 0


if __name__ == "__main__":
    sys.exit(main())
