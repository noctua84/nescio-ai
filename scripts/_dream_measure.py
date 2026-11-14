"""Effectiveness tracking for ``dream.py``: did a promoted note stop its signal recurring?

Each dream run leaves a ``<stem>.json`` sidecar next to its proposal listing
*every* signal it saw (id, key, distinct sessions) and how many sessions it read.
``--link HASH12 SIG_ID`` records, in ``links.json`` beside the sidecars, that the
ledger note ``HASH12`` was promoted because of signal ``SIG_ID``; ``--compare``
then sets the signal's per-session rate in the runs before the note's date
against the runs after it.

Deliberate design decisions, each with a failure mode behind it:

  * **Machine-local, never the tracked ledger.** A signal key can carry private
    tool or command text; the link file lives in the dream state dir with the
    proposals, so none of it reaches a synced repo.

  * **Overlapping runs are dropped, not summed.** A ``--no-stamp`` rerun re-reads
    the same window; counting both would double its sessions. A run is kept only
    if its window starts at or after the last kept run's end.

  * **Runs straddling the note date are excluded.** Their sessions are a mix of
    before and after; assigning them to either side would blur the comparison.

  * **A signal absent from the baseline is ``no baseline``, not ``ineffective``.**
    ``0 >= 0`` would otherwise read as "did not drop" for a pattern that never
    occurred. Likewise a corrupt ``links.json`` is refused, never overwritten.

  * **Reads only the sidecars.** It never runs the extractor or moves the
    watermark, and a sidecar that is unreadable or has another schema is
    counted and skipped rather than failing the comparison.

This is a trend aid, not a controlled experiment: usage mix shifts week to week.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from _learning_common import parse_ledger

SCHEMA = 1
LINKS_NAME = "links.json"
RESERVED = {LINKS_NAME, "last-dream.json"}  # state files that share the dir with sidecars
HASH_RE = re.compile(r"^[0-9a-f]{12}$")
SIG_RE = re.compile(r"^[0-9a-f]{8}$")
KEY_WIDTH = 60


def parse_ts(text: str) -> datetime:
    """ISO date or datetime (``Z`` ok) as an aware UTC datetime; ``ValueError`` if not."""
    dt = datetime.fromisoformat(str(text).strip().replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _n(value) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def load_runs(state_dir: Path) -> tuple[list[dict], int]:
    """``(runs, skipped)``: every readable schema-1 sidecar in ``state_dir``.

    A run is ``{"file", "since", "until", "sessions_read", "signals"}`` with the
    two bounds parsed. Unreadable, malformed or other-schema files are counted
    in ``skipped``; the watermark and link files are not sidecars and not counted.
    """
    runs, skipped = [], 0
    for f in sorted(state_dir.glob("*.json")) if state_dir.is_dir() else []:
        if f.name in RESERVED:
            continue
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            if not isinstance(d, dict) or d.get("schema") != SCHEMA or not isinstance(d.get("signals"), dict):
                raise ValueError("schema")
            run = {"file": f.name, "since": parse_ts(d["since"]), "until": parse_ts(d["until"]),
                   "sessions_read": _n(d.get("sessions_read")), "signals": d["signals"]}
            if run["until"] < run["since"] or not all(isinstance(v, dict) for v in run["signals"].values()):
                raise ValueError("shape")
        except (OSError, ValueError, KeyError, TypeError):
            skipped += 1
            continue
        runs.append(run)
    return runs, skipped


def select_runs(runs: list[dict]) -> list[dict]:
    """Runs by ``until``, dropping any whose window overlaps an earlier kept run."""
    kept: list[dict] = []
    for run in sorted(runs, key=lambda r: (r["until"], r["since"], r["file"])):
        if not kept or run["since"] >= kept[-1]["until"]:
            kept.append(run)
    return kept


def load_links(state_dir: Path) -> list[dict]:
    """The ``links.json`` entries ({hash, sig, linked_at}); ``[]`` if absent, ``ValueError`` if corrupt."""
    path = state_dir / LINKS_NAME
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ValueError(f"{LINKS_NAME} is unreadable: {e}") from e
    if not isinstance(data, list):
        raise ValueError(f"{LINKS_NAME} is not a JSON list")
    return [x for x in data if isinstance(x, dict) and isinstance(x.get("hash"), str) and isinstance(x.get("sig"), str)]


def add_link(state_dir: Path, note_hash: str, sig: str, now: datetime) -> bool:
    """Append a link unless the (hash, sig) pair is already there; True if added."""
    links = load_links(state_dir)
    if any(x["hash"] == note_hash and x["sig"] == sig for x in links):
        return False
    links.append({"hash": note_hash, "sig": sig, "linked_at": now.strftime("%Y-%m-%dT%H:%M:%SZ")})
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / LINKS_NAME).write_text(json.dumps(links, indent=2), encoding="utf-8", newline="")
    return True


def _side(runs: list[dict], sig: str) -> dict:
    sessions = sum(r["sessions_read"] for r in runs)
    hit = sum(_n(r["signals"].get(sig, {}).get("sessions")) for r in runs)
    return {"runs": len(runs), "sessions": sessions, "signal_sessions": hit, "rate": hit / sessions if sessions else None}


def verdict(before: dict, after: dict, min_after: int) -> str:
    """``no baseline`` / ``too early`` / ``working`` / ``ineffective`` / ``unclear``."""
    if not before["sessions"] or not before["signal_sessions"]:
        return "no baseline"
    if after["sessions"] < min_after:
        return "too early"
    if after["rate"] <= 0.5 * before["rate"]:
        return "working"
    return "ineffective" if after["rate"] >= before["rate"] else "unclear"


def compare(runs: list[dict], links: list[dict], ledger_dates: dict[str, str], min_after: int = 10) -> list[dict]:
    """One result per link; ``runs`` should already be through ``select_runs``.

    The note date is the ledger date for the hash, else the link's ``linked_at``
    (``date_source`` says which). Before = runs ending at or before it, after =
    runs starting at or after it; straddling runs count for neither.
    """
    results = []
    for link in links:
        sig, date, source = link["sig"], None, "ledger"
        try:
            date = parse_ts(ledger_dates[link["hash"]])
        except (KeyError, ValueError):
            source = "linked_at"
            try:
                date = parse_ts(link.get("linked_at", ""))
            except ValueError:
                pass
        key = next((r["signals"][sig].get("key") for r in reversed(runs) if sig in r["signals"]), None)
        res = {"hash": link["hash"], "sig": sig, "key": key if isinstance(key, str) else None,
               "date": date.strftime("%Y-%m-%d") if date else None, "date_source": source}
        if date is None:
            res.update(before=None, after=None, verdict="no date")
        else:
            before = _side([r for r in runs if r["until"] <= date], sig)
            after = _side([r for r in runs if r["since"] >= date], sig)
            res.update(before=before, after=after, verdict=verdict(before, after, min_after))
        results.append(res)
    return results


def _cell(side: dict | None) -> str:
    if not side or side["rate"] is None:
        return f"n/a ({side['sessions'] if side else 0} sessions)"
    return f"{side['rate']:.0%} ({side['sessions']} sessions)"


def render(results: list[dict]) -> str:
    """Markdown table of the results, with a note for any date taken from ``linked_at``."""
    if not results:
        return "No links recorded. Use `--link HASH12 SIG_ID` after promoting a note.\n"
    rows = ["| Note | Signal | Before | After | Verdict |", "|---|---|---|---|---|"]
    for r in results:
        key = (r["key"] or "(not seen in any run)").replace("|", "\\|")
        key = key if len(key) <= KEY_WIDTH else key[: KEY_WIDTH - 1] + "…"
        rows.append(f"| {r['hash']} | {key} | {_cell(r['before'])} | {_cell(r['after'])} | {r['verdict']} |")
    rows += [
        f"- {r['hash']}: not in the ledger; used the link date {r['date'] or '(unparseable)'} as the note date."
        for r in results if r["date_source"] == "linked_at"
    ]
    return "\n".join(rows) + "\n"


def run_link(state_dir: Path, note_hash: str, sig: str, now: datetime) -> int:
    """Validate and record a link; rc 2 on a bad argument or a corrupt link file."""
    if not HASH_RE.match(note_hash) or not SIG_RE.match(sig):
        print("error: HASH12 must be 12 lowercase hex characters and SIG_ID 8 lowercase hex characters.")
        return 2
    try:
        added = add_link(state_dir, note_hash, sig, now)
    except ValueError as e:
        print(f"error: {e}; fix or remove it before linking.")
        return 2
    print(f"linked {note_hash} to signal {sig}" if added else f"already linked: {note_hash} to signal {sig}")
    return 0


def run_compare(state_dir: Path, ledger: Path, min_after: int, as_json: bool) -> int:
    """Print the comparison for every link; never runs the extractor or moves the watermark."""
    try:
        links = load_links(state_dir)
    except ValueError as e:
        print(f"error: {e}")
        return 2
    runs, skipped = load_runs(state_dir)
    kept = select_runs(runs)
    ledger_dates = {h: date for h, (date, _target) in parse_ledger(ledger).items()}
    results = compare(kept, links, ledger_dates, min_after)
    if as_json:
        print(json.dumps(results, indent=2))
    else:
        print(render(results), end="")
        print(f"\nRuns used: {len(kept)}; dropped as overlapping: {len(runs) - len(kept)}; unreadable or other schema: {skipped}.")
    return 0
