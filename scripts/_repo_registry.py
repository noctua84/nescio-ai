#!/usr/bin/env python3
"""One GitHub repo, one `memory/repo/<dir>/` — declared, guarded, and aliased.

Nothing in this brain used to state which `memory/repo/<dir>/` belongs to which
GitHub repository, or which learning-trail keys feed it. Both facts lived only in
the coincidence that a clone's directory basename happened to equal the memory
dir's name: `compute_readiness.repo_name()` and `assess_repo_readiness.assess()`
both derive the memory dir from `Path(repo_root).name`. So the day a clone is
renamed — or cloned twice under two names — the brain silently grows a *second*
identity for one repository, and the first one's history is stranded.

In practice that strands hundreds of recorded turns per rename, and nothing
reports it. This module is the declaration that stops it, and it does two jobs:

1. **Guard.** `validate()` cross-checks the registry against `memory/repo/*/`
   (every dir registered, every registered dir real), against itself (no slug
   shared without an explicit exception, no trail key claimed twice), and — when
   it exists — against `adr-publish.toml`'s `brain_dirs`.
2. **Alias.** `dir_for_trail_key()` maps a *historical* trail key (really: the
   basename of a clone directory, which is what the trail records) to the memory
   dir that owns it. `compute_readiness.repo_name()`,
   `_trail_scope.belongs_to_repo()` and `assess_repo_readiness.assess()` consume
   it, which is what re-attaches stranded history and makes the *next* rename a
   one-line config change instead of another orphaned bucket.

## The alias must be honoured in more than one place

`compute_readiness` consuming the alias fixes *reporting* only. A harvest stamps
watermarks on the trail files `_trail_scope.trails_for_repo()` selects, so until
`belongs_to_repo()` also resolves aliased keys, the aliased trail is never
stamped — and the merged bucket reports its turns as un-harvested forever. Fixing
one without the other looks like progress and produces a number that can never go
down. Hence both call sites, and hence this module rather than a helper private to
either.

## Why the hot path is lenient and the gate is strict

`load_registry()` is strict: it raises `RegistryError` on anything malformed,
including an absent file. `alias_map()` / `dir_for_trail_key()` are lenient — any
failure degrades to "no aliases", which is exactly today's behaviour. That split
is deliberate. `_trail_scope`'s contract is that nothing in it raises (a single
bad entry must not derail a harvest sweeping ~100 trail files), and refusing to
run a harvest because a config file has a typo is strictly worse than attributing
records the way the brain did before the registry existed.

Leniency therefore needs a loud gate elsewhere, and it has two:
`scripts/check_repo_registry.py` and `tests/test_repo_registry.py`, which
validates the real file whenever one is present. The *test* is the load-bearing
one: `.github/` is not in `sync_from_upstream.FRAMEWORK_PATHS` but `tests/` is, so
a CI step would guard this repo only while a test guards every instance.

## Instance-owned, like `adr-publish.toml`

`repo-registry.toml` is tracked but **not** synced; `repo-registry.toml.example`
is synced. The real file is a statement about *this* brain's repositories, which
no two instances share — the same ownership split `adr-publish.toml` already uses,
and the reason `validate()` treats the file's absence as "skip", never "fail".

The registry's own directory names are deliberately *not* reconciled with the
GitHub repository name: a dir `widget-service` may be registered against
`your-org/widget-platform` because the repo was renamed on GitHub and the memory
dir was not. Declaring the
divergence is the entire point; renaming memory dirs to chase upstream renames is
the churn the alias exists to replace.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
DEFAULT_REGISTRY_PATH = REPO_DIR / "repo-registry.toml"
DEFAULT_MEMORY_ROOT = REPO_DIR / "memory"
DEFAULT_ADR_CONFIG_PATH = REPO_DIR / "adr-publish.toml"

# One path component: the same positive allowlist `publish_adrs._segment` uses,
# for the same reason (denylisting separators and drive letters proved incomplete
# — `C:` is not `is_absolute()` on Windows). Memory dir names and trail keys are
# both single path components, so both go through it.
_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

# `owner/name`, each side a segment. Not a URL: `adr-publish.toml` already stores
# slugs in this shape and the two files must be comparable without parsing.
_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*$")

# Recognised keys inside a `[dirs.<name>]` table. Unknown keys are an error
# rather than ignored: a silently-dropped `trail_key = [...]` (singular) reads as
# a declared alias and behaves as none at all, which is the failure this whole
# module exists to make impossible.
_ENTRY_KEYS = {"github", "trail_keys", "clone_expected", "note"}


class RegistryError(Exception):
    """`repo-registry.toml` is absent, malformed, or names impossible values."""


@dataclass(frozen=True)
class RepoEntry:
    """One `memory/repo/<dir>/` and the repository it belongs to.

    `trail_keys` is the *effective* set and always contains `dir` itself: a dir
    implicitly owns the trail key equal to its own name, so a registration never
    has to restate it. `declared_trail_keys` keeps what the file literally said,
    for error messages that quote the operator's own text back at them.

    `github` is `""` when deliberately undeclared — the brain holds memory for
    repositories whose slug must not be written into tracked config. Those
    entries are exempt from the shared-slug rule (two undeclared dirs do not
    collide) and must carry a `note`, so an omission is visibly a decision rather
    than an oversight.
    """

    dir: str
    github: str
    trail_keys: tuple[str, ...]
    declared_trail_keys: tuple[str, ...]
    clone_expected: bool
    note: str


@dataclass(frozen=True)
class Registry:
    path: Path
    entries: tuple[RepoEntry, ...]
    # github slug -> the dirs declared to share it. An explicit, documented
    # exception to "one repo, one dir", so a convergence still in flight is
    # declared rather than silently tolerated.
    shared_slugs: dict[str, tuple[str, ...]]

    def by_dir(self) -> dict[str, RepoEntry]:
        return {e.dir: e for e in self.entries}

    def alias_map(self) -> dict[str, str]:
        """Effective trail key -> owning memory dir.

        First claim wins on a duplicate so this cannot raise; a duplicate is a
        `validate()` finding, and the lenient accessors below must stay total.
        """
        out: dict[str, str] = {}
        for entry in self.entries:
            for key in entry.trail_keys:
                out.setdefault(key, entry.dir)
        return out

    def dir_for_trail_key(self, key: str) -> str | None:
        return self.alias_map().get(str(key or ""))


# ── loading ────────────────────────────────────────────────────────────────

def _segment(value, where: str, key: str) -> str:
    if not isinstance(value, str) or not _SEGMENT_RE.match(value) or value in (".", ".."):
        raise RegistryError(
            f"`{key}` in [{where}] must match {_SEGMENT_RE.pattern}, got {value!r}"
        )
    return value


def _str_list(value, where: str, key: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise RegistryError(
            f"`{key}` in [{where}] must be a list of strings, e.g. [\"name\"]"
        )
    return tuple(value)


def _bool(value, where: str, key: str) -> bool:
    if not isinstance(value, bool):
        raise RegistryError(f"`{key}` in [{where}] must be true or false")
    return value


def _slug(value, where: str, key: str) -> str:
    """A `owner/name` slug, or `""` for a deliberately undeclared repository."""
    if not isinstance(value, str):
        raise RegistryError(f"`{key}` in [{where}] must be a string")
    if value and not _SLUG_RE.match(value):
        raise RegistryError(
            f"`{key}` in [{where}] must be `owner/name`, got {value!r}"
        )
    return value


def _load_entry(name: str, table, where: str) -> RepoEntry:
    if not isinstance(table, dict):
        raise RegistryError(f"[{where}] must be a table")
    unknown = sorted(set(table) - _ENTRY_KEYS)
    if unknown:
        raise RegistryError(
            f"[{where}] has unknown key(s) {', '.join(unknown)}; "
            f"recognised: {', '.join(sorted(_ENTRY_KEYS))}"
        )
    declared = tuple(
        _segment(k, where, "trail_keys")
        for k in _str_list(table.get("trail_keys", []), where, "trail_keys")
    )
    # Dedup while preserving declaration order, and guarantee `name` is present.
    effective: list[str] = [name]
    for key in declared:
        if key not in effective:
            effective.append(key)
    return RepoEntry(
        dir=name,
        github=_slug(table.get("github", ""), where, "github"),
        trail_keys=tuple(effective),
        declared_trail_keys=declared,
        clone_expected=_bool(table.get("clone_expected", True), where, "clone_expected"),
        note=str(table.get("note", "")).strip(),
    )


def load_registry(path: Path | str = DEFAULT_REGISTRY_PATH) -> Registry:
    """Parse and structurally validate `path`. Raises `RegistryError`.

    Structural only: types, key names, value shapes, and duplicate-detection
    inside `[shared_slugs]`. Everything that needs to look at the filesystem or
    at another config file is `validate()`'s job, so a caller that only wants the
    alias map does not pay for a `memory/repo/` walk.

    An absent file raises — this is the strict entry point. Callers that must
    tolerate absence use `alias_map()` below, or test `Path.is_file()` first.
    """
    path = Path(path)
    try:
        raw = tomllib.loads(path.read_bytes().decode("utf-8"))
    except FileNotFoundError as exc:
        raise RegistryError(f"no repository registry at {path}") from exc
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise RegistryError(f"cannot read {path}: {exc}") from exc

    dirs_raw = raw.get("dirs")
    if not isinstance(dirs_raw, dict) or not dirs_raw:
        raise RegistryError(
            f"{path}: expected at least one `[dirs.<memory-dir-name>]` table"
        )
    entries = tuple(
        _load_entry(_segment(name, "dirs", "name"), table, f"dirs.{name}")
        for name, table in dirs_raw.items()
    )

    shared_raw = raw.get("shared_slugs", {})
    if not isinstance(shared_raw, dict):
        raise RegistryError(f"{path}: [shared_slugs] must be a table")
    shared: dict[str, tuple[str, ...]] = {}
    for slug, value in shared_raw.items():
        slug = _slug(slug, "shared_slugs", "slug")
        if not slug:
            raise RegistryError("[shared_slugs] keys must be non-empty `owner/name` slugs")
        dirs = tuple(
            _segment(d, "shared_slugs", slug)
            for d in _str_list(value, "shared_slugs", slug)
        )
        if len(set(dirs)) < 2:
            raise RegistryError(
                f"[shared_slugs] `{slug}` must list at least two distinct dirs "
                f"— an exception for one dir is not an exception"
            )
        shared[slug] = dirs

    unknown_top = sorted(set(raw) - {"dirs", "shared_slugs"})
    if unknown_top:
        raise RegistryError(
            f"{path}: unknown top-level table(s) {', '.join(unknown_top)}; "
            "recognised: dirs, shared_slugs"
        )
    return Registry(path=path, entries=entries, shared_slugs=shared)


# ── validation ─────────────────────────────────────────────────────────────

def memory_repo_dirs(memory_root: Path | str = DEFAULT_MEMORY_ROOT) -> list[str]:
    """Sorted names of the directories under `<memory_root>/repo/`.

    Files are skipped (`memory/repo/` holds no loose files today, but a stray
    `.DS_Store` must not read as a repository). An absent `repo/` yields `[]`,
    which `validate()` reads as "nothing to reconcile", not as an error — a fresh
    instance legitimately has none.
    """
    root = Path(memory_root) / "repo"
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.iterdir() if p.is_dir())


def _adr_brain_dirs(path: Path) -> dict[str, tuple[str, str]]:
    """`brain_dir -> (adr slug, github)` from `adr-publish.toml`, or `{}`.

    Parsed here with `tomllib` rather than through `publish_adrs.load_config` on
    purpose. That loader validates the *publishing* concerns — `[target]`,
    `template`, the allowlist's files existing on disk — and raising any of those
    out of a registry check would report an ADR-publishing problem as a registry
    problem. This reads the two fields it needs and tolerates everything else,
    including a file that is mid-edit.
    """
    try:
        raw = tomllib.loads(Path(path).read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return {}
    out: dict[str, tuple[str, str]] = {}
    repos = raw.get("repos")
    if not isinstance(repos, dict):
        return {}
    for slug, table in repos.items():
        if not isinstance(table, dict):
            continue
        github = table.get("github")
        for brain_dir in table.get("brain_dirs", []) or []:
            if isinstance(brain_dir, str):
                out[brain_dir] = (str(slug), str(github or ""))
    return out


def validate(
    registry: Registry,
    *,
    memory_root: Path | str = DEFAULT_MEMORY_ROOT,
    adr_config: Path | str | None = DEFAULT_ADR_CONFIG_PATH,
) -> list[str]:
    """Every problem with `registry`, as human-readable lines. Empty == healthy.

    Returns rather than raises, so one run reports *all* findings instead of the
    first — the registry is edited by hand and a check that stops at finding one
    misspelling costs an edit/run cycle per mistake.

    `adr_config` is cross-checked only when the file exists. `adr-publish.toml` is
    instance-owned and optional; its absence is not a registry defect, and
    treating it as one would fail every instance that does not publish ADRs.
    """
    problems: list[str] = []
    by_dir = registry.by_dir()

    # ── registered dirs vs. memory/repo/ — in both directions ───────────────
    on_disk = set(memory_repo_dirs(memory_root))
    repo_root = Path(memory_root) / "repo"
    for name in sorted(on_disk - set(by_dir)):
        problems.append(
            f"{(repo_root / name).as_posix()}/ exists but is not registered — "
            f"add a [dirs.{name}] table (or fold the dir into the one that owns "
            f"its repository)"
        )
    for name in sorted(set(by_dir) - on_disk):
        problems.append(
            f"[dirs.{name}] is registered but {(repo_root / name).as_posix()}/ "
            f"does not exist"
        )

    # ── slug uniqueness, with declared exceptions ───────────────────────────
    by_slug: dict[str, list[str]] = {}
    for entry in registry.entries:
        if entry.github:
            by_slug.setdefault(entry.github, []).append(entry.dir)
    for slug, dirs in sorted(by_slug.items()):
        if len(dirs) < 2:
            continue
        declared = registry.shared_slugs.get(slug)
        if declared is None:
            problems.append(
                f"`{slug}` is claimed by {len(dirs)} dirs ({', '.join(sorted(dirs))}) "
                f"— one repository, one memory dir. Converge them, or declare the "
                f"exception as [shared_slugs] \"{slug}\" = "
                f"[{', '.join(repr(d) for d in sorted(dirs))}]"
            )
        elif set(declared) != set(dirs):
            problems.append(
                f"[shared_slugs] `{slug}` declares {sorted(declared)} but the dirs "
                f"claiming that slug are {sorted(dirs)}"
            )
    for slug, dirs in sorted(registry.shared_slugs.items()):
        actual = by_slug.get(slug, [])
        if len(actual) < 2:
            problems.append(
                f"[shared_slugs] `{slug}` is a stale exception — only "
                f"{len(actual)} dir(s) claim that slug now; delete the entry"
            )
        for name in dirs:
            if name not in by_dir:
                problems.append(
                    f"[shared_slugs] `{slug}` names unregistered dir `{name}`"
                )

    # ── no trail key claimed twice ──────────────────────────────────────────
    claimed: dict[str, str] = {}
    for entry in registry.entries:
        for key in entry.trail_keys:
            owner = claimed.get(key)
            if owner is not None and owner != entry.dir:
                implicit = " (implicitly, as the dir's own name)"
                problems.append(
                    f"trail key `{key}` is claimed by both [dirs.{owner}] and "
                    f"[dirs.{entry.dir}]"
                    + (implicit if key in (owner, entry.dir) else "")
                    + " — a trail key resolves to exactly one memory dir"
                )
            else:
                claimed[key] = entry.dir

    # ── an undeclared slug, or an unexpected clone, must be explained ───────
    for entry in registry.entries:
        if entry.note:
            continue
        if not entry.github:
            problems.append(
                f"[dirs.{entry.dir}] declares no `github` — add a `note` saying "
                f"why the slug is withheld, so the omission reads as a decision"
            )
        elif not entry.clone_expected:
            problems.append(
                f"[dirs.{entry.dir}] sets clone_expected = false — add a `note` "
                f"saying why no local checkout is expected"
            )

    # ── optional agreement with adr-publish.toml ────────────────────────────
    if adr_config is not None and Path(adr_config).is_file():
        adr = _adr_brain_dirs(Path(adr_config))
        adr_path = Path(adr_config).name
        adr_by_slug: dict[str, list[str]] = {}
        for brain_dir, (slug, github) in sorted(adr.items()):
            entry = by_dir.get(brain_dir)
            if entry is None:
                problems.append(
                    f"{adr_path} [repos.{slug}] names brain dir `{brain_dir}`, "
                    f"which the registry does not register"
                )
                continue
            if github and entry.github and github != entry.github:
                problems.append(
                    f"{adr_path} [repos.{slug}] maps `{brain_dir}` to `{github}` "
                    f"but [dirs.{brain_dir}] declares `{entry.github}`"
                )
            adr_by_slug.setdefault(slug, []).append(brain_dir)
        for slug, brain_dirs in sorted(adr_by_slug.items()):
            if len(brain_dirs) < 2:
                continue
            githubs = {by_dir[d].github for d in brain_dirs if d in by_dir}
            githubs.discard("")
            # adr-publish already treats these as one repository; the registry
            # must say the same thing, either by one slug or by an exception.
            if len(githubs) > 1:
                problems.append(
                    f"{adr_path} [repos.{slug}] feeds from {sorted(brain_dirs)}, "
                    f"but the registry gives them different repositories "
                    f"{sorted(githubs)}"
                )
    return problems


# ── lenient accessors for the hot paths ────────────────────────────────────

# Cache keyed on the resolved registry path. The alias is consulted once per
# trail record in `compute_readiness.collect_activity` (thousands of times per
# run) and once per trail in `_trail_scope.belongs_to_repo`, so re-reading and
# re-parsing the file at each call would be the single most expensive thing in
# either. `clear_cache()` exists for tests and for a caller that rewrote the file
# mid-process; nothing in normal operation needs it.
_ALIAS_CACHE: dict[str, dict[str, str]] = {}


def clear_cache() -> None:
    """Forget every cached alias map."""
    _ALIAS_CACHE.clear()


def alias_map(path: Path | str | None = None) -> dict[str, str]:
    """Cached `trail key -> memory dir`, or `{}` when unavailable.

    **Never raises, and never partially applies.** An absent, unreadable or
    malformed registry yields `{}`, which reproduces the brain's pre-registry
    behaviour exactly: every trail key stays its own bucket. See the module
    docstring for why the hot path degrades instead of refusing, and which two
    strict gates that leniency depends on.
    """
    key = str(Path(path or DEFAULT_REGISTRY_PATH))
    cached = _ALIAS_CACHE.get(key)
    if cached is not None:
        return cached
    try:
        mapping = load_registry(key).alias_map()
    except RegistryError:
        mapping = {}
    _ALIAS_CACHE[key] = mapping
    return mapping


def dir_for_trail_key(key: str, *, path: Path | str | None = None) -> str | None:
    """The memory dir owning trail key `key`, or `None` when it is unregistered.

    `None` — not the key itself — because the callers need to distinguish
    "registered, resolves here" from "unknown to the registry". `_trail_scope`
    relies on that: it may only merge two repository roots when the registry
    *declares* both their keys for one dir, never because two unrelated clones
    happen to share a basename.
    """
    return alias_map(path).get(str(key or "")) or None
