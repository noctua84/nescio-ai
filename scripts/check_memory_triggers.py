#!/usr/bin/env python3
"""Evaluate ADR 0002's four memory revisit triggers (#168).

ADR 0002 named four conditions under which the "no semantic retrieval" decision
should be reopened. ADR 0005 then superseded it and recorded that **two of the
four were never instrumented** — so the largest architectural decision in the
project is being made without half the signals it specified for itself. This
script turns that prose list into something runnable.

**It never writes.** Not to `memory/`, not to the trail directory, not to
GitHub. It is a reporter, exactly as `scripts/check_roadmap_drift.py` is a
checker rather than a generator, and for the same reason: the thing it measures
is hand-curated, and a tool that could edit what it measures cannot be trusted
to report on it.

**It is deliberately not wired into CI.** Triggers 3 and 4 read machine-local
state — the learning-trail directory and the session transcripts under
`~/.claude/projects/` — neither of which exists on a runner. In CI it would
report `unknown` for half its rules forever, which is worse than not running:
a rule that is always unknown stops being read.

## The four triggers, and what each one actually counts

**T1 — any single `memory/` directory exceeds ~100 notes.**
**T2 — the corpus exceeds ~500 notes.**

Both were always computable; nobody had computed them. A "note" here is
precisely *what a `MEMORY.md` indexes*, because that is what the trigger is
about: ADR 0002's own wording is "such that a `MEMORY.md` index no longer fits
comfortably in context". So the count comes from `_wiki_common.iter_notes`, the
same iterator `wiki_index.build_index` uses to generate the index — not from a
fresh `*.md` glob. Deriving it from anything else would let the reported number
and the indexed number drift, and the indexed number is the one the trigger is a
proxy for. It consequently counts `readiness.md` (which *is* indexed) and skips
`MEMORY.md`, `index.md`, and dot-directories (`.obsidian`).

T1's unit is a **directory**, non-recursively, because one directory is one
`MEMORY.md`. `repo/x/adr/` has its own index and so is its own unit rather than
part of `repo/x/`.

The `~` in "~100" and "~500" has to resolve to a number for a check to exist.
It resolves to the literal values, `>=`, and the report always prints the margin
so a human can see proximity rather than only the verdict — a directory at 80 of
100 is a different situation from one at 12, and a bare `clear` hides that.

**T3 — a harvest pass reports it cannot determine where to file a learning.**

This was never a measurement gap; it was a **capability** gap, which is why
instrumenting it needed a change to `promote_learnings.py` and not just a
counter. See that module's docstring and `scripts/_unrouted_record.py`. Here it
is only read.

The ADR supplies this trigger's own threshold — "reports it cannot" is one or
more — so unlike T4 there is nothing for this script to invent.

An **absent** tally reads `unknown`, not `clear`. The file's absence cannot
distinguish "every harvest routed everything" from "no harvest has run since the
instrument landed", and every harvest in this repo's history falls in the second
class. Reporting that as a clean bill would be the precise failure ADR 0004
built its `unknown` state to prevent: missing evidence collapsing into a good
verdict. A *present* tally always means a count of one or more, because the
record is only ever created by an increment.

**T4 — agents are observed grepping past the index because description-routing
stopped resolving.**

This one needs a definition, and the definition is the substance of the trigger,
so it is argued here rather than assumed.

*What counts as going past the index.* A **search** against `memory/` does;
a read of a note does not. The index is a link list you read, not something you
search, so a search is an agent declining the routing mechanism. A read, by
contrast, is what the index is *for* — and an agent reading a note may simply
have been handed the path by its caller, which is evidence of nothing.

*Where the raw definition is wrong, and this is the pushback.* The trigger's
wording carries a causal clause — "**because** description-routing stopped
resolving" — and a bare search does not establish it. Two events look identical
to a naive counter and mean opposite things:

  * the agent read a `MEMORY.md`, then searched `memory/` → the index was
    consulted and **did not suffice**. This is the trigger's actual condition.
  * the agent searched `memory/` cold, having read no index → the index never
    failed, because it was never tried. That is a habit, or a tool preference,
    and counting it as routing failure would inflate the trigger with evidence
    of the opposite problem.

So both are reported, separately, and the report names which one the ADR's
wording actually asks for. Collapsing them into one rate would be the kind of
number that reads as evidence and is not.

*Measurement quality is reported, not hidden.* Searches arrive in two very
different grades:

  * **structured** — a `Grep` or `Glob` call whose own path/glob parameter names
    `memory/`. The tool's parameters say what the target was; there is nothing
    to infer.
  * **shell** — a `Bash`/`PowerShell` command where a search utility takes a
    `memory/` path operand. This is **heuristic**, and measurably so: on this
    machine's corpus, counting any command that mentions `memory/` *and*
    contains a search utility anywhere yields 1730 hits, while requiring the two
    to occur in the same command segment yields 478 — so roughly 70% of the
    naive count is compound commands like
    `git diff -- memory/... && echo x | grep y`, where the search never touched
    `memory/` at all. The segment rule is what this script uses, and the shell
    tier is still reported on its own line because its residual error rate is
    not zero and a reader calibrating a threshold needs to know which half of
    the number they can lean on.

  Excluding the shell tier was considered and rejected: `Bash` is the dominant
  tool by an order of magnitude (735 of ~1180 calls in a sample), so a
  structured-only rate would not be conservative, it would be wrong.

  * **unclassified** — a tool outside `EMITTABLE_TOOLS` (an MCP server, a
    plugin) whose input touched `memory/`. Reported as a coverage caveat and
    **never folded into the rate**: nothing here can distinguish a
    `search_memory` server from a `write_memory` one, and a guess either way
    would put invented data into the trigger that exists to stay honest. This
    bucket is also what keeps the privacy allowlist on a reachable code path —
    see `classify_block`.

*The denominator.* Sessions that touched `memory/` at all. A session that never
went near `memory/` cannot exhibit routing failure, and including it would let
the rate fall simply because unrelated work happened. The raw session total is
printed too, so another denominator can be computed by hand.

*Sessions, not files.* A subagent transcript lives at
`<project>/<session_id>/subagents/agent-*.jsonl` and carries its **parent's**
`sessionId`, so one session spans many files — on this machine 4550 of 5078
transcript files are subagent files. Counting files as sessions would overstate
the denominator by roughly ninefold. Everything here groups on `sessionId`.

*Ordering, for the post-index refinement.* Only ~84% of records carry a
`timestamp`. A search is counted as post-index only when both it and some index
read in the same session have timestamps and the search is not earlier. A record
without a timestamp still counts toward the broad bucket but can never establish
ordering — it degrades the refinement toward *under*-reporting, which is the
safe direction for a signal nobody has calibrated yet.

**T4 never fires, by design.** It has no threshold, because no threshold has
been chosen, and this script will not choose one: a trigger that fires on a
number nobody picked is worse than one that reports honestly. Its verdict is
always `unknown (uncalibrated)` and it can never affect the exit code. ADR 0004
applies exactly this discipline to its own `unknown` state.

## Privacy — the hard constraint

This repository is public. Transcripts contain arbitrary user content, absolute
file paths, third-party project names, and operator-configured MCP server names
of the form `mcp__<server>__<tool>`. A leak of exactly that class was caught
during #70's review.

So the rule is: **counts, and paths under `memory/`, and nothing else.** No
transcript text, no command strings, no `cwd`, no absolute paths from a record.
Tool names are emitted only from `EMITTABLE_TOOLS`, an allowlist of
Claude Code's own built-ins; anything else is bucketed by `tool_label` to
`MCP tool` or `other tool`. The allowlist is a *list*, not a pattern — an
`mcp__`-prefix denylist would have to anticipate every future namespace, and the
one it failed to anticipate is the one that leaks.

Transcript contents are read freely; the constraint is on what is *emitted*.

## Cost

A full structural pass is I/O-bound over the whole transcript corpus — on this
machine 5078 files and ~4.0 GB, taking ~130s. (#168 estimated ~1600 MB and
"well under a minute"; the corpus has since grown, and the honest figure is
minutes, not seconds.) Lines are prefiltered on the raw bytes `b"emory"` before
any JSON parsing, which reduces the parsed set from ~1.5M records to ~15k. This
never runs in a hook, so minutes are acceptable — but `--skip-transcripts`
exists for when only T1–T3 are wanted.

Exit codes are three-valued, mirroring `check_roadmap_drift.py` and
`verify_commit_position.py`, so a caller can tell "a trigger fired" from "the
check could not run":

  0  no trigger fired (an `unknown` verdict may still be reported)
  1  at least one trigger FIRED
  2  could not check — `memory/` could not be read, which makes T1 and T2,
     the two triggers that are purely computable, unanswerable

A failed *transcript* scan is not a 2: T4 cannot fire, so its failure costs the
report a refinement, not a verdict. A missing unrouted tally is likewise not a
2 — `unknown` is T3's correct answer there, and it is a real answer.

Usage:
    python scripts/check_memory_triggers.py
    python scripts/check_memory_triggers.py --memory-root C:/path/to/brain/memory
    python scripts/check_memory_triggers.py --skip-transcripts
    python scripts/check_memory_triggers.py --json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hooks"))
import record_stop as rs  # noqa: E402

import _trail_scope  # noqa: E402
import _unrouted_record  # noqa: E402
from _wiki_common import iter_notes  # noqa: E402

REPO_DIR = Path(__file__).resolve().parent.parent
DEFAULT_MEMORY_ROOT = REPO_DIR / "memory"

# ADR 0002's "~100" and "~500", resolved to numbers so a check can exist. `>=`,
# so a directory sitting exactly on the named figure is reported as having
# reached it rather than as one short.
DIR_NOTE_LIMIT = 100
CORPUS_NOTE_LIMIT = 500

# How many records the scan reads from a transcript's head to learn which
# session and which repository it belongs to. Borrowed from
# `_trail_scope.HEAD_SCAN_RECORDS` and for the same reason: generous enough that
# a leading run of records without a `cwd` does not lose the file, small enough
# that a corrupt multi-megabyte transcript is still cheap to give up on.
HEAD_SCAN_RECORDS = _trail_scope.HEAD_SCAN_RECORDS

TRIGGER_DIR = "t1-directory-size"
TRIGGER_CORPUS = "t2-corpus-size"
TRIGGER_UNROUTED = "t3-unrouted-harvest"
TRIGGER_BYPASS = "t4-index-bypass"

VERDICT_FIRED = "FIRED"
VERDICT_CLEAR = "clear"
VERDICT_UNKNOWN = "unknown"

EXIT_PASS = 0
EXIT_FIRED = 1
EXIT_ERROR = 2

# ── privacy ────────────────────────────────────────────────────────────────

# Tool names this script may print. Claude Code's own built-ins only: every one
# of these ships with the harness, so none can carry operator configuration.
# Anything absent here is bucketed by `tool_label`.
#
# An allowlist rather than an `mcp__*` denylist, deliberately. A denylist has to
# anticipate every namespace a future plugin, MCP server, or harness feature
# might introduce, and the single namespace it fails to anticipate is the one
# that ends up in a public repository.
EMITTABLE_TOOLS = frozenset(
    {
        "Agent",
        "AskUserQuestion",
        "Bash",
        "BashOutput",
        "Edit",
        "ExitPlanMode",
        "Glob",
        "Grep",
        "KillShell",
        "Monitor",
        "NotebookEdit",
        "PowerShell",
        "Read",
        "SendMessage",
        "Skill",
        "SubagentHandback",
        "Task",
        "TodoWrite",
        "ToolSearch",
        "WebFetch",
        "WebSearch",
        "Write",
    }
)

MCP_BUCKET = "MCP tool"
OTHER_BUCKET = "other tool"


def tool_label(name: object) -> str:
    """A printable label for a tool name — allowlisted, or bucketed.

    The only function in this script that turns a transcript-derived tool name
    into output, so the privacy property is enforced in one place and is
    testable on its own. `tests/test_memory_triggers.py` asserts that no line
    this script emits can contain an `mcp__` name.
    """
    if isinstance(name, str) and name in EMITTABLE_TOOLS:
        return name
    if isinstance(name, str) and name.startswith("mcp__"):
        return MCP_BUCKET
    return OTHER_BUCKET


# ── note counting (T1, T2) ─────────────────────────────────────────────────


def count_notes(memory_root: Path) -> tuple[int, dict[str, int]]:
    """``(corpus total, {relative dir -> note count})`` for ``memory_root``.

    Both numbers come from `_wiki_common.iter_notes` — the index generator's own
    iterator — so what this reports and what a `MEMORY.md` lists cannot diverge.
    The corpus is the recursive sweep; the per-directory map is built from the
    same walk by grouping on each note's parent, which keeps the two numbers
    arithmetically consistent (the directory counts always sum to the corpus).

    Directory keys are posix-relative to ``memory_root`` (`"."` for the root
    itself) — paths under `memory/`, which is what the privacy rule permits.

    Raises ``OSError`` if ``memory_root`` is not a readable directory; the
    caller turns that into exit 2. The existence check is explicit because
    `Path.rglob` on a missing directory yields **nothing** rather than raising —
    so without it a mistyped `--memory-root` reports a corpus of 0 and T2 reads
    `clear`, which is a reassuring verdict derived from a path that does not
    exist. That is the precise failure this script's `unknown` discipline exists
    to prevent, arriving through the one trigger that is supposed to be certain.
    """
    if not memory_root.is_dir():
        raise OSError(f"not a directory: {memory_root}")
    per_dir: dict[str, int] = {}
    total = 0
    for path, _fm, _body in iter_notes(memory_root, recursive=True):
        total += 1
        rel = path.parent.relative_to(memory_root).as_posix() or "."
        per_dir[rel] = per_dir.get(rel, 0) + 1
    return total, per_dir


# ── memory-path recognition (T4) ───────────────────────────────────────────

# `memory` occurring as a genuine PATH SEGMENT, in either of the two shapes a
# command line can present it:
#
#   .../memory      — preceded by a separator, not glued to a longer word
#   memory/...      — at a token boundary, followed by a separator
#
# The lookarounds are what keep two whole classes of false positive out, both of
# which the naive `"memory/" in cmd` test admitted:
#
#   `grep -n "memory" install.py`  → a search PATTERN, not a path. Rejected:
#                                    `memory` is followed by `"`, not a separator.
#   `find .../skills/harvest-memory` → a different directory that merely ends in
#                                    the word. Rejected: preceded by `-`.
_MEM_SEGMENT_RE = re.compile(
    r"(?<=[/\\])memory(?![\w.\-])"      # a trailing segment: ui/memory
    r"|(?<![\w.\-])memory(?=[/\\])"     # a leading segment:  memory/repo/x
)

# A `MEMORY.md` index, inside a `memory/` path. Requiring the `memory` prefix
# stops an unrelated `MEMORY.md` elsewhere in a tree from reading as this
# brain's index.
_INDEX_RE = re.compile(r"memory[/\\](?:[\w.\-]+[/\\])*MEMORY\.md", re.IGNORECASE)

# Search utilities. A command that invokes one of these against a `memory/` path
# is searching the corpus; `cat`, `git`, `ls` and friends are not searches and
# are deliberately absent. `find` is included — it searches by name, which is
# precisely routing-by-filename rather than routing by description.
_SEARCH_RE = re.compile(
    r"(?:^|\s)(?:rg|grep|egrep|fgrep|ag|ack|findstr|Select-String|sls|find)(?:\s|$)"
)

# Command-segment separators. Splitting on these is what scopes a search token
# to the operands that actually belong to it.
_SEG_SPLIT_RE = re.compile(r"\|\||&&|[|;\n]")

# Which input fields of which tool name carry a PATH. Per-tool, because the same
# key means different things to different tools: `Grep`'s `pattern` is content
# to match, while `Glob`'s `pattern` is a path glob. Matching `Grep.pattern`
# would recreate the `grep -n "memory"` false positive inside the tier that is
# supposed to be exact.
SEARCH_TOOL_PATH_FIELDS: dict[str, tuple[str, ...]] = {
    "Grep": ("path", "glob"),
    "Glob": ("pattern", "path"),
}


def is_memory_path(value: object) -> bool:
    """True when ``value`` is a path with a `memory` segment.

    For a structured tool parameter, where the whole value *is* a path, so the
    test is an exact segment comparison rather than the regex used on shell
    text. That also catches the bare `memory` a `Grep(path="memory")` would pass
    — a value the command-line regex cannot accept, because in free shell text a
    bare `memory` is far more often a word than a directory.
    """
    if not isinstance(value, str) or not value:
        return False
    return any(seg == "memory" for seg in re.split(r"[/\\]", value))


def neutralise_quoted_separators(cmd: str) -> str:
    """Replace segment separators *inside quotes* with spaces, preserving length.

    Without this, splitting on `|` tears a command apart at a separator that the
    shell would never have treated as one, and the halves stop being attributable:
    `grep -n "24\\|forfeit" memory/notes.md` splits inside the regex alternation,
    stranding `grep` in one segment and `memory/notes.md` in the next — a genuine
    memory search silently dropped.

    Length is preserved (one character out per character in) so nothing else
    about the text shifts. Only separators are touched; a quoted *path* survives
    intact, so `grep -n x "memory/notes.md"` still matches.
    """
    out = list(cmd)
    quote: str | None = None
    i = 0
    while i < len(out):
        ch = out[i]
        if quote is None:
            if ch in "\"'":
                quote = ch
        elif ch == "\\" and quote == '"':
            # An escaped character inside double quotes is literal text, so a
            # separator there is still not a separator and must be neutralised
            # before the index advances past it. Skipping the pair without
            # neutralising is what let `grep -n "24\|forfeit" memory/x` tear in
            # half -- the exact false negative this function exists to prevent.
            if i + 1 < len(out) and out[i + 1] in "|;&\n":
                out[i + 1] = " "
            i += 2
            continue
        elif ch == quote:
            quote = None
        elif ch in "|;&\n":
            out[i] = " "
        i += 1
    return "".join(out)


def shell_searches_memory(cmd: object) -> bool:
    """True when ``cmd`` invokes a search utility against a `memory/` path.

    The search token and the memory operand must occur in the **same command
    segment**, and the operand must follow the token. Both halves of that rule
    earn their place empirically — see the module docstring's 1730-vs-478
    measurement. Without the segment scoping, every
    `git diff -- memory/x && ... | grep y` counts as a memory search; without
    requiring the operand to come *after* the token, so does
    `cat memory/x | grep y`, which searches a note's contents that the agent had
    already located by path.

    Heuristic by nature: this parses shell text, not a parse tree. Reported on
    its own line for that reason, never merged into the structured count.
    """
    if not isinstance(cmd, str) or not cmd:
        return False
    if not _MEM_SEGMENT_RE.search(cmd):
        return False
    for segment in _SEG_SPLIT_RE.split(neutralise_quoted_separators(cmd)):
        match = _SEARCH_RE.search(segment)
        if match and _MEM_SEGMENT_RE.search(segment[match.end():]):
            return True
    return False


def classify_block(block: dict) -> tuple[str | None, bool]:
    """``(tier, reads the index)`` for one `tool_use` block.

    Tier is ``"structured"``, ``"shell"``, ``"unclassified"``, or None.

    The index flag is set when the block references a `memory/.../MEMORY.md`
    path *and* is not itself a search — an agent that greps the index file is not
    reading it as a routing table, and letting that count as an index read would
    make the post-index refinement treat a bypass as its own justification.

    "References the index" is matched against the whole serialised input rather
    than a named field: the index can arrive as a `Read`'s `file_path`, a
    `Bash`'s `cat`, or an `Agent`'s prompt, and what matters for the refinement
    is only that it was in front of the agent.

    **`EMITTABLE_TOOLS` does double duty here, and deliberately.** It is the set
    of tools whose *semantics this script knows*, which is the same set as the
    tools it is allowed to *name* — both properties follow from "ships with the
    harness". A `Read` of a note is therefore classified (known: not a search);
    an operator-configured MCP or plugin tool that touches `memory/` is
    `unclassified`, because nothing here can tell a `search_memory` server from
    a `write_memory` one, and guessing either way would put invented data into
    the one trigger that is supposed to stay honest.

    That bucket is also what keeps `tool_label` on a reachable path. An earlier
    draft classified only Grep/Glob/Bash/PowerShell — all allowlisted — so no
    unrecognised name could ever reach the output, and the privacy test passed
    because the code it guarded was dead. A vacuous privacy test is worse than a
    failing one.
    """
    name = block.get("name")
    inp = block.get("input")
    if not isinstance(inp, dict):
        return None, False

    try:
        blob = json.dumps(inp, default=str)
    except (TypeError, ValueError):
        blob = ""

    if not (isinstance(name, str) and name in EMITTABLE_TOOLS):
        # An unknown tool. Relevant to T4 only if it went near `memory/` at all;
        # reported as a coverage caveat, never folded into the search rate.
        touches = bool(_MEM_SEGMENT_RE.search(blob)) or any(
            is_memory_path(v) for v in inp.values() if isinstance(v, str)
        )
        return ("unclassified" if touches else None), False

    tier: str | None = None
    if name in SEARCH_TOOL_PATH_FIELDS:
        for key in SEARCH_TOOL_PATH_FIELDS[name]:
            if is_memory_path(inp.get(key)):
                tier = "structured"
                break
    if tier is None and name in ("Bash", "PowerShell"):
        if shell_searches_memory(inp.get("command")):
            tier = "shell"

    reads_index = tier is None and bool(_INDEX_RE.search(blob))
    return tier, reads_index


# ── the transcript scan (T4) ───────────────────────────────────────────────


@dataclass
class _SessionState:
    """Per-session accumulators for the transcript scan. Internal to the scan."""

    touched_memory: bool = False
    structured: int = 0
    shell: int = 0
    unclassified: int = 0
    index_times: list[str] = field(default_factory=list)
    search_times: list[str] = field(default_factory=list)
    untimed_searches: int = 0


@dataclass(frozen=True)
class Scan:
    """What the transcript corpus says about T4. Counts only — see the privacy note.

    `by_tool` is keyed by `tool_label`, so it is already safe to print.
    """

    files: int = 0
    unreadable: int = 0
    sessions: int = 0
    memory_sessions: int = 0
    search_sessions: int = 0
    structured_sessions: int = 0
    shell_sessions: int = 0
    post_index_sessions: int = 0
    structured_calls: int = 0
    shell_calls: int = 0
    unclassified_calls: int = 0
    unclassified_sessions: int = 0
    by_tool: dict[str, int] = field(default_factory=dict)
    scanned: bool = True
    reason: str | None = None

    @property
    def search_calls(self) -> int:
        """Searches only. `unclassified_calls` is deliberately NOT included —
        folding tools of unknown semantics into the rate would invent data."""
        return self.structured_calls + self.shell_calls


def cwd_in_repo(cwd: object, repo_root_posix: str) -> bool:
    """True when a record's ``cwd`` belongs to ``repo_root_posix``.

    Normalisation and worktree-collapsing are `_trail_scope`'s, reused rather
    than re-derived so this script and the harvest tooling cannot disagree about
    which repository a path belongs to.

    Unlike `_trail_scope.belongs_to_repo`, the comparison is **at-or-under**
    rather than equality. That module compares recorded *git roots*, which are
    already repository-identifying; a transcript records a working directory,
    which is legitimately a subdirectory of the repo, so equality would drop
    every session that happened to start one level down.

    Case is compared exactly, following `_trail_scope.posix_path`'s explicit
    decision not to case-fold on any platform. A Windows `cwd` recorded with
    different drive-letter or directory casing than the resolved repo root is
    therefore not attributed. That is a known limitation, not an oversight: the
    alternative is this script holding a second opinion about path identity,
    which is the exact failure `_trail_scope` exists to prevent.
    """
    if not repo_root_posix:
        return True  # unscoped: no repo to compare against
    raw = _trail_scope.posix_path(cwd)
    if not raw:
        return False
    norm = _trail_scope.strip_worktree(raw) or raw
    return norm == repo_root_posix or norm.startswith(repo_root_posix + "/")


def scan_transcripts(transcript_dir: Path, repo_root_posix: str) -> Scan:
    """Derive T4's counts from the transcript corpus. Never raises.

    Streams every `*.jsonl` under ``transcript_dir``, prefiltering on the raw
    bytes `b"emory"` before decoding or parsing — `memory`, `MEMORY` and
    `Memory` all contain it, and on this machine that drops the parsed set from
    ~1.5M records to ~15k, which is the difference between a tolerable pass and
    an untenable one.

    Grouping is on `sessionId`, never on file: subagent transcripts carry their
    parent's id, so one session routinely spans many files.
    """
    if not transcript_dir.is_dir():
        return Scan(scanned=False, reason="no-transcripts")

    # Two containers, and the split is the whole point of the denominator. A
    # session enters `in_scope` on its *existence* in this repo, independently
    # of whether it ever touched `memory/`; it enters `sessions` only when it
    # did. Deriving the denominator from `sessions` instead would make the broad
    # rate 100% by construction — every session in it would be a memory session
    # — which is a number that looks like a measurement and is an identity.
    in_scope: set[str] = set()
    sessions: dict[str, _SessionState] = {}
    by_tool: dict[str, int] = {}
    files = unreadable = 0

    for path in sorted(transcript_dir.rglob("*.jsonl")):
        files += 1
        try:
            handle = open(path, "rb")
        except OSError:
            unreadable += 1
            continue
        try:
            with handle:
                head = 0
                identified = False
                for raw in handle:
                    # Every record in one file shares one `sessionId` (a
                    # subagent file carries its PARENT's), so the file's session
                    # is learnable from its head. Bounded, because a leading run
                    # of records without a `cwd` must not cost a full parse of a
                    # multi-megabyte transcript.
                    if not identified and head < HEAD_SCAN_RECORDS:
                        head += 1
                        identified = _register_session(raw, repo_root_posix, in_scope)
                    if b"emory" not in raw or b'"tool_use"' not in raw:
                        continue
                    try:
                        record = json.loads(raw.decode("utf-8", "replace"))
                    except (json.JSONDecodeError, ValueError):
                        continue
                    if not isinstance(record, dict):
                        continue
                    _consume_record(record, repo_root_posix, sessions, by_tool)
        except OSError:
            unreadable += 1
            continue

    return _summarise_scan(files, unreadable, in_scope, sessions, by_tool)


def _register_session(
    raw: bytes, repo_root_posix: str, in_scope: set[str]
) -> bool:
    """Note the session a transcript line belongs to. True once identified.

    Returns True only when the line yielded both a `sessionId` and a usable
    `cwd` — a record carrying one but not the other says nothing about scope, so
    the head scan continues to the next line rather than attributing the file on
    half the evidence. Mirrors `_trail_scope.trail_repo_root`'s reasoning about a
    rootless head record.
    """
    try:
        record = json.loads(raw.decode("utf-8", "replace"))
    except (json.JSONDecodeError, ValueError):
        return False
    if not isinstance(record, dict):
        return False
    session_id = record.get("sessionId")
    cwd = record.get("cwd")
    if not isinstance(session_id, str) or not session_id:
        return False
    if not _trail_scope.posix_path(cwd):
        return False
    if cwd_in_repo(cwd, repo_root_posix):
        in_scope.add(session_id)
    return True


def _consume_record(
    record: dict,
    repo_root_posix: str,
    sessions: dict[str, _SessionState],
    by_tool: dict[str, int],
) -> None:
    """Fold one transcript record into the per-session accumulators."""
    session_id = record.get("sessionId")
    if not isinstance(session_id, str) or not session_id:
        return
    if not cwd_in_repo(record.get("cwd"), repo_root_posix):
        return
    message = record.get("message")
    if not isinstance(message, dict):
        return
    content = message.get("content")
    if not isinstance(content, list):
        return

    timestamp = record.get("timestamp")
    stamp = timestamp if isinstance(timestamp, str) and timestamp else None

    for block in content:
        if not isinstance(block, dict) or block.get("type") != "tool_use":
            continue
        tier, reads_index = classify_block(block)
        if tier is None and not reads_index:
            continue
        state = sessions.setdefault(session_id, _SessionState())
        state.touched_memory = True
        if reads_index:
            if stamp:
                state.index_times.append(stamp)
            continue
        label = tool_label(block.get("name"))
        by_tool[label] = by_tool.get(label, 0) + 1
        if tier == "unclassified":
            state.unclassified += 1
            continue
        if tier == "structured":
            state.structured += 1
        else:
            state.shell += 1
        if stamp:
            state.search_times.append(stamp)
        else:
            state.untimed_searches += 1


def _summarise_scan(
    files: int,
    unreadable: int,
    in_scope: set[str],
    sessions: dict[str, _SessionState],
    by_tool: dict[str, int],
) -> Scan:
    """Collapse per-session state into the reportable counts."""
    memory_sessions = search_sessions = 0
    structured_sessions = shell_sessions = post_index_sessions = 0
    structured_calls = shell_calls = 0
    unclassified_calls = unclassified_sessions = 0

    for state in sessions.values():
        if state.touched_memory:
            memory_sessions += 1
        structured_calls += state.structured
        shell_calls += state.shell
        unclassified_calls += state.unclassified
        if state.unclassified:
            unclassified_sessions += 1
        if state.structured:
            structured_sessions += 1
        if state.shell:
            shell_sessions += 1
        if state.structured or state.shell:
            search_sessions += 1
            # Post-index requires a timestamp on BOTH sides. An untimed search
            # cannot be ordered against anything, so it never qualifies — the
            # refinement under-reports rather than guessing, which is the safe
            # direction for an uncalibrated signal.
            if state.index_times and state.search_times:
                if max(state.search_times) >= min(state.index_times):
                    post_index_sessions += 1

    return Scan(
        files=files,
        unreadable=unreadable,
        # `in_scope` is the authority, but a session can show memory activity
        # from a subagent file whose head never yielded a `cwd` while the parent
        # file's did not reach the head bound either. Union, so the total can
        # never come out *below* the memory count it is the denominator for.
        sessions=len(in_scope | set(sessions)),
        memory_sessions=memory_sessions,
        search_sessions=search_sessions,
        structured_sessions=structured_sessions,
        shell_sessions=shell_sessions,
        post_index_sessions=post_index_sessions,
        structured_calls=structured_calls,
        shell_calls=shell_calls,
        unclassified_calls=unclassified_calls,
        unclassified_sessions=unclassified_sessions,
        by_tool=dict(sorted(by_tool.items())),
    )


# ── the four checks ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Result:
    """One trigger's verdict and the lines explaining it.

    `verdict` is what `main()` consults for the exit code; only `FIRED` on a
    *firing-capable* trigger can set rc 1, which is enforced by `can_fire`
    rather than by every check remembering the rule.
    """

    trigger: str
    verdict: str
    headline: str
    detail: list[str] = field(default_factory=list)
    reason: str | None = None
    can_fire: bool = True

    @property
    def fired(self) -> bool:
        return self.verdict == VERDICT_FIRED and self.can_fire


def check_directory_size(per_dir: dict[str, int], limit: int = DIR_NOTE_LIMIT) -> Result:
    """T1: does any single `memory/` directory hold `limit` notes or more?"""
    if not per_dir:
        return Result(
            TRIGGER_DIR,
            VERDICT_UNKNOWN,
            "no directory under memory/ holds any indexed note",
            reason="empty-corpus",
        )
    ranked = sorted(per_dir.items(), key=lambda kv: (-kv[1], kv[0]))
    over = [(name, n) for name, n in ranked if n >= limit]
    largest, largest_n = ranked[0]
    detail = [
        f"largest: memory/{largest} — {largest_n} notes "
        f"({largest_n * 100 // limit}% of the ~{limit} trigger)"
    ]
    detail += [f"next:    memory/{name} — {n} notes" for name, n in ranked[1:4]]
    if over:
        return Result(
            TRIGGER_DIR,
            VERDICT_FIRED,
            f"{len(over)} directory/ies at or past ~{limit} notes",
            [f"over:    memory/{name} — {n} notes" for name, n in over] + detail,
        )
    return Result(
        TRIGGER_DIR, VERDICT_CLEAR, f"no directory has reached ~{limit} notes", detail
    )


def check_corpus_size(total: int, limit: int = CORPUS_NOTE_LIMIT) -> Result:
    """T2: does the whole corpus hold `limit` notes or more?"""
    pct = total * 100 // limit if limit else 0
    detail = [f"corpus:  {total} notes ({pct}% of the ~{limit} trigger)"]
    if total >= limit:
        return Result(
            TRIGGER_CORPUS, VERDICT_FIRED, f"corpus is at or past ~{limit} notes", detail
        )
    return Result(
        TRIGGER_CORPUS, VERDICT_CLEAR, f"corpus has not reached ~{limit} notes", detail
    )


def check_unrouted(record_file: Path) -> Result:
    """T3: has a harvest ever reported it could not route a learning?

    One or more is a firing; the ADR supplies that threshold itself. An absent
    or damaged tally is `unknown`, not `clear` — see the module docstring.
    """
    record = _unrouted_record.read_record(record_file)
    if record is None:
        return Result(
            TRIGGER_UNROUTED,
            VERDICT_UNKNOWN,
            "no unrouted tally for this repo — never recorded, not zero",
            [
                "a tally appears the first time a harvest declares a nomination",
                "unrouted; its absence cannot distinguish 'everything routed'",
                "from 'no harvest has run since the instrument landed'.",
            ],
            reason="no-record",
        )
    count = record["count"]
    reasons = [
        e.get("reason", "") for e in record.get("entries", []) if isinstance(e, dict)
    ]
    detail = [f"recorded: {count} unrouted learning(s)"]
    if reasons:
        detail.append(f"retained: {len(reasons)} reason(s) in the tally's diagnostic tail")
    return Result(
        TRIGGER_UNROUTED,
        VERDICT_FIRED if count >= 1 else VERDICT_CLEAR,
        f"{count} harvest nomination(s) could not be routed",
        detail,
    )


def check_index_bypass(scan: Scan) -> Result:
    """T4: at what rate do agents search `memory/` instead of routing by index?

    Always `unknown`, and `can_fire=False`. There is no threshold because none
    has been chosen; this reports the rate and says plainly that firing needs a
    human read. See the module docstring for the definition and its defence.
    """
    if not scan.scanned:
        return Result(
            TRIGGER_BYPASS,
            VERDICT_UNKNOWN,
            "transcripts not scanned",
            [f"reason:  {scan.reason}"],
            reason=scan.reason,
            can_fire=False,
        )
    if scan.memory_sessions == 0:
        return Result(
            TRIGGER_BYPASS,
            VERDICT_UNKNOWN,
            "no session in scope touched memory/ — no rate to report",
            [
                f"scanned: {scan.files} transcript file(s), "
                f"{scan.sessions} session(s) in scope",
            ],
            reason="no-memory-sessions",
            can_fire=False,
        )

    broad = scan.search_sessions * 100 // scan.memory_sessions
    narrow = scan.post_index_sessions * 100 // scan.memory_sessions
    detail = [
        f"scanned: {scan.files} transcript file(s), "
        f"{scan.sessions} session(s) in scope, {scan.unreadable} unreadable",
        f"denom:   {scan.memory_sessions} session(s) touched memory/",
        f"broad:   {scan.search_sessions} searched memory/ "
        f"({broad}%) — any search, index consulted or not",
        f"narrow:  {scan.post_index_sessions} searched AFTER reading an index "
        f"({narrow}%) — this is the ADR's actual condition",
        f"tiers:   {scan.structured_calls} structured call(s) in "
        f"{scan.structured_sessions} session(s) (exact); "
        f"{scan.shell_calls} shell call(s) in {scan.shell_sessions} "
        f"session(s) (heuristic)",
    ]
    if scan.unclassified_calls:
        detail.append(
            f"unknown: {scan.unclassified_calls} call(s) in "
            f"{scan.unclassified_sessions} session(s) touched memory/ from tools "
            f"whose semantics are not known here — NOT counted as searches"
        )
    if scan.by_tool:
        detail.append(
            "tools:   "
            + ", ".join(f"{label} {n}" for label, n in scan.by_tool.items())
        )
    detail.append(
        "NOT CALIBRATED — no threshold has been chosen, so this trigger "
        "cannot fire. Firing is a human read of the two rates above."
    )
    return Result(
        TRIGGER_BYPASS,
        VERDICT_UNKNOWN,
        f"{narrow}% of memory-touching sessions searched past an index "
        f"({broad}% searched at all)",
        detail,
        reason="uncalibrated",
        can_fire=False,
    )


# ── reporting ──────────────────────────────────────────────────────────────


def render_report(
    memory_root: Path,
    record_file: Path,
    transcript_dir: Path | None,
    results: list[Result],
) -> list[str]:
    """Build the human report as lines. The caller prints them.

    Paths printed here are the operator's own arguments, echoed back so a run
    against the wrong brain is obvious — not transcript-derived.
    """
    lines = [
        f"memory:     {memory_root}",
        f"unrouted:   {record_file}",
        f"transcripts:{' ' + str(transcript_dir) if transcript_dir else ' (skipped)'}",
        "",
    ]
    for result in results:
        lines.append(f"{result.verdict:<7} {result.trigger} — {result.headline}")
        lines.extend(f"        {line}" for line in result.detail)
    lines.append("")
    fired = [r.trigger for r in results if r.fired]
    if fired:
        lines.append(f"FIRED: {', '.join(fired)} — ADR 0002/0005 asked to be reopened.")
    else:
        lines.append("No trigger fired. `unknown` verdicts above are not clean bills.")
    return lines


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate ADR 0002's four memory revisit triggers. Read-only: this "
            "never writes memory/, the trail directory, or anything else."
        ),
    )
    parser.add_argument(
        "--memory-root",
        default=str(DEFAULT_MEMORY_ROOT),
        help="path to a memory/ tree (default: this repo's memory/)",
    )
    parser.add_argument(
        "--transcripts",
        default=None,
        help="transcript directory (default: <config dir>/projects)",
    )
    parser.add_argument(
        "--skip-transcripts",
        action="store_true",
        help="skip the T4 scan; T4 reports unknown. Minutes faster.",
    )
    parser.add_argument(
        "--any-repo",
        action="store_true",
        help=(
            "do not scope transcripts to the repo owning --memory-root; count "
            "every session on this machine"
        ),
    )
    parser.add_argument(
        "--json", action="store_true", help="print the findings as JSON instead"
    )
    args = parser.parse_args(argv)

    # The report prints — and ⚠ glyphs and echoes operator-supplied paths that
    # may carry non-ASCII. A legacy Windows console defaults to cp1252 and would
    # raise UnicodeEncodeError while formatting a *successful* run's output;
    # this repo has shipped that bug twice (#55, #71). Guarded, because a
    # redirected StringIO in tests has no `reconfigure`.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass

    memory_root = Path(args.memory_root)
    try:
        total, per_dir = count_notes(memory_root)
    except OSError as exc:
        print(
            f"memory-triggers: could not check — {memory_root} is not readable: {exc}",
            file=sys.stderr,
        )
        return EXIT_ERROR

    # The unrouted tally and the transcript scope are both keyed on the
    # repository that owns the memory tree, not on this script's own checkout —
    # that is what lets one invocation be pointed at a real brain.
    repo_dir = memory_root.parent
    record_file = _unrouted_record.record_path(repo_dir)

    transcript_dir: Path | None = None
    scan = Scan(scanned=False, reason="skipped")
    if not args.skip_transcripts:
        transcript_dir = (
            Path(args.transcripts)
            if args.transcripts
            else rs.config_dir() / "projects"
        )
        repo_root_posix = (
            ""
            if args.any_repo
            else _trail_scope.posix_path(rs.git_roots(str(repo_dir))[1])
        )
        scan = scan_transcripts(transcript_dir, repo_root_posix)

    results = [
        check_directory_size(per_dir),
        check_corpus_size(total),
        check_unrouted(record_file),
        check_index_bypass(scan),
    ]

    if args.json:
        print(
            json.dumps(
                {
                    "memory_root": memory_root.as_posix(),
                    "unrouted_record": record_file.as_posix(),
                    "transcripts": transcript_dir.as_posix() if transcript_dir else None,
                    "corpus_notes": total,
                    "directory_notes": dict(
                        sorted(per_dir.items(), key=lambda kv: (-kv[1], kv[0]))
                    ),
                    "limits": {
                        "directory": DIR_NOTE_LIMIT,
                        "corpus": CORPUS_NOTE_LIMIT,
                    },
                    "scan": {
                        "scanned": scan.scanned,
                        "reason": scan.reason,
                        "files": scan.files,
                        "unreadable": scan.unreadable,
                        "sessions": scan.sessions,
                        "memory_sessions": scan.memory_sessions,
                        "search_sessions": scan.search_sessions,
                        "structured_sessions": scan.structured_sessions,
                        "shell_sessions": scan.shell_sessions,
                        "post_index_sessions": scan.post_index_sessions,
                        "structured_calls": scan.structured_calls,
                        "shell_calls": scan.shell_calls,
                        "unclassified_calls": scan.unclassified_calls,
                        "unclassified_sessions": scan.unclassified_sessions,
                        "by_tool": scan.by_tool,
                    },
                    "triggers": [
                        {
                            "trigger": r.trigger,
                            "verdict": r.verdict,
                            "reason": r.reason,
                            "can_fire": r.can_fire,
                            "headline": r.headline,
                            "detail": r.detail,
                        }
                        for r in results
                    ],
                    "exit": EXIT_FIRED if any(r.fired for r in results) else EXIT_PASS,
                },
                indent=2,
            )
        )
    else:
        for line in render_report(memory_root, record_file, transcript_dir, results):
            print(line)

    return EXIT_FIRED if any(r.fired for r in results) else EXIT_PASS


if __name__ == "__main__":
    raise SystemExit(main())
