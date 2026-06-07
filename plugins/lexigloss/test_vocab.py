import json
import os
import shutil
import tempfile
import unittest

import vocab


class VocabTestBase(unittest.TestCase):
    def setUp(self):
        fd, self.csv_path = tempfile.mkstemp(suffix=".csv")
        os.close(fd)
        os.remove(self.csv_path)  # start with NO file so load_rows() == []
        os.environ["VOCAB_CSV"] = self.csv_path
        os.environ.pop("VOCAB_CONFIG", None)  # tests default unless set explicitly

    def tearDown(self):
        os.environ.pop("VOCAB_CSV", None)
        os.environ.pop("VOCAB_CONFIG", None)
        if os.path.exists(self.csv_path):
            os.remove(self.csv_path)

    def rows_by_word(self):
        return {r["word"]: r for r in vocab.load_rows(vocab.csv_path())}


class AddTest(VocabTestBase):
    def test_add_new_word_starts_at_10_active(self):
        action, row = vocab.add("Throughput", "пропускна здатність")
        self.assertEqual(action, "add")
        self.assertEqual(row["word"], "throughput")  # stored lowercased
        self.assertEqual(row["translation"], "пропускна здатність")
        self.assertEqual(row["remaining"], "10")
        self.assertEqual(row["status"], "active")

    def test_add_existing_active_refreshes_translation_keeps_remaining(self):
        vocab.add("throughput", "old")
        # simulate prior exposure
        rows = vocab.load_rows(vocab.csv_path())
        rows[0]["remaining"] = "7"
        vocab.save_rows(vocab.csv_path(), rows)
        action, row = vocab.add("throughput", "new translation")
        self.assertEqual(action, "refresh")
        self.assertEqual(row["translation"], "new translation")
        self.assertEqual(row["remaining"], "7")  # unchanged
        self.assertEqual(row["status"], "active")

    def test_add_existing_learned_resets_to_10_active(self):
        vocab.add("throughput", "t")
        rows = vocab.load_rows(vocab.csv_path())
        rows[0]["remaining"] = "0"
        rows[0]["status"] = "learned"
        vocab.save_rows(vocab.csv_path(), rows)
        action, row = vocab.add("throughput", "t2")
        self.assertEqual(action, "relearn")
        self.assertEqual(row["remaining"], "10")
        self.assertEqual(row["status"], "active")
        self.assertEqual(row["translation"], "t2")


class RemoveTest(VocabTestBase):
    def test_remove_existing_returns_true_and_deletes(self):
        vocab.add("throughput", "t")
        self.assertTrue(vocab.remove("Throughput"))  # case-insensitive
        self.assertNotIn("throughput", self.rows_by_word())

    def test_remove_unknown_returns_false_no_error(self):
        self.assertFalse(vocab.remove("nonexistent"))


class MatchTest(VocabTestBase):
    def test_long_word_matches_stem_suffixes(self):
        # word >= 4 chars: exact + s/es/ed/ing/d
        for text in ["throughput", "Throughput", "throughputs", "throughputed"]:
            self.assertTrue(vocab.word_in_text("throughput", text), text)

    def test_short_word_exact_only(self):
        # word < 4 chars: exact form only, no suffix expansion
        self.assertTrue(vocab.word_in_text("log", "the log file"))
        self.assertFalse(vocab.word_in_text("log", "logging output"))

    def test_no_substring_false_match(self):
        self.assertFalse(vocab.word_in_text("cat", "category theory"))

    def test_punctuation_term_matches(self):
        # Fix 2: terms ending in non-word chars (e.g. c++) must match
        self.assertTrue(vocab.word_in_text("c++", "I write C++ every day"))
        # Existing stem-suffix cases must still hold
        for text in ["throughput", "Throughput", "throughputs", "throughputed"]:
            self.assertTrue(vocab.word_in_text("throughput", text), text)
        # Short word exact-only still holds
        self.assertTrue(vocab.word_in_text("log", "the log file"))
        self.assertFalse(vocab.word_in_text("log", "logging output"))
        # No substring false match still holds
        self.assertFalse(vocab.word_in_text("cat", "category theory"))


