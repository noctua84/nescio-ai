# Nescio design system

The visual identity for `nescio-ai.org` and everything that carries the Nescio
mark. This is the source of truth: the site config, the logo files, and the
diagrams all derive from what is written here.

**Status:** in build. Waves 0-2 shipped — the deploy pipeline is live at
`docs.nescio-ai.org` and the `brand/` package is in-tree and reproducible.
Wave 3 (the site itself) is next; wave 5 (IBM Plex) is off the critical path.
**Brand kit:** in this repo under `brand/`, off `FRAMEWORK_PATHS` by design
(§8). The Drive originals are a dated read-only archive.

---

## 1. Foundation

**Name.** *Nescio* — Latin, "I do not know." The Socratic starting point.

**Mark.** A geometric owl. `noctua` (the owner's handle) is Latin for owl; the
owl of Athena/Minerva is the classical emblem of wisdom. The mark is flat,
symmetrical, and built from five primitives — one body path, two eye rings, two
pupils, one diamond beak. No gradients, no strokes, no detail that dies below
24px.

**Voice.** Terse. Lead with the answer. Say "I don't know" rather than guess.
No exclamation marks, no emoji as section markers, no marketing verbs. The
project's thesis is epistemic humility, so the copy must never oversell — a page
that promises more than the tool delivers contradicts the product.

**Register.** Dark, geometric, monospace-forward. Modern developer tool, *not*
classical revival. There is no parchment, no serif display face, no Greek
column motif. The philosophy lives in the words and the agent names, not the
decoration.

---

## 2. Colour

### Canonical tokens

| Token | Hex | Role |
|---|---|---|
| `ink-deep` | `#0e1319` | Dark page ground |
| `ink-raised` | `#141b24` | Header, cards, raised surfaces on dark |
| `brand-blue` | `#2f4d7a` | Primary. Light-mode accent and links |
| `periwinkle` | `#8fb0d9` | Dark-mode accent and links |
| `tint` | `#eef2f8` | Highlighted cards, admonition fills (light) |
| `tint-dark` | `#182333` | Same role on dark |
| `text` | `#16191f` | Headings on light |
| `text-dark` | `#e9edf2` | Headings and labels on dark |
| `body` | `#5a616b` | Running text on light |
| `muted` | `#6b727c` | Captions and labels on light — **see the AA note** |
| `muted-dark` | `#8d97a4` | Captions and labels on dark |
| `border` | `#c9cfd8` | Card outlines, rules (light) |
| `border-dark` | `#26313f` | Same role on dark |
| `deferred` | `#a8b0ba` | *Planned, not shipped* — see §7 |

### Two defects in the existing assets

**a) Palette drift.** The brand kit and the diagrams were built from two
independent palettes that have diverged:

| Role | `make_brand.py` | Diagrams | Size sheet | Canonical |
|---|---|---|---|---|
| Near-black | `#111418` | `#16191f` | `#111418` | **`#16191f`** |
| Muted grey | `#8d97a4` | `#8a919b` | `#6b727c` | **`#6b727c`** light / **`#8d97a4`** dark |
| Raised dark | `#141b24` | — | — | **`#141b24`** |

Three near-identical greys and two near-blacks doing the same job. They must
collapse to one set, defined once, imported by every generator.

**b) The diagram captions fail WCAG AA.** `#8a919b` on white measures
**3.2:1** — below the 4.5:1 required for normal-size text. It is currently
carrying the section labels (`TRIAGE & DISCOVERY`), the connector labels
(`delegate`, `session ends`, `you curate, deliberately`), and the deferred
annotations in both diagrams. All of that is small text.

`#6b727c` — already used for the size-sheet captions — measures **4.9:1** and
passes. That is why it wins as canonical `muted`.

This is a real bug in shipped assets, not a preference. It gets fixed when the
diagrams are regenerated.

### The accent rule — non-negotiable

