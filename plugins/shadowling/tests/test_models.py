import os
import shutil
import tempfile
import unittest
from unittest import mock

from models.decode import Decode
from models.friction import Friction
from models.grammar import Grammar


class ModelTestBase(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        os.environ["SHADOWLING_HOME"] = self.home

    def tearDown(self):
        os.environ.pop("SHADOWLING_HOME", None)
        shutil.rmtree(self.home, ignore_errors=True)

    def _insert(self, slug, original="a", fixed="b"):
        return Grammar.insert(
            {
                "slug": slug,
                "problem": "p",
                "original": original,
                "fixed": fixed,
                "rule": "r",
            }
        )


class InsertSelectTest(ModelTestBase):
    def test_insert_returns_running_count_per_key(self):
        self.assertEqual(self._insert("s1"), 1)
        self.assertEqual(self._insert("s1"), 2)
        self.assertEqual(self._insert("s2"), 1)

    def test_select_key_returns_computed_row_without_plumbing(self):
        self._insert("s1", "x", "y")
        row = Grammar.select("s1")
        self.assertEqual(row["counter"], 1)
        self.assertEqual(row["original"], "x")
        self.assertEqual(row["fixed"], "y")
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
        self.assertEqual(Grammar.drop(), 1)  # rowcount of the DELETE
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
        self.assertEqual(row["original"], "c")  # latest incident wins
        self.assertEqual(row["fixed"], "d")

    def test_equal_counters_break_ties_by_most_recent_incident(self):
        self._insert("older")
        self._insert("newer")  # same counter (1); higher last_id ranks first
        self.assertEqual([r["slug"] for r in Grammar.select()], ["newer", "older"])


class InsertNormalizationTest(ModelTestBase):
    def test_insert_normalizes_raw_key(self):
        self.assertEqual(self._insert("Word Choice"), 1)
        self.assertIsNotNone(Grammar.select("word-choice"))
        self.assertIsNone(Grammar.select("Word Choice"))

    def test_insert_raw_and_normalized_keys_collide(self):
        self.assertEqual(self._insert("Word Choice"), 1)
        self.assertEqual(self._insert("word-choice"), 2)  # same key after norm

    def test_insert_empty_key_after_norm_raises(self):
        with self.assertRaises(ValueError):
            self._insert("   _-_  ")  # slugifies to ""

    def test_insert_all_punctuation_key_raises(self):
        with self.assertRaises(ValueError):
            self._insert("!!! ???")


class InsertEnumValidationTest(ModelTestBase):
    def _decode(self, type_):
        return Decode.insert(
            {
                "slug": "s",
                "type": type_,
                "expression": "e",
                "meaning": "m",
                "takeaway": "t",
                "learner_wrote": "lw",
                "context": "c",
            }
        )

    def _friction(self, type_):
        return Friction.insert(
            {
                "slug": "z",
                "type": type_,
                "zone": "zn",
                "learner_wrote": "lw",
                "native_phrase": "np",
                "context": "c",
            }
        )

    def test_decode_valid_type_passes(self):
        self.assertEqual(self._decode("fixed"), 1)
        self.assertEqual(self._decode("method"), 2)

    def test_decode_unknown_type_raises(self):
        with self.assertRaises(ValueError):
            self._decode("bogus")

    def test_friction_valid_type_passes(self):
        self.assertEqual(self._friction("register"), 1)

    def test_friction_unknown_type_raises(self):
        with self.assertRaises(ValueError):
            self._friction("nonsense")


class LatestRowColumnsTest(ModelTestBase):
    def test_all_bare_display_columns_come_from_newest_incident(self):
        # Two incidents for ONE key whose non-key display fields differ. SQLite
        # leaves EVERY bare min/max-mixed column undefined when >1 aggregate is
        # present, so this pins them all to the group's newest incident (MAX id),
        # not just one display column.
        with mock.patch("models.base.today", return_value="2026-06-01"):
            Grammar.insert(
                {
                    "slug": "s1",
                    "problem": "old problem",
                    "original": "old-a",
                    "fixed": "old-b",
                    "rule": "r",
                }
            )
        with mock.patch("models.base.today", return_value="2026-06-09"):
            Grammar.insert(
                {
                    "slug": "s1",
                    "problem": "new problem",
                    "original": "new-a",
                    "fixed": "new-b",
                    "rule": "r",
                }
            )
        row = Grammar.select("s1")
        self.assertEqual(row["counter"], 2)
        self.assertEqual(row["created_at"], "2026-06-01")  # aggregate: first
        self.assertEqual(row["updated_at"], "2026-06-09")  # aggregate: latest
        self.assertEqual(row["original"], "new-a")  # newest incident
        self.assertEqual(row["fixed"], "new-b")
        self.assertEqual(row["problem"], "new problem")  # ALSO from newest
        self.assertNotIn("last_id", row)


if __name__ == "__main__":
    unittest.main()
