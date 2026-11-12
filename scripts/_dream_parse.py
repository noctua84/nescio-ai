"""Streaming transcript parsing for ``dream.py``: transcript file in, summary dict out.

Split from ``dream.py`` at the parse -> aggregate seam: everything here reads
one session and returns plain dicts (no raw message text survives, only scrubbed
excerpts); ``dream.py`` folds those dicts into a proposal and owns the CLI.

Same contract as ``session_anatomy.py``: stream line by line, and count and skip
a malformed line rather than failing the session. Every excerpt passes
``record_stop.redact``, has the home dir replaced by ``~``, and is truncated.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))

import record_stop as rs  # noqa: E402

EXCERPT_MAX = 160
LINE_MAX = 200
MAX_EXCERPTS = 3

VERDICT_RE = re.compile(r"<verdict>\s*(COMPLETE|PARTIAL|BLOCKED)\s*</verdict>")
# Correction detection is a lower bound, not a rate. It is English-only and looks
# only at the start of a message. Measured recall is low (about 2 of 9 corrections
# in a random sample) because many corrections are phrased as plain factual
# statements ("that file is the old one"), which no start-of-message cue can
# separate from ordinary talk. Use the count to watch a trend across runs.
LEAD = r"^(?:(?:hm+|ah|oh|well|wait)\b[\s,.!]*)?"
CORRECTION_RE = re.compile(  # strong cue: counts regardless of context
    LEAD + r"(don'?t\b|do not\b|please don'?t\b|stop (doing|that|it)\b|wrong\b|that'?s (not|wrong)\b|that is not\b|"
    r"this is not\b|it'?s not\b|that (does not|doesn'?t)\b|not what\b|i meant\b|i mean\b(?!,)|i said\b|"
    r"why (did|are|would|do) you\b|you('re| are) (wrong|mistaken)\b|instead\b|undo\b|revert\b)",
    re.IGNORECASE,
)
NO_RE = re.compile(  # weak cue: a bare "no" counts only when it is not answering a question
    LEAD + r"(no\b|nope\b)(?![\s,.!]*(need|thanks?|thank you|nothing|all\b|further|more\b|follow|keep|leave)\b)",
    re.IGNORECASE,
)
REVERT_RE = re.compile(r"\bgit\s+(revert|reset\s+--hard|checkout\s+--\s|restore\s)")
PATH_RE = re.compile(r"(?:[A-Za-z]:[\\/]|~?/)[^\s'\"`<>]+")
HEX_RE = re.compile(r"\b[0-9a-fA-F]{7,}\b")
DIGITS_RE = re.compile(r"\d+")
# Background agents hand their report back as a later user entry, not as the
# Agent tool's result: either `<agent-message from=ID>` + `[Subagent hand-back]`,
# or (older transcripts) a `<task-notification>` carrying `<task-id>` and `<result>`.
AGENT_MSG_RE = re.compile(r'<agent-message\s+from="([^"]+)"[^>]*>')
HANDBACK_MARK = "[Subagent hand-back]"
TASK_ID_RE = re.compile(r"<task-id>\s*([^<\s]+)\s*</task-id>")
TASK_RESULT_RE = re.compile(r"<result>(.*)</result>", re.DOTALL)
# A tool result the *user* declined; an `is_error` flag on it is a decision, not a failure.
REJECTION_RE = re.compile(r"^\s*(the user doesn'?t want to|user rejected|\[request interrupted by user)", re.IGNORECASE)
# Per-session transcript-shape counters; ``dream.drift_warnings`` reads their sum to catch a silent format change.
SHAPE_COUNTS = (
    "entries", "typed", "with_message", "tool_uses", "tool_results", "result_dicts", "agent_results",
)


def _tag_lines(text: str, tag: str) -> list[str]:
    """Non-empty bullet-stripped lines of the last ``<tag>`` block in ``text``."""
    blocks = re.findall(rf"<{tag}>(.*?)</{tag}>", text, re.DOTALL)
    if not blocks:
        return []
    lines = (ln.strip().lstrip("-*").strip() for ln in blocks[-1].splitlines())
    return [ln for ln in lines if ln]


def _text_of(content) -> str:
    """Text of a string or a list of ``{type: text}`` blocks; "" otherwise."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            b["text"]
            for b in content
            if isinstance(b, dict) and b.get("type") == "text" and isinstance(b.get("text"), str)
        )
    return ""


def home_forms() -> list[str]:
    """The home dir in native and forward-slash form, longest first."""
    home = str(Path.home())
    return sorted({home, home.replace("\\", "/")}, key=len, reverse=True)


