import json
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
        r = Vocab.add("Throughput", "пропускна здатність")
        self.assertEqual(r["action"], "add")
        self.assertEqual(r["word"], "throughput")
        self.assertEqual(r["translation"], "пропускна здатність")
        self.assertEqual(r["remaining"], 10)
        self.assertEqual(r["status"], "active")

    def test_add_existing_active_refreshes_translation_keeps_remaining(self):
        Vocab.add("throughput", "old")
        self._set("throughput", remaining=7)
        r = Vocab.add("throughput", "new translation")
        self.assertEqual(r["action"], "refresh")
        self.assertEqual(r["translation"], "new translation")
        self.assertEqual(r["remaining"], 7)

    def test_add_identity_translation_is_untranslated_and_not_saved(self):
        r = Vocab.add("Awesome", "awesome")
        self.assertEqual(r, {"action": "untranslated", "word": "awesome"})
        self.assertNotIn("awesome", self.rows_by_word())

    def test_add_empty_translation_is_untranslated_and_not_saved(self):
        r = Vocab.add("throughput", "   ")
        self.assertEqual(r, {"action": "untranslated", "word": "throughput"})
        self.assertNotIn("throughput", self.rows_by_word())

    def test_add_stamps_created_and_updated(self):
        with mock.patch("core.now", return_value="2026-06-12T08:00:00"):
            Vocab.add("throughput", "переклад")
        r = self.rows_by_word()["throughput"]
        self.assertEqual(r["created_at"], "2026-06-12T08:00:00")
        self.assertEqual(r["updated_at"], "2026-06-12T08:00:00")
        with mock.patch("core.now", return_value="2026-06-12T09:30:00"):
            Vocab.add("throughput", "новий переклад")
        r2 = self.rows_by_word()["throughput"]
        self.assertEqual(r2["created_at"], "2026-06-12T08:00:00")
        self.assertEqual(r2["updated_at"], "2026-06-12T09:30:00")

    def test_add_existing_learned_resets_to_10_active(self):
        Vocab.add("throughput", "t")
        self._set("throughput", remaining=0, status="learned")
        r = Vocab.add("throughput", "t2")
        self.assertEqual(r["action"], "relearn")
        self.assertEqual(r["remaining"], 10)
        self.assertEqual(r["status"], "active")


class RemoveTest(VocabRepoBase):
    def test_remove_existing_returns_true_and_deletes(self):
        Vocab.add("throughput", "t")
        self.assertTrue(Vocab.remove("Throughput"))
        self.assertNotIn("throughput", self.rows_by_word())

    def test_remove_unknown_returns_false(self):
        self.assertFalse(Vocab.remove("nonexistent"))

    def test_remove_cascades_orphaned_mastery_row(self):
        Vocab.add("throughput", "t")
        con = appdb.connect()
        try:
            with con:
                con.execute(
                    "INSERT INTO mastery(item_kind, item_key, box, due_date,"
                    " last_verdict, created_at, updated_at)"
                    " VALUES ('vocab', 'throughput', 1, '2026-06-12', 'pass', 't', 't')"
                )
        finally:
            con.close()
        self.assertTrue(Vocab.remove("Throughput"))
        leftover = appdb.query(
            "SELECT * FROM mastery WHERE item_kind='vocab' AND item_key='throughput'"
        )
        self.assertEqual(leftover, [])

    def test_remove_leaves_other_kinds_mastery_untouched(self):
        Vocab.add("throughput", "t")
        con = appdb.connect()
        try:
            with con:
                con.execute(
                    "INSERT INTO mastery(item_kind, item_key, box, due_date,"
                    " last_verdict, created_at, updated_at)"
                    " VALUES ('grammar', 'throughput', 1, '2026-06-12',"
                    " 'pass', 't', 't')"
                )
        finally:
            con.close()
        Vocab.remove("throughput")
        kept = appdb.query(
            "SELECT * FROM mastery WHERE item_kind='grammar' AND item_key='throughput'"
        )
        self.assertEqual(len(kept), 1)


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

    def test_d_suffix_only_for_e_final_stems(self):
        # the bare 'd' inflection is for '-e' stems (care -> cared); applying it
        # to every word over-matched unrelated words and decremented the wrong
        # vocab entry.
        self.assertFalse(word_in_text("bear", "I grew a beard"))
        self.assertFalse(word_in_text("boar", "a wooden board"))
        self.assertFalse(word_in_text("bran", "a new brand"))
        # '-e' stems still match their 'd' inflection:
        self.assertTrue(word_in_text("care", "she cared"))
        self.assertTrue(word_in_text("love", "he loved it"))


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


