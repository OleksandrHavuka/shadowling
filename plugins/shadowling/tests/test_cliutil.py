import unittest

from cliutil import format_loot_line


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