class ListActiveTest(VocabTestBase):
    def test_list_active_excludes_learned(self):
        vocab.add("alpha", "а")
        vocab.add("beta", "б")
        rows = vocab.load_rows(vocab.csv_path())
        for r in rows:
            if r["word"] == "beta":
                r["status"] = "learned"
        vocab.save_rows(vocab.csv_path(), rows)
        words = [r["word"] for r in vocab.list_active()]
        self.assertEqual(words, ["alpha"])


def make_transcript(text):
    fd, path = tempfile.mkstemp(suffix=".jsonl")
    obj = {
        "type": "assistant",
        "message": {"role": "assistant", "content": [{"type": "text", "text": text}]},
    }
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")
    return path


class ScanTest(VocabTestBase):
    def _stdin(self, transcript_path):
        return json.dumps({"transcript_path": transcript_path})

    def test_scan_decrements_matched_active_word(self):
        vocab.add("throughput", "п")
        tpath = make_transcript("This improves throughput under load.")
        try:
            changed = vocab.scan(self._stdin(tpath))
        finally:
            os.remove(tpath)
        self.assertEqual(changed, ["throughput"])
        self.assertEqual(self.rows_by_word()["throughput"]["remaining"], "9")

    def test_scan_ignores_absent_word(self):
        vocab.add("throughput", "п")
        tpath = make_transcript("Nothing relevant here.")
        try:
            changed = vocab.scan(self._stdin(tpath))
        finally:
            os.remove(tpath)
        self.assertEqual(changed, [])
        self.assertEqual(self.rows_by_word()["throughput"]["remaining"], "10")

    def test_scan_graduates_at_zero(self):
        vocab.add("throughput", "п")
        rows = vocab.load_rows(vocab.csv_path())
        rows[0]["remaining"] = "1"
        vocab.save_rows(vocab.csv_path(), rows)
        tpath = make_transcript("throughput throughput")  # still one decrement
        try:
            vocab.scan(self._stdin(tpath))
        finally:
            os.remove(tpath)
        row = self.rows_by_word()["throughput"]
        self.assertEqual(row["remaining"], "0")
        self.assertEqual(row["status"], "learned")

    def test_scan_skips_learned_words(self):
        vocab.add("throughput", "п")
        rows = vocab.load_rows(vocab.csv_path())
        rows[0]["status"] = "learned"
        rows[0]["remaining"] = "0"
        vocab.save_rows(vocab.csv_path(), rows)
        tpath = make_transcript("throughput throughput")
        try:
            changed = vocab.scan(self._stdin(tpath))
        finally:
            os.remove(tpath)
        self.assertEqual(changed, [])

    def test_scan_uses_last_assistant_message_only(self):
        vocab.add("throughput", "п")
        # transcript with two assistant turns; only the LAST counts
        fd, tpath = tempfile.mkstemp(suffix=".jsonl")
        a = {"type": "assistant",
             "message": {"role": "assistant",
                         "content": [{"type": "text", "text": "throughput here"}]}}
        b = {"type": "assistant",
             "message": {"role": "assistant",
                         "content": [{"type": "text", "text": "no vocab word now"}]}}
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(a) + "\n")
            f.write(json.dumps(b) + "\n")
        try:
            changed = vocab.scan(self._stdin(tpath))
        finally:
            os.remove(tpath)
        self.assertEqual(changed, [])  # last message has no match

    def test_scan_bad_stdin_never_raises(self):
        self.assertEqual(vocab.scan("not json"), [])
        self.assertEqual(vocab.scan(""), [])

    def test_scan_missing_transcript_path_returns_empty(self):
        self.assertEqual(vocab.scan(json.dumps({"transcript_path": "/no/such.jsonl"})), [])

    def test_scan_corrupt_remaining_does_not_raise_and_skips_row(self):
        # Fix 1: corrupt 'remaining' must not cause scan() to raise
        vocab.add("throughput", "п")
        rows = vocab.load_rows(vocab.csv_path())
        rows[0]["remaining"] = "oops"  # corrupt value
        vocab.save_rows(vocab.csv_path(), rows)
        tpath = make_transcript("This improves throughput under load.")
        try:
            result = vocab.scan(self._stdin(tpath))
        finally:
            os.remove(tpath)
        # Must not raise, and the corrupt row must NOT appear in changed list
        self.assertNotIn("throughput", result)
        # The row must remain unchanged (remaining still "oops")
        row = self.rows_by_word()["throughput"]
        self.assertEqual(row["remaining"], "oops")

    def test_scan_main_bad_stdin_returns_zero(self):
        # Hook path must never crash even on completely invalid stdin
        import io
        old_stdin = vocab.sys.stdin
        vocab.sys.stdin = io.StringIO("not json at all")
        try:
            ret = vocab.main(["scan"])
        finally:
            vocab.sys.stdin = old_stdin
        self.assertEqual(ret, 0)


