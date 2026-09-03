"""Direct coverage for `scripts/_marker_block.py`.

The module is shared by `wiki_index.py` and `compute_readiness.py` (#121). Its
only coverage used to be transitive, through `tests/test_wiki_index.py` — which
means every rule was proven for exactly one marker pair, and the first
divergence between the two consumers would land here unnoticed. So every
behavioural test below runs against **both** real pairs via `subTest`, and the
module is exercised on its own terms rather than through a generator.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from _marker_block import (  # noqa: E402
    MarkerBlock,
    fenced_line_indices,
    split_lines,
)

# The two pairs actually in production. Spelled out rather than imported from
# the owning scripts: importing `compute_readiness` would drag in `record_stop`
# and the trail machinery, and this module knows nothing about either. The
# drift guard below is what keeps these literals honest.
INDEX_PAIR = ("<!-- memory-index:generated start -->",
              "<!-- memory-index:generated end -->")
READINESS_PAIR = ("<!-- readiness:generated start -->",
                  "<!-- readiness:generated end -->")
PAIRS = {"memory-index": INDEX_PAIR, "readiness": READINESS_PAIR}


def _crlf(text):
    return text.replace("\n", "\r\n")


def _cr(text):
    return text.replace("\n", "\r")


class DriftGuardTest(unittest.TestCase):
    """The literals above must stay the pairs the two scripts really use."""

    def test_index_pair_matches_wiki_index(self):
        import wiki_index
        self.assertEqual(
            (wiki_index.GENERATED_BEGIN, wiki_index.GENERATED_END), INDEX_PAIR
        )

    def test_readiness_pair_matches_compute_readiness(self):
        sys.path.insert(0, str(ROOT / "hooks"))
        import compute_readiness
        self.assertEqual(
            (compute_readiness.GENERATED_BEGIN, compute_readiness.GENERATED_END),
            READINESS_PAIR,
        )


class SplitLinesTest(unittest.TestCase):
    def test_offsets_reconstruct_the_text_exactly(self):
        for name, text in (
            ("lf", "a\nb\nc\n"),
            ("crlf", "a\r\nb\r\nc\r\n"),
            ("cr", "a\rb\rc\r"),
            ("mixed", "a\nb\r\nc\rd"),
            ("no trailing newline", "a\nb"),
            ("empty", ""),
        ):
            with self.subTest(name):
                parts = split_lines(text)
                self.assertEqual("".join(p[2] for p in parts), text)
                for start, stop, line in parts:
                    self.assertEqual(text[start:stop], line)

    def test_stop_is_past_the_terminator(self):
        (first, second) = split_lines("ab\r\ncd\n")
        self.assertEqual(first, (0, 4, "ab\r\n"))
        self.assertEqual(second, (4, 7, "cd\n"))


class FencedLineIndicesTest(unittest.TestCase):
    def test_closed_fence_covers_its_own_fence_lines(self):
        lines = split_lines("a\n```\nb\n```\nc\n")
        self.assertEqual(fenced_line_indices(lines), {1, 2, 3})

    def test_tilde_fence(self):
        lines = split_lines("a\n~~~\nb\n~~~\nc\n")
        self.assertEqual(fenced_line_indices(lines), {1, 2, 3})

    def test_a_tilde_does_not_close_a_backtick_fence(self):
        lines = split_lines("```\nb\n~~~\nc\n```\n")
        self.assertEqual(fenced_line_indices(lines), {0, 1, 2, 3, 4})

    def test_closing_fence_must_be_at_least_as_long(self):
        lines = split_lines("````\nb\n```\nc\n````\n")
        self.assertEqual(fenced_line_indices(lines), {0, 1, 2, 3, 4})

    def test_a_closing_fence_carries_no_info_string(self):
        # "```py" mid-block cannot close; the later bare fence does.
        lines = split_lines("```\nb\n```py\nc\n```\n")
        self.assertEqual(fenced_line_indices(lines), {0, 1, 2, 3, 4})

    def test_unclosed_fence_opens_nothing(self):
        """Deliberate: an unclosed fence must not hide a real trailing block.

        CommonMark would run it to EOF. Doing that here would make every run
        classify `none`, append, and grow a fresh block forever — the exact
        duplicate-forever failure the classification exists to prevent.
        """
        lines = split_lines("a\n```\nb\nc\n")
        self.assertEqual(fenced_line_indices(lines), set())

    def test_indented_fence_counts(self):
        lines = split_lines("a\n   ```\nb\n   ```\nc\n")
        self.assertEqual(fenced_line_indices(lines), {1, 2, 3})


class MarkerLinesTest(unittest.TestCase):
    def test_finds_both_markers_in_document_order(self):
        for name, (begin, end) in PAIRS.items():
            with self.subTest(name):
                block = MarkerBlock(begin, end)
                text = f"# t\n\n{begin}\nbody\n{end}\n\ntail\n"
                kinds = [k for k, _, _ in block.marker_lines(text)]
                self.assertEqual(kinds, ["start", "end"])

    def test_surrounding_spaces_and_tabs_are_tolerated(self):
        for name, (begin, end) in PAIRS.items():
            with self.subTest(name):
                block = MarkerBlock(begin, end)
                text = f"  {begin}  \n\t{end}\t\n"
                self.assertEqual(
                    [k for k, _, _ in block.marker_lines(text)], ["start", "end"]
                )

    def test_a_marker_quoted_inline_is_not_a_marker(self):
        """#102's own failure class: prose that documents the convention."""
        for name, (begin, end) in PAIRS.items():
            with self.subTest(name):
                block = MarkerBlock(begin, end)
                text = (
                    f"Write `{begin}` above your block and `{end}` below it.\n"
                    "Words that must survive.\n"
                )
                self.assertEqual(block.marker_lines(text), [])
                self.assertEqual(block.classify(text), ("none", ""))

    def test_a_marker_with_other_text_on_the_line_is_not_a_marker(self):
        for name, (begin, end) in PAIRS.items():
            with self.subTest(name):
                block = MarkerBlock(begin, end)
                self.assertEqual(block.marker_lines(f"x {begin}\n"), [])
                self.assertEqual(block.marker_lines(f"{end} x\n"), [])

    def test_markers_inside_a_fenced_example_are_skipped(self):
        for name, (begin, end) in PAIRS.items():
            with self.subTest(name):
                block = MarkerBlock(begin, end)
                text = f"Example:\n\n```\n{begin}\nbody\n{end}\n```\n\nprose\n"
                self.assertEqual(block.marker_lines(text), [])
                self.assertEqual(block.classify(text), ("none", ""))

    def test_a_fenced_example_does_not_shadow_the_real_block(self):
        for name, (begin, end) in PAIRS.items():
            with self.subTest(name):
                block = MarkerBlock(begin, end)
                text = (
                    f"```\n{begin}\nexample\n{end}\n```\n\n"
                    f"{begin}\nreal body\n{end}\n"
                )
                self.assertEqual(block.classify(text), ("ok", ""))
                self.assertEqual(block.outside(text).count("example"), 1)
                self.assertNotIn("real body", block.outside(text))

    def test_each_pair_ignores_the_other_pairs_markers(self):
        """The two blocks coexist in one file without either seeing the other."""
        i_begin, i_end = INDEX_PAIR
        r_begin, r_end = READINESS_PAIR
        text = (
            f"{i_begin}\nindex body\n{i_end}\n\n"
            f"{r_begin}\nreadiness body\n{r_end}\n"
        )
        index = MarkerBlock(i_begin, i_end)
        readiness = MarkerBlock(r_begin, r_end)
        self.assertEqual(index.classify(text), ("ok", ""))
        self.assertEqual(readiness.classify(text), ("ok", ""))
        self.assertNotIn("index body", index.outside(text))
        self.assertIn("readiness body", index.outside(text))
        self.assertNotIn("readiness body", readiness.outside(text))
        self.assertIn("index body", readiness.outside(text))