def scrub(text: str, limit: int = EXCERPT_MAX) -> str:
    """Redact secrets, replace the home dir with ``~``, collapse and truncate."""
    text = rs.redact(" ".join(text.split()))
    for form in home_forms():
        text = re.sub(re.escape(form), "~", text, flags=re.IGNORECASE if os.name == "nt" else 0)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def split_tier(agent_type: str) -> tuple[str, int]:
    """``(family, tier)``: ``-simple`` 0, ``-standard`` 1, anything else 2."""
    for tier, suffix in enumerate(("-simple", "-standard")):
        if agent_type.endswith(suffix):
            return agent_type[: -len(suffix)], tier
    return agent_type, 2


def error_signature(text: str) -> str:
    """First line of an error with paths, hex and numbers collapsed."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    first = " ".join(lines[:2]) if lines and lines[0].startswith("Exit code") else (lines[0] if lines else "")
    first = PATH_RE.sub("<path>", first)
    first = HEX_RE.sub("<hex>", first)
    return scrub(DIGITS_RE.sub("<n>", first), 120)


def find_escalations(events: list[tuple]) -> list[tuple[str, int, int]]:
    """Failed (BLOCKED/PARTIAL) family-F report then a later higher-tier F dispatch.

    ``events`` are ``("dispatch", agent)`` / ``("report", agent, verdict)`` in
    transcript order. Each dispatch is consumed by at most one escalation.
    """
    used: set[int] = set()
    found = []
    for i, ev in enumerate(events):
        if ev[0] != "report" or ev[2] not in ("BLOCKED", "PARTIAL"):
            continue
        fam, tier = split_tier(ev[1])
        for j in range(i + 1, len(events)):
            if events[j][0] != "dispatch" or j in used:
                continue
            fam2, tier2 = split_tier(events[j][1])
            if fam2 == fam and tier2 > tier:
                used.add(j)
                found.append((fam, tier, tier2))
                break
    return found


def parse_report(text: str) -> dict:
    """Verdict, pin/deferred-red lines and out-of-scope lines of a builder report."""
    verdicts = VERDICT_RE.findall(text)
    deviations = _tag_lines(text, "deviations")
    return {
        "verdict": verdicts[-1] if verdicts else None,
        "flags": [ln for ln in deviations if ln.startswith(("Inverted pin:", "Deferred red:"))],
        "out_of_scope": [ln for ln in _tag_lines(text, "out-of-scope") if not ln.lower().startswith("none")],
    }


def _new_session(path: Path) -> dict:
    return {
        "id": path.stem, "malformed": 0, "reports": [], "events": [], "corrections": 0,
        "excerpts": [], "interrupts": 0, "errors": Counter(), "reverts": 0, "escalations": [],
        "humans": 0, "last_ask": False,
        "shape": {**dict.fromkeys(SHAPE_COUNTS, 0), "typed_keys": Counter()},
        # Parse-time bookkeeping, dropped before the summary is returned.
        "_sub": {}, "_agents": {}, "_seen_reports": set(),
    }


def _count_shape(entry: dict, s: dict) -> None:
    """Tally which transcript shapes this entry has (counts only, no text kept)."""
    shape = s["shape"]
    shape["entries"] += 1
    if entry.get("type") not in ("user", "assistant"):
        return
    shape["typed"] += 1
    shape["typed_keys"].update(k for k in entry if isinstance(k, str))
    message = entry.get("message")
    if isinstance(message, dict) and "content" in message:
        shape["with_message"] += 1
    result = entry.get("toolUseResult")
    if entry.get("type") == "user" and isinstance(result, dict):
        shape["result_dicts"] += 1
        if isinstance(result.get("agentType"), str):
            shape["agent_results"] += 1


def _on_assistant(entry: dict, s: dict, tools: dict, seen: set) -> None:
    content = (entry.get("message") or {}).get("content")
    text = _text_of(content).strip()
    if text:  # tool_use-only entries leave this alone
        s["last_ask"] = text.endswith("?")
    for block in content if isinstance(content, list) else []:
        if not isinstance(block, dict) or block.get("type") != "tool_use":
            continue
        s["shape"]["tool_uses"] += 1
        uid, name, inp = block.get("id"), block.get("name"), block.get("input")
        tools[uid] = name
        if uid in seen:  # the same message is re-emitted as tool results resolve
            continue
        seen.add(uid)
        inp = inp if isinstance(inp, dict) else {}
        if name in ("Agent", "Task") and isinstance(inp.get("subagent_type"), str):
            s["_sub"][uid] = inp["subagent_type"]
            s["events"].append(("dispatch", inp["subagent_type"]))
        cmd = inp.get("command")
        if name == "Bash" and isinstance(cmd, str) and REVERT_RE.search(cmd):
            s["reverts"] += 1


def add_report(s: dict, agent: str, text: str, agent_id: str, ts) -> None:
    """Record one agent report; an identical (agent id, text) pair counts once."""
    key = (agent_id, hashlib.sha1(" ".join(text.split()).encode("utf-8", "replace")).hexdigest())
    if key in s["_seen_reports"]:
        return
    s["_seen_reports"].add(key)
    rep = parse_report(text)
    rep.update(agent=agent, ts=ts)
    rep["flags"] = [scrub(ln, LINE_MAX) for ln in rep["flags"]]
    rep["out_of_scope"] = [scrub(ln, LINE_MAX) for ln in rep["out_of_scope"]]
    s["reports"].append(rep)
    if rep["verdict"]:
        s["events"].append(("report", agent, rep["verdict"]))


def hand_backs(text: str) -> list[tuple[str, str]]:
    """``(agent id, report text)`` for each ``[Subagent hand-back]`` in ``text``."""
    marks = list(AGENT_MSG_RE.finditer(text))
    found = []
    for i, m in enumerate(marks):
        body = text[m.end(): marks[i + 1].start() if i + 1 < len(marks) else len(text)]
        if HANDBACK_MARK in body:
            found.append((m.group(1), body.split(HANDBACK_MARK, 1)[1].replace("</agent-message>", "")))
    return found


def task_notification(text: str) -> tuple[str, str] | None:
    """``(task id, result text)`` of a task-notification that carries a verdict."""
    ident, result = TASK_ID_RE.search(text), TASK_RESULT_RE.search(text)
    if text.lstrip().startswith("<task-notification>") and ident and result and VERDICT_RE.search(result.group(1)):
        return ident.group(1), result.group(1)
    return None


def _on_user_reports(entry: dict, s: dict, result, text: str, tool_ids: list) -> bool:
    """Record any agent reports this user entry carries; True if it was agent traffic."""
    ts = entry.get("timestamp")
    if isinstance(result, dict):
        agent_id = str(result.get("agentId") or "")
        agent = result["agentType"] if isinstance(result.get("agentType"), str) else None
        agent = agent or next((s["_sub"][t] for t in tool_ids if t in s["_sub"]), None)
        if agent and agent_id:
            s["_agents"][agent_id] = agent
        if isinstance(result.get("agentType"), str) and not result.get("isAsync"):
            add_report(s, agent, _text_of(result.get("content")), agent_id, ts)
            return True
    traffic = False
    for agent_id, body in hand_backs(text):
        add_report(s, s["_agents"].get(agent_id, "unknown"), body, agent_id, ts)
        traffic = True
    note = task_notification(text)
    if note:
        add_report(s, s["_agents"].get(note[0], "unknown"), note[1], note[0], ts)
    return traffic or "<agent-message" in text or text.lstrip().startswith("<task-notification>")


def _on_human(text: str, s: dict) -> None:
    text = text.strip()
    if text.startswith("[Request interrupted by user"):
        s["interrupts"] += 1
    elif text and not text.startswith("<"):  # a ``<...>`` wrapper is not typed by the user
        s["humans"] += 1
        if s["humans"] == 1:  # the task prompt, not a reaction
            return
        # a bare "no" to a question is a decision, not a correction
        if CORRECTION_RE.match(text) or (NO_RE.match(text) and not s["last_ask"]):
            s["corrections"] += 1
            if len(s["excerpts"]) < MAX_EXCERPTS:
                s["excerpts"].append(scrub(text))


def _on_user(entry: dict, s: dict, tools: dict) -> None:
    result = entry.get("toolUseResult")
    content = (entry.get("message") or {}).get("content")
    results = [b for b in content if isinstance(b, dict) and b.get("type") == "tool_result"] if isinstance(content, list) else []
    text = _text_of(content)
    agent_traffic = _on_user_reports(entry, s, result, text, [b.get("tool_use_id") for b in results])
    s["shape"]["tool_results"] += len(results)
    for block in results:
        text = _text_of(block.get("content"))
        if REJECTION_RE.match(text) and "the user said:" in text.lower():  # a rejection with a reason
            s["corrections"] += 1
        if block.get("is_error") is True and not REJECTION_RE.match(text):
            s["errors"][(str(tools.get(block.get("tool_use_id"), "unknown")), error_signature(text))] += 1
    if not results and result is None and not entry.get("isMeta") and not agent_traffic:
        _on_human(text, s)


def parse_session(path: Path) -> dict:
    """Stream one transcript into a per-session summary (no raw text kept)."""
    s, tools, seen = _new_session(path), {}, set()
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                entry = None
            if not isinstance(entry, dict):
                s["malformed"] += 1
                continue
            _count_shape(entry, s)
            if entry.get("type") == "assistant":
                _on_assistant(entry, s, tools, seen)
            elif entry.get("type") == "user":
                _on_user(entry, s, tools)
    s["escalations"] = find_escalations(s["events"])
    for private in ("_sub", "_agents", "_seen_reports"):
        del s[private]
    return s