class InjectTest(VocabTestBase):
    def test_inject_empty_when_no_active_words(self):
        self.assertEqual(vocab.inject(), "")

    def test_inject_emits_sessionstart_json_with_words(self):
        vocab.add("throughput", "пропускна здатність")
        out = vocab.inject()
        data = json.loads(out)
        self.assertEqual(
            data["hookSpecificOutput"]["hookEventName"], "SessionStart"
        )
        ctx = data["hookSpecificOutput"]["additionalContext"]
        self.assertIn("throughput", ctx)
        self.assertIn("пропускна здатність", ctx)  # utf-8 preserved
        self.assertIn("first", ctx.lower())  # instruction present

    def test_inject_excludes_learned_words(self):
        vocab.add("alpha", "а")
        vocab.add("beta", "б")
        rows = vocab.load_rows(vocab.csv_path())
        for r in rows:
            if r["word"] == "beta":
                r["status"] = "learned"
        vocab.save_rows(vocab.csv_path(), rows)
        ctx = json.loads(vocab.inject())["hookSpecificOutput"]["additionalContext"]
        self.assertIn("alpha", ctx)
        self.assertNotIn("beta", ctx)

    def test_inject_defaults_to_sessionstart(self):
        vocab.add("throughput", "п")
        data = json.loads(vocab.inject())
        self.assertEqual(
            data["hookSpecificOutput"]["hookEventName"], "SessionStart")

    def test_inject_accepts_custom_event_name(self):
        vocab.add("throughput", "п")
        data = json.loads(vocab.inject("UserPromptSubmit"))
        self.assertEqual(
            data["hookSpecificOutput"]["hookEventName"], "UserPromptSubmit")
        # word list still present regardless of event
        self.assertIn("throughput", data["hookSpecificOutput"]["additionalContext"])

    def test_inject_includes_remaining_count(self):
        vocab.add("throughput", "пропускна здатність")
        ctx = json.loads(vocab.inject())["hookSpecificOutput"]["additionalContext"]
        self.assertIn("remaining 10", ctx)

    def test_inject_instruction_has_summary_footer_rule(self):
        vocab.add("throughput", "п")
        ctx = json.loads(vocab.inject())["hookSpecificOutput"]["additionalContext"]
        self.assertIn("summary", ctx.lower())
        self.assertIn("Vocabulary", ctx)

    def test_inject_instruction_has_anti_bias_rule(self):
        vocab.add("throughput", "п")
        ctx = json.loads(vocab.inject())["hookSpecificOutput"]["additionalContext"]
        self.assertIn("naturally", ctx.lower())
        self.assertIn("influence", ctx.lower())

    def test_inject_wraps_in_xml_block(self):
        vocab.add("throughput", "пропускна здатність")
        ctx = json.loads(vocab.inject())["hookSpecificOutput"]["additionalContext"]
        self.assertIn("<vocab_glossing>", ctx)
        self.assertIn("</vocab_glossing>", ctx)
        self.assertIn("<rules>", ctx)
        self.assertIn("<active_words>", ctx)
        # the word list lives inside the <active_words> tag (split on the real
        # opening tag '<active_words>\n', not the mention of it in the rules text)
        words = ctx.split("<active_words>\n")[1].split("\n</active_words>")[0]
        self.assertIn("throughput", words)
        self.assertIn("remaining 10", words)

    def test_inject_uses_configured_languages(self):
        cfg = self.csv_path + ".config.json"
        with open(cfg, "w", encoding="utf-8") as f:
            json.dump({"native_language": "Spanish",
                       "learning_language": "German"}, f)
        os.environ["VOCAB_CONFIG"] = cfg
        try:
            vocab.add("throughput", "rendimiento")
            ctx = json.loads(vocab.inject())["hookSpecificOutput"]["additionalContext"]
            self.assertIn("Spanish", ctx)
            self.assertIn("German", ctx)
        finally:
            os.remove(cfg)


