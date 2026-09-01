#!/usr/bin/env python3
"""Generate the agent + skill catalog pages for docs.nescio-ai.org.

Stdlib only. The repo is stdlib-only and the docs build must stay that way, so
the frontmatter parser below is the same fence-delimited, flat-scalar parser the
knowledge-wiki engine uses (``scripts/_wiki_common.py:split_frontmatter``) --
reimplemented locally rather than imported, because ``docs_site/`` sits off
``FRAMEWORK_PATHS`` and the docs build must not need ``scripts/`` on
``PYTHONPATH``.

Two ways to run it, both supported:

1. **Standalone**, as a workflow step immediately before ``mkdocs build``::

       python docs_site/gen_catalog.py

   Exits non-zero (and writes nothing) if the catalog cannot be generated
   faithfully. ``--check`` regenerates in memory and fails on any drift from
   what is on disk, without writing.

2. **From a MkDocs hook**, by importing :func:`generate`::

       import gen_catalog
       def on_pre_build(config):
           gen_catalog.generate()

   ``generate()`` returns ``{"agents": n, "skills": m}`` and raises
   :class:`CatalogError` on any problem, which fails the build.

The pages it writes -- ``docs/agents.md`` and ``docs/skills.md`` -- are
**generated artefacts**. Do not hand-edit them; edit the frontmatter in
``agents/*.md`` / ``skills/*/SKILL.md``, or the grouping tables below.

Count-guard
-----------
After rendering, the number of item sections actually present in each page is
compared against the live directory listing (``agents/*.md`` and
``skills/*/SKILL.md``). A file that exists but never made it into the page fails
the build; a newly *added* agent or skill flows through both sides of the
comparison and is fine. There is no hardcoded 10 or 33 anywhere in this file.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

SITE_DIR = Path(__file__).resolve().parent
REPO_DIR = SITE_DIR.parent
DEFAULT_OUT_DIR = SITE_DIR / "docs"

# Used only to link each entry back at its source file. Kept as a constant so a
# rename of the canonical repo is one edit.
REPO_BLOB_BASE = "https://github.com/noctua84/nescio-ai/blob/main"


class CatalogError(RuntimeError):
    """The catalog could not be generated faithfully. Always fails the build."""


# --------------------------------------------------------------------------
# Grouping
#
# Explicit, hand-curated, and derived from reading the actual files -- an
# alphabetical dump of 43 entries is not scannable, and an invented taxonomy
# would be worse. Anything not listed here still renders, under "Other", and
# prints a warning: a new agent or skill must never silently vanish from the
# page (the count-guard would fail the build if it did).
# --------------------------------------------------------------------------

# Lifecycle order: coordinate -> discover -> plan and challenge -> build ->
# verify -> document. Documenting is last rather than folded into "Build"
# because only doc-researcher overlaps implementation (it runs as a parallel
# research track); doc-writer fires at delivery, once verification has settled
# what there actually is to describe. Putting the pair at the end keeps the
# column reading in the order a reader would meet these agents.
AGENT_GROUPS: list[tuple[str, list[str]]] = [
    ("Coordinate", ["orchestrator"]),
    ("Discover", ["scout", "explore", "librarian", "vision"]),
    ("Plan and challenge", ["planner", "validator", "advisor", "critic"]),
    ("Build", ["builder", "builder-standard", "builder-simple", "test-writer"]),
    ("Verify", ["qa-guard", "reviewer"]),
    ("Document", ["doc-researcher", "doc-writer"]),
]

SKILL_GROUPS: list[tuple[str, list[str]]] = [
    (
        "Security engineering",
        [
            "threat-model",
            "secure-design-spec",
            "secure-code-review",
            "security-architecture-review",
            "api-security-assessment",
            "zero-trust-design",
            "sdlc-security-gates",
        ],
    ),
    (
        "Risk and vulnerability management",
        [
            "risk-assessment",
            "risk-register",
            "vuln-assessment",
            "fix-security-vulnerabilities",
            "sbom",
        ],
    ),
    (
        "Detection and incident response",
        ["detection-rule", "incident-response-plan", "ir-playbook"],
    ),
    (
        "Compliance frameworks",
        [
            "compliance-gap-analysis",
            "iso27001-isms",
            "soc2-report",
            "pci-dss-assessment",
            "hipaa-assessment",
        ],
    ),
    (
        "AI and prompt engineering",
        [
            "llm-application-architecture",
            "rag-system-design",
            "agent-evaluation",
            "prompt-engineering-guide",
            "prompt-evaluation-harness",
            "prompt-testing-plan",
        ],
    ),
    (
        "Development workflow",
        [
            "code-navigation",
            "create-adr",
            "handle-pr-comments",
            "dependency-pr-ci-fix",
            "gh-milestones-projects",
            "repo-hygiene",
            "adopt-config",
        ],
    ),
]

UNGROUPED_TITLE = "Other"

GENERATED_BANNER = (
    "<!-- Generated by docs_site/gen_catalog.py from the YAML frontmatter of\n"
    "     agents/*.md and skills/*/SKILL.md. Do not edit by hand. -->"
)


# --------------------------------------------------------------------------
# Frontmatter parsing (house pattern: scripts/_wiki_common.py)
# --------------------------------------------------------------------------


def split_frontmatter(text: str) -> tuple[dict[str, object], str]:
    """Split a note into (frontmatter dict, body).

    Supports flat scalars and simple ``- `` lists, same as
    ``scripts/_wiki_common.py``. Returns ``({}, text)`` when no frontmatter
    block opens at the start or it never closes -- callers treat an empty dict
    as an error rather than skipping the file.
    """
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}, text
    block, body = text[4:end], text[end + 5:]
    fm: dict[str, object] = {}
    key: str | None = None
    for raw in block.splitlines():
        if not raw.strip():
            continue
        if raw.startswith("  - ") and key is not None:
            bucket = fm.setdefault(key, [])
            if isinstance(bucket, list):
                bucket.append(raw[4:].strip())
            continue
        if ":" in raw:
            k, _, v = raw.partition(":")
            key = k.strip()
            v = v.strip()
            fm[key] = v if v else []
    return fm, body


def _scalar(fm: dict[str, object], key: str) -> str:
    """Frontmatter value as a trimmed scalar string; '' when absent or a list."""
    value = fm.get(key)
    if isinstance(value, str):
        return _unquote(value.strip())
    return ""


def _unquote(value: str) -> str:
    """Strip one layer of matching surrounding quotes, if present."""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


# --------------------------------------------------------------------------
# Model
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Item:
    """One catalog entry, straight out of a file's frontmatter."""

    name: str
    description: str
    rel_path: str
    meta: dict[str, str] = field(default_factory=dict)


