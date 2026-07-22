#!/usr/bin/env python3
"""Apply or revert the optional Graeco-Roman philosopher theme for the crew.

The default agent names are functional (planner / advisor / reviewer / critic).
This renames the four thinker/advisor agents to philosophers (and back) — the
agent files, their ``name:`` frontmatter, and every cross-reference in the crew
(charters + the orchestrator's ``subagent_type`` dispatches). The other agents
(orchestrator, scout, validator, librarian, explore, vision) are already
functional and are left untouched.

    python scripts/apply_theme.py philosophers   # planner->plato, advisor->aristotle,
                                                  #  reviewer->pyrrho, critic->socrates
    python scripts/apply_theme.py functional      # revert to the default names
    python scripts/apply_theme.py --dry-run philosophers

Idempotent: a no-op if the crew is already on the requested theme. The rename is
word-boundary and case-aware, so it updates ``critic``/``Critic`` but preserves
the word "Socratic" (the critic's method) when reverting.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# functional (default)  <->  philosopher
PAIRS = [
    ("planner", "plato"),
    ("advisor", "aristotle"),
    ("reviewer", "pyrrho"),
    ("critic", "socrates"),
]
THEMES = ("functional", "philosophers")


def detect_theme(agents_dir: Path) -> str | None:
    """Which theme is currently on disk (by a representative agent file)?"""
    if (agents_dir / "plato.md").exists():
        return "philosophers"
    if (agents_dir / "planner.md").exists():
        return "functional"
    return None


def _mappings(target: str) -> list[tuple[str, str]]:
    """(from, to) word pairs for the requested direction, both cases."""
    base = [(f, p) for f, p in PAIRS] if target == "philosophers" else [(p, f) for f, p in PAIRS]
    out: list[tuple[str, str]] = []
    for a, b in base:
        out.append((a, b))
        out.append((a.capitalize(), b.capitalize()))
    return out


def _transform(text: str, mappings: list[tuple[str, str]]) -> str:
    for a, b in mappings:
        text = re.sub(rf"\b{re.escape(a)}\b", b, text)
    return text


def apply_theme(agents_dir: Path, target: str, *, dry_run: bool = False) -> int:
    if target not in THEMES:
        print(f"error: unknown theme {target!r} (expected one of {THEMES})", file=sys.stderr)
        return 2
    current = detect_theme(agents_dir)
    if current is None:
        print(f"error: could not detect the crew in {agents_dir} "
              "(neither planner.md nor plato.md found)", file=sys.stderr)
        return 2
    if current == target:
        print(f"already on the '{target}' theme — nothing to do.")
        return 0

    mappings = _mappings(target)
    file_renames = ([(f, p) for f, p in PAIRS] if target == "philosophers"
                    else [(p, f) for f, p in PAIRS])

    # 1) rewrite cross-references in every agent charter (incl. orchestrator dispatch).
    changed = 0
    for md in sorted(agents_dir.glob("*.md")):
        text = md.read_text(encoding="utf-8")
        new = _transform(text, mappings)
        if new != text:
            changed += 1
            if dry_run:
                print(f"  would update refs in {md.name}")
            else:
                md.write_text(new, encoding="utf-8")

    # 2) rename the four agent files.
    for frm, to in file_renames:
        src, dst = agents_dir / f"{frm}.md", agents_dir / f"{to}.md"
        if not src.exists():
            print(f"  ! expected {src.name} not found — skipping", file=sys.stderr)
            continue
        if dry_run:
            print(f"  would rename {src.name} -> {dst.name}")
        else:
            src.rename(dst)
            print(f"  renamed {src.name} -> {dst.name}")

    verb = "would switch" if dry_run else "switched"
    print(f"\n{verb} crew: {current} -> {target} ({changed} file(s) had refs updated).")
    if not dry_run:
        print("If this repo is a git checkout, review with `git status` / `git diff` and commit.")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Apply/revert the philosopher theme for the crew.")
    ap.add_argument("theme", choices=THEMES, help="target theme")
    ap.add_argument("--dry-run", action="store_true", help="preview without writing")
    ap.add_argument("--agents-dir", type=Path,
                    default=Path(__file__).resolve().parent.parent / "agents",
                    help="path to the agents/ directory (default: repo agents/)")
    args = ap.parse_args(argv)
    return apply_theme(args.agents_dir, args.theme, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
