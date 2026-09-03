# scripts/_marker_block.py
"""Whole-line, fence-aware recognition of a generated marker block.

Stdlib-only. Several scripts own one block of a hand-editable markdown file,
delimited by a pair of HTML-comment markers: `wiki_index.py` owns
`<!-- memory-index:generated … -->` and `compute_readiness.py` owns
`<!-- readiness:generated … -->`. The rules for *finding* that block are the
same in both cases and are the part that is easy to get subtly, destructively
wrong, so they live here once, parameterized by the marker pair:

    BLOCK = MarkerBlock("<!-- x:generated start -->", "<!-- x:generated end -->")
    kind, reason = BLOCK.classify(text)   # "none" / "ok" / "malformed"
    if kind == "ok":
        start, stop = BLOCK.span(text)

Two rules carry the weight. **A marker counts only as a whole line** (leading
and trailing spaces and tabs aside) that is **not inside a fenced code block**,
so a file may document the convention — quote both markers in a sentence, or
show the block in a ```-fenced example — without the generator treating the
quoted text as its own block and splicing away everything between the two
mentions. And **classification counts before it locates**: `classify` decides
`none` / `ok` / `malformed` from marker counts alone, and `span` is valid only
once `classify` has returned `ok`, so no caller can find a begin marker, miss
the absent end marker, and splice against some *other* file's end marker.

This module knows nothing about what goes inside a block, how it is rendered,
or what the owning script does with the classification — those stay with the
owner.
"""

from __future__ import annotations

import re

# An opening or closing code fence: three or more backticks or tildes, indented
# or not, plus whatever follows on the line (an info string, or — for a closing
# fence — nothing). Hand-rolled rather than parsed: ADR 0001 is stdlib-only, and
# fence state is the only markdown context these scans need.
_FENCE_RE = re.compile(r"^[ \t]*(`{3,}|~{3,})(.*)$")


def split_lines(text: str) -> list[tuple[int, int, str]]:
    """`[(start, stop, line)]`, where `stop` is past the line's terminator.

    `str.splitlines(keepends=True)` splits on `\\n`, `\\r\\n` and `\\r`, and
    keeping the ends makes the accumulated offsets exact — so a span derived
    from them is byte-faithful under every line ending, with no per-ending
    arithmetic at the call site.
    """
    out: list[tuple[int, int, str]] = []
    pos = 0
    for line in text.splitlines(keepends=True):
        out.append((pos, pos + len(line), line))
        pos += len(line)
    return out


def fenced_line_indices(lines: list[tuple[int, int, str]]) -> set[int]:
    """Indices of the lines inside a **closed** fenced code block, fences included.

    An unclosed fence is deliberately *not* treated as opening a region.
    CommonMark runs it to the end of the document; doing that here would hide a
    real trailing block from `MarkerBlock.classify` on every run, so the file
    would classify `none`, take the append path, and grow a fresh block every
    time — the duplicate-forever bug D7 exists to prevent. Between "an
    unterminated fence hides the block forever" and "an unterminated fence is
    not a fence", only the second is non-destructive.
    """
    fenced: set[int] = set()
    open_at: int | None = None
    open_char = ""
    open_run = 0
    for i, (_, _, raw) in enumerate(lines):
        m = _FENCE_RE.match(raw.rstrip("\r\n"))
        if not m:
            continue
        char, run, rest = m.group(1)[0], len(m.group(1)), m.group(2)
        if open_at is None:
            open_at, open_char, open_run = i, char, run
        elif char == open_char and run >= open_run and not rest.strip():
            fenced.update(range(open_at, i + 1))
            open_at = None
    return fenced


