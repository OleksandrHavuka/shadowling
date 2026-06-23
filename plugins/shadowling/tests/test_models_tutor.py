import os
import shutil
import tempfile
import unittest
from unittest import mock

import appdb
from models.tutor import Tutor


class TutorRepoBase(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        os.environ["SHADOWLING_HOME"] = self.home
        os.environ["CLAUDE_CODE_SESSION_ID"] = "sess-T"

    def tearDown(self):
        os.environ.pop("SHADOWLING_HOME", None)
        os.environ.pop("CLAUDE_CODE_SESSION_ID", None)
        shutil.rmtree(self.home, ignore_errors=True)

    def seed_grammar(self, slug="article-omission", n=1):
        con = appdb.connect()
        try:
            with con:
                for _ in range(n):
                    con.execute(
                        "INSERT INTO grammar(created_at, slug, problem, original,"
                        " fixed, rule) VALUES ('2026-06-12', ?, 'p',"
                        " 'I went to store', 'I went to the store', 'use the')",
                        (slug,),
                    )
        finally:
            con.close()

    def seed_vocab(self, word="throughput", status="learned"):
        con = appdb.connect()
        try:
            with con:
                con.execute(
                    "INSERT INTO vocab(word, translation, remaining, status, examples)"
                    " VALUES (?, 'переклад', 0, ?, json(?))",
                    (word, status, f'["The {word} was impressive."]'),
                )
        finally:
            con.close()

    def mastery(self, kind, key):
        rows = appdb.query(
            f"SELECT * FROM mastery WHERE item_kind='{kind}' AND item_key='{key}'"
        )
        return rows[0] if rows else None


class RecordTest(TutorRepoBase):
    def test_record_inserts_attempt_and_mastery(self):
        self.seed_grammar()
        with mock.patch("models.tutor._today", return_value="2026-06-12"):
            out = Tutor.record(
                "grammar", "article-omission", "fix", "pass", "I went to the store"
            )
        self.assertEqual(out, 2)  # the new box
        a = appdb.query("SELECT * FROM attempts")[0]
        self.assertEqual(a["answer"], "I went to the store")
        self.assertEqual(a["session_id"], "sess-T")
        m = self.mastery("grammar", "article-omission")
        self.assertEqual(m["box"], 2)
        self.assertEqual(m["due_date"], "2026-06-15")
        self.assertEqual(m["counter_seen"], 1)

    def test_leitner_transitions(self):
        self.seed_grammar()

        def rec(verdict):
            with mock.patch("models.tutor._today", return_value="2026-06-12"):
                Tutor.record("grammar", "article-omission", "fix", verdict, "x")

        rec("pass")
        rec("pass")
        self.assertEqual(self.mastery("grammar", "article-omission")["box"], 3)
        rec("partial")
        self.assertEqual(self.mastery("grammar", "article-omission")["box"], 3)
        rec("fail")
        self.assertEqual(self.mastery("grammar", "article-omission")["box"], 1)

    def test_vocab_fail_triggers_relearn(self):
        self.seed_vocab("throughput", status="learned")
        Tutor.record("vocab", "throughput", "reverse", "fail", "wrong word")
        row = appdb.query("SELECT * FROM vocab")[0]
        self.assertEqual(row["status"], "active")
        self.assertEqual(row["remaining"], 10)
        self.assertIsNone(self.mastery("vocab", "throughput")["counter_seen"])

    def test_vocab_fail_relearn_is_atomic_with_attempt_and_mastery(self):
        # The vocab reset runs inside record()'s transaction now: if it fails, the
        # attempt + mastery writes roll back too (all-or-nothing). On the old code
        # relearn ran on a separate connection after the commit, so the attempt
        # survived — this test would catch that regression.
        self.seed_vocab("throughput", status="learned")
        with mock.patch("models.tutor.Vocab.relearn", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                Tutor.record("vocab", "throughput", "reverse", "fail", "wrong")
        self.assertEqual(appdb.query("SELECT COUNT(*) AS c FROM attempts")[0]["c"], 0)
        self.assertIsNone(self.mastery("vocab", "throughput"))
        row = appdb.query("SELECT * FROM vocab")[0]
        self.assertEqual(row["status"], "learned")  # reset rolled back
        self.assertEqual(row["remaining"], 0)

    def test_bad_verdict_or_kind_raises(self):
        with self.assertRaises(ValueError):
            Tutor.record("grammar", "k", "fix", "maybe", "x")
        with self.assertRaises(ValueError):
            Tutor.record("nosuch", "k", "fix", "pass", "x")

    def test_record_stamps_counter_seen_calling_counter_once(self):
        import models.tutor as tutor_mod

        self.seed_grammar("article-omission", n=2)  # counter == 2 in the view
        with mock.patch.object(tutor_mod, "_counter", wraps=tutor_mod._counter) as spy:
            with mock.patch("models.tutor._today", return_value="2026-06-12"):
                Tutor.record("grammar", "article-omission", "fix", "pass", "x")
        m = self.mastery("grammar", "article-omission")
        self.assertEqual(m["counter_seen"], 2)
        self.assertEqual(spy.call_count, 1)


class DeckTest(TutorRepoBase):
    def _mastery_row(self, kind, key, box, due, counter_seen=None):
        con = appdb.connect()
        try:
            with con:
                con.execute(
                    "INSERT INTO mastery(item_kind, item_key, box, due_date,"
                    " last_verdict, counter_seen, created_at, updated_at)"
                    " VALUES (?, ?, ?, ?, 'pass', ?, 't', 't')",
                    (kind, key, box, due, counter_seen),
                )
        finally:
            con.close()

    def test_new_items_ranked_by_counter(self):
        self.seed_grammar("rare", n=1)
        self.seed_grammar("frequent", n=3)
        with mock.patch("models.tutor._today", return_value="2026-06-12"):
            cards = Tutor.deck(8)
        keys = [c["item_key"] for c in cards if c["item_kind"] == "grammar"]
        self.assertEqual(keys, ["frequent", "rare"])
        self.assertEqual(cards[0]["exercise"], "fix")
        self.assertEqual(cards[0]["original"], "I went to store")
        self.assertNotIn("prompt_data", cards[0])

    def test_hot_zone_boost_jumps_queue(self):
        self.seed_grammar("calm", n=1)
        self.seed_grammar("hot", n=3)
        self._mastery_row("grammar", "calm", 2, "2026-06-10")
        self._mastery_row("grammar", "hot", 2, "2026-06-11", counter_seen=1)
        with mock.patch("models.tutor._today", return_value="2026-06-12"):
            keys = [c["item_key"] for c in Tutor.deck(8)]
        self.assertEqual(keys[0], "hot")
        self.assertEqual(keys[1], "calm")

    def test_mix_cap_half_per_kind(self):
        for i in range(8):
            self.seed_grammar(f"g{i}")
        self.seed_vocab("alpha")
        self.seed_vocab("beta")
        with mock.patch("models.tutor._today", return_value="2026-06-12"):
            cards = Tutor.deck(4)
        kinds = [c["item_kind"] for c in cards]
        self.assertEqual(len(cards), 4)
        self.assertLessEqual(kinds.count("grammar"), 2)
        self.assertIn("vocab", kinds)

    def test_vocab_card_prompt_data(self):
        self.seed_vocab("throughput", status="learned")
        with mock.patch("models.tutor._today", return_value="2026-06-12"):
            cards = [c for c in Tutor.deck(8) if c["item_kind"] == "vocab"]
        self.assertEqual(cards[0]["exercise"], "reverse")
        self.assertEqual(cards[0]["translation"], "переклад")

    def test_active_vocab_not_drilled(self):
        self.seed_vocab("active-word", status="active")
        with mock.patch("models.tutor._today", return_value="2026-06-12"):
            self.assertEqual(Tutor.deck(8), [])

    def test_uneven_pool_fills_to_size_with_backfill(self):
        # 10 grammar + 1 verb + 1 vocab learned/new => 12 candidates. Old
        # single-pass code stops grammar at cap=4 and, with >1 kind available,
        # under-fills the rest of the deck. Two-pass must reach size.
        for i in range(10):
            self.seed_grammar(f"g{i}")
        con = appdb.connect()
        try:
            with con:
                con.execute(
                    "INSERT INTO verbs(created_at, verb, past, participle,"
                    " used_form, correction, context) VALUES ('2026-06-12',"
                    " 'go', 'went', 'gone', 'goed', 'went', 'ctx')"
                )
        finally:
            con.close()
        self.seed_vocab("alpha", status="learned")
        with mock.patch("models.tutor._today", return_value="2026-06-12"):
            cards = Tutor.deck(8)
        self.assertEqual(len(cards), 8)
        kinds = [c["item_kind"] for c in cards]
        self.assertEqual(kinds.count("verbs"), 1)
        self.assertEqual(kinds.count("vocab"), 1)
        self.assertEqual(kinds.count("grammar"), 6)

    def test_balanced_pool_respects_cap(self):
        for i in range(6):
            self.seed_grammar(f"g{i}")
        for i in range(6):
            self.seed_vocab(f"v{i}", status="learned")
        with mock.patch("models.tutor._today", return_value="2026-06-12"):
            cards = Tutor.deck(8)
        kinds = [c["item_kind"] for c in cards]
        self.assertEqual(len(cards), 8)
        self.assertEqual(kinds.count("grammar"), 4)
        self.assertEqual(kinds.count("vocab"), 4)

    def test_hollow_card_skipped_and_does_not_displace_real_card(self):
        # A vocab key with a due mastery row but NO vocab row (drilled, then
        # the word was dropped). PROMPT_SQL['vocab'] finds nothing, so the card
        # is hollow and must neither appear nor consume a slot.
        self._mastery_row("vocab", "ghost", 1, "2026-06-10")
        self.seed_grammar("real")
        with mock.patch("models.tutor._today", return_value="2026-06-12"):
            cards = Tutor.deck(1)
        keys = [(c["item_kind"], c["item_key"]) for c in cards]
        self.assertNotIn(("vocab", "ghost"), keys)
        self.assertEqual(keys, [("grammar", "real")])


class StatsTest(TutorRepoBase):
    def test_stats_counts_due(self):
        con = appdb.connect()
        try:
            with con:
                con.execute(
                    "INSERT INTO mastery(item_kind, item_key, box, due_date,"
                    " last_verdict, created_at, updated_at)"
                    " VALUES ('grammar','s1',1,'2026-06-12','fail','t','t')"
                )
                con.execute(
                    "INSERT INTO mastery(item_kind, item_key, box, due_date,"
                    " last_verdict, created_at, updated_at)"
                    " VALUES ('grammar','s2',2,'2026-06-13','pass','t','t')"
                )
        finally:
            con.close()
        with mock.patch("models.tutor._today", return_value="2026-06-12"):
            s = Tutor.stats()
        self.assertEqual(s["due_today"], 1)
        self.assertEqual(s["due_tomorrow"], 1)
        self.assertEqual(s["tracked"], 2)


if __name__ == "__main__":
    unittest.main()