**Periwinkle carries dark mode. Brand blue carries light mode.** Neither
crosses over for text or links.

| Pair | Ratio | Verdict |
|---|---|---|
| `#8fb0d9` on `#0e1319` | 8.3:1 | Passes AAA |
| `#8fb0d9` on `#ffffff` | **2.2:1** | **Fails AA — never use** |
| `#2f4d7a` on `#ffffff` | 8.5:1 | Passes AAA |
| `#5a616b` on `#ffffff` | 6.3:1 | Passes AA |
| `#6b727c` on `#ffffff` | 4.9:1 | Passes AA |
| `#8a919b` on `#ffffff` | **3.2:1** | **Fails AA — retired** |
| `#8d97a4` on `#0e1319` | 6.3:1 | Passes AA |

Periwinkle on a light ground is the easiest way to break this system. It is
permitted as a **fill or border only**, never as text or a link.

> Ratios are computed from WCAG 2.1 relative luminance, not estimated. Re-verify
> with a contrast checker before launch anyway — arithmetic deserves a second
> opinion.

### Scheme default

**Dark by default.** The brand is dark-first and owls are nocturnal. A light
scheme ships alongside; the toggle persists the reader's choice.

---

## 3. Typography

### The pairing

**IBM Plex Sans** (body, UI) + **IBM Plex Mono** (code, labels, agent names).

- **One superfamily.** Plex Sans and Plex Mono share skeletons and metrics, so
  mono agent names sit beside sans body text as siblings. The current pairing —
  Liberation Mono + Carlito — comes from two unrelated families and reads that
  way.
- **Character without trend.** A distinctive `a`, a faint slab on the mono.
  Avoids Inter and Space Grotesk, which now read as defaults.
- **Open licence (OFL), self-hostable.** Ships as `woff2` in the repo. No CDN,
  no third-party request at runtime.

Alternate if Plex is rejected: **Source Sans 3 + Source Code Pro**.

Self-host and subset both faces. Do not link a font CDN.

### What ships today

The Plex migration has not run. The site launches on the interim pairing —
**Carlito** (sans) + **Liberation Mono** (mono) — self-hosted and subset to a
Latin range, four `woff2` files in `brand/fonts/`. The one hard rule is already
kept: no CDN, no third-party font request at runtime.

**The shipped faces are called `Nescio Sans` and `Nescio Mono`.** That is not a
branding flourish and it must not be "corrected" back to the upstream names.
Both upstream families carry a Reserved Font Name (`Carlito`, `Liberation`), and
SIL OFL clause 3 forbids an RFN on a Modified Version. A Latin-only subset *is*
a modification — OFL-FAQ 2.6 says so, and 2.7-2.8 let a modified webfont keep
the RFN only while it stays *Functionally Equivalent*, which requires the same
full character inventory. A subset does not have it. So the subsets are renamed
and the upstream copyright, licence and provenance records are left intact in
the `name` table. The full reasoning and the exact `name` IDs touched are in
[`brand/fonts/README.md`](../../brand/fonts/README.md).

Three things have to agree on those names, and there is a test for it:

| Where | What it says |
|---|---|
| the `woff2` `name` tables | `Nescio Sans`, `Nescio Mono` |
| the site's `@font-face` rules | the same two families |
| `brand/palette.py` — `FONT_SANS` / `FONT_MONO` | the same two, named **first**, upstream names as fallbacks |

The third is the one that bites. Every generated SVG takes its `font-family`
from those two constants; if they name something the `@font-face` rules do not
declare, nothing errors — the diagrams just render in a system fallback with the
suite green. `brand/test_fonts.py` ties the palette to the build recipe so the
two cannot drift apart. (The stacks quote family names with **single** quotes:
they land inside SVG `font-family="..."` attributes, where a double quote would
close the attribute.)

When the Plex migration lands it reruns the same subset recipe against the Plex
sources, under the same OFL logic, and retunes the `wrap()` widths in
`make_diagrams.py` — Plex Sans is wider than Carlito at the same size.

