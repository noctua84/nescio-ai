#!/usr/bin/env python3
"""Overlay-sync framework files from an upstream Nescio checkout into this instance.

A downstream instance (your private fork) runs this to update its *framework*
from the canonical public repo. It copies a fixed allowlist of framework paths
from the upstream checkout into this repo, mirroring additions, updates, and
deletions **within those paths only**. It NEVER touches your memory records or
anything outside the allowlist — `memory/`, `docs/`, notes, and instance config
are left exactly as they are.

Why copy instead of `git pull`: the public and private repos have unrelated git
histories (the public repo was extracted as a fresh scaffold), so a merge is not
meaningful. This overlay keeps each instance's own history intact.

A consequence of that overlay model: `scripts` is itself one of the paths this
script copies, so a downstream instance's `--apply` run overwrites the very
file that is executing. Python has already loaded and compiled this module by
then, so the run in progress finishes against the *old* `FRAMEWORK_PATHS` —
it delivers the new script, but not anything that script's updated allowlist
newly added. A change to `FRAMEWORK_PATHS` therefore takes two `--apply` passes
to fully land: the first replaces the script, the second runs the replacement
and picks up what it now knows to copy. `main()` detects when a run replaced
itself and prints a reminder to sync again.

Theme-awareness, and the framing that produced it
-------------------------------------------------

An instance may be on the optional philosopher theme (`scripts/apply_theme.py`),
which renames eleven agent charters — `agents/planner.md` -> `agents/plato.md` —
and rewrites crew names in the prose of the rest. Compared naively against a
canonical (functional) upstream, every one of those files is a filename upstream
does not have and a filename dest does not have, so a themed instance **exactly
in step with upstream** used to report `11 added, 3 updated, 11 deleted` — every
run, forever. That is a safety problem, not a cosmetic one, for exactly the
reason `_files_equal` states about line endings: this dry run is the only thing
standing between an operator and a destructive `--apply`, and burying the real
changes among phantom ones trains them to skim past it.

The fix comes from *re-framing*, and the framing is the part worth keeping. The
obvious reading is "the comparison needs to know about the theme", which points
at threading a name-mapping lens through `plan_sync`, `apply_sync` and
`render_diff`. Read instead as "the comparison needs an upstream that is already
in dest-space", it points somewhere much smaller: **materialise**. A themed
instance copies upstream's `agents/` into a temp directory, runs the *existing*
theme renderer over that copy, and then runs the ordinary, untouched sync
against it.

So `plan_sync`, `apply_sync`, `_files_equal`, `_iter_files`,
`_normalize_newlines` and `_read_text` are **untouched by this feature** — not
one line. The only signature growth anywhere is two display-only keywords on
`render_diff` (`summary`, `provenance`), both defaulted to today's behaviour.
The consequence that matters: **deletion mirroring — the safety property of this
whole script — is preserved structurally rather than by discipline.** Upstream's
agent set is rendered into dest-space *totally* and then handed to the same set
difference as always, so there is no filter suppressing "phantom" adds or
deletes, nowhere to put one, and no future in which a well-meant suppression
swallows a genuine deletion of `qa-guard.md`/`cato.md`. Do NOT "simplify" this
by teaching `plan_sync` about themes; that reintroduces exactly the filter this
design exists to make unrepresentable.

Why the untheme'd path is a separate branch
-------------------------------------------

An instance with no theme executes *literally* today's code: one `plan_sync`
with no `paths=`, one `render_diff` with no keywords, one `apply_sync`. No temp
directory is created and `scripts/apply_theme.py` is never imported. This is a
requirement, not an optimisation, and it is why the two branches are not
"unified" into one parameterised path. A unified version would (a) make every
instance's correctness depend on the `paths=` split — whose ordering only
reproduces today's output because `"agents"` happens to be first in
`FRAMEWORK_PATHS` — and (b) charge an instance that has no theme a temp-dir copy
of `agents/` and an import of a purely cosmetic module, on every run, to reach
an identical answer.

Why the renderer is imported lazily, and why an ImportError refuses
-------------------------------------------------------------------

`apply_theme.apply_theme` is imported *inside* the themed branch, at the point of
use, for the reason above: an untheme'd instance must never touch the cosmetic
module. If that import fails on a themed instance the sync **refuses** — exit 2,
nothing written. It does not fall back to treating the tree as unthemed. That
fallback is tempting and it is wrong: its failure mode is not a smaller feature
working less well, it is the exact destructive 11-added/11-deleted plan this
machinery exists to prevent. A fallback whose failure mode is destruction is not
graceful degradation.

Bootstrap: the first sync carrying this fix is still noisy
-----------------------------------------------------------

This script, `apply_theme.py`, `_crew_common.py` and `_theme_common.py` all live
inside the synced `scripts/` allowlist entry, and **the script that runs is the
dest's copy**. A themed instance still on the old code therefore gets today's
noisy plan on the pass that *delivers* this fix (together with the new
`_theme_common.py`); only the second pass is clean. Deliberate, and not
engineered around — see the self-replacement note above for the same shape of
one-pass-behind, and `main()`'s reminder for the same remedy: run it again.

The rendering uses **dest's** notion of its own theme
------------------------------------------------------

Materialisation calls the *dest's* `apply_theme.py` and its `PAIRS`, not
upstream's. Consequence, stated so it is a known property and not a surprise:
**a charter added upstream that dest's roster cannot express does not converge
on a later pass — it locks the instance out of syncing until the operator
intervenes.** Concretely: upstream adds `agents/builder-fast.md` (a new tier,
or any `<roster-word>-<suffix>.md`). Dest's *old* renderer rewrites its
`name: builder-fast` to `name: archimedes-fast` on the `\\bbuilder\\b` word rule
but has no rename entry for the file, so the materialised copy carries a
charter whose `name:` disagrees with its stem. The residue check that runs
after every `apply_theme` pass (issue #137) returns 2; P2 turns that into a
full refusal *before* `apply_sync`; and the `scripts/_crew_common.py` that
would resolve it is therefore never delivered. Pass two fails identically.
There is no "later pass" — an earlier version of this paragraph claimed there
was, and it was wrong.

The refusal in `main()` prints the working remediation: take the instance off
its theme for one pass (`apply_theme.py functional`), sync — an untheme'd
instance takes the P1 path, which delivers upstream's new `scripts/` and the
new charter verbatim — then put the theme back with the *delivered* renderer.
That is a workaround, not a fix. The structural fix is tracked as
noctua84/nescio-ai#142 and is deliberately not attempted here; P2 is not
softened to make room for it.

A *retargeted* pair (say `doc-writer` -> `quintilian` replacing `cicero`) has
the same one-pass-behind shape and additionally leaves an orphan `cicero.md`
behind that `desynced_agents` will **not** flag, because that oracle compares
a charter's `name:` against its own filename stem and the orphan is internally
self-consistent.

False negatives: a chosen property (the mapping is many-to-one)
----------------------------------------------------------------

`planner`, `Planner` and `PLANNER` all render to `plato`/`Plato`/`PLATO` — and
so does a literal upstream `plato`. An upstream edit that changes exactly the
word `planner` to the word `plato` therefore renders identically before and
after, and a themed instance's sync sees no change at all. Practical impact is
nil (the instance's own rendering genuinely did not change), but it is recorded
here so a future reader meets it as a property of a many-to-one rename rather
than as a bug to "fix".

Route D — considered, and why it lost
--------------------------------------

The root cause is that the theme is a *mutation* of the tree rather than a
*projection* over it. Resolving philosopher names at load time, leaving the real
files functional, would dissolve this whole problem. It is infeasible: Claude
Code loads charters from real files at `agents/<name>.md` and offers no
name-resolution hook to interpose. Recorded because a reader will propose it.

The cheap-looking near-miss
----------------------------

Having `--apply` simply run `apply_theme` over **dest** as a post-sync step looks
like it solves this for a tenth of the code. It fixes nothing. **The plan is the
broken artefact**: the operator reads twenty-five fictional entries and decides
from them whether to run `--apply` at all, and the dry run never calls
`apply_sync` — so it stays exactly as wrong as it is today. Note the distinction
precisely: this design renders a **temp copy of upstream, before planning**; the
near-miss renders **dest, after applying**.

Usage:
    python scripts/sync_from_upstream.py --upstream /path/to/nescio-ai            # dry run
    python scripts/sync_from_upstream.py --upstream /path/to/nescio-ai --apply    # perform

A themed instance needs no follow-up re-render: the sync materialises upstream
into the instance's own theme and writes themed bytes directly.
"""

