import unittest

import _adr_transform as t


FM_DOC = """---
name: alpha-adr-0002-thing
description: Do the thing, not the other thing.
type: adr
status: accepted
---
# ADR 0002: Do the thing

## Status

Accepted. Enforced by a guard.
"""

BULLET_DOC = """# ADR-0003: Bullet style

- **Status:** Accepted — implemented and merged (payment #99).
- **Date:** 2026-07-29

## Context
"""

HEADING_DOC = """# 0004 — Heading style

## Status

**Superseded by [ADR-0009](0009-x.md) — *by completion*.**
"""


class NormalizeNewlinesTest(unittest.TestCase):
    def test_crlf_and_cr_become_lf(self):
        self.assertEqual(t.normalize_newlines("a\r\nb\rc\n"), "a\nb\nc\n")


class SplitFrontmatterTest(unittest.TestCase):
    def test_parses_leading_block(self):
        fm, body = t.split_frontmatter(FM_DOC)
        self.assertEqual(fm["name"], "alpha-adr-0002-thing")
        self.assertEqual(fm["description"], "Do the thing, not the other thing.")
        self.assertEqual(fm["status"], "accepted")
        self.assertTrue(body.startswith("# ADR 0002: Do the thing\n"))

    def test_no_block_returns_empty_dict_and_whole_text(self):
        fm, body = t.split_frontmatter(BULLET_DOC)
        self.assertEqual(fm, {})
        self.assertEqual(body, BULLET_DOC)

    def test_unterminated_block_is_treated_as_body(self):
        text = "---\nname: x\n# not closed\n"
        fm, body = t.split_frontmatter(text)
        self.assertEqual(fm, {})
        self.assertEqual(body, text)


class ExtractTitleTest(unittest.TestCase):
    def test_first_h1(self):
        self.assertEqual(t.extract_title(BULLET_DOC), "ADR-0003: Bullet style")

    def test_missing_h1_is_empty(self):
        self.assertEqual(t.extract_title("## only h2\n"), "")


class ExtractStatusTest(unittest.TestCase):
    def test_frontmatter_wins(self):
        fm, body = t.split_frontmatter(FM_DOC)
        self.assertEqual(t.extract_status(fm, body), "accepted")

    def test_bullet_header(self):
        self.assertEqual(t.extract_status({}, BULLET_DOC), "accepted")

    def test_status_heading_with_bold_and_link(self):
        self.assertEqual(t.extract_status({}, HEADING_DOC), "superseded")

    def test_as_built_keeps_hyphen(self):
        body = "# x\n\n## Status\n\nAs-built. Documents the code.\n"
        self.assertEqual(t.extract_status({}, body), "as-built")

    def test_unknown_when_nothing_matches(self):
        self.assertEqual(t.extract_status({}, "# x\n\ntext\n"), "unknown")

    def test_unrecognised_word_is_unknown(self):
        self.assertEqual(t.extract_status({"status": "draft"}, ""), "unknown")


class StripProvenanceTest(unittest.TestCase):
    def test_removes_tag_line_and_one_blank(self):
        body = "para one.\n\n[Source: user override — 2026-08-07]\n\npara two.\n"
        self.assertEqual(t.strip_provenance(body), "para one.\n\npara two.\n")

    def test_trailing_tag(self):
        body = "para.\n\n[Source: empirical — 2026-07-29]\n"
        self.assertEqual(t.strip_provenance(body), "para.\n")

    def test_inline_mention_untouched(self):
        body = "see the [Source: x] convention inline.\n"
        self.assertEqual(t.strip_provenance(body), body)

    def test_tag_directly_after_content_keeps_terminator(self):
        body = "last line of prose.\n[Source: user override — 2026-08-07]\n"
        self.assertEqual(t.strip_provenance(body), "last line of prose.\n")

    def test_blank_before_content_after_keeps_paragraph_break(self):
        body = "about.\n\n[Source: empirical — 2026-08-28]\n<!-- promoted:end -->\nThree.\n"
        self.assertEqual(t.strip_provenance(body), "about.\n\n<!-- promoted:end -->\nThree.\n")

    def test_unrelated_blank_runs_are_untouched(self):
        body = "```\nline\n\n\n\nstill code\n```\n\n\n[Source: x — 2026-01-01]\n\nafter.\n\n\n"
        self.assertEqual(t.strip_provenance(body),
                         "```\nline\n\n\n\nstill code\n```\n\n\nafter.\n\n\n")

    def test_no_tag_is_identity(self):
        body = "a.\n\n\nb.\n\n"
        self.assertEqual(t.strip_provenance(body), body)

    def test_tag_at_start_followed_by_blank(self):
        self.assertEqual(t.strip_provenance("[Source: x — 2026-01-01]\n\nfirst.\n"), "first.\n")

    def test_tag_with_blank_after_only(self):
        self.assertEqual(t.strip_provenance("x.\n[Source: x — 2026-01-01]\n\ny.\n"), "x.\n\ny.\n")


