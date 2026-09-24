---
name: publish-adrs
description: Publish the allowlisted, implemented ADRs from memory/repo/*/adr/ into a documentation repository as transformed copies, with a generated index. Use when an ADR graduates to accepted/as-built, when an ADR body changed, or when preparing a docs repo for outside readers. Triggers on "publish ADRs", "sync ADRs to the docs repo", "update the documentation ADRs".
user-invocable: true
---

# Publish ADRs

## Overview

`scripts/publish_adrs.py` copies only the ADRs listed in `adr-publish.toml`
into `<docs>/<adr_root>/<slug>/`, rewriting brain frontmatter and brain-only
links, regenerating `README.md`, copying `TEMPLATE.md`, and deleting copies
that fell off the allowlist. The brain stays the source of truth; the docs
repo is a curated projection. Files numbered ≥ `reserved_from` in the docs
repo belong to its own authors and are never touched.

## When an ADR changes status

1. Decide whether it is *implemented* — the code the decision describes is on
   `main` / in production, or it is superseded by completion. `proposed` never
   qualifies; "accepted but the mechanism is unbuilt" does not either.
2. Edit `[publish]` in `adr-publish.toml`: add the filename, or move it to a
   comment with the reason for exclusion.
3. Run the plan and read it before applying.

## Commands

```bash
python scripts/publish_adrs.py                          # dry run: plan + diffs
python scripts/publish_adrs.py --apply                  # write into the docs checkout
python scripts/publish_adrs.py --config other.toml      # another allowlist/target (default: ./adr-publish.toml)
```

The docs checkout comes from `$<target.path_env>` (named in the config) or
`--docs-path`. It must be clean; the script refuses otherwise. One config file
describes one target repository; use `--config` to switch between several.

## Read the plan before `--apply`

- Every `+ add` should be a file you consciously allowlisted.
- Every `- delete` should be a file you consciously removed from the
  allowlist. A surprise delete means a typo in `[publish]`, or a slug rename
  (the old folder's generated files are removed; files numbered ≥
  `reserved_from` are kept wherever they are).
- In diffs, `(not yet implemented — not published)` marks a link to an ADR
  that is not allowlisted; if the target *is* implemented, allowlist it
  instead of shipping the annotation.
- A `target collision` error means two brain dirs feeding one slug both hold
  the same filename — resolve it in the brain, not by renaming the copy.
- Unnumbered files in any folder under `adr_root` are deleted on sync; only
  numbers ≥ `reserved_from` are protected. If a `- delete` names a file
  someone authored, they need to number it.

## After `--apply`

Commit in the docs repository on its own branch/PR. Review the rendered
files as an outsider would: no dead links, no brain jargon.