from __future__ import annotations

import argparse
import contextlib
import difflib
import filecmp
import io
import shutil
import sys
import tempfile
from pathlib import Path

# Works whether this file is run as a script, imported by the tests (which put
# scripts/ on the path themselves), or collected under PYTHONPATH=scripts in CI.
sys.path.insert(0, str(Path(__file__).resolve().parent))

# The theme *classifier* only — four cheap, I/O-only functions with no CLI. It is
# imported unconditionally because every run must ask "is this dest themed?"
# before it can choose a branch, and answering that must not cost an untheme'd
# instance an import of the cosmetic module.
#
# The *renderer* (`apply_theme.apply_theme`) is deliberately NOT imported here.
# It is imported lazily, inside the themed branch of `main()`, so an instance
# with no theme never touches `scripts/apply_theme.py` at all — see P1 in the
# module docstring, and `main()`'s themed branch for the import itself.
from _theme_common import (  # noqa: E402
    THEME_REPRESENTATIVES,
    desync_reason,
    desynced_agents,
    detect_theme,
    theme_representatives,
)

# Roster *facts* — which filename stems belong to which theme. Imported
# unconditionally, and that does not spend P1: `_crew_common` is the durable,
# stdlib-only, no-I/O data module every script and test already depends on
# (its own docstring: "Stdlib-only, no I/O: pure data"). It is not the
# cosmetic renderer P1 keeps off the untheme'd path — that is
# `apply_theme.py`, still imported lazily inside the themed branch of
# `main()`. What these two names buy is the ability to tell a *crew that has
# lost its representative* apart from a crew that was never there, before
# either branch is chosen — see `_roster_without_representative`.
from _crew_common import THEME_INVARIANT_ROSTER, expected_roster  # noqa: E402

# Framework paths a downstream instance syncs FROM upstream. Everything NOT listed
# here is instance-owned and never touched — notably `memory/` (your records),
# `docs/` (your design bundle), `README.md`, `CLAUDE.md`, `settings.json`,
# `.github/`, `.gitignore`, and any private trees.
#
# `conftest.py` travels with `tests/` on purpose even though it lives at the repo
# root: it is the only thing that puts the repo root, `hooks/`, and `scripts/` on
# `sys.path` for pytest. Without it, an instance receives the test suite but not
# the wiring that makes it importable, and collection fails with
# `ModuleNotFoundError` for `hooks`/`scripts` the moment a test imports them.
FRAMEWORK_PATHS = [
    "agents",
    "skills",
    "commands",
    "hooks",
    "scripts",
    "github-action",
    "tests",
    "conftest.py",
    "install.py",
    "pyproject.toml",
    "uv.lock",
    "CONTRIBUTING.md",
    "LICENSE",
    "stores.example.json",
    "serena.mcp.example.json",
    "CLAUDE.local.md.example",
    "scrub-terms.local.example",
]


def _is_nescio_checkout(root: Path) -> bool:
    """A directory that looks like a Nescio instance/framework checkout."""
    return (root / "install.py").is_file() and (root / "agents").is_dir()


