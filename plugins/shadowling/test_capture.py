import io
import json
import os
import shutil
import tempfile
import unittest

import capture
import core


def make_user_transcript(text):
    return make_multi_user_transcript([{"text": text}])


def make_multi_user_transcript(entries):
    fd, path = tempfile.mkstemp(suffix=".jsonl")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        for e in entries:
            obj = {
                "type": "user",
                "message": {"role": "user",
                            "content": [{"type": "text", "text": e["text"]}]},
            }
            if e.get("isMeta"):
                obj["isMeta"] = True
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")
    return path


class CaptureTestBase(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        os.environ["SHADOWLING_HOME"] = self.home
        core.save_config({"first_language": "Ukrainian",
                          "explanation_language": "English"})

    def tearDown(self):
        os.environ.pop("SHADOWLING_HOME", None)
        shutil.rmtree(self.home, ignore_errors=True)

    def _stdin(self, transcript_path, session="sess-test"):
        return json.dumps({"transcript_path": transcript_path,
                           "session_id": session})

    def _capture_text(self, text, session="sess-test"):
        tpath = make_user_transcript(text)
        try:
            return capture.capture(self._stdin(tpath, session))
        finally:
            os.remove(tpath)

    def _rows(self):
        return capture.query(
            "SELECT id, created_at, text, langs, processed_at FROM messages"
            " ORDER BY id")


class CaptureTest(CaptureTestBase):
    def test_english_message_stored(self):
        self.assertTrue(self._capture_text("Despite the delay we have finished it"))
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["text"], "Despite the delay we have finished it")
        self.assertIsNone(rows[0]["langs"])
        self.assertIsNone(rows[0]["processed_at"])

    def test_ukrainian_message_stored_too(self):
        # language-blind capture: non-English is no longer discarded
        self.assertTrue(self._capture_text("привіт як справи сьогодні зранку"))
        self.assertEqual(len(self._rows()), 1)

    def test_mixed_message_stored(self):
        self.assertTrue(self._capture_text("деплой пройшов але був downtime"))
        self.assertEqual(len(self._rows()), 1)

    def test_too_short_not_stored(self):
        self.assertFalse(self._capture_text("ok thx"))
        self.assertEqual(self._rows(), [])

    def test_slash_command_not_stored(self):
        self.assertFalse(self._capture_text("/drop throughput please now"))
        self.assertEqual(self._rows(), [])

    def test_command_marker_wrapper_not_stored(self):
        tpath = make_multi_user_transcript([
            {"text": "<command-message>shadowling:debrief</command-message>\n"
                     "<command-name>debrief</command-name>"},
        ])
        try:
            self.assertFalse(capture.capture(self._stdin(tpath)))
        finally:
            os.remove(tpath)
        self.assertEqual(self._rows(), [])

    def test_meta_message_skipped_falls_back_to_real_one(self):
        tpath = make_multi_user_transcript([
            {"text": "This is my real english sentence to capture please"},
            {"text": "Turn the user's buffered messages into docs and so on",
             "isMeta": True},
        ])
        try:
            self.assertTrue(capture.capture(self._stdin(tpath)))
        finally:
            os.remove(tpath)
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        self.assertIn("real english sentence", rows[0]["text"])

    def test_same_text_twice_not_duplicated(self):
        self.assertTrue(self._capture_text("This is a perfectly normal sentence"))
        self.assertFalse(self._capture_text("This is a perfectly normal sentence"))
        self.assertEqual(len(self._rows()), 1)

    def test_bad_stdin_never_raises(self):
        self.assertFalse(capture.capture("not json"))
        self.assertFalse(capture.capture(""))

    def test_missing_transcript_returns_false(self):
        self.assertFalse(capture.capture(
            json.dumps({"transcript_path": "/no/such.jsonl"})))

    def test_capture_noop_without_config(self):
        os.remove(os.path.join(self.home, "config.json"))
        self.assertFalse(
            self._capture_text("This is a perfectly fine English sentence"))


class TagTest(CaptureTestBase):
    def setUp(self):
        super().setUp()
        self._capture_text("First normal english sentence here please")
        self._capture_text("друге повідомлення суто українською мовою")

    def test_tag_single_and_multi_code(self):
        ok, errors = capture.tag(["1=en", "2=en,uk"])
        self.assertEqual((ok, errors), (2, []))
        rows = self._rows()
        self.assertEqual(json.loads(rows[0]["langs"]), ["en"])
        self.assertEqual(json.loads(rows[1]["langs"]), ["en", "uk"])

    def test_tag_unknown_id_reported(self):
        ok, errors = capture.tag(["999=en"])
        self.assertEqual(ok, 0)
        self.assertTrue(any("999" in e for e in errors))

    def test_tag_malformed_rejected(self):
        for bad in ["1", "1=", "1=ENGLISH", "1=e", "x=en"]:
            ok, errors = capture.tag([bad])
            self.assertEqual(ok, 0, bad)
            self.assertTrue(errors, bad)
        self.assertIsNone(self._rows()[0]["langs"])

    def test_tag_und_is_valid(self):
        ok, errors = capture.tag(["1=und"])
        self.assertEqual((ok, errors), (1, []))


