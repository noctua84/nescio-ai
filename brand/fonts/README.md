# `brand/fonts/` — the self-hosted web faces

Spec [§3](../../docs/design/design-system.md) has exactly one hard typography
rule: **no CDN, no third-party font request at runtime.** These four `woff2`
files are how that rule is kept. They ship in the repo, the site serves them
from its own origin, and nothing is fetched from Google Fonts or anywhere else.

These are the faces the site **launches** on — the current pairing. Spec §3
settles on IBM Plex as the *target* pairing; that migration is a separate,
later task, and it reruns this same recipe against Plex sources.

---

## What to reference from CSS

| `@font-face` file | Weight | Style | Cut from |
|---|---|---|---|
| `nescio-mono-400.woff2` | 400 | normal | Liberation Mono 2.1.5 Regular |
| `nescio-mono-700.woff2` | 700 | normal | Liberation Mono 2.1.5 Bold |
| `nescio-sans-400.woff2` | 400 | normal | Carlito 1.104 Regular |
| `nescio-sans-700.woff2` | 700 | normal | Carlito 1.104 Bold |

The CSS family name is yours to choose in the `@font-face` block — a browser
takes the family from the rule, not from the file's internal name table — but
these files carry the internal names **`Nescio Mono`** and **`Nescio Sans`**,
and the CSS should match. Use those, not `Liberation Mono` / `Carlito`. See
[Naming](#naming-why-these-are-not-called-liberation-mono-and-carlito) below;
this is a licence requirement, not a preference.

The generated SVGs have to agree. `brand/palette.py` names `Nescio Mono` /
`Nescio Sans` first in `FONT_MONO` / `FONT_SANS`, and every generator takes its
`font-family` from those two constants — if they drift from the `@font-face`
family names, nothing errors, the diagrams just render in a system fallback.
`brand/test_fonts.py` holds the two together.

```css
@font-face {
  font-family: "Nescio Mono";
  src: url("../fonts/nescio-mono-400.woff2") format("woff2");
  font-weight: 400;
  font-style: normal;
  font-display: swap;
}
```

No italics are shipped. Both families synthesise obliques acceptably, and the
site's mono is used for identifiers, which are never italic.

---

## Provenance

Both faces are SIL Open Font License 1.1. Both were downloaded from their
upstream project, pinned by SHA-256, and verified by reading the `name` table
of each file (the digests live in [`../subset_fonts.py`](../subset_fonts.py)
and are re-checked on every fetch).

**Liberation Mono 2.1.5** — Red Hat / [liberationfonts](https://github.com/liberationfonts/liberation-fonts),
from the `liberation-fonts-ttf-2.1.5.tar.gz` attached to the
[2.1.5 release](https://github.com/liberationfonts/liberation-fonts/releases/tag/2.1.5).
The shipped `.ttf`s report:

- `name 0` — *Digitized data copyright (c) 2010 Google Corporation. Copyright (c) 2012 Red Hat, Inc.*
- `name 8` — *Ascender Corporation*, `name 9` — *Steve Matteson* (the original designer)
- `name 13/14` — *Licensed under the SIL Open Font License, Version 1.1* / `http://scripts.sil.org/OFL`

**Carlito 1.104** — [googlefonts/carlito](https://github.com/googlefonts/carlito),
pinned to commit `3a810cab78ebd6e2e4eed42af9e8453c4f9b850a` (the project has no
release artefacts). The shipped `.ttf`s report:

- `name 0` — *Copyright 2013 The Carlito Project Authors (https://github.com/googlefonts/carlito), with Reserved Font Name "Carlito"*
- `name 8` — *tyPoland Lukasz Dziedzic*
- `name 13/14` — SIL Open Font License, Version 1.1

Licence texts are committed beside the fonts as `LiberationMono-LICENSE.txt`,
`LiberationMono-AUTHORS.txt` and `Carlito-LICENSE.txt`.

### The source `.ttf`s are committed on purpose

The subsets are not the only consumer. `make_brand.py` converts the "nescio"
wordmark from live text to SVG `<path>` outlines, and it takes those outlines
from **`LiberationMono-Bold.ttf` in this directory** (`WORDMARK_SOURCE` in that
script). The wordmark must not depend on a font happening to be installed on
whatever machine renders a link preview, so the glyph source is
version-controlled here rather than assumed to exist on the system. Do not
delete the `.ttf`s in favour of the `woff2`s.

**Bold, not Regular.** Both wordmark call sites in `make_brand.py` set
`weight="700"`, so the live text these outlines replaced rendered in Liberation
Mono *Bold*; outlining from Regular would have silently thinned the wordmark.
The two weights are metrically identical here — Liberation Mono is monospaced
and carries no kerning, so the six glyphs advance 7374/2048 em either way — and
only the stem weight differs, which is exactly what would have gone wrong
unnoticed.

---

## The subset

Each face is cut to a fixed Latin range. The range was chosen by scanning every
`.md` / `.html` / `.py` / `.yml` file in this repo for non-ASCII codepoints —
the survivors were `—  →  §  ·  …  ×  –  ≤  │  □  ≥  ←  ∈  ∅  ⇒  ↔` — and then
rounding out to whole Unicode blocks, so that adding a sibling character (a
different arrow, another dash) never silently loses its glyph.

| Block | Why |
|---|---|
| `U+0000-00FF` | Basic Latin + Latin-1 Supplement (`§ · × © ®`) |
| `U+0100-017F` | Latin Extended-A — accented names |
| `U+2000-206F` | General Punctuation (`– — ' ' " " … •`) |
| `U+20A0-20BF` | Currency Symbols (`€`) |
| `U+2100-214F` | Letterlike Symbols (`™ №`) |
| `U+2190-21FF` | Arrows (`→ ← ↔ ⇒`) |
| `U+2200-22FF` | Mathematical Operators (`≤ ≥`) |
| `U+2500-257F` | Box Drawing (`│ ─ └ ├`) — the ASCII diagrams in `docs/plans/` |
| `U+25A0-25FF` | Geometric Shapes (`□ ▪ ●`) |
| `U+2713-2714` | Check marks — *requested, but see below* |

### What the range asks for and what the fonts actually have

Requesting a range does not conjure glyphs. Verified against the built files,
both faces cover `— – → ← ↔ § · … × ≤ ≥ │ □ € ™ № •`, and neither upstream face
contains **`∈` `∅` `⇒` `✓` `✔`** at all. Those five appear once or twice each
in `docs/` and will render from a system fallback. That is a property of
Liberation Mono and Carlito, not of the subset — widening the range cannot fix
it, and the Plex migration should re-check it.

Emoji are **not** in the subset either. `✅ U+2705` appears in some docs and
falls through to the platform emoji font, which is what you want anyway.

### TrueType hinting is kept

Dropping hinting roughly halves every file — mono 30 KB → 16 KB, sans 46 KB →
27 KB. It is kept anyway: this site is mostly small mono text (code blocks,
agent names, commands), and unhinted stems blur under Windows/DirectWrite at
13px. ~150 KB of cached, same-origin font is a cheaper problem than unreadable
code. To reverse the call, add `--no-hinting` to the invocation in
`subset_fonts.py` and rebuild.

---

## Reproducing this directory

Everything here is regenerated by [`../subset_fonts.py`](../subset_fonts.py).
It needs `fonttools` and `brotli`, which are **local-only tooling** — they are
deliberately *not* repo dependencies, because the repo is stdlib-only and the
*output* is what ships. Build them in a throwaway venv:

```sh
uv venv /tmp/fontvenv
uv pip install --python /tmp/fontvenv/bin/python fonttools brotli

# fetch sources (SHA-256 pinned), subset, rename, verify
/tmp/fontvenv/bin/python brand/subset_fonts.py

# start from nothing — deletes brand/fonts/ except this README, re-downloads
/tmp/fontvenv/bin/python brand/subset_fonts.py --clean

# check what is committed without rebuilding it
/tmp/fontvenv/bin/python brand/subset_fonts.py --verify
```

### Eyeballing the result

`specimen.html` sits beside the fonts and sets all four faces at the sizes the
site actually uses — 16px body, 22px heading, 12.5px caption, 13px code — on
the dark ground, with the awkward pairs (`0O` `1lI` `rn/m` `cl/d` `5S` `2Z`)
and every non-ASCII character in the subset. It also prints a runtime report:
which faces loaded, whether the mono is really monospaced (equal advances mean
the file loaded rather than a fallback), and the count of **external requests,
which must be 0**.

Serve it — `@font-face` over `file://` is blocked in Chrome:

```sh
python -m http.server 8731 --directory brand/fonts
# then open http://127.0.0.1:8731/specimen.html
```

**The build is deterministic.** A `--clean` rebuild on the same `fonttools`
produces byte-identical `woff2` files (verified). `head.modified` is frozen via
`--no-recalc-timestamp` and `TTFont(..., recalcTimestamp=False)`; without that,
every rebuild would churn the binaries.

### The underlying `pyftsubset` invocation

The script shells out to `fontTools.subset` once per face. Verbatim, for
`nescio-mono-400.woff2`:

```sh
python -m fontTools.subset brand/fonts/LiberationMono-Regular.ttf \
  --output-file=brand/fonts/nescio-mono-400.woff2 \
  --flavor=woff2 \
  --unicodes=U+0000-00FF,U+0100-017F,U+2000-206F,U+20A0-20BF,U+2100-214F,U+2190-21FF,U+2200-22FF,U+2500-257F,U+25A0-25FF,U+2713-2714 \
  --layout-features=ccmp,locl,kern,liga,clig,calt,rlig,mark,mkmk \
  --name-IDs='*' \
  --name-legacy \
  --notdef-outline \
  --no-recalc-timestamp \
  --drop-tables+=DSIG
```

`--name-IDs='*'` is load-bearing: it keeps the copyright, licence and licence-URL
records in the file, which the OFL requires to travel with the binary. The
script then rewrites only the *naming* records (see below) and saves.

The other three faces use the same flags with the source/output swapped:

| Source | Output |
|---|---|
| `LiberationMono-Regular.ttf` | `nescio-mono-400.woff2` |
| `LiberationMono-Bold.ttf` | `nescio-mono-700.woff2` |
| `Carlito-Regular.ttf` | `nescio-sans-400.woff2` |
| `Carlito-Bold.ttf` | `nescio-sans-700.woff2` |

`FFTM NOT subset; don't know how to subset; dropped` on the Carlito runs is
expected — `FFTM` is a FontForge timestamp table with no business in a webfont.

### Built with

| | |
|---|---|
| Python | 3.14.3 |
| `fonttools` | 4.63.0 |
| `brotli` | 1.2.0 |

A different `fonttools` may compress differently. If you rebuild and the
binaries change size, that is the likely cause — not a corrupted source.

---

## Naming: why these are not called "Liberation Mono" and "Carlito"

Both upstream faces carry a **Reserved Font Name** — `Liberation` and
`Carlito`. Under SIL OFL clause 3, a Modified Version may not use an RFN.

Subsetting a webfont *is* modification: the SIL
[OFL-FAQ 2.6](https://openfontlicense.org/ofl-faq/) says so outright, and
2.7-2.8 allow a modified webfont to keep the RFN only when it stays
*Functionally Equivalent* to the original — which requires, first on the list,
that it "supports the same full character inventory". A Latin-only cut does
not. So the subsets are renamed:

| Upstream | Subset family |
|---|---|
| Liberation Mono | **Nescio Mono** |
| Carlito | **Nescio Sans** |

What the rename touches: `name` IDs 1, 2, 3, 4, 6, 10, 16, 17 — family,
subfamily, unique ID, full name, PostScript name, description, typographic
family/subfamily.

What it deliberately leaves alone: `name` 0 (copyright, including the upstream
RFN declaration), 5 (version), 7 (trademark), 8/9/11/12 (vendor, designer,
URLs), and 13/14 (licence and licence URL). Those are OFL obligations and
provenance, not a claim of identity — `name 3` and `name 10` in every subset
say plainly which upstream font it was cut from.

The **source `.ttf` files in this directory are untouched originals** and keep
their real names. Redistributing them verbatim with their licence text is
exactly what the OFL asks for.