def _iter_files(base: Path):
    """Yield base-relative paths of real files under `base` (skips caches)."""
    if not base.exists():
        return
    for p in sorted(base.rglob("*")):
        if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc":
            yield p.relative_to(base)


def _normalize_newlines(text: str) -> str:
    """Collapse CRLF and lone CR to LF so text compares by content, not by EOL."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _files_equal(a: Path, b: Path) -> bool:
    """Are these two files the same *content*? Text-aware, binary-strict.

    Do NOT "simplify" this back into `filecmp.cmp(..., shallow=False)`. The two
    sides of a sync do not share a line-ending policy, and a byte comparison
    turns that asymmetry into a wall of phantom updates:

    - This framework repo pins its working tree to LF via `.gitattributes`
      (`* text=auto eol=lf`), because the brand generators emit `newline="\\n"`
      and the tests compare generated bytes against the committed copies.
    - A downstream instance is a *private fork* and may carry no `.gitattributes`
      at all. Git for Windows ships `core.autocrlf=true` in its **system**
      config, so such an instance's working tree is CRLF. Neither tree is wrong
      — they simply disagree about newlines, and the framework cannot assume an
      instance mirrors its line-ending policy.

    Byte-comparing across that boundary reported two thirds of one real
    instance's "updated" list as files whose text was identical. That is worse
    than noise: this dry-run report is the only thing standing between an
    operator and a destructive `--apply`, and burying the handful of real
    changes among phantom ones trains them to skim past it.

    Semantics, in order:

    1. Byte-equal -> equal. Fast path and the common case; no decode cost.
    2. Both sides decode as UTF-8 -> compare with newlines normalised. This is
       exactly the case the byte comparison got wrong.
    3. Either side is binary -> **unequal**, preserving today's byte semantics.
       Load-bearing: `.gitattributes` marks `*.woff2 *.ttf *.otf *.png *.ico
       *.pdf` binary precisely because the brand assets are compared
       byte-for-byte. A font or PNG whose payload happens to differ in a
       `0d 0a` is a genuinely different file, and normalising newlines inside
       binary content would silently suppress that real change.
    4. Any OSError on either side -> unequal, i.e. *report* the file. An
       unreadable file is a fact the operator should see in the plan; skipping
       it silently would drop a file that may well need syncing.

    `apply_sync` still copies upstream **bytes** verbatim. It simply never
    selects a file that differs only by line endings any more, so the downstream
    tree stops churning — and no `.gitattributes` policy gets fought on copy.
    """
    try:
        if filecmp.cmp(a, b, shallow=False):
            return True
        try:
            a_text = a.read_bytes().decode("utf-8")
            b_text = b.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            # At least one side is binary (or not UTF-8): keep byte semantics.
            return False
        return _normalize_newlines(a_text) == _normalize_newlines(b_text)
    except OSError:
        # Unreadable or vanished file: deliberately treated as *different* so it
        # surfaces in the plan instead of being silently dropped from it.
        return False


def plan_sync(upstream: Path, dest: Path, paths=FRAMEWORK_PATHS):
    """Compute (added, updated, deleted) dest-relative file paths, no writes.

    Only the allowlisted `paths` are considered; anything else in `dest` is
    invisible to this function and will never be reported or changed.
    """
    added: list[str] = []
    updated: list[str] = []
    deleted: list[str] = []
    for entry in paths:
        up = upstream / entry
        dst = dest / entry
        if up.is_dir():
            up_files = set(_iter_files(up))
            dst_files = set(_iter_files(dst))
            for rel in sorted(up_files):
                target = dst / rel
                rel_str = str(Path(entry) / rel)
                if not target.exists():
                    added.append(rel_str)
                elif not _files_equal(up / rel, target):
                    updated.append(rel_str)
            for rel in sorted(dst_files - up_files):
                deleted.append(str(Path(entry) / rel))
        elif up.is_file():
            if not dst.exists():
                added.append(entry)
            elif not _files_equal(up, dst):
                updated.append(entry)
        else:
            # Framework path absent upstream — mirror the removal downstream.
            if dst.is_dir():
                for rel in sorted(_iter_files(dst)):
                    deleted.append(str(Path(entry) / rel))
            elif dst.exists():
                deleted.append(entry)
    return added, updated, deleted


def apply_sync(upstream: Path, dest: Path, paths=FRAMEWORK_PATHS):
    """Perform the sync computed by :func:`plan_sync`; return the same triple."""
    added, updated, deleted = plan_sync(upstream, dest, paths)
    for rel in deleted:
        (dest / rel).unlink()
    for rel in added + updated:
        src = upstream / rel
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)
    return added, updated, deleted


def _self_was_replaced(dest: Path, added, updated) -> bool:
    """Did this run overwrite the copy of this script that is executing?

    `scripts` is itself a framework path (see the module docstring), so an
    `--apply` run against a downstream instance can rewrite the very file
    Python is midway through running. Detect that by comparing the resolved
    path of this module against the resolved path of every applied change:
    resolving both sides means the comparison holds through symlinks and
    through path-spelling differences (drive letter case, short vs. long
    names, `.` segments) on Windows.

    Deliberately False, not an exception, when `.resolve()` raises `OSError`
    (e.g. from an unresolvable symlink or filesystem error): a sync that
    otherwise succeeded should not fail on this advisory check. Also
    False for the ordinary "run upstream's copy against a remote --dest"
    invocation, since the running script then lives outside `dest` entirely
    and is never among the files just written.
    """
    try:
        self_path = Path(__file__).resolve()
        for rel in added + updated:
            if self_path == (dest / rel).resolve():
                return True
    except OSError:
        return False
    return False


def _read_text(path: Path):
    """Return the file's UTF-8 text as a list of lines, or None if it's binary.

    Newlines are normalised to LF for the same reason :func:`_files_equal`
    normalises them: dest may be a CRLF working tree while upstream is LF, and a
    retained `\\r` on every dest line would make `difflib` mark every line as
    changed — a full-file diff for a file that barely moved.

    The decode is done explicitly over bytes rather than via
    `Path.read_text(encoding="utf-8")`, whose universal-newline translation is
    an *implicit* consequence of `newline=None`. Pinning it here makes the
    guarantee part of this function's contract instead of an inherited default.
    Returning None for undecodable input is load-bearing: `render_diff` keys its
    "(binary file, N bytes)" branch off it.
    """
    try:
        text = path.read_bytes().decode("utf-8")
    except (UnicodeDecodeError, ValueError):
        return None
    return _normalize_newlines(text).splitlines(keepends=True)


def render_diff(upstream: Path, dest: Path, added, updated, deleted, *,
                summary: bool = True,
                provenance: dict[str, str] | None = None) -> str:
    """Return a human-readable content diff for a sync plan (no printing).

    For each UPDATED file, a unified diff of dest (current) vs upstream (new);
    binary files get a one-line size note instead. ADDED files are marked
    NET-NEW (with a content preview) and DELETED files get a one-line note.
    Output is deterministic (paths sorted within each section).

    Args:
        upstream: path to an upstream Nescio checkout
        dest: path to the downstream instance
        added: list of newly added files
        updated: list of updated files
        deleted: list of deleted files
        summary: emit the final net-new summary line (default True). A themed
            instance calls render_diff twice over two different upstream roots —
            once for agents/ and once for everything else — so exactly one call
            should emit the footer. The cost, stated: the three sections interleave
            on the themed path (UPDATED(agents) / ADDED(agents) / DELETED(agents),
            then UPDATED(others) / ADDED(others) / DELETED(others)), affecting
            only a themed instance's --diff output. This is accepted, not
            overlooked. Do NOT 'simplify' this by making main() parse or splice
            render_diff's output — that trades a defaulted keyword for a format
            dependency between two functions.
        provenance: optional dict mapping dest-relative paths to upstream-relative
            paths, for display purposes only. When an UPDATED or ADDED entry is in
            the map, the diff header or ADDED marker is annotated with the source
            file name and marked as themed. No correctness depends on this header
            at all; it exists because a themed diff is rendered in philosopher
            vocabulary (dest-space names), which is more useful for the operator
            reading their own tree but costs them the ability to locate the
            upstream file. A file the map does not cover — agents/orchestrator.md,
            whose content is themed but whose name is not — simply gets no note.
            That is graceful and correct, and it is a chosen property of the
            mapping, not a bug (the mapping is many-to-one: every philosopher name
            maps back to exactly one functional name, but the inverse is not
            guaranteed).
    """
    if provenance is None:
        provenance = {}

    lines: list[str] = []

    for rel in sorted(updated):
        up = upstream / rel
        dst = dest / rel
        posix = Path(rel).as_posix()
        old = _read_text(dst)
        new = _read_text(up)
        if old is None or new is None:
            old_size = dst.stat().st_size if dst.exists() else 0
            new_size = up.stat().st_size if up.exists() else 0
            lines.append(f"~ UPDATED  {posix}")
            lines.append(f"  (binary file, {old_size} bytes -> {new_size} bytes)")
            lines.append("")
            continue
        # Determine the tofile annotation based on provenance
        # Note: provenance keys use POSIX paths (forward slashes)
        if posix in provenance:
            prov_posix = Path(provenance[posix]).as_posix()
            tofile = f"b/{posix} (upstream {prov_posix}, themed)"
        else:
            tofile = f"b/{posix} (upstream)"
        diff = difflib.unified_diff(
            old, new,
            fromfile=f"a/{posix} (current)",
            tofile=tofile,
        )
        text = "".join(diff)
        if not text.endswith("\n"):
            text += "\n"
        lines.append(text.rstrip("\n"))
        lines.append("")

    for rel in sorted(added):
        up = upstream / rel
        posix = Path(rel).as_posix()
        # Determine the annotation based on provenance
        # Note: provenance keys use POSIX paths (forward slashes)
        if posix in provenance:
            prov_posix = Path(provenance[posix]).as_posix()
            annotation = f"(upstream {prov_posix}, themed)"
        else:
            annotation = "(NET-NEW)"
        lines.append(f"+++ ADDED  {posix}  {annotation}")
        content = _read_text(up)
        if content is None:
            size = up.stat().st_size if up.exists() else 0
            lines.append(f"  (binary file, {size} bytes)")
        else:
            preview = content[:20]
            for pline in preview:
                lines.append(f"  +{pline.rstrip(chr(10))}")
            if len(content) > 20:
                lines.append(f"  ... ({len(content) - 20} more line(s))")
        lines.append("")

    for rel in sorted(deleted):
        posix = Path(rel).as_posix()
        lines.append(f"--- DELETED  {posix}")

    if deleted:
        lines.append("")

    if not (added or updated or deleted):
        return ""

    if summary:
        lines.append(
            f"net-new: {len(added)} added file(s), {len(updated)} updated, "
            f"{len(deleted)} deleted"
        )
    return "\n".join(lines) + "\n"


def _roster_without_representative(agents_dir: Path) -> dict[str, list[str]]:
    """{theme: [charter filenames]} for every *theme-specific* roster stem on disk.

    Consulted only when `theme_representatives` found nothing. Zero
    representatives has two very different readings, and `detect_theme`
    cannot tell them apart because it classifies from one file:

    - a fresh or crewless instance (the bootstrap case — every fixture in
      `tests/test_sync_from_upstream.py` seeds only `agents/explore.md`), for
      which today's untheme'd path is exactly right; and
    - a themed crew that has **lost its representative** — an operator who
      archived `agents/plato.md` because they do not use the planner — for
      which today's untheme'd path is the fully destructive plan: ten
      philosopher charters deleted, eleven functional ones added, and no
      warning, because the ten survivors are internally self-consistent and
      `desynced_agents` has nothing to say.

    The roster is the evidence that separates them. Theme-*invariant* stems
    (`explore`, `scout`, ...) are deliberately excluded: they are in both
    rosters, so they are evidence of neither, and counting them would drag
    the bootstrap fixture — `explore.md` alone — into the refusal below.
    Presence is by filename (`is_file()`), not by parsing frontmatter, for the
    same reason `theme_representatives` checks presence: the question is
    "what crew is on disk", and a charter that is present but broken is still
    on disk (and already reported by `desynced_agents`).
    """
    found: dict[str, list[str]] = {}
    for theme in THEME_REPRESENTATIVES:
        stems = expected_roster(theme) - THEME_INVARIANT_ROSTER
        names = sorted(f"{stem}.md" for stem in stems if (agents_dir / f"{stem}.md").is_file())
        if names:
            found[theme] = names
    return found


def _report(args, dest: Path, added, updated, deleted, diff_text: str, *,
            theme: str | None) -> int:
    """Print the plan (and post-run hints) and return `main`'s exit code.

    Extracted so the untheme'd and themed branches of `main()` cannot drift in
    output format. They differ in *how the triple is computed* — one comparison
    against upstream, or two against a materialised temp root plus upstream —
    and in nothing else the operator sees. Keeping one reporting body is what
    makes that claim structural instead of a promise; a second copy would
    silently diverge the first time either branch grew a line.

    `dest` is a parameter for one specific reason: `_self_was_replaced` needs it,
    and that call lives in this block. It is **already correct** over the themed
    branch's concatenated triple and needs no adaptation — it joins each `rel`
    to `dest`, never to `upstream`. The `agents/` half contributes themed
    dest-relative paths (`agents/plato.md`) that are real dest paths by
    construction and can never equal the running script's path, so there is no
    false positive; `scripts/sync_from_upstream.py` reaches the triple only via
    the non-`agents` half and is joined to `dest` exactly as it is today, so the
    true positive survives. Recorded here so the next reader need not re-derive
    it.
    """
    total = len(added) + len(updated) + len(deleted)

    if total == 0:
        print("framework already in sync — nothing to do.")
        return 0

    # Name the rendering that produced these numbers, but only when there are
    # numbers to act on. A themed plan is expressed in the instance's own
    # (philosopher) vocabulary against an upstream that was rendered into it,
    # and the operator deciding whether to run --apply should be able to see
    # which of the two comparisons they are reading.
    if theme is not None:
        print(f"instance theme: {theme} (upstream's crew was rendered into it before comparing)")

    verb = "synced" if args.apply else "would change"
    print(f"{verb}: {len(added)} added, {len(updated)} updated, {len(deleted)} deleted")
    for label, items in (("+ add   ", added), ("~ update", updated), ("- delete", deleted)):
        for it in items:
            print(f"  {label}  {it}")

    if diff_text:
        print()
        print(diff_text, end="")

    if args.apply:
        print("\nmemory/ and all non-framework paths were left untouched. "
              "No follow-up `apply_theme.py` run is needed: if your instance is themed, "
              "the framework files were rendered into that theme before being written.")
        if _self_was_replaced(dest, added, updated):
            print("\nthis sync overwrote scripts/sync_from_upstream.py itself, so it ran "
                  "with the OLD allowlist — anything newly added to FRAMEWORK_PATHS upstream "
                  "was not delivered this pass. Run the sync again to pick it up.")
    else:
        print("\n(dry run — re-run with --apply to perform)")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--upstream", required=True, type=Path,
                    help="path to an upstream Nescio checkout (the canonical framework)")
    ap.add_argument("--dest", type=Path, default=None,
                    help="downstream instance root (default: current directory)")
    ap.add_argument("--apply", action="store_true",
                    help="perform the sync (default: dry run, prints the plan only)")
    ap.add_argument("--diff", action="store_true",
                    help="after the summary, show per-file content diffs so you can see "
                         "exactly WHAT would change (works with dry run; no --apply needed)")
    args = ap.parse_args(argv)

    upstream = args.upstream.resolve()
    dest = (args.dest or Path.cwd()).resolve()

    if not _is_nescio_checkout(upstream):
        print(f"error: --upstream {upstream} is not a Nescio checkout "
              "(need install.py + agents/)", file=sys.stderr)
        return 2
    if not _is_nescio_checkout(dest):
        print(f"error: --dest {dest} is not a Nescio instance "
              "(need install.py + agents/)", file=sys.stderr)
        return 2
    if upstream == dest:
        print("error: --upstream and --dest are the same directory", file=sys.stderr)
        return 2

    # Refuse a dest that carries representatives of BOTH themes at once
    # (`planner.md` *and* `plato.md`). Mirrors apply_theme's own refusal in
    # wording and shape, and it is load-bearing rather than merely tidy:
    # `detect_theme` answers None for such a tree — the same answer it gives a
    # tree with no crew at all — so without this guard the run would fall
    # through to the untheme'd branch and compare a themed dest against a
    # functional upstream, i.e. produce the fully destructive plan this whole
    # change exists to prevent. A tree that cannot be classified must not be
    # classified by branch order.
    reps = theme_representatives(dest / "agents")
    if len(reps) > 1:
        print(f"error: --dest {dest} carries representatives of {len(reps)} themes at "
              "once — the instance cannot be classified:", file=sys.stderr)
        for theme_name, filename in sorted(reps.items()):
            print(f"  ! agents/{filename} ({theme_name})", file=sys.stderr)
        print("no files were changed. This is a half-renamed or hand-mixed tree — remove "
              "or rename the stray file(s) so exactly one theme is represented, then "
              "re-run.", file=sys.stderr)
        return 2

    # Refuse a themed --upstream.
    #
    # Why this guard survives when most of the previous design's risk register
    # dissolved into the materialisation: the materialisation branch below only
    # runs when the **dest** is themed, so it cannot see — let alone correct —
    # a themed *upstream* being synced into an **untheme'd** dest. That
    # combination takes the untheme'd branch and produces today's fully
    # destructive plan in the opposite direction: eleven philosopher charters
    # added, eleven functional ones deleted. `_is_nescio_checkout` requires only
    # `install.py` + `agents/`, so nothing else stops it.
    #
    # The cost is one `theme_representatives` call and **no import of the
    # cosmetic module**, so the untheme'd-path requirement (P1, module
    # docstring) still holds.
    up_reps = theme_representatives(upstream / "agents")
    if up_reps and set(up_reps) != {"functional"}:
        print(f"error: --upstream {upstream} is itself on a theme:", file=sys.stderr)
        for theme_name, filename in sorted(up_reps.items()):
            print(f"  ! agents/{filename} ({theme_name})", file=sys.stderr)
        print("--upstream must be a canonical (unthemed) framework checkout. Syncing FROM a "
              "themed instance would report every functional charter as deleted and every "
              "philosopher one as added — a fully destructive plan in the opposite "
              "direction. No files were changed.", file=sys.stderr)
        return 2

    # Refuse a dest whose crew has lost its representative.
    #
    # Zero representatives is the bootstrap case (decision 4 in the plan: a
    # fresh or crewless instance takes today's path), and it must stay so —
    # but "zero representatives" is not the same fact as "no crew". A themed
    # instance from which only `agents/plato.md` is missing has zero
    # representatives, classifies as None, is internally self-consistent (so
    # the desync warning below has nothing to say), and falls through to the
    # untheme'd branch: eleven functional charters added, the ten surviving
    # philosopher charters deleted, silently. That is the exact destructive
    # plan this whole module exists to prevent, on a tree that is
    # unmistakably themed to anyone who looks at it. `_roster_without_
    # representative` looks. The refusal has the same shape as the
    # both-representatives guard above, and for the same reason: a tree that
    # cannot be classified must not be classified by branch order.
    #
    # The trigger is a theme-specific stem of a theme *other than functional*.
    # A functional crew missing `agents/planner.md` is genuinely untheme'd,
    # today's path is right for it — the sync simply re-adds the missing
    # charter — and refusing it would hold framework updates hostage to a
    # false claim of destruction. The functional stems are still *listed*
    # when the guard fires for another theme's files, so a hand-mixed tree
    # is described in full.
    #
    # `apply_theme.py` is not offered as a remedy, because it cannot be one:
    # it classifies by the same representative file and refuses this tree
    # with "could not detect the crew". The only fix is the file itself.
    if not reps:
        stray = _roster_without_representative(dest / "agents")
        if any(t != "functional" for t in stray):
            print(f"error: --dest {dest} carries a crew but no theme representative — the "
                  "instance cannot be classified:", file=sys.stderr)
            for theme_name, names in sorted(stray.items()):
                for filename in names:
                    print(f"  ! agents/{filename} ({theme_name})", file=sys.stderr)
            for theme_name in sorted(stray):
                print(f"  missing: agents/{THEME_REPRESENTATIVES[theme_name]} "
                      f"(the '{theme_name}' representative)", file=sys.stderr)
            print("no files were changed. Without its representative the sync would treat "
                  "this instance as crewless and compare its agents/ against upstream's "
                  "functional names — deleting every charter listed above and adding the "
                  "functional crew in its place, a fully destructive plan with no warning. "
                  "Restore the missing representative (from this instance's own git "
                  "history, or wherever it went) and re-run. `apply_theme.py` cannot repair "
                  "this: it classifies by the same file.", file=sys.stderr)
            return 2

    theme = detect_theme(dest / "agents")

    # Warn — do not refuse — on a half-renamed dest. This sits ABOVE the P1
    # branch below, not down in the themed tail where an earlier draft put it,
    # and the placement is load-bearing, not cosmetic.
    #
    # `detect_theme` classifies from a single representative file — its own
    # docstring says so: "this answers 'which direction did the last run go',
    # not 'is the tree consistent'". A dest with `agents/plato.md` renamed back
    # to `agents/planner.md`, `name:` frontmatter left declaring `plato`, has
    # exactly one representative on disk and classifies clean as `"functional"`.
    # Checking `desynced_agents` only inside the themed tail — past the P1
    # early return — consulted the tree's one real consistency oracle on
    # whichever branch `detect_theme` happened to pick, and left the *other*
    # branch, the one a half-renamed tree is actually routed to, unguarded. And
    # that branch is the destructive one for such a tree: the ten untouched
    # philosopher charters read as ten deletions against a functional upstream,
    # sight unseen, because `detect_theme` cannot see past the one file it
    # trusts. Consulting the oracle before the branch, unconditionally, is what
    # closes that — not moving it to the other side of the same fork.
    #
    # A charter whose `name:` frontmatter disagrees with its filename does not
    # load at all, so this is worth telling the operator about loudly. It is
    # still not a reason to block a framework sync: the fault is cosmetic and
    # local to the theme, the remedy is a separate one-line command, and
    # refusing would hold a legitimate security or bug fix hostage to it.
    # Materialisation (below, themed branch only) is unaffected either way — it
    # renders upstream's crew, not dest's.
    #
    # This is a deliberate divergence from issue #133's original text, which
    # proposed refusing here. Recorded so the difference reads as a decision
    # rather than as an oversight.
    #
    # P1 is not spent by moving this up. `detect_theme` and `desynced_agents`
    # are both `_theme_common` classifier functions, already imported
    # unconditionally at module scope — every run, themed or not, already pays
    # for `detect_theme` before it can even pick a branch. Running
    # `desynced_agents` alongside it costs an untheme'd instance nothing new:
    # no temp directory, no `scripts/apply_theme.py` import. The obvious
    # objection — "doesn't putting this ahead of the branch put theme
    # machinery on the untheme'd path?" — has a one-word answer: no. What P1
    # actually guards is the *renderer*, and it stays exactly where it was,
    # lazily imported inside the themed branch below, untouched by this move.
    desynced = desynced_agents(dest / "agents")
    if desynced:
        print(f"warning: {len(desynced)} charter(s) in {dest / 'agents'} declare a `name:` "
              "that disagrees with their filename — those agents do not load:", file=sys.stderr)
        for filename, declared in desynced:
            print(f"  ! {filename} {desync_reason(declared)}", file=sys.stderr)
        if theme is None:
            # `detect_theme` found neither representative file, so there is no
            # single theme to hand `apply_theme.py` as a target — guessing one
            # would be exactly the "classification by source order" its own
            # docstring argues against. Point at the evidence instead of a
            # command that might converge the tree in the wrong direction.
            print("the instance's theme could not be determined (neither agents/planner.md "
                  "nor agents/plato.md is present), so there is no single "
                  "`apply_theme.py <theme>` command to name here — inspect the file(s) above, "
                  "correct their `name:` frontmatter or filename by hand, or restore one "
                  "representative file and re-run this sync for a theme-specific fix command.",
                  file=sys.stderr)
        else:
            # `theme` is whatever `detect_theme` found — "functional" here as
            # often as "philosophers"; the reproduction that motivated this
            # check is a "functional" classification. Pointing at THAT SAME
            # theme as apply_theme's target is deliberate, not a placeholder
            # for "philosophers": target == current hits apply_theme's
            # `repairing` path, which re-asks `desynced_agents` and converges
            # the stragglers instead of short-circuiting on "already on the
            # theme". Verified against this exact tree: `apply_theme.py
            # functional` maps the word `plato` back to `planner` wherever it
            # appears, including inside `planner.md`'s own `name:` frontmatter.
            print(f"fix with: python scripts/apply_theme.py {theme}", file=sys.stderr)
        print("the sync will proceed regardless — this is a cosmetic inconsistency in the "
              "theme, not a reason to withhold framework updates.", file=sys.stderr)

    if theme in (None, "functional"):
        # P1 — an instance with no theme executes literally today's code path:
        # one plan_sync with no `paths=`, one render_diff with no keywords, one
        # apply_sync. No temp directory, and `scripts/apply_theme.py` is never
        # imported. Do NOT "unify" this with the themed branch below by
        # parameterising it on `paths=`: that would make every instance's
        # output ordering depend on `"agents"` being first in FRAMEWORK_PATHS
        # (which the themed branch does depend on, deliberately and pinned by a
        # test — but which is a coincidence no untheme'd run should inherit),
        # and it would charge an instance that has no theme a temp-dir copy of
        # agents/ plus an import of a purely cosmetic module to reach an
        # identical answer.
        #
        # Compute the plan first so a --diff preview can read dest files
        # *before* --apply overwrites them (renders "what would/did change"
        # either way).
        added, updated, deleted = plan_sync(upstream, dest)
        diff_text = render_diff(upstream, dest, added, updated, deleted) if args.diff else ""
        if args.apply:
            apply_sync(upstream, dest)
        return _report(args, dest, added, updated, deleted, diff_text, theme=None)

    # The renderer, imported lazily and only here.
    #
    # Two reasons it is not at module scope. (1) P1: an untheme'd instance must
    # never touch `scripts/apply_theme.py`, and the branch above returns before
    # this line. (2) It keeps the classifier/renderer split honest —
    # `_theme_common` is a two-consumer *fact* and is imported unconditionally
    # at the top; `apply_theme.apply_theme` is one module's **public** entry
    # point, called by another module at the point of use, which is an ordinary
    # API use rather than a dependency inversion.
    #
    # On failure this REFUSES. Do NOT add an identity fallback that treats the
    # tree as unthemed: its failure mode is not a smaller feature working less
    # well, it is precisely the destructive 11-added/11-deleted plan this branch
    # exists to prevent. A fallback whose failure mode is destruction is not
    # degradation.
    try:
        from _crew_common import renamed_agents  # lazy on purpose — see above
        from apply_theme import apply_theme as _render_crew  # lazy on purpose — see above
    except ImportError as exc:
        print(f"error: this instance is on the '{theme}' theme, but the theme renderer "
              f"(scripts/apply_theme.py) could not be imported: {exc}", file=sys.stderr)
        print("refusing to sync: without it the plan would compare functional upstream names "
              "against themed instance names and report every agent as both added and "
              "deleted.", file=sys.stderr)
        return 2

    others = [p for p in FRAMEWORK_PATHS if p != "agents"]

    # The `with` block must span plan -> diff -> apply. `apply_sync` re-plans
    # internally and re-reads the materialised tree, so `root` cannot be
    # released after planning; releasing it early would delete the only copy of
    # upstream-in-dest-space out from under the copy step.
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        shutil.copytree(upstream / "agents", root / "agents")
        # Cheap structural guard on the copy's scope. Only `agents/` is ever
        # materialised, which is what makes it *impossible* for the renderer's
        # word-level transform to reach `scripts/_crew_common.py` and rewrite
        # the PAIRS table it is driven by — a transform that would make the
        # theme permanently unrevertable in every instance that synced it. The
        # assertion is not defending against a bug seen in the wild; it is
        # pinning the property that makes the whole class of bug unreachable.
        assert [p.name for p in root.iterdir()] == ["agents"], (
            f"materialisation copied more than agents/: {[p.name for p in root.iterdir()]}"
        )

        # The renderer is chatty — thirteen lines of rename traffic on a normal
        # pass, and stderr warnings on a genuine upstream deletion — and every
        # word of it describes a temp directory the operator has never heard of.
        # Capture both streams: discard them on success, surface stderr on
        # failure.
        out, err = io.StringIO(), io.StringIO()
        # main() frames a render failure before quoting it: without this line
        # the operator sees a bare error about a /tmp path with no account of
        # where it came from — least of all which `--upstream` it is about.
        framing = (f"error: could not render upstream's crew ({upstream}) into the "
                   f"'{theme}' theme — refusing to sync.")
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                rc = _render_crew(root / "agents", theme)
        except Exception:
            # The renderer *raised* rather than returned: a read-only upstream
            # file whose mode `copy2` preserved into the temp root, a
            # non-UTF-8 upstream charter, a filesystem fault. Both context
            # managers have already unwound — streams are restored and
            # `TemporaryDirectory` still cleans up on the way out — so the
            # only thing missing is the framing. Print it, surface whatever
            # the renderer managed to say, and re-raise: an unexpected
            # exception is exactly the case where a traceback is the right
            # output, and swallowing it into `return 2` would hide the one
            # line (the exception's own path and errno) that says why.
            print(framing + " The renderer raised an exception (traceback follows):",
                  file=sys.stderr)
            print(err.getvalue(), end="", file=sys.stderr)
            raise
        if rc != 0:
            # Refuse, do not warn. A non-zero rc means upstream's crew could not
            # be expressed in this instance's theme — a rename collision (a
            # genuinely new upstream `agents/plato.md`), an upstream tree
            # carrying two themes, a charter the renderer cannot converge. In
            # every one of those cases the materialised tree is *wrong*, and a
            # plan computed against a wrong tree is worse than no plan.
            print(framing + " The renderer reported:", file=sys.stderr)
            print(err.getvalue(), end="", file=sys.stderr)
            # The renderer's own remediation ("edit the frontmatter by hand …
            # re-running will not help") is about the temp directory that was
            # just deleted, not about any file in this instance, so it is
            # quoted for *what* failed and then corrected for what to do. The
            # commands below are verified: an untheme'd instance takes the P1
            # path, which delivers upstream's new `scripts/` (the renderer and
            # roster that can express the new charter) and the charter itself
            # verbatim; re-theming with the delivered renderer then converges.
            # Without this the instance is locked out of every framework update
            # for as long as upstream ships the charter — see the module
            # docstring, "The rendering uses dest's notion of its own theme",
            # and the structural fix tracked as noctua84/nescio-ai#142.
            print("if the report above is about a charter the renderer could not converge "
                  "(typically a charter upstream added that this instance's theme roster "
                  "cannot express yet), the renderer's \"edit by hand\" advice refers to a "
                  "temporary copy that no longer exists. The working remediation is to take "
                  "the instance off its theme for one pass, sync, and put the theme back:",
                  file=sys.stderr)
            print("  python scripts/apply_theme.py functional", file=sys.stderr)
            print(f"  python scripts/sync_from_upstream.py --upstream {upstream} --apply",
                  file=sys.stderr)
            print(f"  python scripts/apply_theme.py {theme}", file=sys.stderr)
            print("this works because an untheme'd instance takes the path that delivers "
                  "upstream's new scripts/ — including the renderer that can express the "
                  "new charter — before anything is rendered. Tracked as "
                  "noctua84/nescio-ai#142.", file=sys.stderr)
            return 2

        # Two calls into the UNMODIFIED plan_sync: `agents/` against the
        # materialised (themed) root, everything else against the real upstream.
        # `a1` first in every concatenation below — `"agents"` is first in
        # FRAMEWORK_PATHS, so this reproduces today's entry ordering exactly.
        # That is a dependency, not a coincidence, and a test pins it.
        #
        # Nothing here filters, suppresses or special-cases an entry, and
        # nothing may start to. Upstream's agent set is rendered into dest-space
        # *totally* and handed whole to the same set difference as always; that
        # is what keeps deletion mirroring intact. Skipping dest files with
        # philosopher stems would swallow a real deletion of `qa-guard.md`;
        # skipping a delete when some upstream agent maps onto it does the same
        # thing one indirection later and hides stale orphans besides.
        a1 = plan_sync(root, dest, paths=["agents"])
        a2 = plan_sync(upstream, dest, paths=others)
        added, updated, deleted = (x + y for x, y in zip(a1, a2))

        # Display-only: lets the diff header say which upstream file a themed
        # entry came from. Nothing depends on it.
        #
        # Keys are POSIX, not `str(Path(...))`: `render_diff` looks entries up by
        # `Path(rel).as_posix()`, so a `str(Path("agents") / "plato.md")` key is
        # `agents\plato.md` on Windows and silently never matches — a lookup
        # that fails into "no annotation", which is exactly the graceful,
        # unnoticeable failure this map is designed to have. Build the key the
        # way the lookup spells it.
        prov = {(Path("agents") / f"{dst}.md").as_posix():
                (Path("agents") / f"{src}.md").as_posix()
                for src, dst in renamed_agents(theme)}

        diff_text = ""
        if args.diff:
            # Both halves render with `summary=False` and main() appends one
            # footer with the combined counts. Two footers would be a lie about
            # the second half's numbers. Do NOT "simplify" this by having
            # main() splice or parse render_diff's output — that trades a
            # defaulted keyword for a format dependency between two functions.
            diff_text = (render_diff(root, dest, *a1, summary=False, provenance=prov)
                         + render_diff(upstream, dest, *a2, summary=False))
            if diff_text:
                diff_text += (f"net-new: {len(added)} added file(s), {len(updated)} updated, "
                              f"{len(deleted)} deleted\n")
        if args.apply:
            apply_sync(root, dest, paths=["agents"])
            apply_sync(upstream, dest, paths=others)

        return _report(args, dest, added, updated, deleted, diff_text, theme=theme)


if __name__ == "__main__":
    raise SystemExit(main())
