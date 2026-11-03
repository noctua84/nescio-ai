# scripts/_wiki_common.py
"""Shared helpers for the knowledge-wiki engine (lint, index, and later ingest).

Stdlib-only. Parses the flat YAML frontmatter that promote_learnings.py writes
(`key: value` scalars and `key:\\n  - item` lists) without a YAML dependency,
emits scalars safely for it (`yaml_scalar`), and extracts [[wikilinks]].
Path-parameterized for tests.
"""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Iterator
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent

_WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]")


def extract_wikilinks(text: str) -> list[str]:
    """Target names of every [[link]] in order; alias part (after |) stripped."""
    return [m.group(1).strip() for m in _WIKILINK_RE.finditer(text)]


# --- scalar quoting: the writer (`yaml_scalar`) and reader (`_unquote_scalar`) ---
#
# They live side by side on purpose. promote_learnings writes frontmatter and
# this module reads it back without a YAML library, so the two halves are one
# contract: quoting on the write side alone would only turn "the file does not
# parse" into "the index shows stray quote characters". `_promoted_block`
# imports this module, and this module imports nothing from the scripts, so
# there is no cycle (a separate helper module would have bought nothing).

# Characters that cannot START a plain scalar (YAML indicators). Quoting on the
# first character is deliberately broader than YAML strictly requires for `-`,
# `?` and `:` (those are legal when followed by a non-space) — a needlessly
# quoted value is cosmetic, an unquoted broken one is the bug.
_PLAIN_FORBIDDEN_FIRST = frozenset("-?:,[]{}#&*!|>'\"%@`")

# Words YAML 1.1 (PyYAML's dialect) retypes to bool/null, in any case. `y`/`n`
# are included though PyYAML keeps them as strings: other 1.1 parsers do not.
_RETYPED_WORDS = frozenset(
    {"yes", "no", "true", "false", "on", "off", "y", "n", "null", "~", "=", "<<"}
)

# Anything number-shaped (int, float, 0x/0o/0b, `1_000`, sexagesimal `1:30`,
# `.inf`/`.nan`) or date-shaped (`2026-07-12`, which PyYAML loads as a date).
# Deliberately a superset of what actually retypes.
_NUMBERISH_RE = re.compile(
    r"[-+]?(?:\.(?:inf|nan)|0[xXoObB][0-9a-fA-F_]+|[0-9.][0-9_.:,eE+-]*)",
    re.IGNORECASE,
)
_DATEISH_RE = re.compile(r"\d{4}-\d{1,2}-\d{1,2}")

_ESCAPES = {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\r": "\\r", "\t": "\\t"}
_UNESCAPES = {"\\": "\\", '"': '"', "n": "\n", "r": "\r", "t": "\t"}
_ESCAPE_RE = re.compile(r'\\(["\\nrt]|x[0-9a-fA-F]{2}|u[0-9a-fA-F]{4}|U[0-9a-fA-F]{8})')


def _needs_quoting(s: str) -> bool:
    if not s or s != s.strip() or not s.isprintable():
        return True
    if s[0] in _PLAIN_FORBIDDEN_FIRST:
        return True
    if ": " in s or s.endswith(":") or " #" in s:
        return True
    if s.lower() in _RETYPED_WORDS:
        return True
    return bool(_NUMBERISH_RE.fullmatch(s) or _DATEISH_RE.match(s))


def _escape_char(ch: str) -> str:
    if ch in _ESCAPES:
        return _ESCAPES[ch]
    if ch.isprintable():
        return ch
    cp = ord(ch)
    if cp < 0x100:
        return f"\\x{cp:02x}"
    return f"\\u{cp:04x}" if cp < 0x10000 else f"\\U{cp:08x}"


def yaml_scalar(value: object) -> str:
    """``value`` as a YAML scalar: plain where safe, double-quoted where not.

    Plain output is the value verbatim, so ordinary names and descriptions stay
    readable. The quoted form escapes `\\`, `"` and control characters; it is
    what `split_frontmatter` reads back to the exact original string.
    """
    s = str(value)
    if not _needs_quoting(s):
        return s
    return '"' + "".join(_escape_char(c) for c in s) + '"'


def _unescape(m: re.Match) -> str:
    esc = m.group(1)
    return _UNESCAPES[esc] if esc in _UNESCAPES else chr(int(esc[1:], 16))


def _unquote_scalar(v: str) -> str:
    """Undo `yaml_scalar`'s quoting; a plain value comes back unchanged.

    Double-quoted: unescape `\\\\`, `\\"` (and the control-character escapes
    `yaml_scalar` emits). Single-quoted: `''` is a literal `'`. Only a value
    that both starts and ends with the same quote character is treated as
    quoted — anything else is the plain scalar it always was.
    """
    if len(v) >= 2 and v[0] == v[-1] == '"':
        return _ESCAPE_RE.sub(_unescape, v[1:-1])
    if len(v) >= 2 and v[0] == v[-1] == "'":
        return v[1:-1].replace("''", "'")
    return v


def split_frontmatter(text: str) -> tuple[dict[str, object], str]:
    """Split a note into (frontmatter dict, body).

    Supports flat scalars and simple `- ` lists. Quoted scalars (as written by
    `yaml_scalar`) are unquoted; plain ones are returned as-is. Returns
    ({}, text) when no frontmatter block opens at the start or it never closes.
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
            # An empty *plain* value opens a list; a quoted "" is a real string.
            fm[key] = _unquote_scalar(v) if v else []
    return fm, body


def iter_notes(
    dir_path: Path, *, recursive: bool = True
) -> Iterator[tuple[Path, dict[str, object], str]]:
    """Yield (path, frontmatter, body) for each note under dir_path.

    Skips MEMORY.md / index.md and anything inside a dot-directory (e.g.
    .obsidian). Sorted for deterministic output.
    """
    globber = dir_path.rglob("*.md") if recursive else dir_path.glob("*.md")
    for p in sorted(globber):
        rel_parts = p.relative_to(dir_path).parts
        if any(part.startswith(".") for part in rel_parts):
            continue
        if p.name in {"MEMORY.md", "index.md"}:
            continue
        text = p.read_text(encoding="utf-8")
        fm, body = split_frontmatter(text)
        yield p, fm, body


def load_stores(repo_dir: Path = REPO_DIR) -> dict[str, dict]:
    """Load stores.json (store name -> config); {} when absent.

    stores.example.json documents the schema; the real stores.json is
    machine-local (gitignored in a consuming repo).
    """
    cfg = repo_dir / "stores.json"
    if not cfg.exists():
        return {}
    data = json.loads(cfg.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "stores" in data:
        return data["stores"]
    return data if isinstance(data, dict) else {}


def resolve_dir(args: argparse.Namespace) -> Path | None:
    """Resolve the folder a CLI run targets: `--dir` wins, else `--store`'s path.

    Returns None when the store is absent from stores.json, or when its entry
    has no "path". Shared by wiki_index and wiki_lint.
    """
    if args.dir:
        return (REPO_DIR / args.dir).resolve()
    stores = load_stores()
    store = stores.get(args.store)
    if not store:
        return None
    path = store.get("path")
    return (REPO_DIR / path).resolve() if path else None
