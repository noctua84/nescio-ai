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

Idempotent: a no-op if the crew is already on the requested theme *and* the tree
is consistent. If a charter's ``name:`` frontmatter disagrees with its filename
— the state an older build of this script left behind, in which such an agent
does not load at all — re-running converges the tree instead of reporting
success. The rename is word-boundary and case-aware, so it updates
``critic``/``Critic`` but preserves the word "Socratic" (the critic's method)
when reverting.

All-or-nothing: every rename destination is checked before anything is written,
so a name already taken by another file exits 2 with the tree untouched rather
than clobbering it (POSIX) or aborting half-applied (Windows).

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

# The YAML frontmatter block at the top of every agent charter.
_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def detect_theme(agents_dir: Path) -> str | None:
    """Which theme is currently on disk (by a representative agent file)?

    A *representative* file, deliberately: this answers "which direction did the
    last run go", not "is the tree consistent". A tree half-converted by an
    older build of this script still answers "philosophers" here — see
    ``desynced_agents``, which is what the no-op path must consult before
    believing this.
    """
    if (agents_dir / "plato.md").exists():
        return "philosophers"
    if (agents_dir / "planner.md").exists():
        return "functional"
    return None


def _frontmatter_name(text: str) -> str | None:
    """The ``name:`` a charter declares, or None if it declares none."""
    block = _FRONTMATTER_RE.match(text)
    if block is None:
        return None
    for line in block.group(1).splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip() == "name":
            return value.strip()
    return None


def desynced_agents(agents_dir: Path) -> list[tuple[str, str | None]]:
    """(filename, declared name) for every charter whose ``name:`` != its stem.

    A charter whose frontmatter name disagrees with its filename does not load
    at all, so this is the tree's real consistency oracle — per file, against
    itself, with no roster constant taking part.

    Its purpose is to keep ``apply_theme`` from trusting ``detect_theme`` alone.
    An older build of this script renamed only five of the seven files, so a
    tree it touched has ``builder-simple.md`` declaring ``archimedes-simple``
    while ``plato.md`` sits next to it. ``detect_theme`` reports "philosophers"
    and the no-op path used to short-circuit on that — reporting success while
    leaving two agents silently non-loading, with re-running the *fixed* script
    the obvious remedy that also did nothing.
    """
    out: list[tuple[str, str | None]] = []
    for md in sorted(agents_dir.glob("*.md")):
        declared = _frontmatter_name(md.read_text(encoding="utf-8", newline=""))
        if declared != md.stem:
            out.append((md.name, declared))
    return out


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
    mappings = _mappings(target)
    file_renames = renamed_agents(target)

    # The no-op path is conditional on the tree being *consistent*, not merely
    # on it pointing the right way. `detect_theme` classifies from one
    # representative file, so a tree an older build left half-converted reports
    # `current == target` while carrying charters whose `name:` disagrees with
    # their filename — agents that do not load. Short-circuiting there reported
    # success and repaired nothing, and re-running was the obvious remedy.
    #
    # Converging such a tree needs no separate repair path: every step below is
    # idempotent over an already-converted file (`_transform`'s `\b` rules do
    # not match a name that is already themed, and the rename loop skips a
    # source that no longer exists), so the ordinary pass fixes exactly the
    # stragglers and leaves the rest byte-identical.
    repairing = current == target
    if repairing:
        desynced = desynced_agents(agents_dir)
        if not desynced:
            print(f"already on the '{target}' theme — nothing to do.")
            return 0
        print(f"already on the '{target}' theme, but {len(desynced)} file(s) declare a "
              "`name:` that disagrees with their filename — converging:")
        for name, declared in desynced:
            print(f"  ! {name} declares `name: {declared}` — does not load")

    # Pre-flight every rename before writing anything.
    #
    # `Path.rename` raises FileExistsError on Windows and *silently clobbers* on
    # POSIX. Because the text rewrite below completes in full before the first
    # rename, a conflict discovered mid-loop would leave every charter rewritten
    # and only some files renamed — a state that re-crashes at the same file on
    # every later run, since `detect_theme` still reports the target theme.
    # So the check runs first and the whole operation refuses as a unit: on a
    # conflict nothing has been written, in dry-run mode or otherwise.
    conflicts = [
        (src, dst)
        for src, dst in ((agents_dir / f"{frm}.md", agents_dir / f"{to}.md")
                         for frm, to in file_renames)
        if src.exists() and dst.exists() and dst != src
    ]
    if conflicts:
        print(f"error: cannot switch to '{target}' — {len(conflicts)} rename destination(s) "
              "already exist:", file=sys.stderr)
        for src, dst in conflicts:
            print(f"  ! {src.name} -> {dst.name} (destination exists)", file=sys.stderr)
        print("no files were changed. Remove or rename the destination(s) and re-run.",
              file=sys.stderr)
        return 2

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
            # On a repair pass most sources are legitimately gone — the earlier
            # run already renamed them, which is why only the stragglers remain.
            # Warning on those would put five "expected X not found" lines on
            # stderr for every successful repair. A pair with *neither* file
            # present is still a real gap, and still warns.
            if not (repairing and dst.exists()):
                print(f"  ! expected {src.name} not found — skipping", file=sys.stderr)
            continue
        if dry_run:
            print(f"  would rename {src.name} -> {dst.name}")
        else:
            src.rename(dst)
            print(f"  renamed {src.name} -> {dst.name}")

    if repairing:
        verb = "would converge" if dry_run else "converged"
        print(f"\n{verb} crew onto the '{target}' theme "
              f"({changed} file(s) had refs updated).")
    else:
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