class MessagesSlicesTest(CaptureTestBase):
    def setUp(self):
        super().setUp()
        self._capture_text("First normal english sentence here please")
        self._capture_text("друге повідомлення суто українською мовою")
        self._capture_text("third message чи mixed повідомлення разом")
        capture.tag(["1=en", "2=uk"])  # row 3 left untagged

    def test_messages_lists_all_unprocessed_with_attrs(self):
        block = capture.messages()
        self.assertIn('<m id="1"', block)
        self.assertIn('<m id="3"', block)
        self.assertIn("&quot;en&quot;", block)   # langs attr carries JSON, escaped
        self.assertIn('langs=""', block)          # untagged row → empty attr

    def test_untagged_slice_and_limit(self):
        block = capture.messages(untagged=True)
        self.assertIn('<m id="3"', block)
        self.assertNotIn('<m id="1"', block)
        capture.tag(["3=en,uk"])
        self.assertEqual(capture.messages(untagged=True), "<messages></messages>")

    def test_lang_slice_includes_mixed(self):
        capture.tag(["3=en,uk"])
        block = capture.messages(lang="en")
        self.assertIn('<m id="1"', block)
        self.assertIn('<m id="3"', block)   # mixed row contains en
        self.assertNotIn('<m id="2"', block)

    def test_limit(self):
        block = capture.messages(untagged=True, limit=0)
        self.assertEqual(block, "<messages></messages>")

    def test_xml_escapes_text(self):
        self._capture_text("a < b & c > d here in this sentence")
        block = capture.messages()
        self.assertIn("a &lt; b &amp; c &gt; d", block)


class MarkProcessedTest(CaptureTestBase):
    def setUp(self):
        super().setUp()
        self._capture_text("First normal english sentence here please")
        self._capture_text("друге повідомлення суто українською мовою")

    def test_marks_tagged_only_and_keeps_untagged(self):
        capture.tag(["1=en"])  # row 2 untagged (mid-debrief capture)
        out = capture.mark_processed()
        self.assertEqual(out, "processed 1, kept 1 untagged")
        rows = self._rows()
        self.assertIsNotNone(rows[0]["processed_at"])
        self.assertIsNone(rows[1]["processed_at"])

    def test_processed_rows_leave_listings_but_stay_in_table(self):
        capture.tag(["1=en", "2=uk"])
        capture.mark_processed()
        self.assertEqual(capture.messages(), "<messages></messages>")
        self.assertEqual(capture.pending_count(), 0)
        self.assertEqual(len(self._rows()), 2)  # history kept (via query)

    def test_pending_count_counts_unprocessed(self):
        self.assertEqual(capture.pending_count(), 2)


class QueryTest(CaptureTestBase):
    def test_query_is_read_only(self):
        self._capture_text("First normal english sentence here please")
        with self.assertRaises(Exception):
            capture.query("DELETE FROM messages")
        self.assertEqual(len(self._rows()), 1)


class MainTest(CaptureTestBase):
    def test_capture_via_main_never_crashes_on_bad_stdin(self):
        old = capture.sys.stdin
        capture.sys.stdin = io.StringIO("not json at all")
        try:
            ret = capture.main(["capture"])
        finally:
            capture.sys.stdin = old
        self.assertEqual(ret, 0)

    def test_tag_via_main_reports_errors_with_exit_1(self):
        self._capture_text("First normal english sentence here please")
        self.assertEqual(capture.main(["tag", "1=en"]), 0)
        self.assertEqual(capture.main(["tag", "999=en"]), 1)

    def test_unknown_command_returns_one(self):
        self.assertEqual(capture.main(["bogus"]), 1)


from contextlib import closing as _closing
import appdb as _appdb


def closing_con():
    return _closing(_appdb.connect())


