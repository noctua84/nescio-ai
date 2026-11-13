"""Fold parsed sessions into a dream proposal's data: recurring signals, drift and the sidecar table.

Split from ``dream.py`` at the aggregate -> render seam. Everything here takes
the per-session summaries ``_dream_parse.parse_session`` returns (optionally
carrying ``sub`` from ``_dream_inputs.parse_subagents``) and returns plain
dicts; it reads no files and writes nothing. ``dream.py`` re-exports these
names and owns rendering, discovery and the CLI.

Every recurring signal carries a stable ``id`` (``signal_id`` of its key), and
``signal_table`` lists *every* signal seen, so ``--compare`` never reads a
signature that fell out of the top-N as zero. Keys are built from
already-scrubbed text only.
"""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict

from _dream_inputs import SEVERITIES
from _dream_parse import MAX_EXCERPTS, SHAPE_COUNTS, scrub
from _dream_testruns import AFTER_FAIL_KEYS, add_counts, empty_counts

TOP_ERRORS = 5
TIER_NAMES = ("simple", "standard", "complex")
# Recurring subagent test-run kinds: (kind, summary template); the count comes from ``_session_kind_counts``.
TEST_KINDS = (
    ("test-retry-no-edit", "{} failing subagent test runs rerun with no edit seen between"),
    ("test-not-rerun", "{} failing subagent test runs never rerun"),
    ("test-failure-masked", "{} subagent test failures hidden by a zero exit status"),
    ("complete-on-red", "{} COMPLETE subagent reports whose last test run failed"),
)


# Top-level transcript-entry keys seen in practice; a key outside this set on most entries is reported as drift.
KNOWN_KEYS = frozenset({
    "type", "message", "uuid", "parentUuid", "isSidechain", "userType", "cwd", "sessionId", "version", "gitBranch",
    "timestamp", "requestId", "toolUseResult", "sourceToolAssistantUUID", "isMeta", "promptId", "entrypoint", "slug",
    "effort", "perTurnEffort", "advisorModel", "apiBlockIndex", "rendered", "renderedRole", "requestedModel",
    "serverClassifierRequest", "serverClassifierContext", "wireToolInputs", "requestRef", "isCompactSummary",
    "isVisibleInTranscriptOnly", "thinkingMetadata", "todos", "permissionMode", "level", "subtype", "content",
    "isApiErrorMessage", "error", "origin", "imagePasteIds",
})


def drift_warnings(shape: dict) -> list[str]:
    """One-line warnings when the transcript shapes the parser relies on look different.

    ``shape`` is ``aggregate()["shape"]``. A format change must not read as "zero signals".
    """
    typed = shape["typed"]
    found = []
    if shape["entries"] > 0 and typed == 0:
        found.append("No user/assistant entries found; the `type` field may have changed.")
    if typed > 0 and shape["with_message"] < typed / 2:
        found.append("Most user/assistant entries lack `message.content`; the message shape may have changed.")
    if typed >= 50 and shape["tool_uses"] == 0:
        found.append("No `tool_use` blocks found in a large transcript sample; the content-block shape may have changed.")
    if shape["tool_results"] > 0 and shape["result_dicts"] == 0:
        found.append("Tool results seen but no `toolUseResult` dicts; the field may have changed.")
    if shape["agent_dispatches"] > 0 and shape["agent_reports"] == 0:
        found.append("Agent dispatches seen but no agent reports parsed; the report shape may have changed.")
    if shape["agent_results"] > 0 and shape["agent_dispatches"] == 0:
        found.append("Agent results seen but no Agent/Task dispatches; the dispatch tool may have been renamed.")
    if shape["unknown_keys"]:
        found.append(f"New top-level keys on most entries: {', '.join(shape['unknown_keys'])} (informational).")
    return found


def total_shape(sessions: list[dict], key: str) -> int:
    return sum(s["shape"][key] for s in sessions)


