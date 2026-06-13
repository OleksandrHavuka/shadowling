import contextlib
import io
import os
import shutil
import tempfile
import unittest
from unittest import mock

import appdb
import tutor


def run_main(argv, stdin_text=""):
    out, err = io.StringIO(), io.StringIO()
    old = tutor.sys.stdin
    tutor.sys.stdin = io.StringIO(stdin_text)
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = tutor.main(argv)
    finally:
        tutor.sys.stdin = old
    return code, out.getvalue(), err.getvalue()


class TutorTestBase(unittest.TestCase):
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
                        (slug,))
        finally:
            con.close()

    def seed_vocab(self, word="throughput", status="learned"):
        con = appdb.connect()
        try:
            with con:
                con.execute(
                    "INSERT INTO vocab(word, translation, remaining, status)"
                    " VALUES (?, 'переклад', 0, ?)", (word, status))
        finally:
            con.close()

    def mastery(self, kind, key):
        rows = appdb.query(
            "SELECT * FROM mastery WHERE item_kind=? AND item_key=?"
            if False else
            f"SELECT * FROM mastery WHERE item_kind='{kind}' AND item_key='{key}'"
            )
        return rows[0] if rows else None


class RecordTest(TutorTestBase):
    def test_record_inserts_attempt_and_mastery(self):
        self.seed_grammar()
        with mock.patch("tutor._today", return_value="2026-06-12"):
            code, out, _ = run_main(
                ["record", "grammar", "article-omission", "fix", "pass"],
                stdin_text="I went to the store")
        self.assertEqual(code, 0)
        a = appdb.query("SELECT * FROM attempts")[0]
        self.assertEqual(a["answer"], "I went to the store")
        self.assertEqual(a["session_id"], "sess-T")
        self.assertEqual(a["verdict"], "pass")
        m = self.mastery("grammar", "article-omission")
        self.assertEqual(m["box"], 2)                  # pass: 1 -> 2
        self.assertEqual(m["due_date"], "2026-06-15")  # +3 days (box 2)
        self.assertEqual(m["counter_seen"], 1)

    def test_attempt_created_at_full_ts_and_mastery_stamps(self):
        self.seed_grammar()
        with mock.patch("tutor._today", return_value="2026-06-12"), \
                mock.patch("tutor._now", return_value="2026-06-12T09:00:00"):
            run_main(["record", "grammar", "article-omission", "fix", "pass"],
                     stdin_text="x")
        a = appdb.query("SELECT * FROM attempts")[0]
        self.assertEqual(a["created_at"], "2026-06-12T09:00:00")  # full ISO ts
        m = self.mastery("grammar", "article-omission")
        self.assertEqual(m["created_at"], "2026-06-12T09:00:00")
        self.assertEqual(m["updated_at"], "2026-06-12T09:00:00")  # equal on insert
        with mock.patch("tutor._today", return_value="2026-06-12"), \
                mock.patch("tutor._now", return_value="2026-06-12T10:30:00"):
            run_main(["record", "grammar", "article-omission", "fix", "pass"],
                     stdin_text="y")
        m2 = self.mastery("grammar", "article-omission")
        self.assertEqual(m2["created_at"], "2026-06-12T09:00:00")   # pinned
        self.assertEqual(m2["updated_at"], "2026-06-12T10:30:00")   # bumped

    def test_leitner_transitions(self):
        self.seed_grammar()
        def rec(verdict):
            with mock.patch("tutor._today", return_value="2026-06-12"):
                run_main(["record", "grammar", "article-omission", "fix",
                          verdict], stdin_text="x")
        rec("pass")
        rec("pass")
        self.assertEqual(self.mastery("grammar", "article-omission")["box"], 3)
        rec("partial")                                  # stays
        self.assertEqual(self.mastery("grammar", "article-omission")["box"], 3)
        rec("fail")                                     # back to 1
        m = self.mastery("grammar", "article-omission")
        self.assertEqual(m["box"], 1)
        self.assertEqual(m["due_date"], "2026-06-13")   # +1 day (box 1)

    def test_box_caps_at_5(self):
        self.seed_grammar()
        for _ in range(7):
            with mock.patch("tutor._today", return_value="2026-06-12"):
                run_main(["record", "grammar", "article-omission", "fix",
                          "pass"], stdin_text="x")
        m = self.mastery("grammar", "article-omission")
        self.assertEqual(m["box"], 5)
        self.assertEqual(m["due_date"], "2026-07-17")   # +35 days

    def test_answer_verbatim_with_quotes_and_newlines(self):
        self.seed_grammar()
        tricky = 'he said "it\'s done" — `rm -rf` & $HOME\nsecond line'
        run_main(["record", "grammar", "article-omission", "fix", "pass"],
                 stdin_text=tricky)
        self.assertEqual(appdb.query("SELECT answer FROM attempts")[0]["answer"],
                         tricky)

    def test_vocab_fail_triggers_relearn(self):
        self.seed_vocab("throughput", status="learned")
        run_main(["record", "vocab", "throughput", "reverse", "fail"],
                 stdin_text="wrong word")
        row = appdb.query("SELECT * FROM vocab")[0]
        self.assertEqual(row["status"], "active")
        self.assertEqual(row["remaining"], 10)
        m = self.mastery("vocab", "throughput")
        self.assertIsNone(m["counter_seen"])            # vocab has no counter

    def test_bad_verdict_or_kind_is_error(self):
        self.assertEqual(run_main(["record", "grammar", "k", "fix", "maybe"],
                                  stdin_text="x")[0], 1)
        self.assertEqual(run_main(["record", "nosuch", "k", "fix", "pass"],
                                  stdin_text="x")[0], 1)