class SessionVerbsTest(CaptureTestBase):
    def setUp(self):
        super().setUp()
        self._capture_text("First normal english sentence here please", "sess-A")
        self._capture_text("Second message in another working session", "sess-B")
        self._capture_text("Third message back in the first session!", "sess-A")

    def test_capture_stores_session_id(self):
        rows = capture.query(
            "SELECT session_id FROM messages ORDER BY id")
        self.assertEqual([r["session_id"] for r in rows],
                         ["sess-A", "sess-B", "sess-A"])

    def test_sessions_lists_pending_per_session(self):
        out = capture.sessions()
        self.assertEqual(out, [{"session": "sess-A", "pending": 2},
                               {"session": "sess-B", "pending": 1}])

    def test_sessions_skips_drill_only_sessions(self):
        capture.query  # ensure db exists
        with closing_con() as con:
            with con:
                con.execute("UPDATE messages SET kind='drill' "
                            "WHERE session_id='sess-B'")
        self.assertEqual([s["session"] for s in capture.sessions()],
                         ["sess-A"])

    def test_messages_session_slice(self):
        block = capture.messages(session="sess-A")
        self.assertIn('<m id="1"', block)
        self.assertIn('<m id="3"', block)
        self.assertNotIn('<m id="2"', block)

    def test_messages_excludes_drills(self):
        with closing_con() as con:
            with con:
                con.execute("UPDATE messages SET kind='drill' WHERE id=1")
        block = capture.messages(session="sess-A")
        self.assertNotIn('<m id="1"', block)
        self.assertIn('<m id="3"', block)

    def test_pending_count_excludes_drills(self):
        with closing_con() as con:
            with con:
                con.execute("UPDATE messages SET kind='drill' WHERE id=1")
        self.assertEqual(capture.pending_count(), 2)

    def test_mark_processed_session_scoped_and_stamps_drills(self):
        capture.tag(["1=en", "2=en"])  # id 3 untagged
        with closing_con() as con:
            with con:
                con.execute("UPDATE messages SET kind='drill', langs=NULL "
                            "WHERE id=3")
        out = capture.mark_processed(session="sess-A")
        # id 1 (tagged, sess-A) + id 3 (drill, sess-A) stamped; id 2 stays
        rows = capture.query(
            "SELECT id, processed_at IS NOT NULL AS p FROM messages ORDER BY id")
        self.assertEqual([(r["id"], r["p"]) for r in rows],
                         [(1, 1), (2, 0), (3, 1)])
        self.assertIn("processed 2", out)


class MarkDrillsTest(CaptureTestBase):
    def _attempt(self, answer, session="sess-A"):
        with closing_con() as con:
            with con:
                con.execute(
                    "INSERT INTO attempts(created_at, session_id, item_kind,"
                    " item_key, exercise, answer, verdict) VALUES ('t', ?,"
                    " 'grammar', 'k', 'fix', ?, 'pass')", (session, answer))

    def test_exact_and_drifted_matches_marked(self):
        self._capture_text("I have gone to the gym", "sess-A")
        self._capture_text("I see it differently - here is my concern", "sess-A")
        self._attempt("I have gone to the gym")                  # identical
        self._attempt("i have GONE to the gym")                  # case flip
        self._attempt("I see it differently -  here is my concern ")  # ws drift
        out = capture.mark_drills()
        rows = capture.query("SELECT kind FROM messages ORDER BY id")
        self.assertEqual([r["kind"] for r in rows], ["drill", "drill"])
        self.assertIn("marked 2", out)

    def test_interjection_and_other_session_not_marked(self):
        self._capture_text("стоп забий треба фіксити деплой зараз", "sess-A")
        self._capture_text("I have gone to the gym", "sess-B")   # other session
        self._attempt("I have gone to the gym", session="sess-A")
        out = capture.mark_drills()
        rows = capture.query("SELECT kind FROM messages ORDER BY id")
        self.assertEqual([r["kind"] for r in rows], [None, None])
        self.assertIn("1 attempt(s) unmatched", out)

    def test_short_lookalike_below_threshold(self):
        self._capture_text("went home just now ok", "sess-A")
        self._attempt("went, gone")
        capture.mark_drills()
        self.assertEqual(
            capture.query("SELECT kind FROM messages")[0]["kind"], None)

    def test_similarity_characterization(self):
        similarity = capture._similarity
        self.assertGreaterEqual(
            similarity("I have gone home", "I have gone home"), 1.0)
        self.assertGreaterEqual(
            similarity("I have gone home", "I Have Gone Home!"), 0.9)
        self.assertGreaterEqual(
            similarity("take  a   photo", "take a photo"), 0.9)
        self.assertLess(similarity("went, gone", "went home"), 0.9)
        self.assertLess(
            similarity("I have gone home", "the deploy is green now"), 0.5)

    def test_processed_rows_untouched(self):
        self._capture_text("I have gone to the gym", "sess-A")
        capture.tag(["1=en"])
        capture.mark_processed()
        self._attempt("I have gone to the gym")
        capture.mark_drills()
        self.assertEqual(
            capture.query("SELECT kind FROM messages")[0]["kind"], None)


if __name__ == "__main__":
    unittest.main()
