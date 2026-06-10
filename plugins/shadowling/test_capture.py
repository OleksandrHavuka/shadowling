import io
import json
import os
import shutil
import tempfile
import unittest

import capture
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
        os.environ.pop("SHADOWLING_BUFFER", None)

    def tearDown(self):
        os.environ.pop("SHADOWLING_HOME", None)
        os.environ.pop("SHADOWLING_BUFFER", None)
        shutil.rmtree(self.home, ignore_errors=True)

    def _stdin(self, transcript_path):
        return json.dumps({"transcript_path": transcript_path})

    def _capture_text(self, text):
        tpath = make_user_transcript(text)
        try:
            return capture.capture(self._stdin(tpath))
        finally:
            os.remove(tpath)


class IsEnglishTest(unittest.TestCase):
    def test_english_sentence_is_english(self):
        self.assertTrue(capture.is_english("I have went to the store yesterday"))

    def test_ukrainian_sentence_is_not_english(self):
        self.assertFalse(capture.is_english("я пішов до магазину вчора зранку"))

    def test_mixed_mostly_cyrillic_is_not_english(self):
        self.assertFalse(capture.is_english("деплой пройшов але був downtime"))

    def test_too_short_is_not_english(self):
        self.assertFalse(capture.is_english("ok thx"))


class BufferPathTest(CaptureTestBase):
    def test_default_buffer_filename(self):
        self.assertTrue(capture.buffer_path().endswith("/buffer.jsonl"))


class CaptureTest(CaptureTestBase):
    def test_english_message_buffered(self):
        self.assertTrue(self._capture_text("Despite the delay we have finished it"))
        rows = capture._read_buffer()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["text"], "Despite the delay we have finished it")
        self.assertIn("ts", rows[0])

    def test_ukrainian_message_not_buffered(self):
        self.assertFalse(self._capture_text("привіт як справи сьогодні зранку"))
        self.assertEqual(capture._read_buffer(), [])

    def test_slash_command_not_buffered(self):
        self.assertFalse(self._capture_text("/drop throughput please now"))
        self.assertEqual(capture._read_buffer(), [])

    def test_same_text_twice_not_duplicated(self):
        self.assertTrue(self._capture_text("This is a perfectly normal sentence"))
        self.assertFalse(self._capture_text("This is a perfectly normal sentence"))
        self.assertEqual(len(capture._read_buffer()), 1)

    def test_slash_command_body_is_meta_not_buffered(self):
        tpath = make_multi_user_transcript([
            {"text": "Turn the user's buffered English messages into curated docs",
             "isMeta": True},
        ])
        try:
            self.assertFalse(capture.capture(self._stdin(tpath)))
        finally:
            os.remove(tpath)
        self.assertEqual(capture._read_buffer(), [])

    def test_command_marker_wrapper_not_buffered(self):
        tpath = make_multi_user_transcript([
            {"text": "<command-message>shadowling:debrief</command-message>\n"
                     "<command-name>debrief</command-name>"},
        ])
        try:
            self.assertFalse(capture.capture(self._stdin(tpath)))
        finally:
            os.remove(tpath)
        self.assertEqual(capture._read_buffer(), [])

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
        rows = capture._read_buffer()
        self.assertEqual(len(rows), 1)
        self.assertIn("real english sentence", rows[0]["text"])

    def test_bad_stdin_never_raises(self):
        self.assertFalse(capture.capture("not json"))
        self.assertFalse(capture.capture(""))

    def test_missing_transcript_returns_false(self):
        self.assertFalse(capture.capture(
            json.dumps({"transcript_path": "/no/such.jsonl"})))


class CorpusTest(CaptureTestBase):
    def test_capture_appends_to_messages_log(self):
        self._capture_text("I have went to the store and buyed milk today")
        log = jsonl.read(capture.messages_log_path())
        self.assertEqual(len(log), 1)
        self.assertEqual(log[0]["text"],
                         "I have went to the store and buyed milk today")
        self.assertIn("ts", log[0])
        self.assertIn("date", log[0])

    def test_duplicate_capture_not_logged_twice(self):
        self._capture_text("This is a perfectly normal english sentence here")
        self._capture_text("This is a perfectly normal english sentence here")
        self.assertEqual(len(jsonl.read(capture.messages_log_path())), 1)


class MessagesTest(CaptureTestBase):
    def test_empty_buffer_returns_empty_block(self):
        self.assertEqual(capture.messages(), "<messages></messages>")

    def test_messages_lists_buffered_entries(self):
        self._capture_text("First normal english sentence here please now")
        block = capture.messages()
        self.assertIn("<messages>", block)
        self.assertIn("First normal english sentence", block)
        self.assertIn("<m ts=", block)

    def test_messages_xml_escapes_text(self):
        capture._append_buffer({"ts": "t", "text": "a < b & c > d here"})
        block = capture.messages()
        self.assertIn("a &lt; b &amp; c &gt; d here", block)


class CountAndClearTest(CaptureTestBase):
    def test_pending_count(self):
        self.assertEqual(capture.pending_count(), 0)
        self._capture_text("First normal english sentence here please")
        self._capture_text("Second different english sentence over here")
        self.assertEqual(capture.pending_count(), 2)

    def test_clear_empties_buffer(self):
        self._capture_text("A normal english sentence to be cleared soon")
        self.assertEqual(len(capture._read_buffer()), 1)
        self.assertEqual(capture.clear(), "cleared")
        self.assertEqual(capture._read_buffer(), [])

    def test_clear_keeps_corpus(self):
        self._capture_text("A normal english sentence to be cleared soon")
        capture.clear()
        self.assertEqual(len(jsonl.read(capture.messages_log_path())), 1)


class MainTest(CaptureTestBase):
    def test_capture_via_main_never_crashes_on_bad_stdin(self):
        old = capture.sys.stdin
        capture.sys.stdin = io.StringIO("not json at all")
        try:
            ret = capture.main(["capture"])
        finally:
            capture.sys.stdin = old
        self.assertEqual(ret, 0)

    def test_messages_via_main(self):
        self.assertEqual(capture.main(["messages"]), 0)

    def test_unknown_command_returns_one(self):
        self.assertEqual(capture.main(["bogus"]), 1)

    def test_main_registers_script_path(self):
        capture.main(["pending-count"])
        self.assertTrue(os.path.exists(os.path.join(self.home, ".script_path")))


if __name__ == "__main__":
    unittest.main()
