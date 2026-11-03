# Learning log

Append-only ledger of every learning promoted into `memory/` by
`scripts/promote_learnings.py`. One line per promotion:

    - <date> | <target> | <hash12> | promoted: <name>

The `hash12` is a 12-hex content hash of the *nomination body as submitted*,
taken before the frontmatter and provenance line are composed onto the note. It
is therefore not a checksum of the file on disk and cannot be recomputed from
anything in the repo — it exists to dedup identical re-nominations across
machines. See `memory/CONVENTIONS.md` for the provenance and contradiction rules
the promoter applies.

Written by the script, not by hand.

## Entries
- 2026-10-30 | repo/nescio/module-gate-verdict-belongs-in-the-pr-body-first.md | 17b3682b07ed | promoted: module-gate wants its verdict before the first CI run
- 2026-11-01 | repo/nescio/hooks-siblings-are-two-module-objects.md | f6b1e0e418be | promoted: a hooks sibling imported two ways is two module objects
- 2026-11-02 | repo/nescio/readiness-never-computes-for-this-repo.md | c98f4aea17fc | promoted: readiness is uncomputable here — memory/repo/nescio vs trail key nescio-ai
- 2026-11-01 | repo/nescio/a-harvest-is-curation-not-a-pipeline.md | 6aa50c4ced3a | promoted: the 2026-10-28 harvest produced nothing, and why
- 2026-11-02 | repo/nescio/squash-merge-defeats-ancestry-checks.md | d0d76287ac23 | promoted: after a squash merge, gh is the only merge authority
- 2026-11-01 | repo/nescio/pure-move-claims-need-content-proof.md | 423ba7011465 | promoted: a pure move is a claim an agent can make cheaply
