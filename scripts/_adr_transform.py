"""Pure text transforms for publishing brain ADRs into a documentation repo.

No I/O and no git here — everything takes strings and returns strings so it
can be tested without a checkout. The orchestration lives in publish_adrs.py.
"""
from __future__ import annotations

import posixpath
import re

STATUSES = ("proposed", "accepted", "as-built", "superseded")

NOT_PUBLISHED = " (not yet implemented — not published)"
BRAIN_NOTE = " (brain-internal note, not published)"
INTERNAL_PLAN = " (internal plan)"

_H1 = re.compile(r"^# (.+?)\s*$", re.MULTILINE)
_STATUS_BULLET = re.compile(r"^- \*\*Status:\*\*\s*(.+)$", re.MULTILINE)
_STATUS_HEADING = re.compile(r"^## Status\s*$\n+(.+)$", re.MULTILINE)
_WORD = re.compile(r"[A-Za-z][A-Za-z-]*")

_LINK = re.compile(r"(?<!!)\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_ADR_PATH = re.compile(r"^memory/repo/[^/]+/adr/[^/]+$")
_FENCE = re.compile(r"^```")


def normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def split_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Return (frontmatter, body). Frontmatter is a flat `key: value` map.

    Only a block that starts on line 1 with `---` and is closed by a later
    `---` line counts. Anything else is body. Values keep their raw text
    (no YAML parsing beyond the first colon) — the brain's frontmatter is
    flat scalars by convention.
    """
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}, text
    block = text[4:end]
    body = text[end + len("\n---\n"):]
    fm: dict[str, str] = {}
    for line in block.split("\n"):
        if ":" not in line or line.startswith((" ", "\t", "#")):
            continue
        key, _, value = line.partition(":")
        fm[key.strip()] = value.strip()
    return fm, body


def extract_title(body: str) -> str:
    m = _H1.search(body)
    return m.group(1).strip() if m else ""


def _status_word(raw: str) -> str:
    cleaned = raw.replace("*", "").replace("_", "").strip()
    m = _WORD.search(cleaned)
    if not m:
        return "unknown"
    word = m.group(0).lower()
    return word if word in STATUSES else "unknown"


def extract_status(frontmatter: dict[str, str], body: str) -> str:
    """Status from frontmatter, else the `## Status` heading's first
    paragraph, else the `- **Status:**` bullet; normalised to STATUSES or
    "unknown"."""
    if "status" in frontmatter:
        return _status_word(frontmatter["status"])
    m = _STATUS_HEADING.search(body)
    if m:
        return _status_word(m.group(1))
    m = _STATUS_BULLET.search(body)
    if m:
        return _status_word(m.group(1))
    return "unknown"


_PROVENANCE_LINE = re.compile(r"^\[Source: [^\]]*\]\n", re.MULTILINE)


def strip_provenance(body: str) -> str:
    """Drop whole-line `[Source: …]` provenance tags.

    Only the tag line goes, plus at most one adjacent blank line when removing
    the tag would otherwise leave two blank lines touching or a blank line at
    the very start or end. Nothing away from a removed tag is touched, so
    whitespace inside code fences and in tag-free bodies is preserved.
    """
    out = body
    while True:
        m = _PROVENANCE_LINE.search(out)
        if m is None:
            return out
        start, end = m.span()
        blank_before = start >= 2 and out[start - 2:start] == "\n\n"
        blank_after = out.startswith("\n", end)
        at_end = end == len(out)
        if blank_before and (blank_after or at_end):
            start -= 1
        elif start == 0 and blank_after:
            end += 1
        out = out[:start] + out[end:]


_SYNCED_AT = re.compile(r"^synced_at: .*\n", re.MULTILINE)


def _yaml_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def render_frontmatter(fields: list[tuple[str, str]]) -> str:
    lines = ["---"] + [f"{k}: {_yaml_quote(v)}" for k, v in fields] + ["---", ""]
    return "\n".join(lines)


def _resolve(source_rel: str, target: str) -> str:
    if target.startswith("memory/"):
        return posixpath.normpath(target)
    return posixpath.normpath(posixpath.join(posixpath.dirname(source_rel), target))


def _rewrite_one(m: re.Match, source_rel: str, target_rel: str,
                 published: dict[str, str]) -> str:
    text, target = m.group(1), m.group(2)
    if target.startswith(("http://", "https://", "mailto:", "#")):
        return m.group(0)
    path, hash_, frag = target.partition("#")
    if ".sisyphus/" in path:
        return text + INTERNAL_PLAN
    resolved = _resolve(source_rel, path)
    if resolved in published:
        rel = posixpath.relpath(published[resolved], posixpath.dirname(target_rel) or ".")
        return f"[{text}]({rel}{hash_}{frag})"
    if _ADR_PATH.match(resolved):
        return text + NOT_PUBLISHED
    return text + BRAIN_NOTE


def rewrite_links(body: str, source_rel: str, target_rel: str,
                  published: dict[str, str]) -> str:
    """Rewrite markdown links per the publishing rules; fenced code is skipped."""
    out: list[str] = []
    in_fence = False
    for line in body.split("\n"):
        if _FENCE.match(line):
            in_fence = not in_fence
            out.append(line)
            continue
        if in_fence:
            out.append(line)
            continue
        out.append(_LINK.sub(lambda m: _rewrite_one(m, source_rel, target_rel, published), line))
    return "\n".join(out)


def transform(text: str, *, source_rel: str, target_rel: str, github: str,
              synced_at: str, published: dict[str, str]) -> str:
    """Brain ADR text -> documentation-repo ADR text."""
    text = normalize_newlines(text)
    fm, body = split_frontmatter(text)
    body = strip_provenance(body)
    body = rewrite_links(body, source_rel, target_rel, published)
    fields = [
        ("title", extract_title(body)),
        ("status", extract_status(fm, body)),
        ("source_repo", github),
        ("synced_from", source_rel),
        ("synced_at", synced_at),
    ]
    if fm.get("description"):
        fields.append(("description", fm["description"]))
    return render_frontmatter(fields) + body


def strip_synced_at(text: str) -> str:
    """Remove the `synced_at:` line so two renders can be compared for
    real change (the date alone must not count as a change)."""
    return _SYNCED_AT.sub("", text, count=1)