class ClassifyTest(unittest.TestCase):
    """All seven shapes, for both pairs. `span` is valid only after `ok`."""

    def _shapes(self, begin, end):
        head = "---\nlast_updated: 2026-08-01\n---\n\n# t\n\nkeep me\n\n"
        return {
            "none": (head, ("none", "")),
            "ok": (f"{head}{begin}\nbody\n{end}\n",
                   ("ok", "")),
            "orphan begin": (f"{head}{begin}\nbody\n",
                             ("malformed", "begin marker without an end marker")),
            "orphan end": (f"{head}body\n{end}\n",
                           ("malformed", "end marker without a begin marker")),
            "reversed": (f"{head}{end}\nbody\n{begin}\n",
                         ("malformed", "end marker before begin marker")),
            "duplicate begin": (f"{head}{begin}\na\n{begin}\nb\n{end}\n",
                                ("malformed", "2 begin markers")),
            "duplicate end": (f"{head}{begin}\na\n{end}\nb\n{end}\n",
                              ("malformed", "2 end markers")),
        }

    def test_every_shape_for_both_pairs(self):
        for pair_name, (begin, end) in PAIRS.items():
            for shape, (text, expected) in self._shapes(begin, end).items():
                with self.subTest(pair=pair_name, shape=shape):
                    self.assertEqual(MarkerBlock(begin, end).classify(text), expected)

    def test_nested_markers_are_rejected_not_spliced(self):
        for name, (begin, end) in PAIRS.items():
            with self.subTest(name):
                text = f"{begin}\n{begin}\ninner\n{end}\n{end}\n"
                kind, reason = MarkerBlock(begin, end).classify(text)
                self.assertEqual(kind, "malformed")
                self.assertEqual(reason, "2 begin markers")

    def test_duplicate_count_is_reported_accurately(self):
        begin, end = READINESS_PAIR
        kind, reason = MarkerBlock(begin, end).classify(
            f"{begin}\n{begin}\n{begin}\n{end}\n"
        )
        self.assertEqual((kind, reason), ("malformed", "3 begin markers"))

    def test_classification_is_line_ending_agnostic(self):
        for pair_name, (begin, end) in PAIRS.items():
            for ending, conv in (("lf", str), ("crlf", _crlf), ("cr", _cr)):
                for shape, (text, expected) in self._shapes(begin, end).items():
                    with self.subTest(pair=pair_name, ending=ending, shape=shape):
                        self.assertEqual(
                            MarkerBlock(begin, end).classify(conv(text)), expected
                        )


