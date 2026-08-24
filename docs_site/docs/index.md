---
# This front matter MUST be the first bytes of the file — MkDocs only parses a
# YAML block that opens on line 1, and a page whose front matter is preceded by
# so much as a blank line silently keeps both rails.
#
# Why the homepage hides them: it is a landing page, and every destination it
# offers is already reachable in-page twice — the hero buttons link to Agents,
# Skills and Source, and "Where to go next" at the foot repeats all three. A
# navigation rail and a table of contents here duplicate links the reader can
# already see. What they cost is the whole width the two diagrams need: with
# both rails present the 1400px artwork slid underneath them (see nescio.css §3
# for the measurements). Single column, no rails, no collision.
#
# So this is load-bearing layout, not a cosmetic preference. Re-enable either
# rail and the diagrams go back to overlapping it. agents.md and skills.md keep
# both rails — they are reference pages with real headings to navigate.
hide:
  - navigation
  - toc
---

<!--
  The homepage. Two mechanisms are load-bearing here and neither is obvious:

  1. `<div class="nescio-hero" markdown>` — md_in_html. The `markdown`
     attribute makes Python-Markdown parse the children as block Markdown, so
     the install snippet below is a real fenced block: highlighted, and carrying
     Material's copy button (`content.code.copy`). Raw <div>/<h1>/<p> children
     without a `markdown` attribute of their own are passed through untouched,
     which is what keeps the lockup markup exactly as written.

  2. The two `diagram:` markers further down, each an HTML comment on its own
     line. docs_site/hooks/inline_svg.py splices the tokenised SVG in verbatim
     during `on_page_content`, wrapped in a div.nescio-diagram. Inlined, never
     an image element: that is the only way the page's --diagram-* custom
     properties reach the artwork so the scheme toggle repaints it live
     (design-system.md §6). Do not "simplify" them to Markdown images or to
     pymdownx.snippets — the hook's docstring records why snippets was measured
     and rejected.

     NOTE: an HTML comment cannot contain the two-character sequence that ends
     one, so this block deliberately never spells a marker out in full. Writing
     one here would terminate this comment early and dump the rest of it onto
     the page as prose.

  Hero order is deliberate and is spec §5: lockup, name-gloss, descriptor, the
  86x3px periwinkle rule, the claim, THEN the install commands, THEN the
  buttons. The install block sits above the buttons because the pitch is "no
  fabrication, no ceremony" — a hero that hides two shell commands behind a
  click contradicts it. Do not reorder.

  The owl is the bare mark from brand/dist/nescio-logo-mark.svg with the §4
  dark pairing applied: body periwinkle, cutouts the ground colour (#0e1319).
  Cutouts are not white by definition — they are the ground; white here would
  halo. It is inlined rather than linked so the page makes no request for it,
  and the hero is dark in both schemes (§5), so the two hexes are fixed rather
  than tokenised.

  The wordmark is live text in Nescio Mono 700, not the outlined paths that
  brand/make_brand.py emits. §3 outlines the wordmark because link-preview
  renderers and arbitrary machines do not have the face installed; this site
  self-hosts it, so the failure mode §3 guards against cannot occur here, and
  live text keeps the site name selectable, searchable and readable to a screen
  reader.
-->

<div class="nescio-hero" markdown>

<div class="nescio-hero__lockup">
  <svg class="nescio-hero__owl" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" role="img" aria-label="The Nescio owl">
    <path d="M 140 112 C 160 168 176 176 186 186 Q 256 152 326 186 C 336 176 352 168 372 112 C 394 172 402 262 380 314 C 350 384 306 408 256 408 C 206 408 162 384 132 314 C 110 262 118 172 140 112 Z" fill="#8fb0d9"/>
    <circle cx="202" cy="248" r="49" fill="#0e1319"/>
    <circle cx="202" cy="248" r="21" fill="#8fb0d9"/>
    <circle cx="310" cy="248" r="49" fill="#0e1319"/>
    <circle cx="310" cy="248" r="21" fill="#8fb0d9"/>
    <path d="M 256 296 L 274 318 L 256 340 L 238 318 Z" fill="#0e1319"/>
  </svg>
  <span class="nescio-hero__wordmark">nescio</span>
</div>

<p class="nescio-hero__gloss"><code>nescio</code> — <em>&ldquo;I do not know.&rdquo;</em></p>

<p class="nescio-hero__descriptor">An agent crew for Claude Code.</p>

<hr class="nescio-hero__rule">

<p class="nescio-hero__claim">It says &ldquo;I don't know&rdquo; when it does not know, and argues with itself before it argues with you.</p>

```bash
git clone https://github.com/noctua84/nescio-ai ~/dev/nescio
cd ~/dev/nescio && python install.py
```

<div class="nescio-hero__buttons" markdown>

[The crew](agents.md){ .md-button .md-button--primary }
[Skills](skills.md){ .md-button }
[Source](https://github.com/noctua84/nescio-ai){ .md-button }

</div>

</div>

## What it is

A portable, version-controlled configuration for
[Claude Code](https://claude.com/claude-code): a crew of specialised agents, a
memory that grows from finished work, and a learning loop. `install.py`
symlinks `agents/`, `skills/`, `memory/`, `commands/` and `hooks/` into
`~/.claude`, then asks how to handle `settings.json` and `CLAUDE.md`.

Two things it does that most agent setups do not:

- **Principled refusal.** *&ldquo;I don't know / no competent path&rdquo;* is a
  first-class output. The orchestrator will not relay a sub-answer it trusts
  less than its own read.
- **A built-in devil's advocate.** `critic` red-teams a plan *before* it is
  built, in one bounded pass, and is free to conclude that the plan holds.

## The crew

Ten agents, each with a narrow remit. Delegation goes one way — down — and
every result comes back through a routing quality gate rather than straight to
you. The full roster with descriptions is on [Agents](agents.md).

<!-- diagram: crew -->

## The learning loop

A `Stop` hook records what actually happened in a session, locally and
uncurated. `/harvest-memory` is what turns that trail into durable notes under
`memory/` — a step you run deliberately, not a background process. Nothing
reaches memory without you.

<!-- diagram: loop -->

## Where to go next

- [Agents](agents.md) — the roster, generated from `agents/*.md`.
- [Skills](skills.md) — the on-demand capabilities, generated from
  `skills/*/SKILL.md`.
- [The repository](https://github.com/noctua84/nescio-ai) — installation,
  derivation model, and the rest of the README.