### Roles

| Role | Face | Weight | Notes |
|---|---|---|---|
| Wordmark | *outlined paths* | — | Not live text — see below |
| Page headings | Plex Sans | 700 | `text-wrap: balance` |
| Running text | Plex Sans | 400 | Max ~68ch measure |
| Agent / skill names | Plex Mono | 700 | Always mono — they are identifiers |
| Code blocks | Plex Mono | 400 | |
| Eyebrows, labels | Plex Sans | 700 | Uppercase, `letter-spacing: .12em` |
| Captions | Plex Sans | 400 | `muted` |

**Rule:** anything that is a literal identifier in the system — an agent name, a
command, a filename, a token — is set in mono. Prose is sans. Semantic, not
decorative; readers learn it in one page.

The roles are face-agnostic. Until the Plex migration runs, `Nescio Sans` fills
every Plex Sans row and `Nescio Mono` every Plex Mono row; nothing else about
the table changes.

### The wordmark is outlined — done

`make_brand.py` originally set the wordmark as **live text in
`'Liberation Mono'`**. Almost nothing on the open web has that font installed,
including the servers that render link previews, so the wordmark was at risk of
rendering in an arbitrary fallback anywhere outside a Linux desktop.

It is now emitted as **outlined `<path>` data**, generated from
`brand/fonts/LiberationMono-Bold.ttf` — Bold, because both wordmark call sites
set `weight="700"` and outlining from Regular would have silently thinned it.
The outlines render identically everywhere and are immune to the pairing
decision above; the Plex migration re-runs the outliner against Plex Mono by
changing one constant, `WORDMARK_SOURCE`.

---

## 4. The mark

### Files

| File | Use |
|---|---|
| `nescio-logo-mark.svg` | Bare owl, brand blue on transparent. Default. |
| `nescio-logo-badge.svg` | Rounded tile, white owl on brand blue. Avatars. |
| `nescio-github-social.svg` | 1280×640 OG card. Doubles as the social preview. |
| `nescio-medium-cover.svg` | 1500×750 article cover. |
| `nescio-logo-sizes.svg` | Legibility contact sheet, 128→16px. |

### Colour pairings

The owl is always **two colours**: a body fill and a cutout colour matching the
ground behind it.

| Ground | Body | Cutouts |
|---|---|---|
| `ink-deep` / `ink-raised` | `periwinkle` | the ground colour |
| White / light | `brand-blue` | `#ffffff` |
| `brand-blue` (badge) | `#ffffff` | `brand-blue` |

Cutouts are not white by definition — they are *the ground*. Getting this wrong
produces a halo.

### Constraints

- **Minimum size: 24px**, verified by the contact sheet. Below that the beak and
  pupils merge.
- **Clear space:** one eye-diameter on all sides.
- Never rotate, skew, recolour outside the pairings above, add strokes or
  shadows, or place the transparent mark on a mid-tone ground.

### Favicons — complete

The favicon set is built and documented (`favicons/README.md`). It ships
`favicon.svg`, `favicon.ico`, PNGs at 16/32/48/192/512, and a 180px
`apple-touch-icon.png`, with a `<head>` snippet and a `site.webmanifest`.

Three decisions in that README are part of this system and are restated here so
they survive:

- **Tile, not bare mark.** Tab chrome can be light or dark; a dark-blue
  silhouette on transparency vanishes against dark chrome. The tile carries its
  own ground and reads either way.
- **Apple touch icon has square corners.** iOS applies its own rounded mask —
  a pre-rounded source double-rounds.
- **No simplified 16px variant.** One was tried and was indistinguishable from
  the standard geometry. Not worth maintaining a second shape.

Manifest colours — `theme_color: #2f4d7a`, `background_color: #0e1319` — match
the canonical tokens. No change needed.

---

## 5. Layout

