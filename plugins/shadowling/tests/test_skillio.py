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


class ParseMessageSliceArgsTest(unittest.TestCase):
    def test_defaults_when_no_args(self):
        self.assertEqual(
            skillio.parse_message_slice_args([]),
            {"lang": None, "untagged": False, "limit": None, "session": None},
        )

    def test_all_valid_flags(self):
        self.assertEqual(
            skillio.parse_message_slice_args(
                ["--untagged", "--lang", "en", "--session", "s1", "--limit", "5"]
            ),
            {"lang": "en", "untagged": True, "limit": 5, "session": "s1"},
        )

    def test_limit_is_coerced_to_int(self):
        out = skillio.parse_message_slice_args(["--limit", "12"])
        self.assertEqual(out["limit"], 12)
        self.assertIsInstance(out["limit"], int)

    def test_non_digit_limit_raises_value_error(self):
        with self.assertRaises(ValueError) as ctx:
            skillio.parse_message_slice_args(["--limit", "lots"])
        self.assertIn("--limit", str(ctx.exception))

    def test_limit_without_value_raises_value_error(self):
        with self.assertRaises(ValueError) as ctx:
            skillio.parse_message_slice_args(["--limit"])
        self.assertIn("--limit", str(ctx.exception))

    def test_unknown_option_raises_with_offending_token(self):
        with self.assertRaises(ValueError) as ctx:
            skillio.parse_message_slice_args(["--bogus"])
        self.assertEqual(str(ctx.exception), "unknown option: --bogus")

    def test_lang_without_value_is_unknown_option(self):
        with self.assertRaises(ValueError) as ctx:
            skillio.parse_message_slice_args(["--lang"])
        self.assertEqual(str(ctx.exception), "unknown option: --lang")


class ParseSizeArgTest(unittest.TestCase):
    def test_default_when_no_args(self):
        self.assertEqual(skillio.parse_size_arg([], 8), 8)

    def test_parses_size(self):
        self.assertEqual(skillio.parse_size_arg(["--size", "5"], 8), 5)

    def test_non_digit_falls_back_to_default(self):
        self.assertEqual(skillio.parse_size_arg(["--size", "lots"], 8), 8)

    def test_wrong_flag_falls_back_to_default(self):
        self.assertEqual(skillio.parse_size_arg(["--bogus", "5"], 8), 8)


class ParseSessionArgTest(unittest.TestCase):
    def test_none_when_no_args(self):
        self.assertIsNone(skillio.parse_session_arg([]))

    def test_parses_session(self):
        self.assertEqual(skillio.parse_session_arg(["--session", "s1"]), "s1")

    def test_none_when_flag_only(self):
        self.assertIsNone(skillio.parse_session_arg(["--session"]))


class RenderTest(unittest.TestCase):
    def test_single_record_list(self):
        self.assertEqual(
            skillio.render([{"id": 1, "text": "hi"}]),
            "<row>\n  <id>1</id>\n  <text>hi</text>\n</row>",
        )

    def test_multi_record_list(self):
        self.assertEqual(
            skillio.render([{"a": "1"}, {"a": "2"}]),
            "<row>\n  <a>1</a>\n</row>\n<row>\n  <a>2</a>\n</row>",
        )

    def test_multiline_body_kept_verbatim(self):
        self.assertEqual(
            skillio.render([{"text": "line1\nline2"}]),
            "<row>\n  <text>line1\nline2</text>\n</row>",
        )

    def test_escapes_xml_special_chars(self):
        out = skillio.render([{"t": 'a < b & c > d "q"'}])
        self.assertIn("a &lt; b &amp; c &gt; d &quot;q&quot;", out)

    def test_none_value_renders_empty_element(self):
        self.assertEqual(
            skillio.render([{"langs": None}]),
            "<row>\n  <langs></langs>\n</row>",
        )

    def test_empty_list_is_empty_string(self):
        self.assertEqual(skillio.render([]), "")

    def test_fields_projects_subset_and_order(self):
        self.assertEqual(
            skillio.render(
                [{"id": 1, "created_at": "t", "text": "hi"}], fields=["text", "id"]
            ),
            "<row>\n  <text>hi</text>\n  <id>1</id>\n</row>",
        )

    def test_fields_absent_key_skipped(self):
        self.assertEqual(
            skillio.render([{"id": 1}], fields=["id", "text"]),
            "<row>\n  <id>1</id>\n</row>",
        )


if __name__ == "__main__":
    unittest.main()