class ConfigTest(VocabTestBase):
    def _write(self, data):
        cfg = self.csv_path + ".config.json"
        with open(cfg, "w", encoding="utf-8") as f:
            f.write(data)
        os.environ["VOCAB_CONFIG"] = cfg
        return cfg

    def test_defaults_when_no_config_file(self):
        os.environ["VOCAB_CONFIG"] = self.csv_path + ".missing.json"
        cfg = vocab.load_config()
        self.assertEqual(cfg["native_language"], "Ukrainian")
        self.assertEqual(cfg["learning_language"], "English")

    def test_reads_values_from_file(self):
        path = self._write('{"native_language": "Spanish"}')
        try:
            cfg = vocab.load_config()
            self.assertEqual(cfg["native_language"], "Spanish")
            # unspecified key keeps its default
            self.assertEqual(cfg["learning_language"], "English")
        finally:
            os.remove(path)

    def test_bad_json_falls_back_to_defaults(self):
        path = self._write("not valid json {{")
        try:
            cfg = vocab.load_config()
            self.assertEqual(cfg["native_language"], "Ukrainian")
        finally:
            os.remove(path)


class DataDirTest(unittest.TestCase):
    def setUp(self):
        self._saved = {k: os.environ.get(k)
                       for k in ("VOCAB_HOME", "VOCAB_CSV", "VOCAB_CONFIG")}
        for k in self._saved:
            os.environ.pop(k, None)

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_default_data_dir_is_dot_lexigloss(self):
        self.assertEqual(vocab.data_dir(), os.path.expanduser("~/.lexigloss"))
        self.assertEqual(
            vocab.csv_path(),
            os.path.join(os.path.expanduser("~/.lexigloss"), "words.csv"))

    def test_vocab_home_override(self):
        os.environ["VOCAB_HOME"] = "/tmp/lexi_home"
        self.assertEqual(vocab.data_dir(), "/tmp/lexi_home")
        self.assertEqual(vocab.csv_path(), "/tmp/lexi_home/words.csv")
        self.assertEqual(vocab.config_path(), "/tmp/lexi_home/config.json")

    def test_save_rows_creates_missing_dir(self):
        d = tempfile.mkdtemp()
        try:
            nested = os.path.join(d, "sub", "words.csv")
            vocab.save_rows(nested, [])
            self.assertTrue(os.path.exists(nested))
        finally:
            shutil.rmtree(d)

    def test_main_registers_script_path(self):
        d = tempfile.mkdtemp()
        try:
            os.environ["VOCAB_HOME"] = d
            vocab.main(["list-active"])  # any command triggers registration
            registered = os.path.join(d, ".script_path")
            self.assertTrue(os.path.exists(registered))
            with open(registered, encoding="utf-8") as f:
                self.assertEqual(f.read(), os.path.abspath(vocab.__file__))
        finally:
            shutil.rmtree(d)


if __name__ == "__main__":
    unittest.main()