**Homepage hero.** Dark. Owl and wordmark locked up horizontally, descriptor
beneath, then the 86×3px periwinkle rule, then the claim, then **the install
commands**, then the buttons.

The install block sits above the buttons deliberately. The pitch is "no
fabrication, no ceremony" — a hero that hides two shell commands behind a click
contradicts it.

**Docs pages.** Three columns: left nav, article, right table of contents.
Article measure capped at ~68ch.

**Spacing.** Lay out sibling groups with flex/grid `gap`, never per-element
margins. Wide content — tables, code, diagrams — gets its own
`overflow-x: auto` container so the page body never scrolls sideways.

---

## 6. Diagrams

Diagrams are first-class content here, not illustration. They carry the
architecture explanation.

### Diagram tokens

| Element | Light | Dark |
|---|---|---|
| Ground | *none — page supplies* | *none — page supplies* |
| Emphasised node fill | `#eef2f8` | `#182333` |
| Emphasised node stroke + label | `#2f4d7a` | `#8fb0d9` |
| Plain node fill | `#ffffff` | `#141b24` |
| Plain node stroke | `#c9cfd8` | `#26313f` |
| Plain node label | `#16191f` | `#e9edf2` |
| Body text | `#5a616b` | `#a8b0ba` |
| Caption / connector label | `#6b727c` | `#8d97a4` |
| Connector | `#c9cfd8` | `#26313f` |
| Accent connector | `#2f4d7a` | `#8fb0d9` |
| Deferred (dashed) | `#a8b0ba` | `#a8b0ba` |

### The pipeline

**One tokenised source per diagram → inlined into docs pages → two static files
generated for everything else.**

- The **source** SVG carries no hardcoded colours and **no background `<rect>`**.
  Every fill and stroke is a CSS custom property.
- The **docs site** inlines that SVG so the page's own tokens reach it. The
  diagram follows the scheme toggle live, from one source of truth.
- A **build step** renders the source into `*-light.svg` / `*-dark.svg` for
  contexts that cannot supply CSS variables — the README on GitHub, link
  previews, anything consuming a bare `<img>`. GitHub swaps them via
  `<picture>` + `prefers-color-scheme`.

Generating the pair rather than hand-maintaining it is what stops them drifting.

**Confirmed.** One tokenised source, inlined on the site, twins generated for
GitHub.

### Authoring rules

- No background `<rect>`. The page supplies the ground.
- No hardcoded fills — use the token variables.
- **Retune the wrap width after the font change.** `make_diagrams.py` wraps by
  *character count* (`wrap(s, width)`), not measured advance width. Plex Sans is
  wider than Carlito at the same size, so each call's `width` needs lowering and
  the result eyeballed against its box. A parameter sweep, not hand-positioning.
- Name the new faces explicitly in `font-family`, keeping a generic fallback.

---

## 7. Conventions

### Planned, not shipped

Anything on the roadmap but not built is drawn **dashed, in `#a8b0ba`**, and
labelled with what it waits on.

The convention already exists — the loop diagram uses it for
`readiness.md → autonomy dial` — it was simply never named. It is now
site-wide. Readers learn it once and never mistake a roadmap item for a
feature, which matters more than usual for a project whose whole pitch is not
overclaiming.

### Tagline placement

| Position | Line |
|---|---|
| Under the mark | `nescio` — *"I do not know."* |
| Footer | *The owl of Minerva flies at dusk.* |
| 404 | The Minerva line, extended |

The Minerva line — Hegel, *Philosophy of Right*: understanding arrives only
after the fact — is the best sentence available and the worst tagline. A
tagline must make a stranger understand the project in two seconds; one
requiring a Hegel reference fails that on purpose. In the footer and the 404 it
becomes a reward for people already paying attention rather than a toll on
everyone else.

**404 copy:**

> **nescio.**
> I do not know where this page is. The owl of Minerva flies at dusk; this one
> appears to have flown off entirely.

