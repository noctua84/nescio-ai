#!/usr/bin/env python3
"""Build the self-hosted web faces for the Nescio documentation site.

Spec §3's only hard typography rule is **no CDN, no third-party font request at
runtime**. This script turns the two openly-licensed faces the site launches on
— Liberation Mono (mono) and Carlito (sans) — into small, Latin-only `woff2`
files committed under ``brand/fonts/``.

**This is local-only tooling.** It needs ``fonttools`` and ``brotli``, which are
deliberately *not* repo dependencies — the repo stays stdlib-only. Build them in
a throwaway venv (see ``brand/fonts/README.md``); the *output* is committed, so
nobody needs this script to build or serve the site.

Two steps per face, both reproducible:

1. ``pyftsubset`` cuts the font to :data:`UNICODE_RANGES` and flavours it woff2.
2. The name table is rewritten so the subset does **not** claim the upstream
   Reserved Font Name. Both faces carry an RFN ("Liberation", "Carlito"), and a
   Latin-only subset is not Functionally Equivalent to the original under the
   SIL OFL-FAQ (2.6-2.8) because it drops character coverage. Copyright,
   licence and RFN-declaration metadata are preserved verbatim, as FE requires
   and OFL clause 2 requires regardless.

Usage::

    python brand/subset_fonts.py            # fetch if missing, build, verify
    python brand/subset_fonts.py --verify   # verify committed output only
    python brand/subset_fonts.py --force    # re-download sources, rebuild
"""

from __future__ import annotations

import argparse
import hashlib
import io
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request
from pathlib import Path

FONTS_DIR = Path(__file__).resolve().parent / "fonts"

# --------------------------------------------------------------------------
# Sources — pinned by URL *and* SHA-256. A changed digest is a hard failure.
# --------------------------------------------------------------------------

# Liberation 2.1.5 (Red Hat / liberationfonts), the ttf-only release tarball
# linked from https://github.com/liberationfonts/liberation-fonts/releases/tag/2.1.5
LIBERATION_TARBALL = (
    "https://github.com/liberationfonts/liberation-fonts/files/7261482/"
    "liberation-fonts-ttf-2.1.5.tar.gz"
)
LIBERATION_TARBALL_SHA256 = (
    "7191c669bf38899f73a2094ed00f7b800553364f90e2637010a69c0e268f25d0"
)
LIBERATION_MEMBERS = {
    "LiberationMono-Regular.ttf": (
        "liberation-fonts-ttf-2.1.5/LiberationMono-Regular.ttf",
        "f2b83c763e8afd21709333370bed4774337fae82267937e2b5aea7e2fbd922c1",
    ),
    "LiberationMono-Bold.ttf": (
        "liberation-fonts-ttf-2.1.5/LiberationMono-Bold.ttf",
        "bd62a0672d0b9b6710b01df434c80ad54fa5f0835207eb7b17b7a761463067bb",
    ),
    "LiberationMono-LICENSE.txt": (
        "liberation-fonts-ttf-2.1.5/LICENSE",
        "93fed46019c38bbe566b479d22148e2e8a1e85ada614accb0211c37b2c61c19b",
    ),
    "LiberationMono-AUTHORS.txt": (
        "liberation-fonts-ttf-2.1.5/AUTHORS",
        "b627404917ef824675cb24c32e2facd0b57650627955f3fc3d8a8863c5d0adfc",
    ),
}

# Carlito 1.104 (googlefonts/carlito) has no release artefacts; pin the commit.
CARLITO_COMMIT = "3a810cab78ebd6e2e4eed42af9e8453c4f9b850a"
CARLITO_RAW = f"https://raw.githubusercontent.com/googlefonts/carlito/{CARLITO_COMMIT}/"
CARLITO_FILES = {
    "Carlito-Regular.ttf": (
        "fonts/ttf/Carlito-Regular.ttf",
        "f6418f708baede9789daef5d458c0f53d2a888af9820e8062934e504fedc6595",
    ),
    "Carlito-Bold.ttf": (
        "fonts/ttf/Carlito-Bold.ttf",
        "bb5d20f79b82599ec72983597437373a80f2d2085fa91fc144fd74e876a594db",
    ),
    "Carlito-LICENSE.txt": (
        "OFL.txt",
        "58402f82a7c332a700294988fe7554fbb0a63a8d27ccc1ee3bbc640311990a00",
    ),
}