@dataclass
class Catalog:
    items: list[Item]
    warnings: list[str]


def _parse_item(path: Path, repo_dir: Path, expected_name: str) -> tuple[Item, list[str]]:
    """Parse one agent/skill file. Raises CatalogError on anything unusable."""
    rel_path = path.relative_to(repo_dir).as_posix()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:  # pragma: no cover - filesystem failure
        raise CatalogError(f"{rel_path}: cannot be read ({exc})") from exc

    fm, _ = split_frontmatter(text)
    if not fm:
        raise CatalogError(
            f"{rel_path}: no closing '---' frontmatter fence at the top of the file"
        )

    name = _scalar(fm, "name")
    description = _scalar(fm, "description")
    missing = [k for k, v in (("name", name), ("description", description)) if not v]
    if missing:
        raise CatalogError(
            f"{rel_path}: frontmatter is missing required field(s): "
            + ", ".join(missing)
        )

    warnings: list[str] = []
    if name != expected_name:
        warnings.append(
            f"{rel_path}: frontmatter name '{name}' does not match its location "
            f"(expected '{expected_name}')"
        )

    meta = {k: v for k, v in fm.items() if isinstance(v, str) and k not in {"name", "description"}}
    meta = {k: _unquote(v.strip()) for k, v in meta.items()}
    return Item(name=name, description=description, rel_path=rel_path, meta=meta), warnings


# --------------------------------------------------------------------------
# Discovery
#
# Both discovery functions walk the *live directory listing*. A directory that
# exists but has no parseable definition is an error, never a silent skip.
# --------------------------------------------------------------------------


def agent_paths(repo_dir: Path) -> list[Path]:
    """Live listing of agent definitions -- the count-guard's expectation."""
    return sorted((repo_dir / "agents").glob("*.md"))


def skill_paths(repo_dir: Path) -> list[Path]:
    """Live listing of skill definitions -- the count-guard's expectation."""
    return sorted(repo_dir.glob("skills/*/SKILL.md"))


def discover_agents(repo_dir: Path) -> Catalog:
    agents_dir = repo_dir / "agents"
    if not agents_dir.is_dir():
        raise CatalogError(f"{agents_dir} does not exist")
    items: list[Item] = []
    warnings: list[str] = []
    for path in agent_paths(repo_dir):
        item, warns = _parse_item(path, repo_dir, expected_name=path.stem)
        items.append(item)
        warnings.extend(warns)
    if not items:
        raise CatalogError(f"no agent definitions found under {agents_dir}")
    return Catalog(items, warnings)


