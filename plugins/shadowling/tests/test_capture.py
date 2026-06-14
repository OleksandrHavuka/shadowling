import io
import json
import os
import shutil
import tempfile
import unittest

import appdb
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
                "message": {
                    "role": "user",
                    "content": [{"type": "text", "text": e["text"]}],
                },
            }
            if e.get("isMeta"):
                obj["isMeta"] = True
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")
    return path


class CaptureTestBase(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        os.environ["SHADOWLING_HOME"] = self.home
        core.save_config(
            {
                "first_language": "Ukrainian",
                "explanation_language": "English",
                "learning_language": "English",
            }
        )

    def tearDown(self):
        os.environ.pop("SHADOWLING_HOME", None)
        shutil.rmtree(self.home, ignore_errors=True)

    def _stdin(self, transcript_path, session="sess-test"):
        return json.dumps({"transcript_path": transcript_path, "session_id": session})

    def _capture_text(self, text, session="sess-test"):
        tpath = make_user_transcript(text)
        try:
            return capture.capture(self._stdin(tpath, session))
        finally:
            os.remove(tpath)

    def _rows(self):
        return appdb.query(
            "SELECT id, created_at, text, langs, processed_at FROM messages ORDER BY id"
        )


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
        tpath = make_multi_user_transcript(
            [
                {
                    "text": "<command-message>shadowling:debrief</command-message>\n"
                    "<command-name>debrief</command-name>"
                },
            ]
        )
        try:
            self.assertFalse(capture.capture(self._stdin(tpath)))
        finally:
            os.remove(tpath)
        self.assertEqual(self._rows(), [])

    def test_meta_message_skipped_falls_back_to_real_one(self):
        tpath = make_multi_user_transcript(
            [
                {"text": "This is my real english sentence to capture please"},
                {
                    "text": "Turn the user's buffered messages into docs and so on",
                    "isMeta": True,
                },
            ]
        )
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
        self.assertFalse(
            capture.capture(json.dumps({"transcript_path": "/no/such.jsonl"}))
        )

    def test_capture_runs_without_config(self):
        # capture is NOT config-gated: messages are logged even before /setup so
        # nothing is lost (the glossing hook + analysis skills gate themselves).
        os.remove(os.path.join(self.home, "config.json"))
        self.assertTrue(self._capture_text("This is a perfectly fine English sentence"))
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


if __name__ == "__main__":
    unittest.main()
