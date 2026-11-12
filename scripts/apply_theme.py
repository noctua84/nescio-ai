#!/usr/bin/env python3
"""Apply or revert the optional Graeco-Roman philosopher theme for the crew.

The default agent names are functional (planner / advisor / reviewer / critic /
builder / test-writer / qa-guard / doc-researcher / doc-writer). This renames
those agents to philosophers (and back) — the agent files, their ``name:``
frontmatter, and every cross-reference in the crew (charters + the
orchestrator's ``subagent_type`` dispatches). Eleven files are renamed: the nine
word pairs plus the builder's two cost tiers (``builder-simple`` /
``builder-standard``). The remaining agents (orchestrator, scout, validator,
librarian, explore, vision) are already functional and are left untouched.

    python scripts/apply_theme.py philosophers   # planner->plato, advisor->aristotle,
                                                  #  reviewer->pyrrho, critic->socrates,
                                                  #  builder->archimedes,
                                                  #  test-writer->euclid, qa-guard->cato,
                                                  #  doc-researcher->callimachus,
                                                  #  doc-writer->cicero
                                                  #  (+ builder-simple/-standard)
    python scripts/apply_theme.py functional      # revert to the default names
    python scripts/apply_theme.py --dry-run philosophers

Idempotent: a no-op if the crew is already on the requested theme *and* the tree
is consistent. If a charter's ``name:`` frontmatter disagrees with its filename
— the state an older build of this script left behind, in which such an agent
does not load at all — re-running converges the tree instead of reporting
success — and the convergence is verified afterwards, so a desync the theme
machinery cannot express (a hand-edited ``name:``) exits 2 naming the residue
rather than reporting a repair that did not happen. The rename is word-boundary
(``\b``), so it preserves the word "Socratic" (the critic's method) when
reverting.

**The two directions are deliberately asymmetric.**

*Forward* (``philosophers``) renames an agent name **only where it is written
as an identifier**, because functional names are also ordinary English nouns —
"architecture advisor", "Work plan reviewer", "YOU ARE A PLANNER" — and
rewriting those produced "architecture aristotle", "Work plan pyrrho", "YOU ARE
A PLATO" in routing descriptions that then named the wrong agents. An
identifier is (1) the text inside single backticks, (2) a double-quoted string
whose whole content is name-ish (``"planner"``,
``"builder | builder-standard | builder-simple"``; also inside fenced code
blocks, where the orchestrator's ``subagent_type: "..."`` dispatches live), or
(3) the frontmatter ``name:`` value. Everything else — bare words, Capitalised
or UPPERCASE words, YAML descriptions, quoted prose — is prose and stays as
written. **An author who means the agent writes it in backticks.**

*Reverse* (``functional``) renames **every** ``\b`` occurrence of a philosopher
name, in all three casings, identifier or not. Philosopher names never occur as
prose nouns, so this is lossless — and it is what lets a tree that an older,
over-eager build of this script themed repair itself: run ``functional`` and
then ``philosophers``. Making the reverse identifier-only too would strand the
corrupted prose forever.

The round trip functional -> philosophers -> functional is byte-identical:
forward only touches lowercase identifiers, and reverse undoes every one of
those (and anything else it finds).

A tree carrying representatives of *both* themes at once is not classified by
branch order; it exits 2 naming the collision.

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
from _theme_common import (  # noqa: E402
    THEME_REPRESENTATIVES,  # noqa: F401 — re-exported: tests reach it through this module
    desync_reason,
    desynced_agents,
    detect_theme,
    theme_representatives,
)


def _mappings(target: str) -> list[tuple[str, str]]:
    """(from, to) word pairs for the requested direction.

    **The two directions are deliberately asymmetric** (see the module
    docstring for the reasoning); the casing variants differ with them.

    *Forward* (``philosophers``): the lowercase pair only. ``_transform``
    applies it exclusively inside identifier contexts, and an agent identifier
    is lowercase by construction (``subagent_type: "planner"``, ``name:``,
    ``agents/planner.md``). A Capitalised or UPPERCASE ``Planner`` /
    ``PLANNER`` is a *role noun* ("YOU ARE A PLANNER", "The Planner interviews
    you") — prose, not a name — so there is deliberately no rule for it. That
    reverses an earlier design that rewrote the shouted form too (on the
    grounds that a ``plato.md`` still declaring itself a PLANNER was a leak):
    shouted words are role nouns, not identifiers, and themeing them did not
    fix a leak, it corrupted prose ("YOU ARE A PLATO").

    *Reverse* (``functional``): all three casings — lowercase, ``.capitalize()``
    and ``.upper()`` — and ``_transform`` applies them to **every** ``\\b``
    occurrence, identifier or not. Philosopher names never occur as prose
    nouns, so this is lossless, and it is what lets a tree an older, over-eager
    build of this script themed ("Work plan pyrrho", "YOU ARE A PLATO") repair
    itself: ``functional`` then ``philosophers``.

    Still uncovered: **intercaps** — a term written ``QA-guard`` or ``docWriter``
    matches no rule here, because ``.capitalize()`` lowercases the tail
    (``qa-guard`` -> ``Qa-guard``, never ``QA-guard``), and the forward
    direction has no capitalised rule at all. ``qa-guard``, ``test-writer``,
    ``doc-researcher`` and ``doc-writer`` are mapped terms, and each has an
    intercaps spelling a human would plausibly write; that stays safe only
    because no charter spells an *identifier* that way — checked, not assumed.
    ``ThemeCasingCoverageTest`` in tests/test_apply_theme.py is the guard: it
    scans the identifier contexts of the real ``agents/`` tree (using this
    module's own extractor, ``_identifier_regions``) and fails on the first one
    that grows such a spelling. A red there is a request for a fourth variant
    rule, or for writing the identifier in its lowercase form — not for
    rewording prose.
    """
    if target == "philosophers":
        return [(f, p) for f, p in PAIRS]
    out: list[tuple[str, str]] = []
    for a, b in ((p, f) for f, p in PAIRS):
        out.append((a, b))
        out.append((a.capitalize(), b.capitalize()))
        out.append((a.upper(), b.upper()))
    return out


# Inline code span: single backticks on one line. Group 1 is the contents.
_CODE_SPAN_RE = re.compile(r"`([^`\n]+)`")
# A double-quoted string whose *entire* content is name-ish. `"planner"` and
# `"builder | builder-standard | builder-simple"` qualify; `"Create a plan for
# the planner: ..."` (a prompt) or a YAML description does not.
_NAMEISH_QUOTED_RE = re.compile(r'"([\w\- |]+)"')
# Opening/closing fence of a fenced code block: 3+ backticks or tildes.
_FENCE_RE = re.compile(r"^[ \t]*(`{3,}|~{3,})")
_NAME_LINE_RE = re.compile(r"^name:[ \t]*")


def _identifier_regions(text: str) -> list[tuple[int, int]]:
    """Sorted, non-overlapping ``(start, end)`` offsets where a mapped term is a *name*.

    The forward transform renames a term only inside these regions; the prose
    around them is left exactly as written. Four contexts:

    1. **Inline code spans** — the text between single backticks on one line.
    2. **Name-ish double-quoted strings** — ``"planner"``,
       ``"builder | builder-standard | builder-simple"`` — whose whole content
       matches ``[\\w\\- |]+``. Applies inside fenced code blocks too, which is
       where the orchestrator's ``subagent_type: "..."`` dispatches live. A
       quoted *sentence* (a ``prompt: "..."``, a YAML ``description: "..."``) has
       punctuation in it and does not qualify.
    3. **The frontmatter ``name:`` value** (first ``---`` block of the file).
    4. Nothing else. Bare words, Capitalised and UPPERCASE words, YAML
       descriptions: prose. An author who means the agent writes it in
       backticks.

    Fence handling: a fence marker line is not scanned (so ``` ```python ``` is
    not read as a code span), and inside a fence only rule 2 applies — the
    backticks of rule 1 are prose punctuation there.

    Offsets index into ``text`` itself, with line endings untouched, so a CRLF
    file keeps its ``\\r``. The tests import this function so the real-tree
    scan and the transform cannot drift apart.
    """
    lines = text.split("\n")
    regions: list[tuple[int, int]] = []

    # Frontmatter: a first line of `---`, closed by the next `---` line.
    fm_end = -1
    if lines and lines[0].rstrip() == "---":
        for i in range(1, len(lines)):
            if lines[i].rstrip() == "---":
                fm_end = i
                break

    fence: tuple[str, int] | None = None  # (marker char, marker length)
    offset = 0
    for i, line in enumerate(lines):
        body = line[:-1] if line.endswith("\r") else line
        if 0 < i < fm_end:
            m = _NAME_LINE_RE.match(body)
            if m:
                regions.append((offset + m.end(), offset + len(body)))
        fm = _FENCE_RE.match(body)
        if fence is not None:
            if fm and fm.group(1)[0] == fence[0] and len(fm.group(1)) >= fence[1] \
                    and not body.strip().strip(fence[0]):
                fence = None  # closing fence: nothing to scan on it
            else:
                for q in _NAMEISH_QUOTED_RE.finditer(body):
                    regions.append((offset + q.start(1), offset + q.end(1)))
        elif fm:
            fence = (fm.group(1)[0], len(fm.group(1)))
        else:
            for c in _CODE_SPAN_RE.finditer(body):
                regions.append((offset + c.start(1), offset + c.end(1)))
            for q in _NAMEISH_QUOTED_RE.finditer(body):
                regions.append((offset + q.start(1), offset + q.end(1)))
        offset += len(line) + 1

    # Merge overlaps (a quoted name inside a code span matches both rules).
    regions.sort()
    merged: list[tuple[int, int]] = []
    for start, end in regions:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _rename(text: str, mappings: list[tuple[str, str]]) -> str:
    for a, b in mappings:
        text = re.sub(rf"\b{re.escape(a)}\b", b, text)
    return text


def _transform(text: str, target: str) -> str:
    """Rewrite ``text`` for the ``target`` theme.

    **Asymmetric by design.**

    * ``philosophers`` (forward): rename a functional term only where it is
      written as an *identifier* — see ``_identifier_regions``. Prose nouns
      ("Read-only architecture advisor", "Work plan reviewer", "You are a
      planner, not an implementer") are left alone: they describe a role, and
      themeing them mislabels which agent a routing description names.
    * ``functional`` (reverse): rename **every** ``\\b`` occurrence of a
      philosopher name, in all three casings, everywhere. A philosopher name is
      never a prose noun, so this cannot damage prose — and it is what repairs
      a tree an older build of this script over-themed, by running
      ``functional`` then ``philosophers``.

    The ``\\b`` rule treats ``-`` as a boundary, so ``builder-simple`` is
    rewritten to ``archimedes-simple`` (the matching file rename is
    ``_crew_common.renamed_agents``' job). It does not match inside
    ``qa_guard_scope.py`` — ``_`` is a word character.
    """
    mappings = _mappings(target)
    if target != "philosophers":
        return _rename(text, mappings)
    out: list[str] = []
    pos = 0
    for start, end in _identifier_regions(text):
        out.append(text[pos:start])
        out.append(_rename(text[start:end], mappings))
        pos = end
    out.append(text[pos:])
    return "".join(out)


def apply_theme(agents_dir: Path, target: str, *, dry_run: bool = False) -> int:
    if target not in THEMES:
        print(f"error: unknown theme {target!r} (expected one of {THEMES})", file=sys.stderr)
        return 2
    # Refuse an ambiguous tree before refusing an unrecognisable one: both are
    # `detect_theme is None`, but they are different faults and only one of them
    # names files. A tree carrying representatives of *both* themes cannot be
    # classified from evidence, and picking a winner would only be picking a
    # branch order. The rename-conflict guard below already keeps that from
    # being destructive; this keeps it from being silent.
    present = theme_representatives(agents_dir)
    if len(present) > 1:
        print(f"error: {agents_dir} carries representatives of {len(present)} themes at "
              "once — the tree cannot be classified:", file=sys.stderr)
        for theme, name in sorted(present.items()):
            print(f"  ! {name} ({theme})", file=sys.stderr)
        print("no files were changed. This is a half-renamed or hand-mixed tree — remove "
              "or rename the stray file(s) so exactly one theme is represented, and "
              "re-run.", file=sys.stderr)
        return 2
    current = detect_theme(agents_dir)
    if current is None:
        print(f"error: could not detect the crew in {agents_dir} "
              "(neither planner.md nor plato.md found)", file=sys.stderr)
        return 2
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
            print(f"  ! {name} {desync_reason(declared)} — does not load")

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
        new = _transform(text, target)
        if new != text:
            changed += 1
            if dry_run:
                print(f"  would update refs in {md.name}")
            else:
                md.write_text(new, encoding="utf-8", newline="")

    # 2) rename the eleven agent files (nine pairs + the two builder tiers).
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
            # Warning on those would put nine "expected X not found" lines on
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

    # Re-ask the oracle after *every* non-dry-run pass, not only a repair one.
    # The check exists to catch "the pass ran, but files still declare a
    # `name:` that disagrees with their filename": a desync it cannot express
    # as a rename or a word rewrite — a hand-edited `name: sccout` in
    # scout.md, or a stem outside the roster that a mapped word still matches
    # inside (`reviewer-lite`: `_transform` is word-level and rewrites its
    # frontmatter on `\breviewer\b`, but `renamed_agents` is a roster
    # *membership* lookup with no entry for it, so the file is never renamed
    # to match) — survives the pass untouched either way.
    #
    # This used to run only when `repairing` was True (`repairing = current ==
    # target`), on the reasoning that a repair pass is the one converging a
    # tree already known to be inconsistent. That reasoning gated the wrong
    # half: "switched crew: X -> Y" is exactly as much of a claim about the
    # resulting tree's consistency as "converged crew onto X" is — both assert
    # the pass leaves every charter's `name:` agreeing with its filename — and
    # a direction *switch* can produce the very residue above just as easily
    # as a repair can. Checking only the repair branch meant the switch branch
    # printed "switched crew" and exited 0 over a tree it had just left with a
    # non-loading agent in it, with no signal to the operator at all. So the
    # check now guards both claims, not the one the operator already
    # distrusted.
    #
    # Only after a real pass: in dry-run mode nothing was written, so every
    # desync is trivially still present and a re-check could only report a
    # failure the run never attempted.
    residue = [] if dry_run else desynced_agents(agents_dir)
    if residue:
        print(f"\nerror: the pass ran, but {len(residue)} file(s) still declare a "
              "`name:` that disagrees with their filename:", file=sys.stderr)
        for name, declared in residue:
            print(f"  ! {name} {desync_reason(declared)} — does not load",
                  file=sys.stderr)
        print("the theme machinery cannot converge these — re-running will not help. "
              "Edit the frontmatter (or the filename) by hand so the two agree.",
              file=sys.stderr)
        return 2

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
