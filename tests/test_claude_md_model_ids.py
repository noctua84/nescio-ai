# tests/test_claude_md_model_ids.py
"""Guard the model ids a root CLAUDE.md names against the models the crew runs.

An instance's root `CLAUDE.md` is instance-owned (it is not a synced framework
path) and may name Claude model ids in prose -- e.g. a rule "pass
`claude-sonnet-5-5` as `model:` to start_session". Nothing re-reads that prose
when the crew bumps its models, so it goes stale silently: the rule keeps
telling people to pass an id the crew no longer runs. The agents in `agents/`
are always on current models, so the invariant is:

    every model id named in CLAUDE.md is a model some agent's frontmatter
    declares (a trailing `[1m]` context-window suffix is ignored).

This repo's own CLAUDE.md names no ids, so the check passes vacuously here; it
exists for the instances this tree is synced into. When CLAUDE.md is absent
(a bare framework checkout, or an instance without one) the check is skipped.

What counts as an id: `claude-(opus|sonnet|haiku|fable)-<N>` with an optional
`-<M>` minor (`claude-opus-5`, `claude-opus-4-8`, `claude-haiku-5-5`). A
trailing date suffix of the API form (`claude-haiku-4-5-20251001`) is consumed
but not part of the id, so that example is checked as `claude-haiku-4-5` and
the date is never mistaken for a minor version.

Escape hatch for historical ids (incident notes and the like): an id is exempt
when it is written directly after the marker `superseded:` (case-insensitive),
with optional spaces or tabs and an optional opening backtick between them:

    superseded: claude-sonnet-4-5
    superseded: `claude-sonnet-4-5`

Instances must use exactly this form for an id that is deliberately old. The
exemption is per id, not per line: a per-line exemption would also hide a
current id sharing that line, which is precisely the id that goes stale after
the next bump.
"""

import re
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "scripts"))
from test_agent_definitions import (  # noqa: E402
    AGENTS_DIR,
    ROOT,
    CONTEXT_WINDOW_SUFFIX,
    TestFrontmatterMixin,
    _agent_files,
    _base_model,
)

# A Claude model id as written in prose. The leading lookbehind stops a match in
# the middle of a longer token (`my-claude-opus-5`, `xclaude-opus-5`). The
# optional `-\d{8}` date suffix sits outside the named group so it is consumed
# but never captured; the minor is limited to one or two digits so an eight-digit
# date cannot be read as one. `(?!-?\w)` lets `[1m]`, backticks and punctuation
# follow an id while rejecting a longer word (`claude-opus-5x`). It also rejects
# a hyphen-joined continuation: with a plain `(?!\w)` the regex would backtrack
# off the minor of `claude-opus-4-1x` and report the truncated `claude-opus-4`.
MODEL_ID_RE = re.compile(
    r"(?<![\w-])"
    r"(?P<id>claude-(?:opus|sonnet|haiku|fable)-\d+(?:-\d{1,2})?)"
    r"(?:-\d{8})?"
    r"(?!-?\w)",
    re.IGNORECASE,
)

# An id written directly after this marker is exempt from the check.
SUPERSEDED_MARKER = "superseded:"

# The marker, optional spaces/tabs, an optional opening backtick -- anchored to
# the end of the text before an id, so only an id immediately after it is exempt.
_SUPERSEDED_BEFORE_RE = re.compile(
    re.escape(SUPERSEDED_MARKER) + r"[ \t]*`?\Z", re.IGNORECASE
)
# Enough lookbehind to hold the marker plus its padding without rescanning the
# whole file for every id.
_SUPERSEDED_LOOKBEHIND = 64


class _FrontmatterReader(TestFrontmatterMixin):
    """Lets the shared `_frontmatter` parser run outside a TestCase."""

    def assertTrue(self, condition, message=None):  # noqa: N802
        if not condition:
            raise AssertionError(message)


def in_use_models(agents_dir=AGENTS_DIR) -> set:
    """The base model of every agent's frontmatter `model` (suffix stripped)."""
    reader = _FrontmatterReader()
    models = set()
    for path in _agent_files(agents_dir):
        model = _base_model(reader._frontmatter(path).get("model"))
        if isinstance(model, str) and model:
            models.add(model)
    return models


def stale_model_ids(text: str, in_use) -> list:
    """(1-based line, id) for each non-exempt model id in `text` not in `in_use`."""
    stale = []
    for match in MODEL_ID_RE.finditer(text):
        model_id = match.group("id").lower()
        if model_id in in_use:
            continue
        before = text[max(0, match.start() - _SUPERSEDED_LOOKBEHIND) : match.start()]
        if _SUPERSEDED_BEFORE_RE.search(before):
            continue
        stale.append((text.count("\n", 0, match.start()) + 1, model_id))
    return stale