# --------------------------------------------------------------------------
# Subset definition
# --------------------------------------------------------------------------

#: Latin range the site needs. Derived from an actual scan of every ``.md`` /
#: ``.html`` / ``.py`` / ``.yml`` file in this repo for non-ASCII codepoints —
#: the survivors were — → § · … × – ≤ │ □ ≥ ← ∈ ∅ ⇒ ↔ — rounded out to whole
#: blocks so a new em-dash-adjacent character never silently loses its glyph.
#: Note that neither upstream face actually contains ∈ ∅ ⇒ ✓ ✔; those fall back
#: to a system font no matter what this list asks for. See fonts/README.md.
UNICODE_RANGES = (
    "U+0000-00FF",  # Basic Latin + Latin-1 Supplement (§ · × © ®)
    "U+0100-017F",  # Latin Extended-A (accented names)
    "U+2000-206F",  # General Punctuation (– — ' ' " " … • ‰ †)
    "U+20A0-20BF",  # Currency Symbols (€)
    "U+2100-214F",  # Letterlike Symbols (™ № ℹ)
    "U+2190-21FF",  # Arrows (→ ← ↔ ⇒)
    "U+2200-22FF",  # Mathematical Operators (≤ ≥ ∈ ∅ ∞)
    "U+2500-257F",  # Box Drawing (│ ─ └ ├) — ASCII diagrams in the plans
    "U+25A0-25FF",  # Geometric Shapes (□ ▪ ● ◆)
    "U+2713-2714",  # Check marks (✓ ✔)
)

#: OpenType features to keep. Everything else is dropped.
LAYOUT_FEATURES = "ccmp,locl,kern,liga,clig,calt,rlig,mark,mkmk"

#: (source ttf, output woff2, new family name, weight, upstream description)
FACES = (
    ("LiberationMono-Regular.ttf", "nescio-mono-400.woff2", "Nescio Mono", "Regular", 400),
    ("LiberationMono-Bold.ttf", "nescio-mono-700.woff2", "Nescio Mono", "Bold", 700),
    ("Carlito-Regular.ttf", "nescio-sans-400.woff2", "Nescio Sans", "Regular", 400),
    ("Carlito-Bold.ttf", "nescio-sans-700.woff2", "Nescio Sans", "Bold", 700),
)

#: Upstream family each subset descends from, for the unique-ID / description.
ORIGIN = {
    "LiberationMono-Regular.ttf": "Liberation Mono 2.1.5",
    "LiberationMono-Bold.ttf": "Liberation Mono 2.1.5",
    "Carlito-Regular.ttf": "Carlito 1.104",
    "Carlito-Bold.ttf": "Carlito 1.104",
}

SUBSET_NOTE = (
    "Latin-only subset built for the Nescio documentation site by "
    "brand/subset_fonts.py. Renamed because a subset drops character coverage "
    "and is therefore not a Functionally Equivalent version under the SIL "
    "OFL-FAQ (2.6-2.8), so it may not carry the upstream Reserved Font Name."
)


# --------------------------------------------------------------------------
# Fetch
# --------------------------------------------------------------------------


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _get(url: str, attempts: int = 4) -> bytes:
    """GET with a few retries — raw.githubusercontent resets connections."""
    req = urllib.request.Request(url, headers={"User-Agent": "nescio-subset-fonts"})
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:  # noqa: S310 - pinned https
                return resp.read()
        except OSError as exc:  # URLError subclasses OSError
            if attempt == attempts:
                raise
            print(f"    retry {attempt}/{attempts - 1} after {exc}")
            time.sleep(2 * attempt)
    raise AssertionError("unreachable")