def discover_skills(repo_dir: Path) -> Catalog:
    skills_dir = repo_dir / "skills"
    if not skills_dir.is_dir():
        raise CatalogError(f"{skills_dir} does not exist")
    items: list[Item] = []
    warnings: list[str] = []
    for directory in sorted(p for p in skills_dir.iterdir() if p.is_dir()):
        if directory.name.startswith("."):
            continue
        skill_file = directory / "SKILL.md"
        if not skill_file.is_file():
            # Deliberately fatal: a skill directory whose SKILL.md has gone
            # missing is exactly the "silently dropped file" the guard exists
            # to catch. Remove the whole directory to retire a skill.
            raise CatalogError(
                f"skills/{directory.name}/: directory exists but has no SKILL.md"
            )
        item, warns = _parse_item(skill_file, repo_dir, expected_name=directory.name)
        items.append(item)
        warnings.extend(warns)
    if not items:
        raise CatalogError(f"no skill definitions found under {skills_dir}")
    return Catalog(items, warnings)


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------

# One item section == one "### `name`" heading. Counting these in the *rendered
# text* is what makes the guard meaningful: it measures the page, not the list
# the page was built from.
ITEM_HEADING_RE = re.compile(r"^### `", re.MULTILINE)


def _group(items: list[Item], groups: list[tuple[str, list[str]]]) -> tuple[list[tuple[str, list[Item]]], list[str]]:
    """Bucket items by the curated tables; unlisted names fall to 'Other'."""
    by_name = {item.name: item for item in items}
    placed: set[str] = set()
    grouped: list[tuple[str, list[Item]]] = []
    warnings: list[str] = []

    for title, names in groups:
        bucket: list[Item] = []
        for name in names:
            item = by_name.get(name)
            if item is None:
                warnings.append(
                    f"grouping table lists '{name}' under '{title}', but no such "
                    f"definition exists -- drop it from gen_catalog.py"
                )
                continue
            if name in placed:
                warnings.append(f"'{name}' is listed in more than one group")
                continue
            placed.add(name)
            bucket.append(item)
        if bucket:
            grouped.append((title, bucket))

    leftover = [item for item in items if item.name not in placed]
    if leftover:
        warnings.append(
            "not in any grouping table, rendered under "
            f"'{UNGROUPED_TITLE}': " + ", ".join(sorted(i.name for i in leftover))
        )
        grouped.append((UNGROUPED_TITLE, sorted(leftover, key=lambda i: i.name)))
    return grouped, warnings


def _source_link(rel_path: str) -> str:
    return f"[`{rel_path}`]({REPO_BLOB_BASE}/{rel_path})"


def _at_a_glance(grouped: list[tuple[str, list[Item]]], column: str) -> list[str]:
    lines = [f"| Group | {column} |", "|---|---|"]
    for title, bucket in grouped:
        names = ", ".join(f"`{item.name}`" for item in bucket)
        lines.append(f"| {title} | {names} |")
    return lines


def _agent_meta(item: Item) -> str:
    parts: list[str] = []
    model = item.meta.get("model")
    if model:
        parts.append(f"**Model** `{model}`")
    denied = item.meta.get("disallowedTools")
    if denied:
        tools = ", ".join(f"`{t.strip()}`" for t in denied.split(",") if t.strip())
        parts.append(f"**Denied tools** {tools}")
    allowed = item.meta.get("tools")
    if allowed:
        tools = ", ".join(f"`{t.strip()}`" for t in allowed.split(",") if t.strip())
        parts.append(f"**Allowed tools** {tools}")
    parts.append(_source_link(item.rel_path))
    return " · ".join(parts)


def _skill_meta(item: Item) -> str:
    parts: list[str] = []
    invocable = item.meta.get("user-invocable", "").lower()
    if invocable and invocable not in {"true", "yes"}:
        parts.append("**Not user-invocable**")
    parts.append(_source_link(item.rel_path))
    return " · ".join(parts)


def render_agents(catalog: Catalog) -> tuple[str, list[str]]:
    grouped, warnings = _group(catalog.items, AGENT_GROUPS)
    count = len(catalog.items)
    lines = [
        GENERATED_BANNER,
        "",
        "# Agents",
        "",
        f"Nescio ships {count} agent definitions in `agents/`. Each one is a Markdown",
        "file whose YAML frontmatter declares a `name`, a `description`, the `model`",
        "it runs on, and its tool restrictions. The `description` is what Claude Code",
        "reads when it decides which agent to dispatch, so it is reproduced verbatim",
        "below.",
        "",
        "Agent names are identifiers, and are set in mono throughout.",
        "",
        "## At a glance",
        "",
    ]
    lines += _at_a_glance(grouped, "Agents")
    lines.append("")

    for title, bucket in grouped:
        lines += [f"## {title}", ""]
        for item in bucket:
            lines += [
                f"### `{item.name}`",
                "",
                item.description,
                "",
                _agent_meta(item),
                "",
            ]

    return "\n".join(lines).rstrip() + "\n", warnings


