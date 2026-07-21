# Memory conventions

Rules every promoted memory note obeys. The learning loop enforces them so a
synced note carries its own provenance and contradictions resolve deterministically.

## Provenance tag

Every promoted note ends with exactly one provenance line:

    [Source: user override | empirical | agent inference — YYYY-MM-DD]

- **user override** — a durable preference or correction the user stated directly.
- **empirical** — learned from an observed outcome (a CI run, a failing test, a
  reviewer reaction) rather than asserted.
- **agent inference** — the agent's own generalisation; the weakest source.

The date is when the learning was captured, in `YYYY-MM-DD` form.

## Contradiction resolution

When a new learning targets a note that already exists, the higher-priority
source wins. Ties break toward the **more recent date**:

    user override  >  empirical  >  agent inference

A new learning overwrites the existing note only if it is *strictly* higher
priority, or *equal* priority with a newer date — otherwise it is skipped and the
decision is logged. This is the resolution rule the brain lacked: without it, an
`agent inference` could silently clobber a `user override`.

## Manifest schema

A nomination is a JSON object with a fixed, canonical field set — the same one
documented in `commands/harvest-memory.md` and the `promote_learnings.py`
docstring:

- `scope` — mirrors the top-level `memory/` bucket the note lands in:
  `repo/<name>` | `projects/<name>` | `context` | `feedback` | `people` |
  `glossary`. Its bucket (the part before any `/`) is validated.
- `target` — the note's real path under `memory/`, e.g. `repo/myrepo/foo.md` or
  `feedback/bar.md`. Must stay inside `memory/` (no absolute or `..` paths).
- `type` — the note's frontmatter type: `feedback` | `context` | `adr` | … —
  open-ended, checked only for presence.
- `name`, `description`, `body`, `source`, `date` — all required.

## Enforcement

`scripts/promote_learnings.py` is the only sanctioned way to write a promoted
note — it validates every required field and the `scope` bucket up front (a
malformed nomination fails cleanly with no partial writes), rejects targets that
escape `memory/`, applies the contradiction rule, stamps the provenance line, and
records the promotion in the ledger `memory/learning-log.md` (keyed by a 12-hex
content hash of the note body, for dedup across machines).

## Store profiles

The knowledge-wiki engine serves two store profiles (`stores.json`):

- **operational** (D1, agent hot path, e.g. `memory/`) — notes carry the
  provenance tag and obey the contradiction precedence above. Layers:
  `concepts` + `references` only.
- **knowledge** (D2, personal vault, e.g. `vault/`) — source notes carry
  `author` / `url` / `confidence: high|medium|low`; concept notes carry
  `status: seed|developing|mature|evergreen`. Full layers
  (`sources`/`entities`/`concepts`/`domains`/…). Obsidian opt-in.

Both definitions live here so they evolve together (avoid profile drift).

## Concept notes & generalization

A `concepts/` note states one cross-cutting invariant generalized from ≥2 repos.
Frontmatter adds `seen_in: [<repo>, …]` and `corroboration: <N>`. When a repo
learning recurs in a second repo, the shared truth is lifted here and each repo
note becomes a thin pointer to it (`↑[[concept]]`) keeping only repo-specific
residue.

**Inversion, not merge.** If two repos assert opposing behaviour under the *same*
condition, do not merge — flag `> [!contradiction]` on the concept and keep both
repo notes. Corroboration strengthens a concept; inversion forks it into an open
question.