def _write_checked(path: Path, data: bytes, expected: str) -> None:
    actual = _sha256(data)
    if actual != expected:
        raise SystemExit(
            f"SHA-256 mismatch for {path.name}\n  expected {expected}\n  got      {actual}"
        )
    path.write_bytes(data)
    print(f"  fetched {path.name:34} {len(data):>8,} B  sha256 ok")


def fetch(force: bool = False) -> None:
    """Download and verify the upstream sources into ``brand/fonts/``."""
    FONTS_DIR.mkdir(parents=True, exist_ok=True)
    wanted = list(LIBERATION_MEMBERS) + list(CARLITO_FILES)
    if not force and all((FONTS_DIR / name).exists() for name in wanted):
        print("sources present; skipping fetch (use --force to re-download)")
        return

    print(f"fetching {LIBERATION_TARBALL}")
    blob = _get(LIBERATION_TARBALL)
    if _sha256(blob) != LIBERATION_TARBALL_SHA256:
        raise SystemExit(
            "SHA-256 mismatch for liberation-fonts-ttf-2.1.5.tar.gz\n"
            f"  expected {LIBERATION_TARBALL_SHA256}\n  got      {_sha256(blob)}"
        )
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
        for out_name, (member, digest) in LIBERATION_MEMBERS.items():
            handle = tar.extractfile(member)
            if handle is None:
                raise SystemExit(f"missing tarball member: {member}")
            _write_checked(FONTS_DIR / out_name, handle.read(), digest)

    print(f"fetching googlefonts/carlito @ {CARLITO_COMMIT[:12]}")
    for out_name, (rel, digest) in CARLITO_FILES.items():
        _write_checked(FONTS_DIR / out_name, _get(CARLITO_RAW + rel), digest)


# --------------------------------------------------------------------------
# Build
# --------------------------------------------------------------------------


def _pyftsubset_argv(src: Path, dst: Path) -> list[str]:
    """The exact ``pyftsubset`` invocation. Mirrored in ``fonts/README.md``."""
    return [
        sys.executable,
        "-m",
        "fontTools.subset",
        str(src),
        f"--output-file={dst}",
        "--flavor=woff2",
        f"--unicodes={','.join(UNICODE_RANGES)}",
        f"--layout-features={LAYOUT_FEATURES}",
        "--name-IDs=*",
        "--name-legacy",
        "--notdef-outline",
        # Explicit even though it is the default: a clock in the output would
        # make the build non-reproducible.
        "--no-recalc-timestamp",
        # TrueType hinting is KEPT on purpose. Dropping it roughly halves each
        # file (mono 30K -> 16K, sans 45K -> 27K) but costs stem clarity for
        # small mono text under Windows/DirectWrite, which is exactly where
        # this site's code blocks and agent names live. 150 KB of cached font
        # is cheaper than unreadable 13px code. Add `--no-hinting` here to
        # reverse the call.
        "--drop-tables+=DSIG",
    ]


def _rename(path: Path, family: str, subfamily: str, origin: str) -> None:
    """Strip the upstream Reserved Font Name from a subset's name table.

    Copyright (0), licence (13) and licence URL (14) are left untouched: the
    OFL requires them to travel with the file, and the RFN *declaration* inside
    the copyright string is a statement about the original, not a claim by this
    subset.
    """
    from fontTools.ttLib import TTFont

    postscript = f"{family.replace(' ', '')}-{subfamily}"
    replacements = {
        1: family,
        2: subfamily,
        3: f"{family} {subfamily}; subset of {origin}",
        4: f"{family} {subfamily}",
        6: postscript,
        10: SUBSET_NOTE,
        16: family,
        17: subfamily,
    }
    # recalcTimestamp=False keeps head.modified frozen, so a rebuild from the
    # same sources with the same fonttools is byte-identical.
    font = TTFont(path, recalcTimestamp=False)
    name = font["name"]
    for rec in list(name.names):
        if rec.nameID in replacements:
            name.setName(
                replacements[rec.nameID],
                rec.nameID,
                rec.platformID,
                rec.platEncID,
                rec.langID,
            )
    # nameID 10 (description) may be absent upstream; add it so the provenance
    # note is always in the file.
    if not name.getDebugName(10):
        name.setName(SUBSET_NOTE, 10, 3, 1, 0x409)
    font.save(path)
    font.close()