class RenderFrontmatterTest(unittest.TestCase):
    def test_quotes_and_escapes(self):
        out = t.render_frontmatter([("title", 'ADR "0002": `x`'), ("status", "accepted")])
        self.assertEqual(out, '---\ntitle: "ADR \\"0002\\": `x`"\nstatus: "accepted"\n---\n')


class TransformTest(unittest.TestCase):
    def test_frontmatter_replaced_and_body_kept(self):
        out = t.transform(
            FM_DOC, source_rel="memory/repo/alpha/adr/0002-thing.md",
            target_rel="alpha/0002-thing.md", github="acme/alpha",
            synced_at="2026-09-10", published={"memory/repo/alpha/adr/0002-thing.md": "alpha/0002-thing.md"},
        )
        head, _, body = out.partition("\n---\n")
        self.assertEqual(head.split("\n"), [
            "---",
            'title: "ADR 0002: Do the thing"',
            'status: "accepted"',
            'source_repo: "acme/alpha"',
            'synced_from: "memory/repo/alpha/adr/0002-thing.md"',
            'synced_at: "2026-09-10"',
            'description: "Do the thing, not the other thing."',
        ])
        self.assertTrue(body.startswith("# ADR 0002: Do the thing\n"))
        self.assertNotIn("name:", out)
        self.assertNotIn("type:", out)

    def test_no_source_frontmatter_omits_description(self):
        out = t.transform(
            BULLET_DOC, source_rel="memory/repo/alpha/adr/0003-b.md",
            target_rel="alpha/0003-b.md", github="acme/alpha",
            synced_at="2026-09-10", published={},
        )
        self.assertIn('status: "accepted"', out)
        self.assertNotIn("description:", out)

    def test_crlf_input_yields_lf_output(self):
        out = t.transform(
            BULLET_DOC.replace("\n", "\r\n"), source_rel="memory/repo/alpha/adr/0003-b.md",
            target_rel="alpha/0003-b.md", github="acme/alpha",
            synced_at="2026-09-10", published={},
        )
        self.assertNotIn("\r", out)


class StripSyncedAtTest(unittest.TestCase):
    def test_only_that_line_goes(self):
        text = '---\ntitle: "x"\nsynced_at: "2026-09-10"\nstatus: "accepted"\n---\nbody\n'
        self.assertEqual(t.strip_synced_at(text), '---\ntitle: "x"\nstatus: "accepted"\n---\nbody\n')


PUBLISHED = {
    "memory/repo/alpha/adr/0002-thing.md": "alpha/0002-thing.md",
    "memory/repo/alpha/adr/0009-later.md": "alpha/0009-later.md",
    "memory/repo/beta/adr/0001-b.md": "beta/0001-b.md",
}
SRC = "memory/repo/alpha/adr/0002-thing.md"
TGT = "alpha/0002-thing.md"


class RewriteLinksTest(unittest.TestCase):
    def rw(self, body):
        return t.rewrite_links(body, SRC, TGT, PUBLISHED)

    def test_http_and_fragment_untouched(self):
        body = "[pr](https://github.com/acme/alpha/pull/1) and [sec](#status)\n"
        self.assertEqual(self.rw(body), body)

    def test_same_dir_published_adr(self):
        self.assertEqual(self.rw("see [ADR-0009](0009-later.md)."),
                         "see [ADR-0009](0009-later.md).")

    def test_published_adr_with_fragment(self):
        self.assertEqual(self.rw("[x](0009-later.md#decision)"), "[x](0009-later.md#decision)")

    def test_cross_slug_published_adr(self):
        self.assertEqual(self.rw("[b](../../beta/adr/0001-b.md)"), "[b](../beta/0001-b.md)")

    def test_unpublished_adr_annotated(self):
        self.assertEqual(self.rw("see [ADR-0006](0006-nope.md) too"),
                         "see ADR-0006 (not yet implemented — not published) too")

    def test_brain_note_annotated(self):
        self.assertEqual(self.rw("[readiness](../readiness.md)"),
                         "readiness (brain-internal note, not published)")

    def test_deep_relative_brain_note(self):
        self.assertEqual(self.rw("[verify](../../../feedback/verify-before-assuming.md)"),
                         "verify (brain-internal note, not published)")

    def test_memory_root_relative_link(self):
        self.assertEqual(self.rw("[rules](memory/projects/acme/rules.md)"),
                         "rules (brain-internal note, not published)")

    def test_sisyphus_plan(self):
        self.assertEqual(self.rw("[plan](../../../../.sisyphus/plans/foo.md)"),
                         "plan (internal plan)")

    def test_fenced_code_untouched(self):
        body = "```md\n[readiness](../readiness.md)\n```\n[readiness](../readiness.md)\n"
        self.assertEqual(self.rw(body),
                         "```md\n[readiness](../readiness.md)\n```\nreadiness (brain-internal note, not published)\n")

    def test_image_untouched(self):
        body = "![diagram](../diagram.png)\n"
        self.assertEqual(self.rw(body), body)


if __name__ == "__main__":
    unittest.main()
