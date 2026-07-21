# scripts/_wiki_common.py
"""Shared helpers for the knowledge-wiki engine (lint, index, and later ingest).

Stdlib-only. Parses the flat YAML frontmatter that promote_learnings.py writes
(`key: value` scalars and `key:\\n  - item` lists) without a YAML dependency,
and extracts [[wikilinks]]. Path-parameterized for tests.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent

_WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]")


def extract_wikilinks(text: str) -> list[str]:
    """Target names of every [[link]] in order; alias part (after |) stripped."""
    return [m.group(1).strip() for m in _WIKILINK_RE.finditer(text)]


def split_frontmatter(text: str) -> tuple[dict[str, object], str]:
    """Split a note into (frontmatter dict, body).

    Supports flat scalars and simple `- ` lists. Returns ({}, text) when no
    frontmatter block opens at the start or it never closes.
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