---

## 8. The generator toolchain

**The brand is code, not files.** This is the most consequential thing about the
existing kit and it shapes every task below.

| Script | Produces | State |
|---|---|---|
| `make_brand.py` | mark, badge, social, Medium cover, size sheet | Present |
| `make_diagrams.py` | both diagram SVGs | Present |
| `make_favicons.py` | the whole favicon set | Present |
| `render_diagrams.py` | 2× PNGs from the diagram SVGs | Present (rasteriser) |
| `make_carousel.py` | LinkedIn carousel PDF | Present — out of scope |

**Every asset is reproducible.** Nothing in the kit is a hand-edited file.

### The drift, and how it was resolved

*Retrospective — this describes the kit as it stood before it moved into the
repo. All of it is fixed.* The drift in §2 was a three-line problem, not an
audit: each generator declared its own palette constants at the top of the file.

| Script | Declared |
|---|---|
| `make_brand.py` | `INK #111418`, `ACCENT`, `ACCENT_LIGHT`, `PAPER`, `DARK`, `MUTED_D` |
| `make_diagrams.py` | `INK #16191f`, `INK2`, `MUTED #8a919b`, `ACCENT`, `ACCENT_FILL`, `LINE`, `FUTURE`, `SURFACE` |
| `make_favicons.py` | `ACCENT`, `PAPER` |

Collapsing those into one imported module fixed the drift permanently, and the
WCAG failure in §2 was a **single line**: `MUTED = "#8a919b"` became `"#6b727c"`.
Both retired hexes — `#8a919b` and `#111418` — are now barred outright by
`brand/test_palette.py`, so neither can return.

The scripts were also **sandbox artefacts**: they wrote to `/home/claude/`, and
`render_diagrams.py` and `make_favicons.py` hardcoded a Chromium path under
`/opt/pw-browsers/`. Both were fixed when the kit came into the repo.

### Current state

Every generator imports `brand/palette.py`; no script declares a colour of its
own, and none names a font stack of its own — `FONT_SANS` / `FONT_MONO` come
from the same module (§3).

**Paths are portable.** Output resolves in this order, highest precedence first:

1. `--out DIR`
2. `$BRAND_OUT`
3. `brand/dist/` — resolved relative to the *script file*, not the current
   working directory

Where a headless Chromium is needed it is located via `$CHROME`. No absolute
path is hardcoded anywhere in the package.

**What runs in CI and what does not.** `make_brand.py` and `make_diagrams.py`
are pure string generation, stdlib only — they run anywhere, and the suite runs
them. `make_favicons.py` and `render_diagrams.py` are rasterisers: they need
Pillow and a local Chromium, so they are deliberately **not** run in CI, and
`brand/test_rasterisers.py` reads their *source* rather than importing them —
enough to prove they still take every colour from `palette.py` and declare none
of their own. The favicon set is generated locally and committed to
`brand/favicons/`, which is checked as an artefact; the 2× diagram PNGs are
rendered on demand into the gitignored `brand/dist/` and are not committed.

**Direction — delivered:** one `brand/` package in this repo, a single
`palette.py` every generator imports, portable paths, and `make_diagrams.py`
extended to emit tokenised SVGs plus the generated light/dark twins (§6).

---

## 9. Implementation notes

Target: **MkDocs Material**, deployed to GitHub Pages via GitHub Actions, custom
domain **`docs.nescio-ai.org`**. The apex is reserved for a future landing page.

### DNS

A subdomain avoids the apex entirely — no `A` records, no hardcoded GitHub IPs
to go stale:

```
docs.nescio-ai.org.   CNAME   noctua84.github.io.
```

**No `CNAME` file is needed.** GitHub only writes one when publishing from a
branch; for an Actions workflow the domain lives in repo settings instead —
"If you are publishing from a custom GitHub Actions workflow, no `CNAME` file is
created." ([docs](https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site/managing-a-custom-domain-for-your-github-pages-site))
The DNS record with the registrar is still required.

