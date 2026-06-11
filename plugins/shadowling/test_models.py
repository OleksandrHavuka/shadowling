import os
import shutil
import tempfile
import unittest
from unittest import mock

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


class LifecycleAndOrderingTest(ModelTestBase):
    def test_created_fixed_while_updated_advances_across_dates(self):
        # The core of the lifecycle fields: created_at pins to the FIRST
        # incident's date, updated_at tracks the LATEST. today() is constant
        # within a run, so the two dates must be injected to prove it.
        with mock.patch("models.base.today", return_value="2026-06-01"):
            self._insert("s1", "a", "b")
        with mock.patch("models.base.today", return_value="2026-06-09"):
            self._insert("s1", "c", "d")
        row = Grammar.select("s1")
        self.assertEqual(row["counter"], 2)
        self.assertEqual(row["created_at"], "2026-06-01")  # fixed at first
        self.assertEqual(row["updated_at"], "2026-06-09")  # advances to latest
        self.assertEqual(row["last example"], "c → d")     # latest incident wins

    def test_equal_counters_break_ties_by_most_recent_incident(self):
        self._insert("older")
        self._insert("newer")  # same counter (1); higher last_id ranks first
        self.assertEqual([r["slug"] for r in Grammar.select()],
                         ["newer", "older"])


if __name__ == "__main__":
    unittest.main()
