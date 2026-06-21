import os
import shutil
import tempfile
import unittest

from models.anki_link import AnkiLink


class AnkiLinkBase(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        os.environ["SHADOWLING_HOME"] = self.home

    def tearDown(self):
        os.environ.pop("SHADOWLING_HOME", None)
        shutil.rmtree(self.home, ignore_errors=True)


class UpsertTest(AnkiLinkBase):
    def test_insert_then_get(self):
        AnkiLink.upsert("Throughput", note_id=11, card_id=22, deck="d", lapses=0)
        row = AnkiLink.get("throughput")  # normalized lookup
        self.assertEqual(row["word"], "throughput")
        self.assertEqual(row["note_id"], 11)
        self.assertEqual(row["card_id"], 22)
        self.assertEqual(row["deck"], "d")

    def test_update_writes_only_provided_columns(self):
        AnkiLink.upsert("w", note_id=1, card_id=2, deck="d", lapses=0)
        AnkiLink.upsert("w", lapses=3, reps=7)  # note_id/card_id/deck untouched
        row = AnkiLink.get("w")
        self.assertEqual(row["lapses"], 3)
        self.assertEqual(row["reps"], 7)
        self.assertEqual(row["note_id"], 1)
        self.assertEqual(row["deck"], "d")

    def test_get_unknown_returns_none(self):
        self.assertIsNone(AnkiLink.get("nope"))


class AllTest(AnkiLinkBase):
    def test_all_sorted_by_word(self):
        AnkiLink.upsert("beta", note_id=2)
        AnkiLink.upsert("alpha", note_id=1)
        self.assertEqual([r["word"] for r in AnkiLink.all()], ["alpha", "beta"])


class DeleteTest(AnkiLinkBase):
    def test_delete_existing_true_then_gone(self):
        AnkiLink.upsert("w", note_id=1)
        self.assertTrue(AnkiLink.delete("W"))
        self.assertIsNone(AnkiLink.get("w"))

    def test_delete_unknown_false(self):
        self.assertFalse(AnkiLink.delete("ghost"))


if __name__ == "__main__":
    unittest.main()