class DeckTest(TutorTestBase):
    def _mastery_row(self, kind, key, box, due, counter_seen=None):
        con = appdb.connect()
        try:
            with con:
                con.execute(
                    "INSERT INTO mastery(item_kind, item_key, box, due_date,"
                    " last_verdict, counter_seen, created_at, updated_at)"
                    " VALUES (?, ?, ?, ?, 'pass', ?, 't', 't')",
                    (kind, key, box, due, counter_seen))
        finally:
            con.close()

    def test_new_items_ranked_by_counter(self):
        self.seed_grammar("rare", n=1)
        self.seed_grammar("frequent", n=3)
        with mock.patch("tutor._today", return_value="2026-06-12"):
            cards = tutor.deck(8)
        keys = [c["item_key"] for c in cards if c["item_kind"] == "grammar"]
        self.assertEqual(keys, ["frequent", "rare"])
        card = cards[0]
        self.assertEqual(card["exercise"], "fix")
        self.assertEqual(card["prompt_data"]["original"], "I went to store")
        self.assertEqual(card["prompt_data"]["fixed"], "I went to the store")

    def test_due_before_new_and_overdue_first(self):
        self.seed_grammar("s-due-old")
        self.seed_grammar("s-due-new")
        self.seed_grammar("s-fresh")
        self._mastery_row("grammar", "s-due-old", 2, "2026-06-10")
        self._mastery_row("grammar", "s-due-new", 2, "2026-06-12")
        self._mastery_row("grammar", "s-fresh", 2, "2026-07-01")  # not due
        with mock.patch("tutor._today", return_value="2026-06-12"):
            keys = [c["item_key"] for c in tutor.deck(8)]
        self.assertEqual(keys[:2], ["s-due-old", "s-due-new"])
        self.assertNotIn("s-fresh", keys)

    def test_hot_zone_boost_jumps_queue(self):
        self.seed_grammar("calm", n=1)
        self.seed_grammar("hot", n=3)        # counter now 3
        self._mastery_row("grammar", "calm", 2, "2026-06-10")
        self._mastery_row("grammar", "hot", 2, "2026-06-11", counter_seen=1)
        with mock.patch("tutor._today", return_value="2026-06-12"):
            keys = [c["item_key"] for c in tutor.deck(8)]
        self.assertEqual(keys[0], "hot")     # boosted past the older due
        self.assertEqual(keys[1], "calm")

    def test_mix_cap_half_per_kind(self):
        for i in range(8):
            self.seed_grammar(f"g{i}")
        self.seed_vocab("alpha")
        self.seed_vocab("beta")
        with mock.patch("tutor._today", return_value="2026-06-12"):
            cards = tutor.deck(4)
        kinds = [c["item_kind"] for c in cards]
        self.assertEqual(len(cards), 4)
        self.assertLessEqual(kinds.count("grammar"), 2)
        self.assertIn("vocab", kinds)

    def test_vocab_card_prompt_data(self):
        self.seed_vocab("throughput", status="learned")
        with mock.patch("tutor._today", return_value="2026-06-12"):
            cards = [c for c in tutor.deck(8) if c["item_kind"] == "vocab"]
        self.assertEqual(cards[0]["exercise"], "reverse")
        self.assertEqual(cards[0]["prompt_data"]["translation"], "переклад")

    def test_active_vocab_not_drilled(self):
        self.seed_vocab("active-word", status="active")
        with mock.patch("tutor._today", return_value="2026-06-12"):
            self.assertEqual(tutor.deck(8), [])


class StatsTest(TutorTestBase):
    def test_stats_counts_due(self):
        self.seed_grammar("s1")
        con = appdb.connect()
        try:
            with con:
                con.execute(
                    "INSERT INTO mastery(item_kind, item_key, box, due_date,"
                    " last_verdict, created_at, updated_at)"
                    " VALUES ('grammar','s1',1,'2026-06-12','fail','t','t')")
                con.execute(
                    "INSERT INTO mastery(item_kind, item_key, box, due_date,"
                    " last_verdict, created_at, updated_at)"
                    " VALUES ('grammar','s2',2,'2026-06-13','pass','t','t')")
        finally:
            con.close()
        with mock.patch("tutor._today", return_value="2026-06-12"):
            s = tutor.stats()
        self.assertEqual(s["due_today"], 1)
        self.assertEqual(s["due_tomorrow"], 1)
        self.assertEqual(s["mastered" if "mastered" in s else "tracked"], 2)


if __name__ == "__main__":
    unittest.main()
