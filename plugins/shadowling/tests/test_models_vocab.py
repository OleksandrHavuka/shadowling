import os
import shutil
import tempfile
import unittest
from unittest import mock

import appdb
from models.vocab import Vocab, word_in_text


class VocabRepoBase(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        os.environ["SHADOWLING_HOME"] = self.home

    def tearDown(self):
        os.environ.pop("SHADOWLING_HOME", None)
        shutil.rmtree(self.home, ignore_errors=True)

    def rows_by_word(self):
        return {r["word"]: r for r in appdb.query("SELECT * FROM vocab")}

    def _set(self, word, **cols):
        con = appdb.connect()
        try:
            with con:
                for col, val in cols.items():
                    con.execute(
                        f"UPDATE vocab SET {col} = ? WHERE word = ?", (val, word)
                    )
        finally:
            con.close()


class AddTest(VocabRepoBase):
    def test_add_new_word_starts_at_10_active(self):
        action, row = Vocab.add("Throughput", "пропускна здатність")
        self.assertEqual(action, "add")
        self.assertEqual(row["word"], "throughput")
        self.assertEqual(row["translation"], "пропускна здатність")
        self.assertEqual(row["remaining"], 10)
        self.assertEqual(row["status"], "active")

    def test_add_existing_active_refreshes_translation_keeps_remaining(self):
        Vocab.add("throughput", "old")
        self._set("throughput", remaining=7)
        action, row = Vocab.add("throughput", "new translation")
        self.assertEqual(action, "refresh")
        self.assertEqual(row["translation"], "new translation")
        self.assertEqual(row["remaining"], 7)

    def test_add_identity_translation_is_untranslated_and_not_saved(self):
        action, _ = Vocab.add("Awesome", "awesome")
        self.assertEqual(action, "untranslated")
        self.assertNotIn("awesome", self.rows_by_word())

    def test_add_empty_translation_is_untranslated_and_not_saved(self):
        action, _ = Vocab.add("throughput", "   ")
        self.assertEqual(action, "untranslated")
        self.assertNotIn("throughput", self.rows_by_word())

    def test_add_stamps_created_and_updated(self):
        with mock.patch("models.vocab._now", return_value="2026-06-12T08:00:00"):
            Vocab.add("throughput", "переклад")
        r = self.rows_by_word()["throughput"]
        self.assertEqual(r["created_at"], "2026-06-12T08:00:00")
        self.assertEqual(r["updated_at"], "2026-06-12T08:00:00")
        with mock.patch("models.vocab._now", return_value="2026-06-12T09:30:00"):
            Vocab.add("throughput", "новий переклад")
        r2 = self.rows_by_word()["throughput"]
        self.assertEqual(r2["created_at"], "2026-06-12T08:00:00")
        self.assertEqual(r2["updated_at"], "2026-06-12T09:30:00")

    def test_add_existing_learned_resets_to_10_active(self):
        Vocab.add("throughput", "t")
        self._set("throughput", remaining=0, status="learned")
        action, row = Vocab.add("throughput", "t2")
        self.assertEqual(action, "relearn")
        self.assertEqual(row["remaining"], 10)
        self.assertEqual(row["status"], "active")


class RemoveTest(VocabRepoBase):
    def test_remove_existing_returns_true_and_deletes(self):
        Vocab.add("throughput", "t")
        self.assertTrue(Vocab.remove("Throughput"))
        self.assertNotIn("throughput", self.rows_by_word())

    def test_remove_unknown_returns_false(self):
        self.assertFalse(Vocab.remove("nonexistent"))


class RelearnTest(VocabRepoBase):
    def test_relearn_resets_remaining_and_status(self):
        Vocab.add("throughput", "t")
        self._set("throughput", remaining=0, status="learned")
        Vocab.relearn("throughput")
        r = self.rows_by_word()["throughput"]
        self.assertEqual(r["remaining"], 10)
        self.assertEqual(r["status"], "active")


class MatchTest(VocabRepoBase):
    def test_long_word_matches_stem_suffixes(self):
        for text in ["throughput", "Throughput", "throughputs", "throughputed"]:
            self.assertTrue(word_in_text("throughput", text), text)

    def test_short_word_exact_only(self):
        self.assertTrue(word_in_text("log", "the log file"))
        self.assertFalse(word_in_text("log", "logging output"))

    def test_no_substring_false_match(self):
        self.assertFalse(word_in_text("cat", "category theory"))

    def test_punctuation_term_matches(self):
        self.assertTrue(word_in_text("c++", "I write C++ every day"))


class ListActiveTest(VocabRepoBase):
    def test_list_active_excludes_learned(self):
        Vocab.add("alpha", "а")
        Vocab.add("beta", "б")
        self._set("beta", status="learned")
        self.assertEqual([r["word"] for r in Vocab.list_active()], ["alpha"])


class ScanDecrementTest(VocabRepoBase):
    def test_decrements_matched_active_word(self):
        Vocab.add("throughput", "п")
        self.assertEqual(
            Vocab.scan_decrement("This improves throughput under load."),
            ["throughput"],
        )
        self.assertEqual(self.rows_by_word()["throughput"]["remaining"], 9)

    def test_ignores_absent_word(self):
        Vocab.add("throughput", "п")
        self.assertEqual(Vocab.scan_decrement("Nothing relevant here."), [])
        self.assertEqual(self.rows_by_word()["throughput"]["remaining"], 10)

    def test_graduates_at_zero(self):
        Vocab.add("throughput", "п")
        self._set("throughput", remaining=1)
        Vocab.scan_decrement("throughput throughput")
        row = self.rows_by_word()["throughput"]
        self.assertEqual(row["remaining"], 0)
        self.assertEqual(row["status"], "learned")

    def test_skips_learned_words(self):
        Vocab.add("throughput", "п")
        self._set("throughput", status="learned", remaining=0)
        self.assertEqual(Vocab.scan_decrement("throughput throughput"), [])


if __name__ == "__main__":
    unittest.main()