def build() -> None:
    """Subset + rename every face. Overwrites the committed ``woff2``."""
    for src_name, out_name, family, subfamily, _weight in FACES:
        src = FONTS_DIR / src_name
        dst = FONTS_DIR / out_name
        if not src.exists():
            raise SystemExit(f"missing source: {src} (run without --verify to fetch)")
        argv = _pyftsubset_argv(src, dst)
        print(f"  subset  {src_name} -> {out_name}")
        subprocess.run(argv, check=True)
        _rename(dst, family, subfamily, ORIGIN[src_name])


# --------------------------------------------------------------------------
# Verify
# --------------------------------------------------------------------------


def verify() -> int:
    """Reload every committed woff2 with fontTools and report what is in it."""
    from fontTools.ttLib import TTFont

    failures = 0
    print(f"\n{'file':28} {'source':>10} {'subset':>9} {'saved':>7} {'glyphs':>7} {'chars':>6}  family")
    print("-" * 96)
    for src_name, out_name, family, subfamily, _weight in FACES:
        src = FONTS_DIR / src_name
        dst = FONTS_DIR / out_name
        if not dst.exists():
            print(f"{out_name:28} MISSING")
            failures += 1
            continue
        if dst.read_bytes()[:4] != b"wOF2":
            print(f"{out_name:28} NOT WOFF2 (bad signature)")
            failures += 1
            continue
        font = TTFont(dst)
        if font.flavor != "woff2":
            print(f"{out_name:28} flavor={font.flavor!r} (expected woff2)")
            failures += 1
        glyphs = font["maxp"].numGlyphs
        chars = len(font.getBestCmap())
        got_family = font["name"].getDebugName(1)
        s_size, d_size = src.stat().st_size, dst.stat().st_size
        saved = 100 - (d_size * 100 // s_size)
        print(
            f"{out_name:28} {s_size:>9,} {d_size:>8,} {saved:>6}% "
            f"{glyphs:>7,} {chars:>6,}  {got_family} {font['name'].getDebugName(2)}"
        )
        if got_family != family:
            print(f"    ! family is {got_family!r}, expected {family!r}")
            failures += 1
        if d_size >= s_size:
            print("    ! subset is not smaller than its source")
            failures += 1
        for probe in "Aa0→—§│":
            if ord(probe) not in font.getBestCmap():
                print(f"    ! missing expected codepoint U+{ord(probe):04X}")
                failures += 1
        font.close()

    for licence in ("LiberationMono-LICENSE.txt", "Carlito-LICENSE.txt"):
        if not (FONTS_DIR / licence).exists():
            print(f"\nMISSING LICENCE: {licence}")
            failures += 1
    print("\nOK" if not failures else f"\n{failures} problem(s)")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--verify", action="store_true", help="verify committed output only")
    parser.add_argument("--force", action="store_true", help="re-download sources first")
    parser.add_argument("--clean", action="store_true", help="delete brand/fonts/ first")
    args = parser.parse_args()

    if args.clean and FONTS_DIR.exists():
        readme = FONTS_DIR / "README.md"
        keep = readme.read_bytes() if readme.exists() else None
        shutil.rmtree(FONTS_DIR)
        FONTS_DIR.mkdir(parents=True)
        if keep is not None:
            readme.write_bytes(keep)
        print(f"cleaned {FONTS_DIR}")

    if not args.verify:
        fetch(force=args.force or args.clean)
        build()
    return verify()


if __name__ == "__main__":
    raise SystemExit(main())