class MarkerBlock:
    """One marker pair, and the scans that locate the block it delimits.

    Immutable and cheap to construct, but the marker-line regex is compiled
    once here, so owning modules build a single module-level instance rather
    than one per call.
    """

    def __init__(self, begin: str, end: str) -> None:
        self.begin = begin
        self.end = end
        # A marker counts only as a **whole line** — spaces and tabs around it,
        # nothing else on it. Built from the two constants above so the pattern
        # and the markers can never drift apart.
        #
        # The first version of this fix scanned for the markers as bare
        # substrings anywhere in the file. A curated `MEMORY.md` that merely
        # *mentions* both markers in one sentence — the shape
        # `memory/CONVENTIONS.md` teaches downstream users to write — then
        # classified `ok`, and the words between the two mentions were spliced
        # away silently, at rc 0, with no ⚠. That is issue #102's own failure
        # class re-entering through its fix, so recognition is anchored.
        self._marker_line_re = re.compile(
            r"^[ \t]*(?:(?P<start>{})|(?P<end>{}))[ \t]*$".format(
                re.escape(begin), re.escape(end)
            )
        )

    def marker_lines(self, text: str) -> list[tuple[str, int, int]]:
        """`[(kind, start, stop)]` for every marker line, in document order.

        `kind` is `start` or `end`; `start`/`stop` bound the whole line
        **including its terminator**. Lines inside a fenced code block are
        skipped, so a fenced example documenting the block shape is not mistaken
        for the block itself. HTML comments are deliberately *not* skipped — the
        markers are HTML comments, so skipping those would blind this scan to
        its own subject.
        """
        lines = split_lines(text)
        fenced = fenced_line_indices(lines)
        out: list[tuple[str, int, int]] = []
        for i, (start, stop, raw) in enumerate(lines):
            if i in fenced:
                continue
            m = self._marker_line_re.match(raw.rstrip("\r\n"))
            if m:
                out.append(("start" if m.group("start") else "end", start, stop))
        return out

    def classify(self, text: str) -> tuple[str, str]:
        """Classify a file's markers as `none` / `ok` / `malformed` (D7).

        Counts first, and only compares positions once the counts prove there is
        exactly one of each. Both generators previously tested marker *presence*
        and spliced with `.index()`, so a begin marker with no end fell to the
        append branch and the *next* run spliced from the orphan through the
        appended block, destroying everything between (#102 in
        `wiki_index.regenerate`, #121 in `compute_readiness.compose`). Refusing
        is the deliberate improvement: with a begin and no end the block's
        extent is unknowable — appending duplicates, truncating at EOF may
        delete prose — so a human resolves it.

        Counting and position-finding both go through `marker_lines`, so the two
        can never disagree about what is a marker — a disagreement would mean
        classifying `ok` on one span and splicing another.

        Returns (kind, reason); `reason` is "" unless the kind is `malformed`.
        """
        markers = self.marker_lines(text)
        begins = [m for m in markers if m[0] == "start"]
        ends = [m for m in markers if m[0] == "end"]
        if not begins and not ends:
            return "none", ""
        if len(begins) > 1:
            return "malformed", f"{len(begins)} begin markers"
        if len(ends) > 1:
            return "malformed", f"{len(ends)} end markers"
        if not ends:
            return "malformed", "begin marker without an end marker"
        if not begins:
            return "malformed", "end marker without a begin marker"
        if ends[0][1] < begins[0][1]:
            return "malformed", "end marker before begin marker"
        return "ok", ""

    def span(self, text: str) -> tuple[int, int]:
        """(start, stop) of the owned block, including its own trailing newline.

        Only valid once `classify` has returned `ok`. The bounds are whole
        marker *lines*, so the end marker's terminator — `\\n`, `\\r\\n` or a
        lone `\\r` — is consumed by construction rather than by per-ending
        arithmetic.
        """
        markers = self.marker_lines(text)
        start = next(m for m in markers if m[0] == "start")[1]
        stop = next(m for m in markers if m[0] == "end")[2]
        return start, stop

    def outside(self, text: str) -> str:
        """Everything in `text` that is not the owned block — the preserved content.

        Only valid once `classify` has returned `ok`.
        """
        start, stop = self.span(text)
        return text[:start] + text[stop:]
