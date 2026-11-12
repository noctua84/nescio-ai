"""Extra inputs for ``dream.py``: subagent transcripts and QA audit reports.

Split from ``dream.py`` because both sources are read differently from a parent
session: a subagent transcript has its own file (and its own tool errors and
retries that the parent never sees -- the parent only gets the final report),
and a QA report is Markdown, not JSONL. Everything here returns plain dicts and
counters; no raw text survives.

Deliberate design decisions, each with a failure mode behind it:

  * **Subagent reads are capped per parent session, newest first.** Subagent
    transcripts roughly double the bytes a dream pass reads; one fan-out session
    can own hundreds. The cap keeps the pass bounded and ``skipped`` makes the
    truncation visible instead of silent.

  * **Only errors and exact Bash reruns are collected.** That is the signal the
    parent lacks. Errors are keyed ``(agent, tool, signature)`` and the signature
    goes through ``error_signature`` (paths, hex and numbers collapsed, secrets
    redacted); commands are compared in memory and only the *count* is kept.

  * **User rejections are not errors**, same rule as the parent parse.

  * **QA reports yield severity counts only -- never finding titles.** Titles
    are free text from an audited codebase and would bypass the privacy
    contract; counts are enough to see whether audits keep finding things.
    The ``Severity Summary`` line is trusted first; heading counting is the
    fallback for reports whose summary line is missing or mangled.

Stdlib only; reuses the parse helpers so the redaction path is the same one.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import date, datetime
from pathlib import Path

from _dream_parse import REJECTION_RE, _text_of, error_signature

UNKNOWN_AGENT = "unknown"
SEVERITIES = ("critical", "major", "minor", "info")
REPORT_NAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-.+\.md$")
SUMMARY_RE = re.compile(r"\*\*Severity Summary:\*\*(.*)", re.IGNORECASE)
COUNT_RE = re.compile(r"(\d+)\s*(critical|major|minor|info)\b", re.IGNORECASE)
HEADING_RE = re.compile(r"^###\s*\[(CRITICAL|MAJOR|MINOR|INFO)\]", re.MULTILINE | re.IGNORECASE)


def _agent_type(meta_path: Path) -> str:
    """``agentType`` from a sibling ``.meta.json``; "unknown" if missing, unreadable or not a string."""
    try:
        value = json.loads(meta_path.read_text(encoding="utf-8")).get("agentType")
    except (OSError, ValueError, AttributeError):
        return UNKNOWN_AGENT
    return value if isinstance(value, str) and value else UNKNOWN_AGENT


def subagent_files(main_path: Path, cap: int) -> tuple[list[tuple[Path, str]], int]:
    """Newest-first subagent transcripts of one parent session, capped; ``(kept, skipped)``.

    Each kept entry is ``(path, agentType)``. A parent with no ``subagents/``
    directory yields ``([], 0)``.
    """
    found = []
    for f in (main_path.with_suffix("") / "subagents").glob("agent-*.jsonl"):
        try:
            found.append((f.stat().st_mtime, f))
        except OSError:
            continue
    found.sort(key=lambda t: (-t[0], str(t[1])))
    cap = max(0, cap)
    kept = [(f, _agent_type(f.with_suffix("").with_suffix(".meta.json"))) for _, f in found[:cap]]
    return kept, max(0, len(found) - cap)


def _norm(command: str) -> str:
    return " ".join(command.split())


def parse_subagent(path: Path, agent: str) -> dict:
    """Stream one subagent transcript: non-rejection tool errors and identical Bash reruns.

    ``errors`` is a Counter keyed ``(agent, tool, signature)``; ``reruns`` is the
    sum of ``count - 1`` over Bash commands issued more than once. A tool_use
    re-emitted as results resolve is counted once (deduped by id), and a
    malformed line is counted and skipped.
    """
    errors: Counter = Counter()
    commands: Counter = Counter()
    tools: dict = {}
    seen: set = set()
    malformed = 0
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                entry = None
            if not isinstance(entry, dict):
                malformed += 1
                continue
            content = (entry.get("message") or {}).get("content")
            if not isinstance(content, list):
                continue
            if entry.get("type") == "assistant":
                for b in content:
                    if not isinstance(b, dict) or b.get("type") != "tool_use":
                        continue
                    tools[b.get("id")] = b.get("name")
                    if b.get("id") in seen:
                        continue
                    seen.add(b.get("id"))
                    inp = b.get("input") if isinstance(b.get("input"), dict) else {}
                    if b.get("name") == "Bash" and isinstance(inp.get("command"), str) and inp["command"].strip():
                        commands[_norm(inp["command"])] += 1
            elif entry.get("type") == "user":
                for b in content:
                    if not isinstance(b, dict) or b.get("type") != "tool_result" or b.get("is_error") is not True:
                        continue
                    text = _text_of(b.get("content"))
                    if not REJECTION_RE.match(text):
                        tool = str(tools.get(b.get("tool_use_id"), "unknown"))
                        errors[(agent, tool, error_signature(text))] += 1
    return {"errors": errors, "reruns": sum(n - 1 for n in commands.values() if n > 1), "malformed": malformed}


def parse_subagents(main_path: Path, cap: int) -> dict:
    """All (capped) subagent transcripts of one parent session, folded together."""
    files, skipped = subagent_files(main_path, cap)
    out = {"files": len(files), "skipped": skipped, "malformed": 0, "errors": Counter(), "reruns": 0, "rerun_agents": Counter()}
    for path, agent in files:
        try:
            r = parse_subagent(path, agent)
        except OSError:
            out["files"] -= 1
            continue
        out["malformed"] += r["malformed"]
        out["errors"].update(r["errors"])
        out["reruns"] += r["reruns"]
        if r["reruns"]:
            out["rerun_agents"][agent] += r["reruns"]
    return out


def _severity_counts(text: str) -> tuple[dict, str] | None:
    """``(counts, source)`` from the summary line, else from headings; ``None`` if neither."""
    m = SUMMARY_RE.search(text)
    pairs = COUNT_RE.findall(m.group(1)) if m else []
    if pairs:
        counts = dict.fromkeys(SEVERITIES, 0)
        for n, sev in pairs:
            counts[sev.lower()] += int(n)
        return counts, "summary"
    heads = Counter(h.lower() for h in HEADING_RE.findall(text))
    if heads:
        return {sev: heads[sev] for sev in SEVERITIES}, "headings"
    return None


def qa_reports(repo_root: Path, since: datetime, cap: int) -> list[dict]:
    """Severity counts of ``docs/reports/YYYY-MM-DD-*.md`` dated on/after ``since``, newest first.

    Files with neither a summary line nor finding headings, and unreadable
    files, are skipped. Finding titles are never returned.
    """
    found: list[tuple[date, Path]] = []
    for f in (repo_root / "docs" / "reports").glob("*.md"):
        m = REPORT_NAME_RE.match(f.name)
        if not m:
            continue
        try:
            d = date.fromisoformat(m.group(1))
        except ValueError:
            continue
        if d >= since.date():
            found.append((d, f))
    found.sort(key=lambda t: (t[0], t[1].name), reverse=True)
    out = []
    for d, f in found:
        if len(out) >= max(0, cap):
            break
        try:
            parsed = _severity_counts(f.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        if parsed:
            counts, source = parsed
            out.append({"name": f.name, "date": d.isoformat(), **counts, "source": source})
    return out
