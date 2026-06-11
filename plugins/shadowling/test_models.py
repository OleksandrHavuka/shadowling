import os
import shutil
import tempfile
import unittest

from models.grammar import Grammar


class ModelTestBase(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        os.environ["SHADOWLING_HOME"] = self.home

    def tearDown(self):
        os.environ.pop("SHADOWLING_HOME", None)
        shutil.rmtree(self.home, ignore_errors=True)

    def _insert(self, slug, original="a", fixed="b"):
        return Grammar.insert({"slug": slug, "problem": "p",
                               "original": original, "fixed": fixed,
                               "rule": "r"})


class InsertSelectTest(ModelTestBase):
    def test_insert_returns_running_count_per_key(self):
        self.assertEqual(self._insert("s1"), 1)
        self.assertEqual(self._insert("s1"), 2)
        self.assertEqual(self._insert("s2"), 1)

    def test_select_key_returns_computed_row_without_plumbing(self):
        self._insert("s1", "x", "y")
        row = Grammar.select("s1")
        self.assertEqual(row["counter"], 1)
        self.assertEqual(row["last example"], "x → y")
        self.assertNotIn("last_id", row)

    def test_select_all_ranked_by_counter(self):
        self._insert("rare")
        self._insert("frequent")
        self._insert("frequent")
        rows = Grammar.select()
        self.assertEqual([r["slug"] for r in rows], ["frequent", "rare"])

    def test_select_missing_returns_none(self):
        self.assertIsNone(Grammar.select("ghost"))

    def test_drop_empties_the_table(self):
        self._insert("s1")
        self.assertEqual(Grammar.drop(), "dropped")
        self.assertEqual(Grammar.select(), [])


if __name__ == "__main__":
    unittest.main()