"Enforce HTTPS" becomes selectable once the certificate provisions — **up to 24
hours** after the domain is saved.

**Verify the domain** at account level (Settings → Pages → Add a domain). It
adds a TXT record that blocks other GitHub users from claiming the domain, and
"when you verify a domain, any immediate subdomains are also included" — so
verifying the apex `nescio-ai.org` covers `docs.nescio-ai.org` too.
([docs](https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site/verifying-your-custom-domain-for-github-pages))
Keep the TXT record permanently.

### Coexisting sites

One Pages site per repo, each with its own custom domain. The planned layout:

| Site | Repo | Domain |
|---|---|---|
| Nescio docs | `nescio-ai` (project) | `docs.nescio-ai.org` |
| Nescio landing | a new repo (project) | `nescio-ai.org` apex |
| Personal portfolio | `noctua84.github.io` (user site) | its own, or none |

**The one rule that bites:** a custom domain on the *user site* is inherited by
every project site that has no domain of its own — "if you set a custom domain
for a user site or organization site, that same custom domain will be used for
all project sites owned by the same account."
([docs](https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site/about-custom-domains-and-github-pages))

This repo is immune, because an explicit domain overrides the inherited one.
Other project sites (e.g. `nestjs-demo`) are not.

Apex records, if the landing page needs them — `A`: `185.199.108.153`,
`185.199.109.153`, `185.199.110.153`, `185.199.111.153`; `AAAA`:
`2606:50c0:8000::153` through `8003::153`. Re-check at the time; these move.

### Theming Material — verified against the pinned 9.7.7

The custom-scheme approach stands: define `[data-md-color-scheme="nescio-dark"]`
and `[data-md-color-scheme="nescio-light"]` rather than fight the stock palette,
dark listed first, both carrying a toggle.

Everything this section used to say *about* those schemes was written from
memory and asked the implementer to "verify the variable names". They have now
been verified — by reading what `mkdocs-material==9.7.7` actually ships
(`material/templates/assets/stylesheets/{main,palette}.*.min.css` and
`material/templates/base.html`), the version pinned in
`.github/workflows/docs.yml`. The six names all exist. The advice around them was
wrong in four ways, each of which fails **silently**: the build stays green and
the page just looks wrong.

**1. Six variables is necessary and nowhere near sufficient.** In 9.7.7 the full
light token set is declared on `:root,[data-md-color-scheme=default]` in
*main*.css — 49 custom properties. The dark set is declared on
`[data-md-color-scheme=slate]` in *palette*.css, and on nothing else: palette.css
contains **no** `[data-md-color-scheme=default]` rule at all. Slate restates 41
of those 49 tokens and introduces none of its own.

A custom scheme name matches neither selector. It therefore inherits the `:root`
**light** defaults and does **not** inherit slate. A dark custom scheme that sets
only an accent and a background gets light code blocks, light kbd chrome, light
admonition fills and light-mode shadows on a dark page. It has to restate the
whole ramp slate restates — surface (`--md-default-bg-color` ×4), foreground
(`--md-default-fg-color` ×4), the sixteen `--md-code-*` values including every
`--md-code-hl-*` hue, `--md-typeset-{color,a-color,kbd-*,mark,table-*}`,
`--md-admonition-*`, `--md-footer-bg-color{,--dark}` and `--md-shadow-z1..z3` —
plus the eight tokens that live only on `:root` and are therefore *not* in slate
either: `--md-footer-fg-color{,--light,--lighter}`, `--md-hue`,
`--md-typeset-{del,ins}-color` and `--md-warning-{fg,bg}-color`.