def check_claude_md(path, agents_dir=AGENTS_DIR) -> list:
    """Stale ids in the CLAUDE.md at `path`; skips the test when it is absent."""
    path = Path(path)
    if not path.is_file():
        raise unittest.SkipTest(
            f"{path.name} not found: a root CLAUDE.md is instance-owned, "
            "so a framework checkout without one has nothing to check"
        )
    return stale_model_ids(path.read_text(encoding="utf-8"), in_use_models(agents_dir))


class TestClaudeMdModelIds(unittest.TestCase):
    def _check_text(self, text):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "CLAUDE.md"
            path.write_text(text, encoding="utf-8")
            return check_claude_md(path)

    def test_agents_declare_models(self):
        # Guards against every check below passing vacuously because no agent
        # frontmatter was parsed.
        self.assertTrue(in_use_models(), "no agent declares a model")

    def test_root_claude_md_names_only_models_the_crew_runs(self):
        stale = check_claude_md(ROOT / "CLAUDE.md")
        listing = "\n".join(f"  line {line}: {model_id}" for line, model_id in stale)
        self.assertEqual(
            [],
            stale,
            "CLAUDE.md names model ids no agent declares:\n"
            f"{listing}\n"
            f"Update each to a model an agent uses ({sorted(in_use_models())}), or, "
            f"if it is a deliberate historical reference, write it as "
            f"`{SUPERSEDED_MARKER} <id>`.",
        )

    def test_superseded_id_is_reported_with_its_line(self):
        stale = self._check_text("# Rules\n\nUse the default.\nPass claude-sonnet-4-5 here.\n")
        self.assertEqual([(4, "claude-sonnet-4-5")], stale)

    def test_in_use_ids_pass(self):
        ids = sorted(in_use_models())
        text = "\n".join(f"Pass `{i}` as model." for i in ids)
        text += f"\nOr the long window: {ids[0]}{CONTEXT_WINDOW_SUFFIX}.\n"
        self.assertEqual([], self._check_text(text))

    def test_suffix_variant_reports_base_id(self):
        stale = self._check_text("Pass claude-sonnet-4-5[1m] here.\n")
        self.assertEqual([(1, "claude-sonnet-4-5")], stale)

    def test_missing_file_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(unittest.SkipTest) as ctx:
                check_claude_md(Path(tmp) / "CLAUDE.md")
        self.assertIn("instance-owned", str(ctx.exception))

    def test_superseded_marker_exempts_the_id(self):
        for text in (
            "superseded: `claude-sonnet-4-5` was retired.\n",
            "superseded: claude-sonnet-4-5 was retired.\n",
            "Superseded:claude-sonnet-4-5 was retired.\n",
            "SUPERSEDED:\t`claude-sonnet-4-5`\n",
        ):
            with self.subTest(text=text):
                self.assertEqual([], self._check_text(text))

    def test_exemption_is_per_id_not_per_line(self):
        text = "superseded: `claude-sonnet-4-5` replaced claude-opus-4-1 here.\n"
        self.assertEqual([(1, "claude-opus-4-1")], self._check_text(text))

    def test_marker_does_not_exempt_a_distant_id(self):
        text = "superseded: nothing at all; pass claude-sonnet-4-5 now.\n"
        self.assertEqual([(1, "claude-sonnet-4-5")], self._check_text(text))

    def test_date_suffixed_stale_id_is_reported_without_the_date(self):
        stale = self._check_text("Pin claude-haiku-4-5-20251001 for cost.\n")
        self.assertEqual([(1, "claude-haiku-4-5")], stale)

    def test_date_suffixed_in_use_id_passes(self):
        model = sorted(in_use_models())[0]
        self.assertEqual([], self._check_text(f"Pin {model}-20251001 for cost.\n"))

    def test_date_is_not_read_as_a_minor_version(self):
        self.assertEqual(
            ["claude-haiku-4"],
            [i for _, i in stale_model_ids("claude-haiku-4-20251001", set())],
        )

    def test_embedded_or_longer_tokens_are_not_ids(self):
        text = "my-claude-opus-4-1 xclaude-opus-4-1 claude-opus-4-1x\n"
        self.assertEqual([], self._check_text(text))

    def test_realistic_instance_line(self):
        text = (
            "Pass `claude-sonnet-5-5` or `claude-haiku-5-5` as `model:`; never guess "
            "(superseded: `claude-sonnet-4-5` started two side sessions on an old "
            "generation).\n"
        )
        self.assertEqual([], self._check_text(text))


if __name__ == "__main__":
    unittest.main()
