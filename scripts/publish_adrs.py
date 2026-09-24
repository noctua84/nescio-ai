#!/usr/bin/env python3
"""Publish an allowlisted set of brain ADRs into a documentation repository.

The brain keeps every ADR under `memory/repo/<dir>/adr/`. This script copies
only the ones listed in `adr-publish.toml`, transforms them for an outside
reader (see `_adr_transform.py`), regenerates an index, and deletes copies
that are no longer allowlisted. Files numbered at or above
`target.reserved_from` belong to the target repo's own authors and are never
touched.

Usage (from the brain root):

    python scripts/publish_adrs.py                  # plan: report + diffs, no writes
    python scripts/publish_adrs.py --apply          # write
    python scripts/publish_adrs.py --docs-path P    # override $<target.path_env>
    python scripts/publish_adrs.py --config P       # default ./adr-publish.toml
"""
from __future__ import annotations

import argparse
import datetime as _dt
import difflib
import os
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import _adr_transform as tr


class ConfigError(Exception):
    """The config file is malformed or names things that do not exist."""


class PublishError(Exception):
    """A precondition on the target checkout failed."""


@dataclass(frozen=True)
class Target:
    github: str
    path_env: str
    adr_root: str
    reserved_from: int
    template: str


@dataclass(frozen=True)
class RepoMap:
    slug: str
    github: str
    brain_dirs: tuple[str, ...]


@dataclass(frozen=True)
class Config:
    target: Target
    repos: tuple[RepoMap, ...]
    publish: dict[str, tuple[str, ...]]
    brain_root: Path


@dataclass(frozen=True)
class Entry:
    brain_dir: str
    filename: str
    slug: str
    github: str
    source: Path
    source_rel: str
    target_rel: str


def _require(table: dict, key: str, where: str):
    if key not in table:
        loc = "the top level" if where == "" else f"[{where}]"
        raise ConfigError(f"missing `{key}` in {loc}")
    return table[key]