def render_skills(catalog: Catalog) -> tuple[str, list[str]]:
    grouped, warnings = _group(catalog.items, SKILL_GROUPS)
    count = len(catalog.items)
    lines = [
        GENERATED_BANNER,
        "",
        "# Skills",
        "",
        f"Nescio ships {count} skills in `skills/`. Each one is a directory holding a",
        "`SKILL.md` whose YAML frontmatter declares a `name`, a `description`, and",
        "whether the skill is `user-invocable`. Skills are loaded on demand, and the",
        "`description` is what that decision is made against, so it is reproduced",
        "verbatim below.",
        "",
        "Skill names are identifiers, and are set in mono throughout.",
        "",
        "## At a glance",
        "",
    ]
    lines += _at_a_glance(grouped, "Skills")
    lines.append("")

    for title, bucket in grouped:
        lines += [f"## {title}", ""]
        for item in bucket:
            lines += [
                f"### `{item.name}`",
                "",
                item.description,
                "",
                _skill_meta(item),
                "",
            ]

    return "\n".join(lines).rstrip() + "\n", warnings


# --------------------------------------------------------------------------
# Count-guard
# --------------------------------------------------------------------------


def check_count(kind: str, page: str, live_paths: list[Path], repo_dir: Path) -> int:
    """Assert the rendered page carries one section per live definition file.

    Compares against the *live directory listing*, never a hardcoded number, so
    adding an agent or a skill can never red the build -- but a definition that
    exists on disk and failed to reach the page always does.
    """
    rendered = len(ITEM_HEADING_RE.findall(page))
    expected = len(live_paths)
    if rendered != expected:
        listing = ", ".join(p.relative_to(repo_dir).as_posix() for p in live_paths)
        raise CatalogError(
            f"count-guard: rendered {rendered} {kind} but the live directory "
            f"listing has {expected}. Something was dropped between the "
            f"filesystem and the page. Live listing: {listing}"
        )
    return rendered


# --------------------------------------------------------------------------
# Entry points
# --------------------------------------------------------------------------


def build_pages(repo_dir: Path = REPO_DIR) -> tuple[dict[str, str], list[str]]:
    """Render both pages in memory. Returns ({filename: text}, warnings)."""
    agents = discover_agents(repo_dir)
    skills = discover_skills(repo_dir)

    agents_page, agent_warnings = render_agents(agents)
    skills_page, skill_warnings = render_skills(skills)

    check_count("agents", agents_page, agent_paths(repo_dir), repo_dir)
    check_count("skills", skills_page, skill_paths(repo_dir), repo_dir)

    warnings = agents.warnings + agent_warnings + skills.warnings + skill_warnings
    return {"agents.md": agents_page, "skills.md": skills_page}, warnings


def generate(
    repo_dir: Path | None = None,
    out_dir: Path | None = None,
    *,
    check_only: bool = False,
) -> dict[str, int]:
    """Write ``agents.md`` + ``skills.md``; return the rendered counts.

    Safe to call from a MkDocs ``on_pre_build`` hook. Raises
    :class:`CatalogError` on any problem, which fails the build.
    """
    repo_dir = Path(repo_dir) if repo_dir else REPO_DIR
    out_dir = Path(out_dir) if out_dir else DEFAULT_OUT_DIR

    pages, warnings = build_pages(repo_dir)
    for warning in warnings:
        print(f"gen_catalog: warning: {warning}", file=sys.stderr)

    if check_only:
        drift = []
        for filename, text in pages.items():
            target = out_dir / filename
            current = target.read_text(encoding="utf-8") if target.is_file() else None
            if current != text:
                drift.append(str(target))
        if drift:
            raise CatalogError(
                "--check: these pages are stale or hand-edited, rerun "
                "gen_catalog.py: " + ", ".join(drift)
            )
    else:
        out_dir.mkdir(parents=True, exist_ok=True)
        for filename, text in pages.items():
            (out_dir / filename).write_text(text, encoding="utf-8", newline="\n")

    return {
        "agents": len(ITEM_HEADING_RE.findall(pages["agents.md"])),
        "skills": len(ITEM_HEADING_RE.findall(pages["skills.md"])),
    }


def on_pre_build(config) -> None:  # noqa: ANN001 - MkDocs hook signature
    """MkDocs hook entry point, for `hooks:` in mkdocs.yml."""
    generate()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--repo-dir", type=Path, default=REPO_DIR, help="repo root (default: %(default)s)"
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help="where agents.md/skills.md are written (default: %(default)s)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="do not write; fail if the pages on disk differ from a fresh render",
    )
    args = parser.parse_args(argv)

    try:
        counts = generate(args.repo_dir, args.out_dir, check_only=args.check)
    except CatalogError as exc:
        print(f"gen_catalog: ERROR: {exc}", file=sys.stderr)
        return 1

    verb = "verified" if args.check else "wrote"
    print(f"gen_catalog: {verb} {counts['agents']} agents and {counts['skills']} skills")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
