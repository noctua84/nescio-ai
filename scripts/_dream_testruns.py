"""What a subagent does after a failing test run, from its own transcript.

Why this exists: a subagent's test runs never reach the parent transcript, and
``is_error`` cannot be trusted to find the failures. Measured on two weeks of
real subagent transcripts, 279 test runs failed and 236 of them exited 0,
because the command was piped (``... | tail -3``) and the pipeline's status is
the last stage's. So the outcome comes from the runner's own summary line
first (``OK``, ``FAILED (...)``, ``N passed``, ``N failed``) and ``is_error``
is only the fallback. A failing outcome seen without ``is_error`` is counted as
``masked``.

Each failing run is then paired with the *next* test run whose outcome is
known, whatever its command: identical-command reruns are about 1% of runs, so
pairing by command would see almost nothing. The pair is classed by whether an
edit tool call (or an editing shell command) happened in between:

  * ``fixed_after_edit`` / ``passed_no_edit_seen`` -- the next run passed;
  * ``refailed_after_edit`` / ``retried_no_edit`` -- the next run failed too;
  * ``not_rerun`` -- no later run with a known outcome.

"No edit seen" is a statement about the transcript, not about the tree: an edit
made by a command this module does not recognise looks the same. Test commands
are never themselves classed as edits, so a redirect in ``pytest > log`` does
not turn a rerun into a "fix".

A user-rejected run never ran; it counts as a run but has no outcome. The
tracker keeps counts only: no command text and no test output survive.

Stdlib only; fed by the single streaming pass in ``_dream_inputs.parse_subagent``.
"""

from __future__ import annotations

import re
from collections import Counter

from _dream_parse import REJECTION_RE

TEST_CMD_RE = re.compile(
    r"\b(unittest|pytest|npm (run )?test|yarn test|go test|cargo test|jest|vitest|mvn test|gradle test|dotnet test)\b"
)
TAIL_CHARS = 3000
AFTER_FAIL_KEYS = ("fixed_after_edit", "passed_no_edit_seen", "refailed_after_edit", "retried_no_edit", "not_rerun")
EDIT_TOOLS = frozenset({"Edit", "Write", "MultiEdit", "NotebookEdit"})
SHELL_TOOLS = frozenset({"Bash", "PowerShell"})

_FAIL_RES = (
    re.compile(r"^FAILED \(", re.MULTILINE),
    re.compile(r"^ERRORS?!", re.MULTILINE),
    re.compile(r"\b\d+ failed\b"),
    re.compile(r"\b\d+ errors? in\b"),
)
_PASS_RES = (re.compile(r"^OK\b", re.MULTILINE), re.compile(r"\b\d+ passed\b"))
# A redirect to a file: not ``2>&1`` / ``>&2``, not ``> /dev/null``, not an arrow (``->``) or comparison (``>=``).
_EDIT_SHELL_RE = re.compile(
    r"\bsed\s+(?:-\S+\s+)*-(?:\w*i|-in-place)"
    r"|(?<![-=>])>>?(?![&=])(?!\s*/dev/null)"
    r"|\btee\s|\bSet-Content\b|\bOut-File\b|\bAdd-Content\b"
)


def outcome(text: str, is_error: bool) -> bool | None:
    """``True`` = the run passed, ``False`` = it failed, ``None`` = unknown.

    The runner's summary in the last ~3000 chars wins; ``is_error`` only decides
    when there is no summary, and a clean exit with no summary is unknown.
    """
    tail = text[-TAIL_CHARS:] if isinstance(text, str) else ""
    if any(r.search(tail) for r in _FAIL_RES):
        return False
    if any(r.search(tail) for r in _PASS_RES):
        return True
    return False if is_error else None


def is_edit(tool_name, tool_input) -> bool:
    """Whether a tool call changes files: an edit tool, or a shell command that writes."""
    if tool_name in EDIT_TOOLS:
        return True
    if tool_name in SHELL_TOOLS and isinstance(tool_input, dict):
        command = tool_input.get("command")
        return isinstance(command, str) and bool(_EDIT_SHELL_RE.search(command))
    return False


def empty_counts() -> dict:
    return {"runs": 0, "known": 0, "failed": 0, "masked": 0, "after_fail": Counter()}


def add_counts(into: dict, summary: dict) -> None:
    """Add one ``TestTracker.summary()`` (or an earlier roll-up) into ``into``, in place."""
    for key in ("runs", "known", "failed", "masked"):
        into[key] += summary.get(key, 0)
    into["after_fail"].update(summary.get("after_fail", ()))


class TestTracker:
    """Counts test runs and classifies what followed each failure; feed it in transcript order."""

    __test__ = False  # not a unittest/pytest case despite the name

    def __init__(self) -> None:
        self.pending: set = set()  # ids of test commands whose result has not arrived
        self.runs = self.known = self.failed = self.masked = 0
        self.after_fail: Counter = Counter()
        self.last_ok: bool | None = None
        self._failed_open = False  # a failure is waiting for the next known run
        self._edit_since = False  # an edit happened since that failure

    def on_tool_use(self, tool_id, name, tool_input) -> None:
        """Call once per tool_use id."""
        command = tool_input.get("command") if isinstance(tool_input, dict) else None
        if name in SHELL_TOOLS and isinstance(command, str) and TEST_CMD_RE.search(command):
            self.runs += 1
            self.pending.add(tool_id)
        elif is_edit(name, tool_input):
            self._edit_since = True

    def tracks(self, tool_use_id) -> bool:
        return tool_use_id in self.pending

    def on_tool_result(self, tool_use_id, text: str, is_error: bool) -> None:
        if tool_use_id not in self.pending:
            return
        self.pending.discard(tool_use_id)
        if is_error and REJECTION_RE.match(text or ""):
            return  # never ran
        ok = outcome(text, is_error)
        if ok is None:
            return
        self.known += 1
        self.last_ok = ok
        if self._failed_open:
            if ok:
                self.after_fail["fixed_after_edit" if self._edit_since else "passed_no_edit_seen"] += 1
            else:
                self.after_fail["refailed_after_edit" if self._edit_since else "retried_no_edit"] += 1
        if ok:
            self._failed_open = False
        else:
            self.failed += 1
            if not is_error:
                self.masked += 1
            self._failed_open = True
        self._edit_since = False

    def summary(self) -> dict:
        after = Counter(self.after_fail)
        if self._failed_open:
            after["not_rerun"] += 1
        return {
            "runs": self.runs, "known": self.known, "failed": self.failed, "masked": self.masked,
            "after_fail": after, "last_ok": self.last_ok,
        }
