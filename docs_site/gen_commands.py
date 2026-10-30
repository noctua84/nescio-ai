"""Generate the Commands catalogue page (``docs/commands.md``) for the docs site.

Mirrors ``gen_catalog.py``'s agents/skills renderers, but over ``commands/*.md``
and with one extra thing neither of those carries: each command's own **lead
prose** -- the paragraph(s) right after its ``# /name`` heading, up to (but not
including) the next heading. The frontmatter ``description`` says what a
command is *for*; the lead says what it *does*, in the author's own words, and
dropping it would leave the page thinner than the source it is generated from.

Stdlib only, same constraint as the rest of ``docs_site/``: the docs build must
work with nothing from ``scripts/`` on ``PYTHONPATH``.

This module is wired into ``gen_catalog.build_pages`` by a later task (see the
plan's file-ownership table) -- it does not touch ``gen_catalog.py`` or
``mkdocs.yml`` itself, and exposes exactly the public contract that wiring
needs:

* ``command_paths(repo_dir) -> list[Path]`` -- the live directory listing, used
  as the count-guard's expectation.
* ``discover_commands(repo_dir) -> Catalog`` -- parse every ``commands/*.md``.
* ``render_commands(catalog) -> tuple[str, list[str]]`` -- page text, warnings.

MUST stay a top-level import below: verified against mkdocs 1.6.1
(``mkdocs.config.config_options.Hooks._load_hook``), the hook loader puts a
hook file's own directory on ``sys.path`` only *around* module exec and
restores it afterward. A function-level ``import catalog_core`` would work
when this module is imported as an ordinary sibling of a CLI entry point, but
would fail if anything in this chain were ever loaded the way ``gen_catalog.py``
is loaded as a ``hooks:`` entry.
"""

from __future__ import annotations

import re
from pathlib import Path

from catalog_core import (
    Catalog,
    CatalogError,
    GENERATED_BANNER,
    Item,
    REPO_BLOB_BASE,
    REPO_DIR,
    _parse_item,
    _source_link,
    split_frontmatter,
)

# Matches a markdown heading of any level ("#" through "######" followed by a
# space). Used to find where a command's lead prose ends -- the text runs from
# just after its "# /name" heading to the next heading of ANY level.
_HEADING_RE = re.compile(r"^#{1,6}\s")

# A markdown link: `[label](target)`. Used to rewrite repo-relative targets to
# absolute REPO_BLOB_BASE URLs -- `mkdocs build --strict` fails on a broken
# internal link, and a path relative to the source .md file does not resolve
# inside the rendered site at all.
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")


# --------------------------------------------------------------------------
# Discovery
#
# Walks the live directory listing, same as gen_catalog.discover_agents/
# discover_skills. A command file that exists but cannot be parsed faithfully
# is an error, never a silent skip.
# --------------------------------------------------------------------------


def command_paths(repo_dir: Path) -> list[Path]:
    """Live listing of command definitions -- the count-guard's expectation."""
    return sorted((repo_dir / "commands").glob("*.md"))


def _lead_prose(body: str, name: str, rel_path: str) -> str:
    """Text after "# /name" up to the next heading, skipping fenced blocks.

    A ```` ``` ````-fenced block inside a command's body can itself contain
    ``## ``-prefixed lines (``commands/harvest-memory.md`` is ~25 KB of exactly
    that shape) -- those must not be mistaken for the terminating heading, so
    fence state is tracked while scanning.
    """
    heading = f"# /{name}"
    lines = body.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.strip() == heading:
            start = i + 1
            break
    if start is None:
        raise CatalogError(f"{rel_path}: no '{heading}' heading found in the body")

    in_fence = False
    end = len(lines)
    for i in range(start, len(lines)):
        stripped = lines[i].strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            continue
        if not in_fence and _HEADING_RE.match(lines[i]):
            end = i
            break
    return "\n".join(lines[start:end]).strip()


