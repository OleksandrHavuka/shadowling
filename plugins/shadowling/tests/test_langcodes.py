import unittest

import langcodes


class LangcodesTest(unittest.TestCase):
    def test_und_is_a_valid_code(self):
        self.assertIn("und", langcodes.CODES)

    def test_common_names_map_to_codes(self):
        self.assertEqual(langcodes.NAME_TO_CODE["english"], "en")
        self.assertEqual(langcodes.NAME_TO_CODE["ukrainian"], "uk")
        self.assertEqual(langcodes.NAME_TO_CODE["german"], "de")

    def test_every_named_code_is_in_codes(self):
        self.assertTrue(set(langcodes.NAME_TO_CODE.values()) <= langcodes.CODES)

    def test_names_are_lowercased_keys(self):
        self.assertEqual({k for k in langcodes.NAME_TO_CODE if k != k.lower()}, set())

    def test_unknown_name_absent(self):
        self.assertNotIn("klingon", langcodes.NAME_TO_CODE)
