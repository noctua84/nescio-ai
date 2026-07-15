#!/usr/bin/env python3
"""Promote a reviewed adopt-run to the archive and record it in the ledger.

Stage 2 of the adoption flow. After you've reviewed `eval/adopt/<ts>/` and
integrated the worthwhile parts into the repo, run:

    python scripts/mark_adopted.py <ts> --status integrated --note "what you did"

It moves `eval/adopt/<ts>/` -> `eval/adopted/<ts>/` and appends one ledger line
per staged item to `memory/adoption-log.md`, so future scans skip these hashes.

--status is the disposition for the whole run (per-item nuance goes in --note or
by hand-editing the ledger afterwards):
  integrated  merged into the repo            (terminal — skipped on future scans)
  no-change   reviewed, nothing to merge      (terminal)
  dropped     reviewed, deliberately discarded (terminal)
  pending     still needs work                (re-surfaces on future scans)
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime

from _adopt_common import ADOPT, ADOPTED, LEDGER, MAX_LEDGER_LINES, TERMINAL


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("timestamp", help="run folder under eval/adopt/ (e.g. 20260709-101500)")
    ap.add_argument("--status", default="integrated",
                    choices=sorted(TERMINAL | {"pending"}),
                    help="integrated | no-change | dropped | pending")
    ap.add_argument("--note", default="", help="short note appended to each ledger line")
    args = ap.parse_args()

    src = ADOPT / args.timestamp
    if not src.is_dir():
        print(f"error: no such run: {src}")
        return 1
    sources_file = src / "sources.json"
    if not sources_file.is_file():
        print(f"error: {sources_file} missing — was this staged by adopt_existing_config.py?")
        return 1

    records = json.loads(sources_file.read_text(encoding="utf-8"))
    date = datetime.now().strftime("%Y-%m-%d")
    note = f": {args.note}" if args.note else f": {args.status}"
    new_lines = [
        f"- {date} | {r['source']} | {r['sha8']} | {args.status}{note}"
        for r in records
    ]

    if not LEDGER.exists():
        print(f"error: {LEDGER} missing — create the ledger first.")
        return 1
    lines = LEDGER.read_text(encoding="utf-8").splitlines()
    for rec, new in zip(records, new_lines):
        tag = f"| {rec['sha8']} |"
        for i in range(len(lines) - 1, -1, -1):
            if tag in lines[i]:
                lines[i] = new        # update the LAST existing entry (parse_ledger() treats it as canonical)
                break
        else:
            lines.append(new)        # new content — append
    LEDGER.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Archive the run.
    ADOPTED.mkdir(parents=True, exist_ok=True)
    dest = ADOPTED / args.timestamp
    if dest.exists():
        shutil.rmtree(dest)
    shutil.move(str(src), str(dest))

    total = sum(1 for ln in LEDGER.read_text(encoding="utf-8").splitlines() if ln.startswith("- "))
    print(f"Recorded {len(new_lines)} item(s) as '{args.status}'. Archived -> {dest}")
    if args.status in TERMINAL:
        print("These hashes will be skipped on future scans.")
    file_lines = len(LEDGER.read_text(encoding="utf-8").splitlines())
    if file_lines > MAX_LEDGER_LINES:
        print(f"\n⚠  {LEDGER.name} is {file_lines} lines (> {MAX_LEDGER_LINES}). "
              f"Compact the oldest entries into a one-line summary to stay under the cap.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
