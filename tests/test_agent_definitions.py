"""Validate the crew's agent definitions.

Agent behaviour is prose and cannot be unit-tested. What *can* be pinned
mechanically is the frontmatter contract and the orchestrator's dispatch
wiring — which is precisely what drifts silently when these files are
edited by hand.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
AGENTS_DIR = REPO_ROOT / "agents"

# Models the crew is allowed to name. Anything else is a typo or an
# unreviewed bump.
ALLOWED_MODELS = {
    "claude-opus-5",
    "claude-opus-4-8",
    "claude-sonnet-5",
    "claude-haiku-4-5",
}

EXPECTED_ROSTER = {
    "advisor",
    "builder",
    "critic",
    "explore",
    "librarian",
    "orchestrator",
    "planner",
    "reviewer",
    "scout",
    "validator",
    "vision",
}

FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _agent_files() -> list[Path]:
    return sorted(AGENTS_DIR.glob("*.md"))


def _frontmatter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    match = FRONTMATTER_RE.match(text)
    assert match, f"{path.name}: missing YAML frontmatter block"
    fields: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" in line and not line.startswith((" ", "\t", "#")):
            key, _, value = line.partition(":")
            fields[key.strip()] = value.strip()
    return fields


def test_roster_matches_expected() -> None:
    found = {path.stem for path in _agent_files()}
    assert found == EXPECTED_ROSTER


@pytest.mark.parametrize("path", _agent_files(), ids=lambda p: p.stem)
def test_name_matches_filename(path: Path) -> None:
    assert _frontmatter(path).get("name") == path.stem


@pytest.mark.parametrize("path", _agent_files(), ids=lambda p: p.stem)
def test_model_is_allowed(path: Path) -> None:
    model = _frontmatter(path).get("model")
    assert model in ALLOWED_MODELS, f"{path.name}: unexpected model {model!r}"


@pytest.mark.parametrize("path", _agent_files(), ids=lambda p: p.stem)
def test_description_is_substantive(path: Path) -> None:
    description = _frontmatter(path).get("description", "")
    assert len(description) >= 40, f"{path.name}: description too thin to route on"


def test_builder_is_the_only_editor() -> None:
    """builder is the only agent permitted to edit production code.

    Note this is about Edit, not Write. orchestrator, planner and reviewer
    deliberately retain Write so they can produce plans and audit reports —
    but none of them may Edit. vision restricts itself with a read-only
    ``tools`` allowlist instead of ``disallowedTools``.
    """
    for path in _agent_files():
        fields = _frontmatter(path)
        disallowed = fields.get("disallowedTools", "")
        tools = fields.get("tools", "")
        if path.stem == "builder":
            assert "Edit" not in disallowed, "builder must retain Edit access"
            assert "Write" not in disallowed, "builder must retain Write access"
        else:
            read_only_allowlist = bool(tools) and "Edit" not in tools and "Write" not in tools
            assert "Edit" in disallowed or read_only_allowlist, (
                f"{path.stem}: must not be able to Edit production code"
            )