def _subagent_rollup(sessions: list[dict]) -> tuple[list, dict, dict]:
    """``(ranked errors, reruns, read/skipped/malformed)`` over the sessions' optional ``sub`` summaries."""
    errs: dict[tuple, list] = defaultdict(lambda: [set(), 0])
    by_agent: Counter = Counter()
    rerun_ids: set = set()
    totals = {"read": 0, "skipped": 0, "malformed": 0}
    for s in sessions:
        sub = s.get("sub")
        if not sub:
            continue
        totals["read"] += sub["files"]
        totals["skipped"] += sub["skipped"]
        totals["malformed"] += sub["malformed"]
        for key, n in sub["errors"].items():
            errs[key][0].add(s["id"])
            errs[key][1] += n
        if sub["reruns"] > 0:
            rerun_ids.add(s["id"])
            by_agent.update(sub["rerun_agents"])
    top = sorted(errs.items(), key=lambda kv: (-len(kv[1][0]), -kv[1][1], kv[0]))[:TOP_ERRORS]
    reruns = {"count": sum(by_agent.values()), "sessions": len(rerun_ids), "by_agent": dict(sorted(by_agent.items()))}
    return top, reruns, totals


def _session_kind_counts(sub: dict) -> dict:
    """``{kind: n}`` for one session's ``sub`` summary; ``TEST_KINDS`` keys, zero when absent."""
    tot = empty_counts()
    for c in (sub.get("tests_by_agent") or {}).values():
        add_counts(tot, c)
    return {
        "test-retry-no-edit": tot["after_fail"]["retried_no_edit"], "test-not-rerun": tot["after_fail"]["not_rerun"],
        "test-failure-masked": tot["masked"], "complete-on-red": sub.get("complete_on_red", 0),
    }


def _test_rollup(sessions: list[dict]) -> tuple[dict, dict]:
    """``(subagent_tests, {kind: (session ids, count)})`` over the sessions' optional ``sub`` summaries."""
    totals, by_agent, red_agents = empty_counts(), {}, Counter()
    red_ids: set = set()
    per_kind: dict[str, tuple[set, int]] = {k: (set(), 0) for k, _ in TEST_KINDS}
    for s in sessions:
        sub = s.get("sub")
        if not sub:
            continue
        for agent, c in (sub.get("tests_by_agent") or {}).items():
            add_counts(totals, c)
            add_counts(by_agent.setdefault(agent, empty_counts()), c)
        red_agents.update(sub.get("complete_on_red_agents") or {})
        for kind, n in _session_kind_counts(sub).items():
            if n > 0:
                ids, total_n = per_kind[kind]
                ids.add(s["id"])
                per_kind[kind] = (ids, total_n + n)
    fix = lambda c: {**c, "after_fail": {k: c["after_fail"][k] for k in AFTER_FAIL_KEYS}}  # noqa: E731
    tests = {
        "totals": fix(totals), "by_agent": {a: fix(c) for a, c in sorted(by_agent.items())},
        "complete_on_red": {
            "count": per_kind["complete-on-red"][1], "sessions": len(per_kind["complete-on-red"][0]),
            "by_agent": dict(sorted(red_agents.items())),
        },
    }
    return tests, per_kind


