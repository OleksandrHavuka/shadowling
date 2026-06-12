import contextlib
import io
import json
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
                        "INSERT INTO grammar(date, slug, problem, original,"
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
            "SELECT * FROM mastery WHERE item_kind='{0}' AND item_key='{1}'"
            .format(kind, key))
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

    def test_leitner_transitions(self):
        self.seed_grammar()
        def rec(verdict):
            with mock.patch("tutor._today", return_value="2026-06-12"):
                run_main(["record", "grammar", "article-omission", "fix",
                          verdict], stdin_text="x")
        rec("pass"); rec("pass")
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


if __name__ == "__main__":
    unittest.main()
