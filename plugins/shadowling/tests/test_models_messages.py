import json
import os
import shutil
import sqlite3
import tempfile
import unittest
from contextlib import closing

import appdb
from models.messages import DRILL_SIMILARITY, Messages


def closing_con():
    return closing(appdb.connect())


class MessagesRepoBase(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        os.environ["SHADOWLING_HOME"] = self.home

    def tearDown(self):
        os.environ.pop("SHADOWLING_HOME", None)
        shutil.rmtree(self.home, ignore_errors=True)

    def _rows(self):
        return appdb.query(
            "SELECT id, created_at, text, langs, processed_at FROM messages ORDER BY id"
        )


class CaptureTest(MessagesRepoBase):
    def test_english_message_stored(self):
        self.assertTrue(Messages.capture("Despite the delay we finished it", "s"))
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["text"], "Despite the delay we finished it")

    def test_too_short_not_stored(self):
        self.assertFalse(Messages.capture("ok thx", "s"))
        self.assertEqual(self._rows(), [])

    def test_slash_command_not_stored(self):
        self.assertFalse(Messages.capture("/drop throughput please now", "s"))
        self.assertEqual(self._rows(), [])

    def test_command_wrapper_not_stored(self):
        self.assertFalse(Messages.capture("<command-name>debrief</command-name>", "s"))
        self.assertEqual(self._rows(), [])

    def test_same_text_twice_not_duplicated(self):
        self.assertTrue(Messages.capture("This is a perfectly normal sentence", "s"))
        self.assertFalse(Messages.capture("This is a perfectly normal sentence", "s"))
        self.assertEqual(len(self._rows()), 1)

    def test_empty_text_not_stored(self):
        self.assertFalse(Messages.capture("", "s"))
        self.assertFalse(Messages.capture(None, "s"))

    def test_capture_stores_session_id(self):
        Messages.capture("First normal english sentence here please", "sess-A")
        Messages.capture("Second message in another working session", "sess-B")
        rows = appdb.query("SELECT session_id FROM messages ORDER BY id")
        self.assertEqual([r["session_id"] for r in rows], ["sess-A", "sess-B"])


class TagTest(MessagesRepoBase):
    def setUp(self):
        super().setUp()
        Messages.capture("First normal english sentence here please", "s")
        Messages.capture("друге повідомлення суто українською мовою", "s")

    def test_tag_single_and_multi_code(self):
        n = Messages.tag([{"id": "1", "langs": "en"}, {"id": "2", "langs": "en,uk"}])
        self.assertEqual(n, 2)
        rows = self._rows()
        self.assertEqual(json.loads(rows[0]["langs"]), ["en"])
        self.assertEqual(json.loads(rows[1]["langs"]), ["en", "uk"])

    def test_tag_unknown_id_not_counted(self):
        self.assertEqual(Messages.tag([{"id": "999", "langs": "en"}]), 0)

    def test_tag_non_numeric_id_matches_nothing(self):
        # a non-numeric id can't match the INTEGER pk; persistence-only -> no
        # crash, just no update (the old in-model validation is gone).
        self.assertEqual(Messages.tag([{"id": "²", "langs": "es"}]), 0)

    def test_tag_strips_blank_codes(self):
        n = Messages.tag([{"id": "1", "langs": "en, ,uk"}])
        self.assertEqual(n, 1)
        self.assertEqual(json.loads(self._rows()[0]["langs"]), ["en", "uk"])


class ListTest(MessagesRepoBase):
    def setUp(self):
        super().setUp()
        Messages.capture("First normal english sentence here please", "s")
        Messages.capture("друге повідомлення суто українською мовою", "s")
        Messages.capture("third message чи mixed повідомлення разом", "s")
        with closing_con() as con, con:  # row 3 left untagged
            con.execute("UPDATE messages SET langs = ? WHERE id = 1", ('["en"]',))
            con.execute("UPDATE messages SET langs = ? WHERE id = 2", ('["uk"]',))

    def test_lists_all_unprocessed_as_rows(self):
        rows = Messages.list()
        self.assertEqual([r["id"] for r in rows], [1, 2, 3])
        self.assertEqual(rows[0]["langs"], '["en"]')
        self.assertIsNone(rows[2]["langs"])  # row 3 untagged
        self.assertIn("id", rows[0])
        self.assertIn("created_at", rows[0])
        self.assertIn("text", rows[0])

    def test_untagged_slice(self):
        rows = Messages.list(untagged=True)
        self.assertEqual([r["id"] for r in rows], [3])

    def test_lang_slice_includes_mixed(self):
        with closing_con() as con, con:
            con.execute("UPDATE messages SET langs = ? WHERE id = 3", ('["en","uk"]',))
        rows = Messages.list(lang="en")
        self.assertEqual([r["id"] for r in rows], [1, 3])

    def test_limit_zero_empty(self):
        self.assertEqual(Messages.list(untagged=True, limit=0), [])