**2. `--md-typeset-a-color` has no colour of its own.** main.css declares it as
`var(--md-primary-fg-color)`. Nescio's dark primary is the raised chrome
`#141b24` (§2 `ink-raised`), because that is what the header and nav rail are —
so every link on the site would render ink-on-ink and be effectively invisible.
It must be set explicitly to periwinkle in the dark scheme and to brand blue in
the light one. This is the single most easily missed line in the stylesheet.

**3. `palette.primary` and `palette.accent` must both be `custom`.** Any stock
value makes base.html stamp `data-md-color-primary="…"` /
`data-md-color-accent="…"` on `<body>` — the *same element* that carries
`data-md-color-scheme`. palette.css then matches it with, e.g.,
`[data-md-color-primary=indigo]{--md-primary-fg-color:#4051b5;…}`, and a second
rule redefining `--md-typeset-a-color`. Those are single attribute selectors,
specificity 0-1-0, identical to `[data-md-color-scheme=nescio-dark]`, on the same
element. Nothing decides the winner but stylesheet source order, which today
happens to favour us only because `extra_css` is emitted after `{% block styles %}`
in base.html. That is load order, not intent, and it is not something to stake the
identity on. `custom` matches no stock rule, so the contest never happens.

**4. `theme.font: false` also drops `--md-text-font` and `--md-code-font`.** The
`{% block fonts %}` it disables emits three things, not one: the
`fonts.gstatic.com` preconnect, the `fonts.googleapis.com` stylesheet **and** an
inline `<style>:root{--md-text-font:"…";--md-code-font:"…"}`. Material composes
those two into `--md-text-font-family` / `--md-code-font-family` with its own
generic fallbacks, so with `font: false` and nothing else the whole site silently
renders in the generic fallback. The stylesheet must set both — which is separate
from, and additional to, declaring the `@font-face` rules for the self-hosted
faces in `extra_css`.

> The general lesson, and the reason the pin is hard: none of these four produce
> an error. `mkdocs build --strict` catches broken links, not a periwinkle that
> has quietly reverted to the stock accent. A Material upgrade is a deliberate
> task with a visual re-check.

### Build & publish

- **The 404 page is a theme override, not a page.** GitHub Pages serves
  `/404.html` for any unmatched path, and that file comes from MkDocs' *static
  template* pass — `mkdocs.commands.build` iterates `config.theme.static_templates`,
  and Material 9.7.7 declares exactly one, `404.html`, in its `mkdocs_theme.yml`.
  A `docs/404.md` builds to `404/index.html`, which GitHub Pages never looks at,
  while `_site/404.html` keeps Material's stock *"404 - Not found"*. Put the §7
  copy in `overrides/404.html`.
- The `social` plugin is **not needed** — `nescio-github-social.svg` is already
  a 1280×640 OG card. Drops the Cairo/Pillow dependency from CI.
- Favicon wiring is already specified in `favicons/README.md`. Use it verbatim,
  including the `sizes="32x32"` on the ICO.
- Workflow needs `permissions: {contents: read, pages: write, id-token: write}`
  and a `github-pages` environment. Generate the workflow from GitHub's own
  starter template rather than pinning action versions from memory.
- Publish from a dedicated source directory. **Do not point Pages at `docs/`** —
  it holds internal specs, including this file. Publication is by explicit
  allowlist.
- Run `scripts/scrub_check.py` against the **generated output**, not just the
  source tree. A docs build is a new path for internal content to reach the
  public web.

### Distribution & brand isolation

Nescio is cloned and derived into private instances, so "does the brand leak
downstream?" is a real question. It does not — the isolation already exists in
code, and predates this work.

| Mechanism | Effect |
|---|---|
| `install.py` → `LINKS` | Symlinks only `memory`, `skills`, `agents`, `commands`, `hooks`. A `brand/` directory is never linked into `~/.claude` — functionally inert. |
| `sync_from_upstream.py` → `FRAMEWORK_PATHS` | Allowlist. `brand/`, `docs/`, `mkdocs.yml` and `.github/` are **not** on it, so they never propagate to a derived instance. |
| README's derivation model | "A derived instance starts from its own `initial` commit, not a fork of this one." |