class AddRaceTest(VocabRepoBase):
    # True concurrency (two processes first-adding the same word at once) is not
    # unit-tested here; the guarantee is the BEGIN IMMEDIATE write lock that tx()
    # takes around the existence SELECT + the INSERT, which serializes the
    # read-then-write so two callers can't both see None and double-INSERT. This
    # pins the single-process invariant: add-then-add of the same word is
    # add -> refresh, never raises, and leaves exactly one row.
    def test_repeat_add_is_idempotent_single_row(self):
        a1 = Vocab.add("throughput", "переклад")
        a2 = Vocab.add("throughput", "новий переклад")
        self.assertEqual(a1["action"], "add")
        self.assertEqual(a2["action"], "refresh")
        self.assertEqual(
            appdb.query("SELECT word FROM vocab"), [{"word": "throughput"}]
        )


class AddConTest(VocabRepoBase):
    def test_add_con_inserts_inside_caller_tx(self):
        con = appdb.connect()
        try:
            with appdb.tx(con):
                r = Vocab.add("Throughput", "пропускна здатність", con=con)
        finally:
            con.close()
        self.assertEqual(r["action"], "add")
        self.assertEqual(r["word"], "throughput")
        self.assertEqual(self.rows_by_word()["throughput"]["remaining"], 10)

    def test_add_con_reads_back_its_own_write_in_tx(self):
        con = appdb.connect()
        try:
            with appdb.tx(con):
                Vocab.add("throughput", "old", con=con)
                r = Vocab.add("throughput", "new translation", con=con)
        finally:
            con.close()
        self.assertEqual(r["action"], "refresh")
        self.assertEqual(r["translation"], "new translation")

    def test_add_con_untranslated_writes_nothing(self):
        con = appdb.connect()
        try:
            with appdb.tx(con):
                r = Vocab.add("awesome", "awesome", con=con)
        finally:
            con.close()
        self.assertEqual(r, {"action": "untranslated", "word": "awesome"})
        self.assertNotIn("awesome", self.rows_by_word())

    def test_add_con_relearns_learned_word(self):
        Vocab.add("throughput", "t")
        self._set("throughput", remaining=0, status="learned")
        con = appdb.connect()
        try:
            with appdb.tx(con):
                r = Vocab.add("throughput", "t2", con=con)
        finally:
            con.close()
        self.assertEqual(r["action"], "relearn")
        self.assertEqual(self.rows_by_word()["throughput"]["remaining"], 10)
        self.assertEqual(self.rows_by_word()["throughput"]["status"], "active")


class EnrichmentUpsertTest(VocabRepoBase):
    def test_add_new_word_with_enrichment_round_trips_json(self):
        Vocab.add(
            "Throughput",
            "пропускна здатність",
            definition="rate of processing",
            source_context="It improves throughput.",
            examples=["Throughput is high.", "We measured throughput."],
            synonyms=["rate", "bandwidth"],
        )
        r = self.rows_by_word()["throughput"]
        self.assertEqual(r["definition"], "rate of processing")
        self.assertEqual(r["source_context"], "It improves throughput.")
        self.assertEqual(
            json.loads(r["examples"]),
            ["Throughput is high.", "We measured throughput."],
        )
        self.assertEqual(json.loads(r["synonyms"]), ["rate", "bandwidth"])

    def test_enrichment_overwrites_only_provided_columns(self):
        Vocab.add("w", "t", examples=["old one with w"], definition="old def")
        Vocab.add("w", "t", examples=["new one with w"])  # synonyms/def NOT provided
        r = self.rows_by_word()["w"]
        self.assertEqual(json.loads(r["examples"]), ["new one with w"])
        self.assertEqual(r["definition"], "old def")  # untouched — not provided

    def test_bare_add_does_not_wipe_existing_enrichment(self):
        # debrief's friction-loot path: Vocab.add(word, translation), no enrichment
        Vocab.add("w", "t", examples=["grounded w example"], source_context="ctx")
        Vocab.add("w", "t2")  # bare refresh
        r = self.rows_by_word()["w"]
        self.assertEqual(r["translation"], "t2")
        self.assertEqual(json.loads(r["examples"]), ["grounded w example"])
        self.assertEqual(r["source_context"], "ctx")  # preserved

    def test_relearn_path_also_writes_provided_enrichment(self):
        Vocab.add("w", "t")
        self._set("w", remaining=0, status="learned")
        r = Vocab.add("w", "t2", examples=["w again"])
        self.assertEqual(r["action"], "relearn")
        row = self.rows_by_word()["w"]
        self.assertEqual(row["status"], "active")
        self.assertEqual(row["remaining"], 10)
        self.assertEqual(json.loads(row["examples"]), ["w again"])


class GetManyTest(VocabRepoBase):
    def test_returns_existing_rows_and_omits_absent(self):
        Vocab.add("alpha", "а")
        Vocab.add("beta", "б")
        got = Vocab.get_many(["Alpha", "beta", "missing"])
        self.assertEqual(set(got), {"alpha", "beta"})
        self.assertEqual(got["alpha"]["translation"], "а")

    def test_empty_input_returns_empty(self):
        self.assertEqual(Vocab.get_many([]), {})


if __name__ == "__main__":
    unittest.main()
