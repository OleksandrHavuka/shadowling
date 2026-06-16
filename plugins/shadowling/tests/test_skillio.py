import unittest

import skillio
from skillio import TEXT, read_fields, rows


class ScalarTest(unittest.TestCase):
    def test_inline_and_block_forms(self):
        self.assertEqual(read_fields({"a": TEXT}, "<a>x</a>"), {"a": "x"})
        # block form: the single layout newline on each side is stripped
        self.assertEqual(read_fields({"a": TEXT}, "<a>\nx\n</a>"), {"a": "x"})

    def test_verbatim_special_chars_and_internal_newlines(self):
        val = 'he said "it\'s done" — `rm -rf` & $HOME\nsecond line'
        got = read_fields({"a": TEXT}, "<a>\n" + val + "\n</a>")
        self.assertEqual(got["a"], val)  # no unescape, internal newline kept

    def test_internal_trailing_newline_preserved(self):
        # value ends with its own newline -> only the layout newline is stripped
        got = read_fields({"a": TEXT}, "<a>\nx\n\n</a>")
        self.assertEqual(got["a"], "x\n")

    def test_multiple_fields_order_independent(self):
        text = "<b>two</b>\n<a>one</a>"
        got = read_fields({"a": TEXT, "b": TEXT}, text)
        self.assertEqual(got, {"a": "one", "b": "two"})

    def test_unknown_extra_tags_ignored(self):
        text = "<a>x</a>\n<junk>ignored</junk>"
        self.assertEqual(read_fields({"a": TEXT}, text), {"a": "x"})

    def test_nearest_close_is_used(self):
        self.assertEqual(read_fields({"a": TEXT}, "<a>x</a><a>y</a>")["a"], "x")


class RowsTest(unittest.TestCase):
    def test_tsv_rows_to_list_of_dicts(self):
        body = "<items>\nget rid of\tпозбутися\nredundant\tзайвий\n</items>"
        got = read_fields({"items": rows("word", "translation")}, body)
        self.assertEqual(
            got["items"],
            [
                {"word": "get rid of", "translation": "позбутися"},
                {"word": "redundant", "translation": "зайвий"},
            ],
        )

    def test_commas_and_special_chars_are_free(self):
        # tab is the only boundary, so commas/quotes/$ inside a cell survive
        body = '<items>\na, b, c\tце "$сленг", тощо\n</items>'
        got = read_fields({"items": rows("word", "translation")}, body)
        self.assertEqual(
            got["items"], [{"word": "a, b, c", "translation": 'це "$сленг", тощо'}]
        )

    def test_blank_lines_skipped(self):
        body = "<items>\n\nalpha\tа\n\nbeta\tб\n\n</items>"
        got = read_fields({"items": rows("word", "translation")}, body)
        self.assertEqual([r["word"] for r in got["items"]], ["alpha", "beta"])

    def test_wrong_column_count_raises(self):
        body = "<items>\nalpha\tа\nbeta\tб\tжарт\n</items>"
        with self.assertRaises(ValueError) as cm:
            read_fields({"items": rows("word", "translation")}, body)
        msg = str(cm.exception)
        self.assertIn("line 2", msg)  # names the offending data row (1-based)
        self.assertIn("expected 2", msg)
        self.assertIn("TAB", msg)


class MixedTest(unittest.TestCase):
    def test_text_and_rows_side_by_side(self):
        text = "<slug>code-switch</slug>\n<items>\nword\ttr\n</items>"
        got = read_fields({"slug": TEXT, "items": rows("word", "translation")}, text)
        self.assertEqual(got["slug"], "code-switch")
        self.assertEqual(got["items"], [{"word": "word", "translation": "tr"}])


class SelfCorrectingErrorTest(unittest.TestCase):
    """Every failure must name the problem AND embed the expected-syntax template,
    so the LLM can retry without guessing."""

    def test_missing_field_message(self):
        with self.assertRaises(ValueError) as cm:
            read_fields({"slug": TEXT, "fixed": TEXT}, "<slug>s</slug>")
        msg = str(cm.exception)
        self.assertIn("missing required tag <fixed>", msg)
        self.assertIn("expected stdin format:", msg)
        self.assertIn("<slug>...</slug>", msg)  # the template is shown
        self.assertIn("<fixed>...</fixed>", msg)

    def test_unclosed_tag_message(self):
        with self.assertRaises(ValueError) as cm:
            read_fields({"problem": TEXT}, "<problem>oops")
        msg = str(cm.exception)
        self.assertIn("<problem>", msg)
        self.assertIn("never closed", msg)
        self.assertIn("</problem>", msg)

    def test_rows_template_shows_tab_columns(self):
        with self.assertRaises(ValueError) as cm:
            read_fields({"items": rows("word", "translation")}, "")
        msg = str(cm.exception)
        self.assertIn("word<TAB>translation", msg)


class RowsFactoryTest(unittest.TestCase):
    def test_rows_needs_a_column(self):
        with self.assertRaises(ValueError):
            skillio.rows()


class FlatFieldLimitationTest(unittest.TestCase):
    """Characterization (NOT a fix): fields are located independently from
    position 0, so a TEXT body containing a *later* field's literal open tag
    contaminates that field's extraction. Pins the documented limitation so it
    cannot change silently; see the skillio module/_extract docstring."""

    def test_literal_later_open_tag_in_body_contaminates(self):
        text = "<a>value with <b> literal open tag inside</a>\n<b>real b body</b>"
        got = read_fields({"a": TEXT, "b": TEXT}, text)
        self.assertEqual(got["a"], "value with <b> literal open tag inside")
        self.assertEqual(got["b"], " literal open tag inside</a>\n<b>real b body")

    def test_literal_self_close_tag_in_body_truncates(self):
        text = "<a>oops </a> early close then more</a>"
        self.assertEqual(read_fields({"a": TEXT}, text), {"a": "oops "})


if __name__ == "__main__":
    unittest.main()
