import io
import json
import os
import shutil
import tempfile
import unittest
from datetime import datetime

import capture


def make_user_transcript(text):
    return make_multi_user_transcript([{"text": text}])


def make_multi_user_transcript(entries):
    """entries: list of {'text': str, 'isMeta': bool?} written as user turns."""
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
        os.environ.pop("SHADOWLING_EN_BUFFER", None)

    def tearDown(self):
        os.environ.pop("SHADOWLING_HOME", None)
        os.environ.pop("SHADOWLING_EN_BUFFER", None)
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
        self.assertFalse(self._capture_text("/vocab remove throughput please now"))
        self.assertEqual(capture._read_buffer(), [])

    def test_same_text_twice_not_duplicated(self):
        self.assertTrue(self._capture_text("This is a perfectly normal sentence"))
        self.assertFalse(self._capture_text("This is a perfectly normal sentence"))
        self.assertEqual(len(capture._read_buffer()), 1)

    def test_slash_command_body_is_meta_not_buffered(self):
        # the expanded /en-review body lands as a user message with isMeta=True
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
            {"text": "<command-message>shadowling:en-review</command-message>\n"
                     "<command-name>en-review</command-name>"},
        ])
        try:
            self.assertFalse(capture.capture(self._stdin(tpath)))
        finally:
            os.remove(tpath)
        self.assertEqual(capture._read_buffer(), [])

    def test_local_command_stdout_not_buffered(self):
        tpath = make_multi_user_transcript([
            {"text": "<local-command-stdout>Installed shadowling successfully now"
                     "</local-command-stdout>"},
        ])
        try:
            self.assertFalse(capture.capture(self._stdin(tpath)))
        finally:
            os.remove(tpath)

    def test_meta_message_skipped_falls_back_to_real_one(self):
        # a real typed message followed by a meta slash-command body:
        # capture the real message, ignore the meta one
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


class AddRowTest(CaptureTestBase):
    def _read(self, doc):
        with open(capture.doc_path(doc), encoding="utf-8") as f:
            return f.read()

    def test_creates_header_and_separator(self):
        self.assertEqual(
            capture.add_row("grammar", "I has", "I have", "subj-verb"), "added")
        text = self._read("grammar")
        lines = text.strip().splitlines()
        self.assertEqual(lines[0], "| date | ❌ original | ✅ fixed | rule |")
        self.assertEqual(lines[1], "| --- | --- | --- | --- |")
        # date is auto-filled (today, ISO); assert the content columns landed
        today = datetime.now().strftime("%Y-%m-%d")
        self.assertIn("| {0} | I has | I have | subj-verb |".format(today), lines[2])

    def test_duplicate_key_is_skipped(self):
        capture.add_row("grammar", "I has", "I have", "rule")
        # same key, different case/spacing -> dup
        self.assertEqual(capture.add_row("grammar", "  I HAS ", "x", "y"), "dup")
        rows = [l for l in self._read("grammar").splitlines()
                if l.startswith("| ") and "date" not in l and "---" not in l]
        self.assertEqual(len(rows), 1)

    def test_pipe_in_content_is_escaped(self):
        capture.add_row("rephrasings", "a|b", "c", "why")
        self.assertIn("a\\|b", self._read("rephrasings"))
        # and the key round-trips so a second identical add is a dup
        self.assertEqual(capture.add_row("rephrasings", "a|b", "c", "why"), "dup")

    def test_irregular_verbs_key_is_base(self):
        capture.add_row("irregular_verbs", "go", "went", "gone", "fix")
        self.assertEqual(
            capture.add_row("irregular_verbs", "Go", "x", "y", "z"), "dup")

    def test_date_column_is_auto_filled(self):
        capture.add_row("grammar", "orig", "fixed", "rule")
        today = datetime.now().strftime("%Y-%m-%d")
        self.assertIn("| " + today + " |", self._read("grammar"))

    def test_unknown_doc_returns_error(self):
        self.assertEqual(capture.add_row("nonsense", "a", "b"), "error")


class ReadKeysTest(CaptureTestBase):
    def test_parses_existing_table_keys(self):
        capture.add_row("idioms", "finishing work", "wrap up",
                        "закінчити", "let's finish")
        capture.add_row("idioms", "agreeing", "I'm in",
                        "я за", "I agree")
        self.assertEqual(capture.read_keys("idioms"), {"wrap up", "i'm in"})

    def test_missing_file_is_empty_set(self):
        self.assertEqual(capture.read_keys("grammar"), set())


class DumpAndCountTest(CaptureTestBase):
    def test_pending_count(self):
        self.assertEqual(capture.pending_count(), 0)
        self._capture_text("First normal english sentence here please")
        self._capture_text("Second different english sentence over here")
        self.assertEqual(capture.pending_count(), 2)

    def test_dump_contains_pending_and_existing(self):
        self._capture_text("I have went there and seen the results already")
        capture.add_row("grammar", "old mistake", "fixed", "rule")
        text = capture.dump()
        self.assertIn("<pending>", text)
        self.assertIn("I have went there", text)
        self.assertIn("<existing>", text)
        self.assertIn("<grammar>", text)
        self.assertIn("old mistake", text)

    def test_clear_empties_buffer(self):
        self._capture_text("A normal english sentence to be cleared soon")
        self.assertEqual(len(capture._read_buffer()), 1)
        self.assertEqual(capture.clear(), "cleared")
        self.assertEqual(capture._read_buffer(), [])


class MainTest(CaptureTestBase):
    def test_capture_via_main_never_crashes_on_bad_stdin(self):
        old = capture.sys.stdin
        capture.sys.stdin = io.StringIO("not json at all")
        try:
            ret = capture.main(["capture"])
        finally:
            capture.sys.stdin = old
        self.assertEqual(ret, 0)

    def test_unknown_command_returns_one(self):
        self.assertEqual(capture.main(["bogus"]), 1)

    def test_main_registers_script_path(self):
        capture.main(["pending-count"])
        self.assertTrue(os.path.exists(os.path.join(self.home, ".script_path")))


if __name__ == "__main__":
    unittest.main()