So brand assets and site config live in this repo, and the allowlist is the
isolation boundary. **Do not add `brand/`, the site config, or `docs/` to
`FRAMEWORK_PATHS`** — that allowlist is load-bearing for this decision.

Two guards to add with the site:

- **Scope the deploy workflow to the canonical repo** —
  `if: github.repository == 'noctua84/nescio-ai'` — so a GitHub fork's Actions
  cannot publish a branded build. This is the only path by which a third party
  could stand up something that looks official.
- **Exclude `brand/` from initial instance derivation.** `FRAMEWORK_PATHS`
  governs *updates*; no script in the repo performs the *first* derivation, so
  it appears to be manual. Either script it against the same allowlist or
  document the exclusion.

**What would reverse this decision:** if `git fork` ever becomes the documented
primary distribution path. A fork inherits the whole tree, and the allowlists —
which govern `install` and `sync`, not `git` — stop applying. The README
currently says "if you fork Nescio and fill `memory/`" in one place while the
sync section says instances are *not* forks; that wording should be tightened,
since it is the exact ambiguity that raised the question.

### Decision log

| # | Decision | Rationale |
|---|---|---|
| 1 | Name gloss under the mark; Minerva line in footer + 404 | Clarity for strangers; reward for the converted |
| 2 | One tokenised diagram source, inlined; twins generated | Single source of truth; twins cannot drift |
| 3 | IBM Plex Sans + Mono, self-hosted; SVGs updated to match | One superfamily; open licence; avoids default faces |
| 4 | Dark by default, light via toggle | Brand is dark-first. Owls are nocturnal. |
| 5 | Wordmark converted to outlined paths | Removes the font dependency from the identity |
| 6 | `#a8b0ba` + dashed = planned, not shipped | Formalises a convention already in use |
| 7 | Canonical palette; `#8a919b` retired | Kills three-way drift and a live AA failure |
| 8 | Brand kit moves into the repo as a `brand/` package | Files drift; generators don't |
| 9 | Docs live at `docs.nescio-ai.org` | Subdomain CNAME beats apex A records; apex kept free |
| 10 | Brand and site stay in `nescio-ai` | `FRAMEWORK_PATHS` already isolates them; a split buys nothing |

---

## 10. Open items

- [x] **Move the brand kit into the repo** as a `brand/` package; portable paths.
- [x] **Normalise the palette** into one shared `palette.py` (§2, §8).
- [x] **Fix the AA failure** — one line in `make_diagrams.py`.
- [x] **Extend `make_diagrams.py`** to emit tokenised SVGs + generated twins (§6).
- [x] **Outline the wordmark** in `make_brand.py`.
- [ ] **Retune wrap widths** after the Plex swap.
- [ ] **Decide where the apex landing page lives** (§9).
- [x] **Guard the deploy workflow** against forks (`github.repository ==`).
- [ ] **Exclude `brand/` from initial instance derivation** — currently unscripted.
- [ ] **Tighten the README's fork/derive wording.**
- [x] **Re-verify contrast ratios** — `palette.contrast_ratio()` reproduces
      every §2 value independently; asserted in `brand/test_palette.py`.
- [x] **Confirm Material CSS variable names** against the pinned version — done
      against `mkdocs-material==9.7.7`. All six exist; the surrounding advice did
      not survive contact and §9 has been rewritten around what the shipped
      `main`/`palette` stylesheets and `base.html` actually do.

### Closed

- [x] Legibility contact sheet as SVG — `nescio-logo-sizes.svg`.
- [x] Favicon set — complete and documented.
- [x] Diagram pipeline confirmed — one source, inlined, twins generated.
- [x] Generator toolchain complete — `make_diagrams.py` and `make_favicons.py` located.
- [x] Domain settled — `docs.nescio-ai.org`, apex reserved.
