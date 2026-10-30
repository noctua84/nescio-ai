#!/usr/bin/env python3
"""Generate the agent/skill/commands/lifecycle catalog pages for docs.nescio-ai.org.

Stdlib only. The repo is stdlib-only and the docs build must stay that way, so
the frontmatter parser below is the same fence-delimited, flat-scalar parser the
knowledge-wiki engine uses (``scripts/_wiki_common.py:split_frontmatter``) --
reimplemented locally rather than imported, because ``docs_site/`` sits off
``FRAMEWORK_PATHS`` and the docs build must not need ``scripts/`` on
``PYTHONPATH``. (The frontmatter parser itself now lives in
``catalog_core.py``, imported below -- this module still does not import
anything from ``scripts/``. ``gen_theme.py``, imported below for the theme
fragment appended to ``agents.md``, is the one deliberate exception -- see its
own docstring.)

Two ways to run it, both supported:

1. **Standalone**, as a workflow step immediately before ``mkdocs build``::

       python docs_site/gen_catalog.py

   This is what ``.github/workflows/docs.yml`` runs, so the published site is a
   fresh render whatever state the committed pages are in. Exits non-zero (and
   writes nothing) if the catalog cannot be generated faithfully. ``--check``
   regenerates in memory and fails on any drift from what is on disk, without
   writing.

2. **From a MkDocs hook**. This file is registered directly in the ``hooks:``
   list of ``docs_site/mkdocs.yml``; its :func:`on_pre_build` calls
   ``generate(check_only=True)``, so a build **verifies** the committed pages
   and refuses on drift rather than rewriting them. See that function for why
   the hook must not write.

   ``generate()`` returns ``{"agents": n, "skills": m}`` and raises
   :class:`CatalogError` on any problem, which fails the build. (It does not
   also report a ``"commands"`` count: see the comment on its return
   statement for why that count is kept out of the dict this function hands
   back, rather than added to it.)

The pages it writes -- ``docs/agents.md``, ``docs/skills.md``,
``docs/commands.md`` and ``docs/lifecycle.md`` -- are **generated
artefacts**. Do not hand-edit them; edit the frontmatter in ``agents/*.md`` /
``skills/*/SKILL.md`` / ``commands/*.md``, the grouping tables below, or (for
the lifecycle page) ``agents/orchestrator.md`` itself.

What raises, and what does not
------------------------------
Anything that would make the page *lie* raises :class:`CatalogError`: an
unparseable definition, a missing required frontmatter field, a skill directory
with no ``SKILL.md``, a count-guard mismatch. **Grouping never raises.** An
agent or skill that no table routes is rendered under ``UNGROUPED_TITLE`` with a
warning, and a routed name with nothing on disk warns too. The rationale is
recorded in full above ``AGENT_GROUPS`` -- read it before making either fatal.

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
import sys
from pathlib import Path

# Shared primitives (path constants, CatalogError, frontmatter parsing, the
# Item/Catalog model, the source-link helper, ITEM_HEADING_RE and
# check_count) now live in catalog_core.py, one module lower, to break a
# would-be import cycle with the new gen_commands/gen_theme/gen_lifecycle
# renderers and to bring this file back under the 400-line module tripwire.
# Re-exported here so test_gen_catalog.py, test_site_content.py and brand/
# keep importing them from gen_catalog unchanged.
#
# MUST stay a top-level import: verified against mkdocs 1.6.1
# (mkdocs.config.config_options.Hooks._load_hook), the hook loader puts this
# file's directory on sys.path only *around* module exec and restores it
# afterward. A function-level `import catalog_core` would work when this file
# is run as a CLI (its directory is already on sys.path via the usual script
# rules) but fail when MkDocs loads it as a `hooks:` entry and calls
# on_pre_build after that window has closed.
from catalog_core import (  # noqa: F401 - re-exported for callers
    CatalogError,
    Catalog,
    DEFAULT_OUT_DIR,
    GENERATED_BANNER,
    ITEM_HEADING_RE,
    Item,
    REPO_BLOB_BASE,
    REPO_DIR,
    SITE_DIR,
    _parse_item,
    _scalar,
    _source_link,
    _unquote,
    check_count,
    generated_banner,
    split_frontmatter,
)

# Same top-level-import rule as the catalog_core import above, and for the same
# reason (mkdocs.config.config_options.Hooks._load_hook, mkdocs 1.6.1): this
# file is itself the registered hook, so by the time on_pre_build runs, a
# function-level import here would already be too late. gen_commands and
# gen_lifecycle are both stdlib-only, same as this module; gen_theme is the
# one exception that reaches into scripts/_crew_common (see its docstring for
# why that is deliberate and safe).
import gen_commands
import gen_lifecycle
import gen_theme

# --------------------------------------------------------------------------
# Grouping
#
# Explicit, hand-curated, and derived from reading the actual files -- an
# alphabetical dump of 50 entries is not scannable, and an invented taxonomy
# would be worse.
#
# Both tables are *routing tables*, and both are LENIENT: an entry with no
# definition on disk warns, and a definition no table routes warns and renders
# under UNGROUPED_TITLE ("Other"). Nothing here raises over grouping.
#
# THAT LENIENCE IS DELIBERATE, AND IT IS NOT THE OLD BUG. Do not "fix" it back
# to a build failure. An earlier revision made the agent side fatal in both
# directions; the effect was that adding an agent obliged the contributor to
# make an editorial judgement (pick a bucket) and commit a regenerated artefact,
# or be refused -- on a docs site that is presentation, not part of running the
# framework. A new agent nobody routed now appears under "Other" on a site that
# still deploys, which is strictly better than the failure that argument was
# aimed at: under the original defect (PR #90) six agents were routed nowhere
# and the page silently OMITTED them. Lenient-plus-visible was never what broke;
# what broke was a tracked artifact nobody regenerated. That is fixed elsewhere
# -- .github/workflows/docs.yml regenerates before `mkdocs build`, so the
# published page cannot go stale regardless of the committed copy.
#
# The strict promise still exists, it just is not enforced here. `AGENT_GROUPS`
# equals `agents/*.md` as a set, asserted by
# docs_site/test_gen_catalog.py::TestAgainstTheRealRepo, which runs in the
# non-required `docs-tests` CI job: maintainers see the drift, contributors are
# not gated by it.
# --------------------------------------------------------------------------

# Lifecycle order: coordinate -> discover -> plan and challenge -> build ->
# verify -> document. Documenting is last rather than folded into "Build"
# because only doc-researcher overlaps implementation (it runs as a parallel
# research track); doc-writer fires at delivery, once verification has settled
# what there actually is to describe. Putting the pair at the end keeps the
# column reading in the order a reader would meet these agents.
#
# `test-writer` sits in "Build", not "Verify": it authors the tests rather than
# auditing what was built. `qa-guard` is the one that audits, and it is a
# CODE_WRITER in scripts/_crew_common.py, so it stays in "Verify" beside
# `reviewer`.
#
# Every agent in agents/ should appear here exactly once. Nothing in this file
# enforces that -- see the leniency note above; the set equality is asserted by
# docs_site/test_gen_catalog.py instead.
AGENT_GROUPS: list[tuple[str, list[str]]] = [
    ("Coordinate", ["orchestrator"]),
    ("Discover", ["scout", "explore", "librarian", "vision"]),
    # `critic` before `advisor` is deliberate, and this order was reconciled TO
    # the crew diagram rather than the other way round. Two reasons, neither
    # visible from this list alone:
    #
    #   * `validator` and `critic` are the two challenge roles, and the diagram
    #     accents both. Drawn in this order their cards are adjacent; with
    #     `advisor` between them a plain card splits the pair, and the diagram's
    #     "Why three are highlighted" note -- which exists to explain exactly
    #     that grouping -- has to reach around it.
    #   * It is the real dispatch order. planner -> validator -> critic is the
    #     PLAN phase in sequence; `advisor` is consulted during ANALYZE, outside
    #     it, so it trails the three rather than interrupting them.
    #
    # Left alphabetical-looking on purpose is NOT what happened here: swapping
    # these two back to read `advisor, critic` reds
    # docs_site/test_site_content.py::CrewRosterTest, which compares this table
    # against brand/make_diagrams.CREW_GROUPS in order.
    ("Plan and challenge", ["planner", "validator", "critic", "advisor"]),
    ("Build", ["builder", "builder-standard", "builder-simple", "test-writer"]),
    ("Verify", ["qa-guard", "reviewer"]),
    # `doc-writer`'s charter says it does not write code, so Build was the only
    # fit among the original five buckets and a poor one. Its own bucket keeps
    # the research -> write pair adjacent.
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
            "publish-adrs",
            "modular-design",
            "layered-api-design",
            "handle-pr-comments",
            "dependency-pr-ci-fix",
            "gh-milestones-projects",
            "repo-hygiene",
            "adopt-config",
        ],
    ),
]

UNGROUPED_TITLE = "Other"


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


def _group(
    items: list[Item],
    groups: list[tuple[str, list[str]]],
) -> tuple[list[tuple[str, list[Item]]], list[str]]:
    """Bucket items by the curated tables. Never raises over grouping.

    A name in the table with no definition on disk warns; a definition no table
    routes warns and renders under ``UNGROUPED_TITLE``. Both tables get the same
    treatment -- there is no strict mode, deliberately. See the leniency note
    above ``AGENT_GROUPS``: a rendered page carrying an unrouted entry under
    'Other' is the outcome worth having, because the alternative on offer was
    refusing to render the page at all.
    """
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


def _at_a_glance(grouped: list[tuple[str, list[Item]]], column: str) -> list[str]:
    lines = [f"| Group | {column} |", "|---|---|"]
    for title, bucket in grouped:
        names = ", ".join(f"`{item.name}`" for item in bucket)
        lines.append(f"| {title} | {names} |")
    return lines


def _split_tool_list(value: str) -> list[str]:
    """Split a `tools:`/`disallowedTools:` frontmatter value on top-level commas.

    A plain `value.split(",")` breaks a parenthesised entry like
    `Agent(explore, librarian)` into two fragments, because the comma inside
    the parentheses is not a separator between tools — it is part of one
    tool's own argument list. This tracks parenthesis depth and only treats a
    comma as a separator at depth zero, so `Agent(explore, librarian)` stays
    one token while `Read, Write` still splits into two. Each token is
    stripped, and empty tokens (a trailing comma, stray whitespace) are
    dropped.
    """
    tokens: list[str] = []
    current: list[str] = []
    depth = 0
    for char in value:
        if char == "(":
            depth += 1
            current.append(char)
        elif char == ")":
            depth = max(0, depth - 1)
            current.append(char)
        elif char == "," and depth == 0:
            tokens.append("".join(current))
            current = []
        else:
            current.append(char)
    tokens.append("".join(current))
    return [t.strip() for t in tokens if t.strip()]


def _agent_meta(item: Item) -> str:
    parts: list[str] = []
    model = item.meta.get("model")
    if model:
        parts.append(f"**Model** `{model}`")
    denied = item.meta.get("disallowedTools")
    if denied:
        tools = ", ".join(f"`{t}`" for t in _split_tool_list(denied))
        parts.append(f"**Denied tools** {tools}")
    allowed = item.meta.get("tools")
    if allowed:
        tools = ", ".join(f"`{t}`" for t in _split_tool_list(allowed))
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
# Entry points
# --------------------------------------------------------------------------


def build_pages(repo_dir: Path = REPO_DIR) -> tuple[dict[str, str], list[str]]:
    """Render all four pages in memory. Returns ({filename: text}, warnings).

    Every page honours ``repo_dir`` -- that parameter exists so
    ``test_gen_catalog.py`` can point this function at a small synthetic
    fixture tree instead of the real repo, and the real CLI and the MkDocs
    hook run it against ``REPO_DIR`` by default.
    """
    agents = discover_agents(repo_dir)
    skills = discover_skills(repo_dir)
    commands = gen_commands.discover_commands(repo_dir)

    agents_page, agent_warnings = render_agents(agents)
    # The theme fragment is appended AFTER the detail sections (and after the
    # count-guard below runs against it) so it cannot shift "## At a glance"
    # later than any "### `name`" heading, and it introduces none of its own
    # (see gen_theme's docstring), so the guard's count is unaffected either
    # way.
    agents_page = agents_page.rstrip() + "\n\n" + gen_theme.render_theme_section()
    skills_page, skill_warnings = render_skills(skills)
    commands_page, commands_warnings = gen_commands.render_commands(commands)
    lifecycle_page, lifecycle_warnings = gen_lifecycle.render_lifecycle(repo_dir)

    # Both renderers open with the generic agents/skills banner (they import
    # the same GENERATED_BANNER everything else here does); swap in the
    # correct source description for each page without touching either
    # renderer module.
    commands_page = commands_page.replace(
        GENERATED_BANNER, generated_banner("commands/*.md"), 1
    )
    lifecycle_page = lifecycle_page.replace(
        GENERATED_BANNER,
        generated_banner(
            "agents/orchestrator.md (the phase list and triage table; the "
            "surrounding prose is hand-written and pinned by a staleness digest)"
        ),
        1,
    )

    check_count("agents", agents_page, agent_paths(repo_dir), repo_dir)
    check_count("skills", skills_page, skill_paths(repo_dir), repo_dir)
    check_count(
        "commands", commands_page, gen_commands.command_paths(repo_dir), repo_dir
    )

    warnings = (
        agents.warnings
        + agent_warnings
        + skills.warnings
        + skill_warnings
        + commands.warnings
        + commands_warnings
        + lifecycle_warnings
    )
    return {
        "agents.md": agents_page,
        "skills.md": skills_page,
        "commands.md": commands_page,
        "lifecycle.md": lifecycle_page,
    }, warnings


def generate(
    repo_dir: Path | None = None,
    out_dir: Path | None = None,
    *,
    check_only: bool = False,
) -> dict[str, int]:
    """Write all four pages; return the rendered agents/skills counts.

    Safe to call from a MkDocs ``on_pre_build`` hook. Raises
    :class:`CatalogError` on any problem, which fails the build.

    The returned dict stays ``{"agents": n, "skills": m}``, the same shape it
    has always had -- ``test_gen_catalog.py::TestRendering.test_writes_both_pages``
    asserts it by exact equality, so a third ``"commands"`` key would fail that
    assertion for a reason that has nothing to do with what it is actually
    guarding. The CLI below still reports a commands count in its closing
    message -- it just gets it from the live directory listing directly, the
    same number ``check_count`` already proved the rendered page matches,
    rather than from this dict.
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
    """MkDocs hook entry point, for `hooks:` in mkdocs.yml. Checks, never writes.

    Registered as `hooks: [gen_catalog.py]` -- this module sits at
    `docs_site/gen_catalog.py`, not under `docs_site/hooks/`, and is pointed at
    directly rather than being re-exported through a one-line shim in `hooks/`.
    A shim there would have to put `docs_site/` on `sys.path` to import this
    module, which is a worse thing to own than a path with a `/` fewer in it.
    Like the other two hooks it resolves its own root from `__file__`
    (`REPO_DIR`) and signals failure by raising, which fails the build.

    WHY `check_only=True` AND NOT `generate()`
    ------------------------------------------
    `agents.md` and `skills.md` are generated artefacts that are also *tracked
    source files* under `docs_dir`. A writing hook rewrites them mid-build:
    measured on this repo, `mkdocs build` silently took the committed page from
    11 item sections to 17 and exited 0. That is unacceptable twice over -- a
    build must not mutate the working tree, and rewriting the page in the same
    process that publishes it launders drift instead of reporting it. The
    guarantee worth having is the opposite one: a build refuses when the
    committed pages do not match a fresh render, and says so.

    Regenerating is a deliberate act: run `python docs_site/gen_catalog.py` and
    commit the result.
    """
    generate(check_only=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--repo-dir", type=Path, default=REPO_DIR, help="repo root (default: %(default)s)"
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help="where the generated pages are written (default: %(default)s)",
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

    # `commands` is not one of `counts`' keys (see generate()'s docstring for
    # why), so it is read here straight from the live directory listing --
    # the same number check_count already proved the rendered page matches.
    commands_count = len(gen_commands.command_paths(args.repo_dir))
    verb = "verified" if args.check else "wrote"
    print(
        f"gen_catalog: {verb} {counts['agents']} agents, {counts['skills']} skills "
        f"and {commands_count} commands"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
