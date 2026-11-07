"""Shared helpers for the learning-loop scripts.

The learning loop promotes vetted "nominations" into the synced repo `memory/`
tree with provenance discipline and contradiction resolution — the mechanical
committer, analogous to how `mark_adopted.py` commits an adopt run.

  memory/<target>            promoted note (YAML frontmatter + body + provenance)
  memory/learning-log.md     tracked ledger — the dedup source

The ledger is keyed by a 12-hex content hash of the *nomination body as
submitted* — taken before the frontmatter and the provenance line are composed
on, so it is not a checksum of the note on disk and cannot be recomputed from the
repo. It dedups identical re-nominations, across machines, without re-writing the
note.

Contradiction resolution — when a nomination targets an existing note, the
higher-priority source wins; ties break toward the more recent date:

    user override  >  empirical  >  agent inference

## The brain guard

A promotion's destination follows the module default `REPO_DIR` above, which is
pinned to *whichever checkout the running script lives in* — not the cwd, and
not necessarily "the brain" (the one repository `<config>/memory` is meant to
point at). A real incident ran a promote from a sibling checkout and wrote 8
notes into the wrong tree at exit 0; because `promote_learnings.py` reads the
*destination* tree to dedup and resolve contradictions, every conclusion it drew
came out wrong in the same direction.

`check_brain()`/`guard_brain()` below make "run this in the brain" mechanical.
They compare the git identity of `REPO_DIR` against the git identity of
whatever `<config>/memory` resolves into, using a three-way evidence model:

  * **match** (`brain`) — both sides resolve to git repositories and their
    `--git-common-dir`s are equal. Silent; this is the expected case on every
    normal run.
  * **confirmed mismatch** (`mismatch`) — both sides resolve, and the
    common-dirs differ. This is the one state with positive evidence of a wrong
    destination, so it is the one state that refuses.
  * **everything else** (`broken` or `unknown`) — no `<config>/memory` entry; a
    symlink that does not resolve; `memory` resolving outside any git repo (a
    consumer who copied the tree instead of symlinking it); git missing, erroring,
    or timing out. None of these carries evidence of a *wrong* destination, only
    an *unverifiable* one, so none of them may hard-fail — they warn and proceed.

`broken` is split out of `unknown` deliberately, even though both warn-and-proceed
once the override is considered: a **dangling** symlink (`is_symlink()` true,
`exists()` false) means a brain was configured and has since moved or a relink
failed, which is a different, more actionable fact than "no `memory` entry was
ever created" — and conflating them would hide that the configuration is stale.

The comparison is on `--git-common-dir`, not `--show-toplevel`: the former is
identical between a worktree and its main checkout (verified empirically), while
the latter differs per worktree. Comparing common-dirs is what keeps a worktree
cut from the brain out of the `mismatch` branch — `REPO_DIR` itself may well be
such a worktree. Equal common-dirs alone only prove "same git repository",
though — a non-git copy of this tree nested inside the brain's own working copy
(no `.git` of its own) resolves up to the brain's common-dir too, so a `brain`
verdict additionally requires `repo_dir` to be its own git toplevel
(`git_toplevel`); a nested non-git subdirectory fails that second check and
falls to `mismatch`, while the brain's main checkout, any of its worktrees, and
a symlinked-in consumer all pass it.

Known limitations, recorded rather than left for a reader to rediscover:

  * A Windows **junction** that dangles reports `Path.is_symlink() == False`
    (junctions are not Win32 symlinks), so it lands in `unknown` rather than
    `broken`. Low likelihood in practice — `install.py` only ever creates real
    symlinks, never a junction — but it is a real hole in the `broken` verdict.
  * **CI structurally cannot reproduce a `mismatch`.** A CI runner has no
    `<config>/memory` at all, so every verdict there is `unknown`. These three
    `main()`s are therefore environment-dependent in a way the test suite
    cannot catch for real on that runner; the tests simulate each verdict with
    a controlled `CLAUDE_CONFIG_DIR` instead of relying on the ambient one.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

# ``sha8`` hashes a *file* (adopt flow) and is out of scope to rename here; it is
# re-exported only for callers that already depend on it. New learning-loop code
# uses ``content_hash12`` below, whose name reflects the 12 hex chars it returns.
from _adopt_common import sha8  # noqa: F401  (re-exported)

REPO_DIR = Path(__file__).resolve().parent.parent
LEARNING_LEDGER = REPO_DIR / "memory" / "learning-log.md"

# Source-of-truth precedence for contradiction resolution. Higher wins.
PRIORITY = {"user override": 3, "empirical": 2, "agent inference": 1}
VALID_SOURCES = set(PRIORITY)


def content_hash12(s: str) -> str:
    """Stable 12-hex content hash for a string (e.g. a nomination body).

    The first 12 hex chars of SHA-256 — enough to dedup note bodies while
    keeping the ledger line short.
    """
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:12]


def priority(source: str) -> int:
    """Precedence rank of a source; 0 for anything unrecognised."""
    return PRIORITY.get(source, 0)


def parse_ledger(path: Path = LEARNING_LEDGER) -> dict[str, tuple[str, str]]:
    """Return {hash12: (date, target)} for every recorded promotion.

    Line format: ``- <date> | <target> | <hash12> | promoted: <name>``
    """
    seen: dict[str, tuple[str, str]] = {}
    if not path.exists():
        return seen
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line.startswith("- "):
            continue
        parts = [p.strip() for p in line[2:].split("|")]
        if len(parts) < 4:
            continue
        date, target, h = parts[0], parts[1], parts[2]
        seen[h] = (date, target)
    return seen


# ── brain guard ──────────────────────────────────────────────────────────────
# See the "The brain guard" section of the module docstring for the evidence
# model this implements. The functions below are deliberately split so the
# check (`check_brain`) is pure and testable, and the side effect (printing,
# in `guard_brain`) is a thin wrapper around it — a pattern the entry points'
# own `main()`s already use for their own summaries.

# The env var name is spelled out once, here, so every message and every test
# that mentions it draws from the same string.
BRAIN_OVERRIDE_VAR = "NESCIO_LEARNING_ALLOW_NON_BRAIN"

# Environment variables that, if inherited from the caller, can distort the two
# git calls this guard makes, in one of two distinct attack shapes:
#
#   * REDIRECT git's answer to a fixed repository regardless of the ``cwd``
#     passed to ``subprocess.run`` — ``GIT_DIR``, ``GIT_COMMON_DIR``,
#     ``GIT_WORK_TREE``. This is the one failure direction where the guard
#     would confidently bless a *wrong* destination: a silent false MATCH,
#     rather than a false mismatch an operator would at least notice and could
#     override past.
#   * SUPPRESS git's answer entirely — ``GIT_CEILING_DIRECTORIES`` (stops
#     discovery at a named ancestor) and ``GIT_DISCOVERY_ACROSS_FILESYSTEM``.
#     A suppressed answer on either side degrades a confirmed ``mismatch`` to
#     ``unknown`` — warn and proceed at rc 0 — which is exactly the inherited,
#     destination-less boolean escape hatch the override mechanism in this
#     module (``BRAIN_OVERRIDE_VAR``) was written to prevent: unlike that
#     override, a bare ``GIT_CEILING_DIRECTORIES`` export names no destination
#     and silences the guard for every repository in the session. Verified:
#     exporting ``GIT_CEILING_DIRECTORIES`` to an ancestor of both repositories
#     turns a confirmed mismatch into ``unknown`` without this stripping.
#
# Nothing in this codebase exports any of them today; stripping them is cheap
# insurance against a future caller's environment, not a fix for an observed
# bug. The residual (git missing from ``PATH`` entirely) is inherent to the
# warn-on-no-evidence policy and is not something stripping can close.
_GIT_ENV_OVERRIDES = (
    "GIT_DIR",
    "GIT_COMMON_DIR",
    "GIT_WORK_TREE",
    "GIT_CEILING_DIRECTORIES",
    "GIT_DISCOVERY_ACROSS_FILESYSTEM",
)


def config_dir() -> Path:
    """Base config dir: $CLAUDE_CONFIG_DIR if set and non-empty, else ~/.claude.

    Mirrors ``hooks/record_stop.py``'s ``config_dir()`` exactly (same env var,
    same fallback). Duplicated rather than imported: scripts under
    ``scripts/`` run with ``PYTHONPATH=scripts``, so ``hooks/`` is not on
    ``sys.path`` and importing across that boundary would be the wrong fix for
    a one-function precedent.
    """
    env = os.environ.get("CLAUDE_CONFIG_DIR")
    return Path(env) if env else Path.home() / ".claude"


def _git_rev_parse(path: Path, *args: str) -> str | None:
    """Run ``git rev-parse <args>`` in ``path``; normalised stdout, or ``None``.

    Shared by ``git_common_dir`` and ``git_toplevel`` below — same env
    stripping (see ``_GIT_ENV_OVERRIDES`` above), same decoding, same
    None-on-any-failure contract. ``--path-format=absolute`` requires
    git >= 2.31; an older git simply errors, which this treats the same as
    every other failure: ``None``.

    DELIBERATE: ``encoding="utf-8", errors="replace"`` is not optional
    polish — do not "simplify" it away. Without it, ``text=True`` decodes
    git's (always-UTF-8) output using the *process locale* — cp1252, cp932,
    etc. on a legacy Windows console — and a byte sequence undefined in that
    codepage raises ``UnicodeDecodeError`` **inside subprocess's own reader
    thread**, where the exception does not propagate to this frame:
    ``result.returncode`` still comes back ``0`` and ``result.stdout`` comes
    back ``None``, so a bare ``result.stdout.strip()`` would raise
    ``AttributeError`` instead — a crash out of a function whose entire
    contract is "never raise, return ``None``", in exactly the locale this
    codebase has been bitten in before (see ``ConsoleEncodingTest`` in
    ``tests/test_promote_learnings.py``, the same failure class on the
    *output* side). ``scripts/module_gate.py``'s ``_run_git`` is the in-tree
    precedent for this call shape.

    The returned string is normalised — stripped, backslashes turned to
    forward slashes, case-folded — so a comparison between two calls is a
    plain string equality: git emits forward slashes on every platform,
    ``pathlib`` emits backslashes on Windows, and Windows paths compare
    case-insensitively.

    ``None`` covers a non-zero exit, empty or missing stdout, git not being
    on ``PATH`` (``FileNotFoundError``, a subclass of ``OSError``), any other
    OS-level failure, and a hung git process (bounded by ``timeout``). There
    is no partial-credit result: a caller that cannot tell "equal" from
    "unequal" must receive "unknown", never a guessed match or mismatch.
    """
    # See _GIT_ENV_OVERRIDES above: strip these so the git calls this guard
    # makes cannot be pinned to, or steered away from, a fixed answer by
    # inherited state.
    env = os.environ.copy()
    for var in _GIT_ENV_OVERRIDES:
        env.pop(var, None)
    try:
        result = subprocess.run(
            ["git", "rev-parse", *args],
            cwd=str(path),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=10,
        )
    except (OSError, ValueError, subprocess.TimeoutExpired):
        # OSError covers FileNotFoundError (no git on PATH) and every other
        # failure to even launch the process. ValueError — and so its
        # UnicodeDecodeError subclass — is belt-and-braces: it should not be
        # reachable with encoding=/errors= both set above, but a future edit
        # that drops either must not resurrect an uncaught crash here.
        return None
    # Test stdout for falsiness *before* .strip(): with encoding=/errors= set,
    # result.stdout should never be None, but this function's whole contract
    # is "never raise", so a None is handled rather than assumed away.
    if result.returncode != 0 or not result.stdout:
        return None
    out = result.stdout.strip()
    if not out:
        return None
    return out.replace("\\", "/").casefold()


def git_common_dir(path: Path) -> str | None:
    """Normalised ``git --git-common-dir`` for ``path``, or ``None`` on any failure.

    ``--git-common-dir`` (not ``--show-toplevel``) is what is identical between
    a worktree and its main checkout, which is the comparison the brain guard
    needs — a worktree cut from the brain must not register as a mismatch.
    See ``_git_rev_parse`` for the decoding, env-stripping and
    None-on-any-failure contract shared with ``git_toplevel``.
    """
    return _git_rev_parse(path, "--path-format=absolute", "--git-common-dir")


def git_toplevel(path: Path) -> str | None:
    """Normalised ``git --show-toplevel`` for ``path``, or ``None`` on any failure.

    Used only to confirm that ``repo_dir`` is its *own* git toplevel, not
    merely somewhere inside one — the check that catches a non-git copy of
    this tree nested inside the brain's working copy (see ``check_brain``'s
    "brain" branch). Unlike ``git_common_dir``, ``--show-toplevel``
    legitimately differs per worktree, which is exactly the property this
    check needs: a worktree's toplevel is its own root, and so is a nested
    non-git subdirectory's *parent* repository's root — never the
    subdirectory itself. Same call shape, env stripping, decoding and
    None-on-any-failure contract as ``git_common_dir``, via
    ``_git_rev_parse``.
    """
    return _git_rev_parse(path, "--path-format=absolute", "--show-toplevel")


def check_brain(repo_dir: Path = REPO_DIR) -> tuple[str, list[str]]:
    """Is ``repo_dir`` the brain? Returns ``(verdict, lines-to-print)``.

    Verdict is exactly one of ``"brain"``, ``"mismatch"``, ``"broken"``,
    ``"unknown"``, ``"override"`` — see the module docstring's "brain guard"
    section for what each one means and why only ``mismatch``/``broken`` may
    refuse.

    DELIBERATE: no line returned here ever contains an absolute filesystem path
    or a repository name — not even a basename, since the brain's basename *is*
    the string this public repo must not leak into a pasted stderr, a tracked
    ``.sisyphus/`` note, or a PR body. There is no mechanical backstop for this
    (``scrub-terms.local`` is gitignored and typically absent; the baseline
    home-path pattern only warns), so do not "improve" these messages by adding
    a path back in — that is the one change to this function that would be a
    regression even though it looks like better diagnostics.

    A ``"brain"`` verdict requires both equal ``--git-common-dir``s *and*
    ``repo_dir`` being its own git toplevel (``git_toplevel``) — see the
    module docstring for why common-dir equality alone is not enough.
    """
    mem = config_dir() / "memory"

    if mem.is_symlink() and not mem.exists():
        # Configured, but the target has moved or a relink failed (see
        # install.py's own handling of exactly this state). A *broken* brain,
        # not an absent one — kept apart from "unknown" below so this state is
        # never silently indistinguishable from "no brain was ever set up".
        verdict = "broken"
    elif not mem.exists():
        return "unknown", [
            "warning: no brain is configured (~/.claude/memory does not exist);"
            " proceeding without checking the promotion destination."
        ]
    elif not mem.is_dir():
        # `memory` exists but is not a directory -- a regular file, or a
        # symlink to one. Same "configured but broken" class as the dangling
        # symlink above, not merely "unverifiable": something set this up and
        # it is not a usable memory tree. Checked ahead of the git calls
        # below on purpose -- passing a non-directory as `cwd` to
        # subprocess.run would raise NotADirectoryError, which git_common_dir
        # would otherwise swallow into a generic "unknown" via its
        # None-on-any-failure contract, hiding this specific, actionable case
        # inside "nothing is configured at all".
        verdict = "broken"
    else:
        brain_key = git_common_dir(mem.resolve())
        repo_key = git_common_dir(repo_dir)
        if brain_key is None or repo_key is None:
            return "unknown", [
                "warning: could not determine whether this repository is the"
                " brain (git could not be queried on one side); proceeding"
                " without checking the promotion destination."
            ]
        if brain_key != repo_key:
            verdict = "mismatch"
        else:
            # Equal common-dirs prove "same git repository", not "same
            # memory/ tree": a non-git copy of this tree nested inside the
            # brain's own working copy (no .git of its own) resolves up to
            # the brain's common-dir too. Require repo_dir to also be its
            # own git toplevel -- the brain's main checkout, any of its
            # worktrees, and a symlinked-in consumer all satisfy this; a
            # nested non-git subdirectory does not, and falls to "mismatch".
            toplevel = git_toplevel(repo_dir)
            if toplevel is None:
                return "unknown", [
                    "warning: could not determine whether this repository is"
                    " the brain (git could not be queried on one side);"
                    " proceeding without checking the promotion destination."
                ]
            # Normalised the same way git_common_dir/git_toplevel normalise
            # their own output (posix separators, casefold) -- comparing a
            # raw Path against git's string would false-mismatch on every
            # Windows path.
            normalised_repo = str(repo_dir).replace("\\", "/").casefold()
            if toplevel == normalised_repo:
                return "brain", []
            verdict = "mismatch"

    # Only "broken" and "mismatch" reach this point — "brain" and both
    # "unknown" branches above already returned. Per the design, the override
    # is considered for exactly these two refusing verdicts.
    override = os.environ.get(BRAIN_OVERRIDE_VAR, "")
    if override and override.casefold() == repo_dir.name.casefold():
        # Deliberately a one-sided equality, not a truthiness check: a bare
        # ``=1`` must not override (unless the repo dir is literally named
        # "1", which this equality handles on its own). An env var is
        # inherited silently by every subprocess, so a boolean exported once
        # to unblock one refusal would silence the guard for every repository
        # in that shell session; requiring it to name its destination means a
        # stale export cannot bless a different repository.
        return "override", [
            f"warning: brain check overridden via {BRAIN_OVERRIDE_VAR}"
            " (value matched this repository's directory name); proceeding"
            " anyway."
        ]

    if verdict == "broken":
        return "broken", [
            "error: the configured brain does not resolve -- refusing to write.",
            "       ~/.claude/memory is a symlink, but its target is missing.",
            "       recreate it (see install.py), or run:",
            "           readlink -f ~/.claude/memory",
            "       to see what it currently points at, then fix it there, or",
            f"       set {BRAIN_OVERRIDE_VAR} to this repository's directory",
            "       name to override.",
        ]

    return "mismatch", [
        "error: this repository is not the brain -- refusing to write.",
        "       the brain is whichever repository ~/.claude/memory resolves",
        "       into:",
        "           readlink -f ~/.claude/memory",
        "       run this flow from there, or set",
        f"       {BRAIN_OVERRIDE_VAR} to this repository's directory name to",
        "       override.",
    ]


def guard_brain(repo_dir: Path = REPO_DIR, stream=None) -> int:
    """Print ``check_brain``'s verdict for ``repo_dir`` and return its exit code.

    Returns ``2`` for ``mismatch``/``broken`` (refuse) and ``0`` for
    ``brain``/``unknown``/``override`` (proceed) — callers do
    ``rc = guard_brain(); if rc: return rc`` as the very first thing in
    ``main()``, before any other work.

    Defaults to ``sys.stderr``, not ``sys.stdout`` — matching this codebase's
    own convention for a refusal/warning line (see ``mark_harvested.py``'s
    ``REFUSE`` path and its ``WARNING`` lines, both on stderr). This is also
    what keeps the guard from being observable on stdout at all in the normal
    case: several entry points' tests assert on the exact first line or shape
    of stdout (e.g. ``begin_harvest``'s ``read_at`` being line one), and those
    fixtures legitimately run with no ``<config>/memory`` entry — the
    "unknown" verdict's warning line must not land in the stream those
    assertions read.

    Called **only** from an entry point's ``main()`` — never at import time and
    never from inside ``promote()``, ``collect()``, ``summarise()``, or any
    other function that a test or a programmatic caller might invoke directly
    with an explicit destination. Every such caller has already stated where it
    is writing; the thing this guard exists to catch is the *implicit* default
    that only a bare CLI invocation relies on.
    """
    verdict, lines = check_brain(repo_dir)
    out = stream or sys.stderr
    for line in lines:
        print(line, file=out)
    return 2 if verdict in ("mismatch", "broken") else 0
