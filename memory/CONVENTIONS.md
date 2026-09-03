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
records the promotion in the ledger `memory/learning-log.md`. The ledger key is a
12-hex content hash of the *nomination's* `body` field as submitted — taken
before the frontmatter and the provenance line are composed onto the file, and
the staging directory it came from is gitignored and ephemeral. So the key is not
a checksum of the note on disk and cannot be recomputed from anything in the
repo; it exists to dedup identical re-nominations across machines.

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

## Folder indexes

A folder's `MEMORY.md` is **yours to write**. `scripts/wiki_index.py` owns only
the block between these two markers:

    <!-- memory-index:generated start -->
    <!-- memory-index:generated end -->

Everything between them is rewritten on every run; **everything outside them is
preserved byte-for-byte**. Put orientation prose, headings, hand-curated link
lists and anything else above or below the block and the generator will not
touch it. (Before issue #102 the script replaced the whole file, which destroyed
hand-written content unattended.)

**Adopting a marker-less file.** A `MEMORY.md` that predates the markers is
replaced by the block only when **every non-blank line in it is byte-identical
to a line this run would emit**. Anything else — a heading, a sentence, an
annotated bullet, a link into a subfolder — makes the file "not ours": the block
is *appended*, nothing is removed, and the run prints a `⚠` line saying so. The
test is line identity, not "does this look generated": a bullet like
`- [START HERE — read first](auth-model.md) — ask Markus first` has a generated
shape and a generated target, and only byte-identity notices the human's
annotation.

**Hand-curated ordering is not preserved in the adopt case.** The test is
order-insensitive set membership, so a file whose lines are all generated lines
but deliberately reordered *is* adopted, and comes back in generator order
(sorted by filename). This is the one thing adoption can lose, and only in a file
that contains nothing but generated lines. To pin an order, write the list
outside the markers — then it is preserved text, not a candidate for adoption.

**The block omits what the surrounding text already links.** Any note whose file
is already linked outside the markers is left out of the generated block, so
appending a block to a hand-maintained list never doubles it. The flip side: a
note mentioned in passing in prose stays out of the block. It is still linked, so
the index is not lying and `wiki_lint` still counts it as referenced.

**Malformed markers stop the run.** A begin without an end, an end without a
begin, reversed markers or duplicates make the block's extent unknowable. The
file is left untouched and the run exits 2 with a `⚠ malformed index markers:`
line — a human resolves it.