class SessionsAndMarkTest(MessagesRepoBase):
    def setUp(self):
        super().setUp()
        Messages.capture("First normal english sentence here please", "sess-A")
        Messages.capture("Second message in another working session", "sess-B")
        Messages.capture("Third message back in the first session!", "sess-A")

    def test_sessions_lists_pending_per_session(self):
        self.assertEqual(
            Messages.sessions(),
            [{"session": "sess-A", "pending": 2}, {"session": "sess-B", "pending": 1}],
        )

    def test_pending_count(self):
        self.assertEqual(Messages.pending_count(), 3)

    def test_mark_processed_session_scoped(self):
        Messages.tag(
            [{"id": "1", "langs": "en"}, {"id": "3", "langs": "en"}]
        )  # id 2 untagged
        out = Messages.mark_processed(session="sess-A")
        rows = appdb.query(
            "SELECT id, processed_at IS NOT NULL AS p FROM messages ORDER BY id"
        )
        self.assertEqual([(r["id"], r["p"]) for r in rows], [(1, 1), (2, 0), (3, 1)])
        self.assertEqual(out, {"processed": 2, "kept": 1})

    def test_mark_processed_empty_targets_null_session_group_only(self):
        # add a row whose session_id IS NULL (sessions() can emit {"session": null})
        with closing_con() as con, con:
            con.execute(
                "INSERT INTO messages(created_at, text, session_id, langs)"
                " VALUES ('t', 'A standalone null-session sentence here',"
                " NULL, '[\"en\"]')"
            )
        Messages.tag(
            [
                {"id": "1", "langs": "en"},
                {"id": "2", "langs": "en"},
                {"id": "3", "langs": "en"},
            ]
        )  # tag the seeded session rows

        out = Messages.mark_processed("")  # falsy -> NULL group, NOT global
        rows = appdb.query(
            "SELECT id, processed_at IS NOT NULL AS p FROM messages ORDER BY id"
        )
        self.assertEqual(
            [(r["id"], r["p"]) for r in rows],
            [(1, 0), (2, 0), (3, 0), (4, 1)],
        )
        self.assertEqual(out["processed"], 1)

        out2 = Messages.mark_processed(None)  # same: only the NULL group
        rows2 = appdb.query(
            "SELECT id, processed_at IS NOT NULL AS p FROM messages ORDER BY id"
        )
        self.assertEqual(
            [(r["id"], r["p"]) for r in rows2],
            [(1, 0), (2, 0), (3, 0), (4, 1)],
        )
        self.assertEqual(out2["processed"], 0)


class MarkDrillsTest(MessagesRepoBase):
    def _attempt(self, answer, session="sess-A"):
        with closing_con() as con:
            with con:
                con.execute(
                    "INSERT INTO attempts(created_at, session_id, item_kind,"
                    " item_key, exercise, answer, verdict) VALUES ('t', ?,"
                    " 'grammar', 'k', 'fix', ?, 'pass')",
                    (session, answer),
                )

    def test_exact_and_drifted_matches_marked(self):
        Messages.capture("I have gone to the gym today okay", "sess-A")
        Messages.capture("I see it differently - here is my concern", "sess-A")
        self._attempt("I have gone to the gym today okay")
        self._attempt("I see it differently -  here is my concern ")
        out = Messages.mark_drills()
        rows = appdb.query("SELECT kind FROM messages ORDER BY id")
        self.assertEqual([r["kind"] for r in rows], ["drill", "drill"])
        self.assertEqual(out, 2)

    def test_return_has_no_unmatched_tail(self):
        Messages.capture("I have gone to the gym today okay", "sess-A")
        self._attempt("I have gone to the gym today okay")
        self._attempt("a recorded answer that was never captured at all")
        out = Messages.mark_drills()
        self.assertEqual(out, 1)

    def test_empty_recorded_answer_does_not_mark_drill(self):
        with closing_con() as con, con:
            con.execute(
                "INSERT INTO messages(created_at, text, session_id)"
                " VALUES ('t', '   ', 'sess-A')"
            )
            con.execute(
                "INSERT INTO messages(created_at, text, session_id)"
                " VALUES ('t', 'A perfectly ordinary unrelated sentence here',"
                " 'sess-A')"
            )
        self._attempt("")  # blank recorded answer in the same session
        out = Messages.mark_drills()
        rows = appdb.query("SELECT kind FROM messages ORDER BY id")
        self.assertEqual([r["kind"] for r in rows], [None, None])
        self.assertEqual(out, 0)

    def test_similarity_characterization(self):
        # Comprehensive pin of _similarity around DRILL_SIMILARITY (0.90) — the
        # matcher's safety net that replaces the removed runtime `unmatched` metric.
        sim = Messages._similarity
        gate = DRILL_SIMILARITY
        self.assertEqual(gate, 0.90)

        # TRUE POSITIVES: a captured drill answer the matcher MUST recognize
        self.assertGreaterEqual(sim("I have gone home", "I have gone home"), gate)
        self.assertGreaterEqual(sim("I have gone home", "I HAVE GONE HOME"), gate)
        self.assertGreaterEqual(sim("I have gone home", "   I have gone home   "), gate)
        self.assertGreaterEqual(sim("I have gone home", "I  have   gone home"), gate)
        self.assertGreaterEqual(sim("I have gone home", "I have gone home!"), gate)
        self.assertGreaterEqual(
            sim("I have gone to the gym today", "  i Have Gone To The Gym Today.  "),
            gate,
        )
        self.assertGreaterEqual(
            sim(
                "Despite the delay we finally finished the report",
                "Despite the delay we finally finished that report",
            ),
            gate,
        )

        # TRUE NEGATIVES: text the matcher MUST NOT call a drill
        self.assertLess(
            sim(
                "I have gone to the gym today",
                "The weather forecast looks completely different tomorrow",
            ),
            gate,
        )
        self.assertLess(sim("went, gone", "went home"), gate)
        self.assertLess(sim("go to the store", "go to the park instead"), gate)


class ReadOnlyQueryTest(MessagesRepoBase):
    def test_appdb_query_is_read_only(self):
        Messages.capture("First normal english sentence here please", "s")
        with self.assertRaises(sqlite3.Error):
            appdb.query("DELETE FROM messages")


if __name__ == "__main__":
    unittest.main()
