import io
import json
import os
import shutil
import tempfile
import unittest

import capture
import core
import jsonl


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
        core.save_config({"native_language": "Ukrainian",
                          "explanation_language": "English"})

    def tearDown(self):
        os.environ.pop("SHADOWLING_HOME", None)
        shutil.rmtree(self.home, ignore_errors=True)

    def _stdin(self, transcript_path):
        return json.dumps({"transcript_path": transcript_path})

    def _capture_text(self, text):
        tpath = make_user_transcript(text)
        try:
            return capture.capture(self._stdin(tpath))
        finally:
            os.remove(tpath)

    def _rows(self):
        return capture.query(
            "SELECT id, ts, text, langs, processed_at FROM messages ORDER BY id")


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


class MigrationTest(CaptureTestBase):
    def test_imports_both_legacy_files_once(self):
        with open(os.path.join(self.home, "messages.log.jsonl"), "w",
                  encoding="utf-8") as f:
            f.write(json.dumps({"date": "2026-06-01", "ts": "2026-06-01T10:00:00",
                                "text": "old corpus english message here"}) + "\n")
        with open(os.path.join(self.home, "buffer.jsonl"), "w",
                  encoding="utf-8") as f:
            f.write(json.dumps({"ts": "2026-06-09T10:00:00",
                                "text": "old buffered message awaiting debrief"}) + "\n")
        self.assertEqual(capture.pending_count(), 1)  # first DB touch migrates
        rows = self._rows()
        self.assertEqual(len(rows), 2)
        by_text = {r["text"]: r for r in rows}
        self.assertIsNotNone(
            by_text["old corpus english message here"]["processed_at"])
        self.assertIsNone(
            by_text["old buffered message awaiting debrief"]["processed_at"])
        self.assertFalse(os.path.exists(os.path.join(self.home, "buffer.jsonl")))
        self.assertFalse(
            os.path.exists(os.path.join(self.home, "messages.log.jsonl")))


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


if __name__ == "__main__":
    unittest.main()