def _str_list(value, where: str, key: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ConfigError(f"`{key}` in [{where}] must be a list of strings, e.g. [\"name\"]")
    return tuple(value)


def _int(value, where: str, key: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"`{key}` in [{where}] must be an integer")
    return value


_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _segment(value: str, where: str, key: str) -> str:
    """One path component: letters, digits, `.`, `_`, `-`; must start with a
    letter or digit. A positive allowlist — denylisting separators and drive
    letters proved incomplete (`C:` is not `is_absolute()` on Windows)."""
    if not _SEGMENT_RE.match(value) or value in (".", ".."):
        raise ConfigError(f"`{key}` in [{where}] must match {_SEGMENT_RE.pattern}, got {value!r}")
    return value


def _relative_dir(value: str, where: str, key: str) -> str:
    """A `/`-separated path of allowlisted segments (no `..`, no anchors)."""
    parts = value.split("/")
    if not value or "\\" in value or any(not _SEGMENT_RE.match(p) or p in (".", "..") for p in parts):
        raise ConfigError(f"`{key}` in [{where}] must be a relative path of segments matching "
                          f"{_SEGMENT_RE.pattern}, joined by `/`, got {value!r}")
    return value


def load_config(path: Path) -> Config:
    path = path.resolve()
    try:
        raw = tomllib.loads(path.read_bytes().decode("utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from exc
    t = _require(raw, "target", "")
    target = Target(
        github=str(_require(t, "github", "target")),
        path_env=str(_require(t, "path_env", "target")),
        adr_root=_relative_dir(str(t.get("adr_root", "adr")), "target", "adr_root"),
        reserved_from=_int(t.get("reserved_from", 1000), "target", "reserved_from"),
        template=str(_require(t, "template", "target")),
    )
    repos_raw = _require(raw, "repos", "")
    repos = tuple(
        RepoMap(slug=_segment(slug, "repos", "slug"),
                github=str(_require(r, "github", f"repos.{slug}")),
                brain_dirs=tuple(
                    _segment(d, f"repos.{slug}", "brain_dirs")
                    for d in _str_list(_require(r, "brain_dirs", f"repos.{slug}"),
                                       f"repos.{slug}", "brain_dirs")))
        for slug, r in repos_raw.items()
    )
    publish = {
        str(k): tuple(_segment(f, "publish", k) for f in _str_list(v, "publish", k))
        for k, v in raw.get("publish", {}).items()
    }
    return Config(target=target, repos=repos, publish=publish, brain_root=path.parent)


def build_entries(cfg: Config) -> list[Entry]:
    """Resolve the allowlist to concrete source/target paths; fail on any
    unmapped brain dir, missing source, or two sources sharing a target."""
    dir_to_repo: dict[str, RepoMap] = {}
    for repo in cfg.repos:
        for d in repo.brain_dirs:
            if d in dir_to_repo:
                raise ConfigError(f"brain dir `{d}` is mapped to both "
                                  f"`{dir_to_repo[d].slug}` and `{repo.slug}`")
            dir_to_repo[d] = repo
    entries: list[Entry] = []
    seen: dict[str, Entry] = {}
    for brain_dir, files in cfg.publish.items():
        repo = dir_to_repo.get(brain_dir)
        if repo is None:
            raise ConfigError(f"[publish] names brain dir `{brain_dir}` which no [repos.*] maps")
        for filename in files:
            source_rel = f"memory/repo/{brain_dir}/adr/{filename}"
            source = cfg.brain_root / Path(source_rel)
            if not source.is_file():
                raise ConfigError(f"allowlisted file does not exist: {source_rel}")
            target_rel = f"{repo.slug}/{filename}"
            entry = Entry(brain_dir=brain_dir, filename=filename, slug=repo.slug,
                          github=repo.github, source=source, source_rel=source_rel,
                          target_rel=target_rel)
            if target_rel in seen:
                raise ConfigError(
                    f"target collision: {target_rel} would be written from both "
                    f"{seen[target_rel].source_rel} and {source_rel}")
            seen[target_rel] = entry
            entries.append(entry)
    return entries


def git(args: list[str], cwd: Path) -> str:
    """Run git in `cwd`; return stripped stdout; raise PublishError on failure."""
    try:
        proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    except OSError as exc:
        raise PublishError(f"cannot run git in {cwd}: {exc}") from exc
    if proc.returncode != 0:
        raise PublishError(f"git {' '.join(args)} failed in {cwd}: {proc.stderr.strip()}")
    return proc.stdout.strip()


def brain_sha(cfg: Config) -> str:
    return git(["rev-parse", "--short", "HEAD"], cfg.brain_root)


def resolve_docs_path(cfg: Config, override: Path | None) -> Path:
    if override is not None:
        return override.resolve()
    value = os.environ.get(cfg.target.path_env)
    if not value:
        raise PublishError(
            f"target checkout unknown: set ${cfg.target.path_env} or pass --docs-path")
    return Path(value).resolve()


def check_preconditions(cfg: Config, entries: list[Entry], docs: Path) -> list[str]:
    """Return a list of human-readable errors; empty means safe to write."""
    if not docs.is_dir():
        return [f"{docs} does not exist or is not a directory"]
    errors: list[str] = []
    template = cfg.brain_root / cfg.target.template
    if not template.is_file():
        errors.append(f"template not found: {template}")
    try:
        top = git(["rev-parse", "--show-toplevel"], docs)
    except PublishError:
        errors.append(f"{docs} is not a git checkout")
        return errors
    if Path(top).resolve() != docs.resolve():
        errors.append(f"{docs} is not the top level of its checkout ({top})")
    root = (docs / cfg.target.adr_root).resolve()
    if not root.is_relative_to(docs.resolve()):
        errors.append(f"adr_root {cfg.target.adr_root!r} resolves outside {docs}")
    try:
        origin = git(["remote", "get-url", "origin"], docs)
    except PublishError:
        origin = ""
    if cfg.target.github.casefold() not in origin.casefold():
        errors.append(f"origin of {docs} is `{origin}`, expected it to contain `{cfg.target.github}`")
    if git(["status", "--porcelain"], docs):
        errors.append(f"working tree of {docs} is not clean — commit or discard first")
    return errors


@dataclass(frozen=True)
class IndexRow:
    slug: str
    number: str
    title: str
    status: str
    description: str
    target_rel: str


INDEX_FOOTER_PREFIX = "_Synced "
_NUMBER = re.compile(r"^(\d{4})-")


def adr_number(filename: str) -> int | None:
    m = _NUMBER.match(filename)
    return int(m.group(1)) if m else None


def _cell(text: str) -> str:
    """Escape characters that would break a markdown table cell or a link label."""
    return text.replace("\\", "\\\\").replace("|", "\\|").replace("[", "\\[").replace("]", "\\]")


def render_index(cfg: Config, rows: list[IndexRow], brain_sha: str, synced_at: str) -> str:
    n = cfg.target.reserved_from
    lines = [
        "# Architecture Decision Records",
        "",
        f"Files numbered below {n} are generated from the maintainer's decision",
        "records and are overwritten on every sync — do not edit them here; send",
        "corrections to the maintainer.",
        "",
        "To record a new decision in this repository, copy `TEMPLATE.md` into the",
        f"matching repository folder and number it from {n} upward so it can never",
        "collide with a maintainer decision published later.",
        "Any other Markdown file inside these folders is removed on the next sync — number it, or keep it outside this tree.",
        "",
    ]
    for repo in cfg.repos:
        repo_rows = sorted((r for r in rows if r.slug == repo.slug),
                           key=lambda r: (r.number == "—", r.number, r.target_rel))
        if not repo_rows:
            continue
        lines += [f"## {repo.github}", "", "| Number | Title | Status | Description |", "|---|---|---|---|"]
        for r in repo_rows:
            label = r.title or r.target_rel.rsplit("/", 1)[-1]
            lines.append(f"| {r.number} | [{_cell(label)}]({r.target_rel}) | {r.status} | {_cell(r.description)} |")
        lines.append("")
    lines.append(f"{INDEX_FOOTER_PREFIX}{synced_at} from brain commit {brain_sha}._")
    return "\n".join(lines) + "\n"


def strip_index_footer(text: str) -> str:
    return "\n".join(l for l in text.split("\n") if not l.startswith(INDEX_FOOTER_PREFIX))


@dataclass
class Plan:
    added: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    contents: dict[str, str] = field(default_factory=dict)


def _read(path: Path) -> str | None:
    try:
        return tr.normalize_newlines(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError):
        return None


def _classify(plan: Plan, rel: str, new: str, old: str | None, same) -> bool:
    """Record `rel` in the plan; return True when it changed."""
    if old is None:
        plan.added.append(rel)
    elif same(old, new):
        plan.unchanged.append(rel)
        return False
    else:
        plan.updated.append(rel)
    plan.contents[rel] = new
    return True


def compute_plan(cfg: Config, entries: list[Entry], docs: Path, *,
                 synced_at: str, brain_sha: str) -> Plan:
    plan = Plan()
    root = docs / cfg.target.adr_root
    published = {e.source_rel: e.target_rel for e in entries}
    rows: list[IndexRow] = []
    changed = False

    for e in entries:
        src = _read(e.source)
        if src is None:
            raise PublishError(f"cannot read {e.source_rel}")
        new = tr.transform(src, source_rel=e.source_rel, target_rel=e.target_rel,
                           github=e.github, synced_at=synced_at, published=published)
        target = root / e.target_rel
        if target.exists() and _read(target) is None:
            raise PublishError(f"cannot decode existing file {e.target_rel} as UTF-8")
        old = _read(target)
        changed |= _classify(plan, e.target_rel, new, old,
                             lambda a, b: tr.strip_synced_at(a) == tr.strip_synced_at(b))
        src_fm, src_body = tr.split_frontmatter(tr.normalize_newlines(src))
        num = adr_number(e.filename)
        rows.append(IndexRow(
            slug=e.slug, number=f"{num:04d}" if num is not None else "—",
            title=tr.extract_title(src_body), status=tr.extract_status(src_fm, src_body),
            description=src_fm.get("description", ""), target_rel=e.target_rel))

    template_new = _read(cfg.brain_root / cfg.target.template)
    if template_new is None:
        raise PublishError(f"cannot read template {cfg.target.template}")
    template_target = root / "TEMPLATE.md"
    if template_target.exists() and _read(template_target) is None:
        raise PublishError("cannot decode existing file TEMPLATE.md as UTF-8")
    changed |= _classify(plan, "TEMPLATE.md", template_new, _read(template_target),
                         lambda a, b: a == b)

    targets = set(published.values())
    if root.is_dir():
        for slug_dir in sorted(p for p in root.iterdir() if p.is_dir()):
            for p in sorted(slug_dir.glob("*.md")):
                if not p.is_file():
                    continue
                rel = f"{slug_dir.name}/{p.name}"
                if rel in targets:
                    continue
                num = adr_number(p.name)
                if num is not None and num >= cfg.target.reserved_from:
                    continue
                plan.deleted.append(rel)
                changed = True

    index_new = render_index(cfg, rows, brain_sha, synced_at)
    index_old = _read(root / "README.md")
    if index_old is None:
        plan.added.append("README.md")
        plan.contents["README.md"] = index_new
    elif changed or strip_index_footer(index_old) != strip_index_footer(index_new):
        plan.updated.append("README.md")
        plan.contents["README.md"] = index_new
    else:
        plan.unchanged.append("README.md")
    return plan


def apply_plan(plan: Plan, docs: Path, adr_root: str) -> None:
    root = docs / adr_root
    resolved_root = root.resolve()
    for rel in list(plan.deleted) + list(plan.contents):
        target = (root / rel).resolve()
        if not target.is_relative_to(resolved_root):
            raise PublishError(f"refusing to touch {target}: outside {resolved_root}")
    for rel in plan.deleted:
        (root / rel).unlink()
    for rel, text in plan.contents.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)


def render_plan(plan: Plan, docs: Path, adr_root: str) -> str:
    """Summary lines, then a unified diff per updated file, a preview per
    added file, and a line per deletion. Deterministic ordering."""
    root = docs / adr_root
    lines: list[str] = []
    for label, items in (("+ add    ", plan.added), ("~ update ", plan.updated), ("- delete ", plan.deleted)):
        for rel in sorted(items):
            lines.append(f"  {label} {rel}")
    lines.append("")
    for rel in sorted(plan.updated):
        old = (_read(root / rel) or "").splitlines(keepends=True)
        new = plan.contents[rel].splitlines(keepends=True)
        diff = "".join(difflib.unified_diff(old, new, fromfile=f"a/{rel} (current)", tofile=f"b/{rel} (new)"))
        lines.append(diff.rstrip("\n"))
        lines.append("")
    for rel in sorted(plan.added):
        lines.append(f"+++ ADDED  {rel}  (NET-NEW)")
        preview = plan.contents[rel].splitlines()[:12]
        lines += [f"  +{l}" for l in preview]
        lines.append("")
    for rel in sorted(plan.deleted):
        lines.append(f"--- DELETED  {rel}")
    return "\n".join(lines).rstrip("\n") + "\n"


def main(argv=None) -> int:
    # Reports carry em dashes and non-ASCII paths; a legacy Windows console
    # defaults to cp1252 and would raise UnicodeEncodeError. Reconfigure to
    # UTF-8 when possible (guarded — a redirected StringIO has no reconfigure).
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", type=Path, default=Path("adr-publish.toml"))
    ap.add_argument("--docs-path", type=Path, default=None,
                    help="target documentation checkout (default: $<target.path_env>)")
    ap.add_argument("--apply", action="store_true", help="write (default: dry run)")
    args = ap.parse_args(argv)

    try:
        cfg = load_config(args.config)
        entries = build_entries(cfg)
        docs = resolve_docs_path(cfg, args.docs_path)
    except (ConfigError, PublishError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    errors = check_preconditions(cfg, entries, docs)
    if errors:
        for e in errors:
            print(f"error: {e}", file=sys.stderr)
        return 2

    today = _dt.date.today().isoformat()
    try:
        plan = compute_plan(cfg, entries, docs, synced_at=today, brain_sha=brain_sha(cfg))
    except PublishError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    total = len(plan.added) + len(plan.updated) + len(plan.deleted)
    if total == 0:
        print(f"{docs / cfg.target.adr_root} already matches the allowlist — nothing to do.")
        return 0

    report = render_plan(plan, docs, cfg.target.adr_root)  # before apply overwrites the old text
    if args.apply:
        apply_plan(plan, docs, cfg.target.adr_root)
    verb = "published" if args.apply else "would publish"
    print(f"{verb}: {len(plan.added)} added, {len(plan.updated)} updated, "
          f"{len(plan.deleted)} deleted, {len(plan.unchanged)} unchanged")
    print(report, end="")
    if args.apply:
        print(f"\nReview `git -C {docs} diff` and commit in the target repository.")
    else:
        print("\n(dry run — re-run with --apply to write)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