def _rewrite_relative_links(text: str, source_path: Path, repo_dir: Path) -> str:
    """Rewrite repo-relative markdown links in ``text`` to absolute blob URLs.

    Links already absolute (``http(s)://``) or in-page (``#anchor``) are left
    alone. A link that would resolve outside ``repo_dir`` is left alone too,
    rather than guessed at.
    """

    def _replace(match: re.Match[str]) -> str:
        label, target = match.group(1), match.group(2)
        if target.startswith(("http://", "https://", "#")):
            return match.group(0)
        resolved = (source_path.parent / target).resolve()
        try:
            rel = resolved.relative_to(repo_dir).as_posix()
        except ValueError:
            return match.group(0)
        return f"[{label}]({REPO_BLOB_BASE}/{rel})"

    return _LINK_RE.sub(_replace, text)


def discover_commands(repo_dir: Path) -> Catalog:
    """Parse every live ``commands/*.md`` into an ``Item`` carrying its lead.

    Each item's ``meta`` dict carries a ``"lead"`` key holding the extracted,
    link-rewritten lead prose, alongside whatever other scalar frontmatter the
    file declares (``user-invocable``).
    """
    commands_dir = repo_dir / "commands"
    if not commands_dir.is_dir():
        raise CatalogError(f"{commands_dir} does not exist")

    items: list[Item] = []
    warnings: list[str] = []
    for path in command_paths(repo_dir):
        item, name_warnings = _parse_item(path, repo_dir, expected_name=path.stem)
        if name_warnings:
            # Unlike agents/skills, a command's frontmatter `name` disagreeing
            # with its filename is fatal, not a warning -- the slash command a
            # user types IS the filename, so a mismatch here means the page
            # would advertise a command that does not invoke what it says.
            raise CatalogError(
                f"{item.rel_path}: frontmatter name '{item.name}' does not "
                f"match its filename (expected '{path.stem}')"
            )

        if "user-invocable" not in item.meta:
            warnings.append(
                f"{item.rel_path}: frontmatter is missing 'user-invocable'; "
                "treating it as false"
            )

        text = path.read_text(encoding="utf-8")
        _, body = split_frontmatter(text)
        lead = _lead_prose(body, item.name, item.rel_path)
        lead = _rewrite_relative_links(lead, path, repo_dir)

        items.append(
            Item(
                name=item.name,
                description=item.description,
                rel_path=item.rel_path,
                meta={**item.meta, "lead": lead},
            )
        )

    if not items:
        raise CatalogError(f"no command definitions found under {commands_dir}")
    return Catalog(items, warnings)


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------


def _command_meta(item: Item) -> str:
    invocable = item.meta.get("user-invocable", "false").strip().lower() in {
        "true",
        "yes",
    }
    parts = [f"**User-invocable** {'yes' if invocable else 'no'}"]
    parts.append(_source_link(item.rel_path))
    return " · ".join(parts)


def render_commands(catalog: Catalog) -> tuple[str, list[str]]:
    """Render the Commands page. Returns (page text, warnings).

    Mirrors ``gen_catalog.render_agents``/``render_skills`` in shape, minus
    grouping -- there is no curated routing table for commands, just an
    at-a-glance table followed by one detail section per command. There is
    nothing for this function itself to warn about; the one warning this
    module raises (a missing ``user-invocable``) is produced at discovery
    time and lives on ``catalog.warnings`` instead.
    """
    count = len(catalog.items)
    lines = [
        GENERATED_BANNER,
        "",
        "# Commands",
        "",
        f"Nescio ships {count} slash commands in `commands/`. Each one is a",
        "Markdown file whose YAML frontmatter declares a `name`, a",
        "`description`, and whether it is `user-invocable`. The description and",
        "the command's own lead paragraph are reproduced verbatim below.",
        "",
        "Command names are identifiers, and are set in mono throughout.",
        "",
        "## At a glance",
        "",
        "| Command | What it does |",
        "|---|---|",
    ]
    for item in catalog.items:
        lines.append(f"| `/{item.name}` | {item.description} |")
    lines.append("")

    for item in catalog.items:
        lines += [
            f"### `/{item.name}`",
            "",
            item.description,
            "",
            item.meta.get("lead", ""),
            "",
            _command_meta(item),
            "",
        ]

    return "\n".join(lines).rstrip() + "\n", []


if __name__ == "__main__":  # pragma: no cover - manual smoke-check only
    page, page_warnings = render_commands(discover_commands(REPO_DIR))
    for warning in page_warnings:
        print(f"gen_commands: warning: {warning}")
    print(page)