class SpanTest(unittest.TestCase):
    def test_span_consumes_whole_marker_lines_under_every_ending(self):
        for pair_name, (begin, end) in PAIRS.items():
            for ending, conv in (("lf", str), ("crlf", _crlf), ("cr", _cr)):
                with self.subTest(pair=pair_name, ending=ending):
                    text = conv(f"before\n\n{begin}\nbody\n{end}\n\nafter\n")
                    start, stop = MarkerBlock(begin, end).span(text)
                    # No terminator is left behind and none is eaten early.
                    self.assertTrue(text[:start].endswith(conv("\n")))
                    self.assertEqual(text[stop:], conv("\nafter\n"))
                    self.assertTrue(text[start:stop].startswith(begin))
                    self.assertTrue(text[start:stop].endswith(conv("\n")))

    def test_outside_is_the_text_minus_the_span(self):
        for pair_name, (begin, end) in PAIRS.items():
            for ending, conv in (("lf", str), ("crlf", _crlf), ("cr", _cr)):
                with self.subTest(pair=pair_name, ending=ending):
                    text = conv(f"head\n{begin}\nbody\n{end}\ntail\n")
                    block = MarkerBlock(begin, end)
                    start, stop = block.span(text)
                    self.assertEqual(block.outside(text), text[:start] + text[stop:])
                    self.assertEqual(block.outside(text), conv("head\ntail\n"))

    def test_span_on_a_block_with_no_trailing_newline(self):
        for name, (begin, end) in PAIRS.items():
            with self.subTest(name):
                text = f"head\n{begin}\nbody\n{end}"
                block = MarkerBlock(begin, end)
                start, stop = block.span(text)
                self.assertEqual(stop, len(text))
                self.assertEqual(block.outside(text), "head\n")

    def test_splicing_a_replacement_preserves_everything_outside(self):
        for name, (begin, end) in PAIRS.items():
            with self.subTest(name):
                block = MarkerBlock(begin, end)
                text = f"---\nk: v\n---\n\nprose\n\n{begin}\nold\n{end}\n\ntail\n"
                start, stop = block.span(text)
                new = text[:start] + f"{begin}\nnew\n{end}\n" + text[stop:]
                self.assertIn("prose", new)
                self.assertIn("tail", new)
                self.assertIn("k: v", new)
                self.assertNotIn("old", new)
                self.assertEqual(block.classify(new), ("ok", ""))
                # And it is a fixed point: splicing the same body again is a no-op.
                start2, stop2 = block.span(new)
                self.assertEqual(
                    new[:start2] + f"{begin}\nnew\n{end}\n" + new[stop2:], new
                )


class ImmutabilityTest(unittest.TestCase):
    def test_two_instances_of_one_pair_agree(self):
        begin, end = READINESS_PAIR
        text = f"{begin}\nbody\n{end}\n"
        self.assertEqual(
            MarkerBlock(begin, end).span(text), MarkerBlock(begin, end).span(text)
        )

    def test_regex_metacharacters_in_a_marker_are_escaped(self):
        block = MarkerBlock("<!-- a.b(c) -->", "<!-- end -->")
        self.assertEqual(block.marker_lines("<!-- axbXcY -->\n"), [])
        self.assertEqual(
            [k for k, _, _ in block.marker_lines("<!-- a.b(c) -->\n")], ["start"]
        )


if __name__ == "__main__":
    unittest.main()
