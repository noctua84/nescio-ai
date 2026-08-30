#!/usr/bin/env python3
"""Apply or revert the optional Graeco-Roman philosopher theme for the crew.

The default agent names are functional (planner / advisor / reviewer / critic
/ builder). This renames those agents to philosophers (and back) — the agent
files, their ``name:`` frontmatter, and every cross-reference in the crew
(charters + the orchestrator's ``subagent_type`` dispatches). Seven files are
renamed: the five word pairs plus the builder's two cost tiers
(``builder-simple`` / ``builder-standard``). The remaining agents
(orchestrator, scout, validator, librarian, explore, vision, test-writer,
qa-guard, doc-researcher, doc-writer) are already functional and are left
untouched.

    python scripts/apply_theme.py philosophers   # planner->plato, advisor->aristotle,
                                                  #  reviewer->pyrrho, critic->socrates,
                                                  #  builder->archimedes
                                                  #  (+ builder-simple/-standard)
    python scripts/apply_theme.py functional      # revert to the default names
    python scripts/apply_theme.py --dry-run philosophers

Idempotent: a no-op if the crew is already on the requested theme. The rename is
word-boundary and case-aware, so it updates ``critic``/``Critic`` but preserves
the word "Socratic" (the critic's method) when reverting.

The roster itself lives in ``_crew_common``, not here — see that module's
docstring. This script declares no roster facts of its own.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Works whether this file is run as a script, imported by the tests (which put
# scripts/ on the path themselves), or collected under PYTHONPATH=scripts in CI.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _crew_common import PAIRS, THEMES, renamed_agents  # noqa: E402


def detect_theme(agents_dir: Path) -> str | None:
    """Which theme is currently on disk (by a representative agent file)?"""
    if (agents_dir / "plato.md").exists():
        return "philosophers"
    if (agents_dir / "planner.md").exists():
        return "functional"
    return None


def _mappings(target: str) -> list[tuple[str, str]]:
    """(from, to) word pairs for the requested direction, in every covered casing.

    Three variants per pair, because charters write these names three ways and
    a casing with no rule is a name that silently survives the rename:

    * lowercase — ``subagent_type: planner``, ``name:`` frontmatter, prose.
    * Capitalised — sentence-initial prose, headings ("The Planner").
    * UPPERCASE — shouted directives. ``agents/planner.md`` carries two
      ("**YOU ARE A PLANNER...**"), and without the ``.upper()`` rule the
      philosopher tree shipped a ``plato.md`` still declaring itself a
      PLANNER. That leak was invisible to the round-trip test because it is
      symmetric: the reverse leg leaves the same word alone, so the tree
      restores byte-for-byte over a broken intermediate state.

    Still uncovered: **intercaps** — a term written ``QA-guard`` or ``docWriter``
    matches no rule here. Harmless today, since no such spelling exists for any
    term in ``PAIRS``; it becomes live the moment a mixed-case agent name (e.g.
    ``qa-guard``) is mapped to a philosopher. ``ThemeCasingCoverageTest`` in
    tests/test_apply_theme.py is the guard that will notice.
    """
    base = [(f, p) for f, p in PAIRS] if target == "philosophers" else [(p, f) for f, p in PAIRS]
    out: list[tuple[str, str]] = []
    for a, b in base:
        out.append((a, b))
        out.append((a.capitalize(), b.capitalize()))
        out.append((a.upper(), b.upper()))
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
    file_renames = renamed_agents(target)

    # 1) rewrite cross-references in every agent charter (incl. orchestrator dispatch).
    #
    # newline="" on both ends disables universal-newline translation, so a
    # charter keeps the line endings it had. Without it `write_text` expands
    # "\n" to os.linesep, which on Windows rewrote every LF charter as CRLF —
    # dirtying a tree that .gitattributes pins to `eol=lf`, and making the
    # advertised round trip non-identical on disk.
    changed = 0
    for md in sorted(agents_dir.glob("*.md")):
        text = md.read_text(encoding="utf-8", newline="")
        new = _transform(text, mappings)
        if new != text:
            changed += 1
            if dry_run:
                print(f"  would update refs in {md.name}")
            else:
                md.write_text(new, encoding="utf-8", newline="")

    # 2) rename the seven agent files (five pairs + the two builder tiers).
    #
    # The tiers must be renamed here as well as rewritten above: `-` is a
    # non-word character, so the `\bbuilder\b` rule already rewrote
    # `name: builder-simple` to `name: archimedes-simple`. Without the matching
    # file rename the charter's name and its filename desync and the agent
    # stops loading entirely.
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
