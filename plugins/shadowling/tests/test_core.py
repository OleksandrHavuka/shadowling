import unittest
from datetime import datetime

import core


class TodayTest(unittest.TestCase):
    def test_today_is_iso_date(self):
        self.assertRegex(core.today(), r"^\d{4}-\d{2}-\d{2}$")

    def test_today_matches_now(self):
        self.assertEqual(core.today(), datetime.now().strftime("%Y-%m-%d"))


class SlugifyTest(unittest.TestCase):
    # Unicode-aware: a run of one-or-more word chars (letters/digits of any
    # script, but NOT underscore) separated by single hyphens. \w includes "_",
    # so exclude it via the negative set.
    KEBAB = r"^[^\W_]+(-[^\W_]+)*$"

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

    def test_word_choice_lowercases(self):
        self.assertEqual(core.slugify("Word Choice"), "word-choice")

    def test_keeps_cyrillic(self):
        # Non-Latin letters survive (no transliteration); the slug is an internal
        # GROUP BY key. Distinct inputs stay distinct and non-empty. The full
        # any-script contract (incl. CJK, etc.) is fuzzed by the hypothesis
        # property test in test_properties (st.text() over all Unicode).
        self.assertEqual(core.slugify("Відмінювання"), "відмінювання")
        self.assertNotEqual(core.slugify("дієслово"), core.slugify("іменник"))

    def test_output_always_matches_kebab_or_empty(self):
        for raw in ["A B", "x__y", "-a-", "Wørd Choice!!", "ok", "Відмінювання"]:
            out = core.slugify(raw)
            if out:
                self.assertRegex(out, self.KEBAB)

    def test_woerd_choice_keeps_unicode_letter(self):
        # ø is a Unicode letter -> kept (the old ASCII slugify dropped it).
        self.assertEqual(core.slugify("Wørd Choice!!"), "wørd-choice")


class NowTest(unittest.TestCase):
    def test_now_is_iso_seconds(self):
        self.assertRegex(core.now(), r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")

    def test_now_matches_datetime(self):
        self.assertEqual(core.now(), datetime.now().isoformat(timespec="seconds"))


if __name__ == "__main__":
    unittest.main()
