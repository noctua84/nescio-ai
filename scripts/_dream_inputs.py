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

  * **Test runs are classified, not just counted.** What a subagent does after
    a failing test run (and whether a COMPLETE report ended on a red run) comes
    from ``_dream_testruns``; counts only, same contract.

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

from _dream_testruns import TestTracker, add_counts, empty_counts
from _dream_parse import LINE_MAX, REJECTION_RE, VERDICT_RE, _text_of, error_signature, find_escalations, parse_report, scrub

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
    malformed line is counted and skipped. ``report`` is the parsed report of
    the last assistant text block carrying a ``<verdict>`` (flags and
    out-of-scope lines scrubbed, no raw text), or ``None``. ``tests`` is the
    ``_dream_testruns.TestTracker`` summary (counts only).
    """
    errors: Counter = Counter()
    commands: Counter = Counter()
    tests = TestTracker()
    tools: dict = {}
    seen: set = set()
    malformed = 0
    last_report = None
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
                text = _text_of(content)
                if VERDICT_RE.search(text):
                    last_report = parse_report(text)
                for b in content:
                    if not isinstance(b, dict) or b.get("type") != "tool_use":
                        continue
                    tools[b.get("id")] = b.get("name")
                    if b.get("id") in seen:
                        continue
                    seen.add(b.get("id"))
                    inp = b.get("input") if isinstance(b.get("input"), dict) else {}
                    tests.on_tool_use(b.get("id"), b.get("name"), inp)
                    if b.get("name") == "Bash" and isinstance(inp.get("command"), str) and inp["command"].strip():
                        commands[_norm(inp["command"])] += 1
            elif entry.get("type") == "user":
                for b in content:
                    if not isinstance(b, dict) or b.get("type") != "tool_result":
                        continue
                    if tests.tracks(b.get("tool_use_id")):
                        tests.on_tool_result(b.get("tool_use_id"), _text_of(b.get("content")), b.get("is_error") is True)
                    if b.get("is_error") is not True:
                        continue
                    text = _text_of(b.get("content"))
                    if not REJECTION_RE.match(text):
                        tool = str(tools.get(b.get("tool_use_id"), "unknown"))
                        sig = error_signature(text)
                        if sig:
                            errors[(agent, tool, sig)] += 1
    if last_report:
        last_report["flags"] = [scrub(ln, LINE_MAX) for ln in last_report["flags"]]
        last_report["out_of_scope"] = [scrub(ln, LINE_MAX) for ln in last_report["out_of_scope"]]
    return {
        "errors": errors, "reruns": sum(n - 1 for n in commands.values() if n > 1), "malformed": malformed,
        "report": last_report, "tests": tests.summary(),
    }


def parse_subagents(main_path: Path, cap: int) -> dict:
    """All (capped) subagent transcripts of one parent session, folded together."""
    files, skipped = subagent_files(main_path, cap)
    out = {"files": len(files), "skipped": skipped, "malformed": 0, "errors": Counter(), "reruns": 0, "rerun_agents": Counter(), "reports": [],
           "tests_by_agent": {}, "complete_on_red": 0, "complete_on_red_agents": Counter()}
    for path, agent in files:
        try:
            r = parse_subagent(path, agent)
        except OSError:
            out["files"] -= 1
            continue
        out["malformed"] += r["malformed"]
        out["errors"].update(r["errors"])
        out["reruns"] += r["reruns"]
        if r["tests"]["runs"]:
            add_counts(out["tests_by_agent"].setdefault(agent, empty_counts()), r["tests"])
        if r["report"] and r["report"]["verdict"] == "COMPLETE" and r["tests"]["last_ok"] is False:
            out["complete_on_red"] += 1
            out["complete_on_red_agents"][agent] += 1
        if r["report"]:
            out["reports"].append((path.stem.removeprefix("agent-"), agent, r["report"]))
        if r["reruns"]:
            out["rerun_agents"][agent] += r["reruns"]
    return out


def merge_subagent_reports(s: dict, sub: dict) -> int:
    """Add reports found only in subagent transcripts to a parent session summary; returns how many.

    A background agent's report often never reaches the parent transcript, but
    its own transcript ends with it. ``sub`` is ``parse_subagents`` output and
    ``s`` a ``parse_session`` summary. Why it works this way:

      * **Dedupe by agent id; the parent's copy wins.** An id in
        ``s["reported_ids"]`` already has a report (possibly an edited
        re-statement of the same text), so the subagent copy is dropped.
      * **Placement is an approximation.** Events carry no timestamps, so the
        ``("report", agent, verdict)`` event goes right after the agent's own
        dispatch (``s["agent_dispatch"]``), or at the end when that is unknown.
        That keeps a failed report ahead of the later higher-tier dispatch that
        ``find_escalations`` looks for, but it can misorder against other
        reports. Escalations are recomputed after the merge.
    """
    known = set(s.get("reported_ids", ()))
    dispatch_at = s.get("agent_dispatch", {})
    merged = 0
    inserts: list[tuple[int, int, tuple]] = []  # (position, order, event)
    for agent_id, agent, rep in sub.get("reports", ()):
        if agent_id in known:
            continue
        known.add(agent_id)
        s["reports"].append({**rep, "agent": agent, "ts": None, "source": "subagent"})
        at = dispatch_at.get(agent_id)
        inserts.append((len(s["events"]) if at is None else at + 1, merged, ("report", agent, rep["verdict"])))
        merged += 1
    # Descending position keeps earlier indices valid; later-merged goes first so equal positions keep merge order.
    for pos, _, ev in sorted(inserts, key=lambda t: (-t[0], -t[1])):
        s["events"].insert(pos, ev)
    if merged:
        s["escalations"] = find_escalations(s["events"])
    return merged


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
