import unittest

from cliutil import format_loot_line, parse_message_slice_args


class ParseMessageSliceArgsTest(unittest.TestCase):
    def test_defaults_when_no_args(self):
        self.assertEqual(
            parse_message_slice_args([]),
            {"lang": None, "untagged": False, "limit": None, "session": None},
        )

    def test_all_valid_flags(self):
        self.assertEqual(
            parse_message_slice_args(
                ["--untagged", "--lang", "en", "--session", "s1", "--limit", "5"]
            ),
            {"lang": "en", "untagged": True, "limit": 5, "session": "s1"},
        )

    def test_limit_is_coerced_to_int(self):
        out = parse_message_slice_args(["--limit", "12"])
        self.assertEqual(out["limit"], 12)
        self.assertIsInstance(out["limit"], int)

    def test_non_digit_limit_raises_value_error(self):
        with self.assertRaises(ValueError) as ctx:
            parse_message_slice_args(["--limit", "lots"])
        self.assertIn("--limit", str(ctx.exception))

    def test_limit_without_value_raises_value_error(self):
        with self.assertRaises(ValueError) as ctx:
            parse_message_slice_args(["--limit"])
        self.assertIn("--limit", str(ctx.exception))

    def test_unknown_option_raises_with_offending_token(self):
        with self.assertRaises(ValueError) as ctx:
            parse_message_slice_args(["--bogus"])
        self.assertEqual(str(ctx.exception), "unknown option: --bogus")

    def test_lang_without_value_is_unknown_option(self):
        with self.assertRaises(ValueError) as ctx:
            parse_message_slice_args(["--lang"])
        self.assertEqual(str(ctx.exception), "unknown option: --lang")


class FormatLootLineTest(unittest.TestCase):
    def test_exact_line(self):
        row = {
            "word": "hello",
            "translation": "привіт",
            "remaining": 10,
            "status": "active",
        }
        self.assertEqual(
            format_loot_line("add", row), "add: hello = привіт (remaining 10, active)"
        )

    def test_untranslated_placeholders(self):
        row = {"word": "foo", "translation": "foo", "remaining": "-", "status": "-"}
        self.assertEqual(
            format_loot_line("untranslated", row),
            "untranslated: foo = foo (remaining -, -)",
        )


if __name__ == "__main__":
    unittest.main()
