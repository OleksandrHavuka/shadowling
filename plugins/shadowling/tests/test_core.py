import unittest
from datetime import datetime

import core


class TodayTest(unittest.TestCase):
    def test_today_is_iso_date(self):
        self.assertRegex(core.today(), r"^\d{4}-\d{2}-\d{2}$")

    def test_today_matches_now(self):
        self.assertEqual(core.today(), datetime.now().strftime("%Y-%m-%d"))


class SlugifyTest(unittest.TestCase):
    KEBAB = r"^[a-z0-9]+(-[a-z0-9]+)*$"

    def test_spaces_to_hyphens_and_lowercase(self):
        self.assertEqual(
            core.slugify("Article Omission Before Countable"),
            "article-omission-before-countable",
        )

    def test_underscores_and_mixed_separators(self):
        self.assertEqual(
            core.slugify("word choice_demonstrative"), "word-choice-demonstrative"
        )

    def test_trims_outer_and_collapses_inner_hyphens(self):
        self.assertEqual(core.slugify("  -tense--shift-  "), "tense-shift")

    def test_drops_disallowed_chars(self):
        self.assertEqual(core.slugify("calque! (literal)"), "calque-literal")

    def test_already_canonical_unchanged(self):
        self.assertEqual(
            core.slugify("subject-verb-agreement-plural"),
            "subject-verb-agreement-plural",
        )

    def test_blank_becomes_empty(self):
        self.assertEqual(core.slugify("   _-_  "), "")

    def test_output_always_matches_kebab_or_empty(self):
        for raw in ["A B", "x__y", "-a-", "Wørd Choice!!", "ok"]:
            out = core.slugify(raw)
            if out:
                self.assertRegex(out, self.KEBAB)


if __name__ == "__main__":
    unittest.main()