def signal_id(key: str) -> str:
    """Stable 8-hex id of a signal key; independent of counts, so it survives across runs."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:8]


def _esc_key(fam: str, t1: int, t2: int) -> str:
    return f"escalation:{scrub(fam, 80)}:{TIER_NAMES[t1]}->{TIER_NAMES[t2]}"


def _err_key(tool: str, sig: str) -> str:
    return f"tool-error:{scrub(tool, 80)}:{sig}"


def _sub_err_key(agent: str, tool: str, sig: str) -> str:
    return f"subagent-tool-error:{scrub(agent, 80)}:{scrub(tool, 80)}:{sig}"


def signal_table(sessions: list[dict]) -> dict:
    """``{sig_id: {key, sessions, count}}`` for *every* signal seen in at least one session.

    Unlike ``aggregate``'s top-N and ``--min-sessions`` cuts, nothing is dropped:
    a signature that slips out of the top 5 must not read as zero to ``--compare``.
    Keys are built from already-scrubbed text only.
    """
    seen: dict[str, list] = defaultdict(lambda: [set(), 0])

    def add(key: str, sid: str, n: int) -> None:
        seen[key][0].add(sid)
        seen[key][1] += n

    for s in sessions:
        for rep in s["reports"]:
            if rep["verdict"] in ("BLOCKED", "PARTIAL"):
                add(f"{rep['verdict'].lower()}:{scrub(rep['agent'], 80)}", s["id"], 1)
            pins = sum(1 for t in rep["flags"] if t.startswith("Inverted pin:"))
            if pins:
                add("inverted-pins", s["id"], pins)
        for fam, t1, t2 in s["escalations"]:
            add(_esc_key(fam, t1, t2), s["id"], 1)
        for (tool, sig), n in s["errors"].items():
            add(_err_key(tool, sig), s["id"], n)
        for key in ("corrections", "reverts", "interrupts"):
            if s[key]:
                add(key, s["id"], s[key])
        sub = s.get("sub")
        if sub:
            for (agent, tool, sig), n in sub["errors"].items():
                add(_sub_err_key(agent, tool, sig), s["id"], n)
            if sub["reruns"] > 0:
                add("subagent-reruns", s["id"], sub["reruns"])
            for kind, n in _session_kind_counts(sub).items():
                if n > 0:
                    add(kind, s["id"], n)
    return {signal_id(k): {"key": k, "sessions": len(ids), "count": n} for k, (ids, n) in sorted(seen.items())}


def aggregate(sessions: list[dict], *, min_sessions: int = 2, skipped: int = 0, qa: list[dict] | None = None) -> dict:
    """Fold per-session summaries into the proposal's data.

    Sessions may carry an optional ``sub`` summary (``parse_subagents``) and
    ``qa`` is the optional ``qa_reports`` list; both default to "not read".
    """
    verdicts: dict[str, Counter] = defaultdict(Counter)
    esc: dict[tuple, set] = defaultdict(set)
    errs: dict[tuple, list] = defaultdict(lambda: [set(), 0])
    oos: dict[str, list] = defaultdict(lambda: [set(), ""])
    flags = []
    for s in sessions:
        for rep in s["reports"]:
            verdicts[rep["agent"]][rep["verdict"] or "none"] += 1
            flags += [{"session": s["id"], "ts": rep["ts"], "agent": rep["agent"], "text": t} for t in rep["flags"]]
            for t in rep["out_of_scope"]:
                entry = oos[" ".join(t.lower().split())]
                entry[0].add(s["id"])
                entry[1] = t
        for fam, t1, t2 in s["escalations"]:
            esc[(fam, t1, t2)].add(s["id"])
        for key, n in s["errors"].items():
            errs[key][0].add(s["id"])
            errs[key][1] += n
    top = sorted(errs.items(), key=lambda kv: (-len(kv[1][0]), -kv[1][1], kv[0]))[:TOP_ERRORS]
    having = lambda key: {s["id"] for s in sessions if s[key]}  # noqa: E731
    total = lambda key: sum(s[key] for s in sessions)  # noqa: E731
    pins = {f["session"] for f in flags if f["text"].startswith("Inverted pin:")}
    recurring = sorted(
        (
            {"kind": "escalation", "summary": f"{f}: {TIER_NAMES[a]}→{TIER_NAMES[b]}", "sessions": len(v),
             "id": signal_id(_esc_key(f, a, b))}
            for (f, a, b), v in esc.items()
        ),
        key=lambda r: r["summary"],
    )
    recurring += [
        {"kind": "tool-error", "summary": f"{t}: {sig}", "sessions": len(ids), "count": n, "id": signal_id(_err_key(t, sig))}
        for (t, sig), (ids, n) in top
    ]
    sub_top, sub_reruns, sub_totals = _subagent_rollup(sessions)
    recurring += [
        {"kind": "subagent-tool-error", "summary": f"{a} {t}: {sig}", "sessions": len(ids), "count": n,
         "id": signal_id(_sub_err_key(a, t, sig))}
        for (a, t, sig), (ids, n) in sub_top
    ]
    if sub_reruns["sessions"]:
        recurring.append({
            "kind": "subagent-reruns", "sessions": sub_reruns["sessions"],
            "summary": f"{sub_reruns['count']} identical Bash reruns in subagents", "id": signal_id("subagent-reruns"),
        })
    sub_tests, test_kinds = _test_rollup(sessions)
    recurring += [
        {"kind": kind, "summary": template.format(test_kinds[kind][1]), "sessions": len(test_kinds[kind][0]), "id": signal_id(kind)}
        for kind, template in TEST_KINDS
        if test_kinds[kind][0]
    ]
    recurring += [
        {"kind": kind, "summary": text, "sessions": len(ids), "id": signal_id(kind)}
        for kind, text, ids in (
            ("corrections", f"{total('corrections')} user corrections", having("corrections")),
            ("reverts", f"{total('reverts')} revert-style git commands", having("reverts")),
            ("inverted-pins", "inverted test pins in builder reports", pins),
        )
    ]
    shape = {k: total_shape(sessions, k) for k in SHAPE_COUNTS}
    keys = sum((s["shape"]["typed_keys"] for s in sessions), Counter())
    shape["agent_dispatches"] = sum(1 for s in sessions for e in s["events"] if e[0] == "dispatch")
    from_subs = sum((s.get("sub") or {}).get("merged", 0) for s in sessions)
    # Drift looks at the parent transcripts only: reports recovered from subagent files must not mask a parent-format change.
    shape["agent_reports"] = sum(len(s["reports"]) for s in sessions) - from_subs
    shape["unknown_keys"] = sorted(k for k, n in keys.items() if n * 2 > shape["typed"] and k not in KNOWN_KEYS)
    return {
        "sessions_read": len(sessions),
        "sessions_skipped": skipped,
        "malformed_lines": total("malformed") + sub_totals["malformed"],
        "subagents_read": sub_totals["read"],
        "subagents_skipped": sub_totals["skipped"],
        "agent_reports": shape["agent_reports"] + from_subs,
        "agent_dispatches": shape["agent_dispatches"],
        "reports_from_subagents": from_subs,
        "shape": shape,
        "drift": drift_warnings(shape),
        "min_sessions": min_sessions,
        "recurring": [r for r in recurring if r["sessions"] >= min_sessions],
        "verdicts": {a: dict(c) for a, c in sorted(verdicts.items())},
        "tool_errors": [{"tool": t, "signature": sig, "sessions": len(i), "count": n} for (t, sig), (i, n) in top],
        "subagent_errors": [
            {"agent": a, "tool": t, "signature": sig, "sessions": len(i), "count": n} for (a, t, sig), (i, n) in sub_top
        ],
        "subagent_reruns": sub_reruns,
        "subagent_tests": sub_tests,
        "qa_reports": {
            "reports": list(qa or []),
            "totals": {sev: sum(r[sev] for r in qa or []) for sev in SEVERITIES},
        },
        "corrections": {
            "count": total("corrections"),
            "sessions": len(having("corrections")),
            "excerpts": [x for s in sessions for x in s["excerpts"]][:MAX_EXCERPTS],
        },
        "interrupts": total("interrupts"),
        "reverts": {"count": total("reverts"), "sessions": len(having("reverts"))},
        "to_confirm": flags,
        "follow_ups": sorted(
            ({"text": t, "sessions": len(ids)} for ids, t in oos.values()), key=lambda f: (-f["sessions"], f["text"])
        ),
    }
