import contextlib
import io
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

import appdb
import core
import vocab


def run_main(argv):
    """Run vocab.main(argv), returning (exit_code, stdout)."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = vocab.main(argv)
    return code, buf.getvalue()


class VocabTestBase(unittest.TestCase):
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

    def rows_by_word(self):
        return {r["word"]: r for r in appdb.query("SELECT * FROM vocab")}

    def _set(self, word, **cols):
        """Force a vocab row's state directly (replaces the old CSV poke)."""
        con = appdb.connect()
        try:
            with con:
                for col, val in cols.items():
                    con.execute(
                        f"UPDATE vocab SET {col} = ? WHERE word = ?", (val, word)
                    )
        finally:
            con.close()


class AddTest(VocabTestBase):
    def test_add_new_word_starts_at_10_active(self):
        action, row = vocab.add("Throughput", "пропускна здатність")
        self.assertEqual(action, "add")
        self.assertEqual(row["word"], "throughput")  # stored lowercased
        self.assertEqual(row["translation"], "пропускна здатність")
        self.assertEqual(row["remaining"], 10)
        self.assertEqual(row["status"], "active")

    def test_rows_persist_in_sqlite(self):
        vocab.add("throughput", "пропускна здатність")
        rows = self.rows_by_word()
        self.assertEqual(rows["throughput"]["remaining"], 10)
        self.assertEqual(rows["throughput"]["status"], "active")

    def test_add_existing_active_refreshes_translation_keeps_remaining(self):
        vocab.add("throughput", "old")
        self._set("throughput", remaining=7)  # simulate prior exposure
        action, row = vocab.add("throughput", "new translation")
        self.assertEqual(action, "refresh")
        self.assertEqual(row["translation"], "new translation")
        self.assertEqual(row["remaining"], 7)  # unchanged
        self.assertEqual(row["status"], "active")

    def test_add_identity_translation_is_untranslated_and_not_saved(self):
        action, _ = vocab.add("Awesome", "awesome")  # case/space-insensitive match
        self.assertEqual(action, "untranslated")
        self.assertNotIn("awesome", self.rows_by_word())

    def test_add_empty_translation_is_untranslated_and_not_saved(self):
        action, _ = vocab.add("throughput", "   ")
        self.assertEqual(action, "untranslated")
        self.assertNotIn("throughput", self.rows_by_word())

    def test_add_stamps_created_and_updated(self):
        with mock.patch("vocab._now", return_value="2026-06-12T08:00:00"):
            vocab.add("throughput", "переклад")
        r = self.rows_by_word()["throughput"]
        self.assertEqual(r["created_at"], "2026-06-12T08:00:00")
        self.assertEqual(r["updated_at"], "2026-06-12T08:00:00")
        with mock.patch("vocab._now", return_value="2026-06-12T09:30:00"):
            vocab.add("throughput", "новий переклад")  # refresh
        r2 = self.rows_by_word()["throughput"]
        self.assertEqual(r2["created_at"], "2026-06-12T08:00:00")  # pinned
        self.assertEqual(r2["updated_at"], "2026-06-12T09:30:00")  # bumped

    def test_add_existing_learned_resets_to_10_active(self):
        vocab.add("throughput", "t")
        self._set("throughput", remaining=0, status="learned")
        action, row = vocab.add("throughput", "t2")
        self.assertEqual(action, "relearn")
        self.assertEqual(row["remaining"], 10)
        self.assertEqual(row["status"], "active")
        self.assertEqual(row["translation"], "t2")


class RemoveTest(VocabTestBase):
    def test_remove_existing_returns_true_and_deletes(self):
        vocab.add("throughput", "t")
        self.assertTrue(vocab.remove("Throughput"))  # case-insensitive
        self.assertNotIn("throughput", self.rows_by_word())

    def test_remove_unknown_returns_false_no_error(self):
        self.assertFalse(vocab.remove("nonexistent"))


class MainAddTest(VocabTestBase):
    def test_add_multiple_pairs_stores_all(self):
        code, out = run_main(
            ["add", "hello", "привіт", "machine learning", "машинне навчання"]
        )
        self.assertEqual(code, 0)
        rows = self.rows_by_word()
        self.assertEqual(rows["hello"]["translation"], "привіт")
        self.assertEqual(rows["machine learning"]["translation"], "машинне навчання")
        # one result line per word
        self.assertEqual(out.count("\n"), 2)

    def test_add_single_pair_still_works(self):
        code, out = run_main(["add", "throughput", "пропускна здатність"])
        self.assertEqual(code, 0)
        self.assertEqual(
            self.rows_by_word()["throughput"]["translation"], "пропускна здатність"
        )

    def test_add_odd_arg_count_is_error(self):
        code, _ = run_main(["add", "hello", "привіт", "orphan"])
        self.assertEqual(code, 1)

    def test_add_no_args_is_error(self):
        code, _ = run_main(["add"])
        self.assertEqual(code, 1)


class MainRemoveTest(VocabTestBase):
    def test_remove_multiple_words(self):
        vocab.add("alpha", "а")
        vocab.add("beta", "б")
        code, out = run_main(["remove", "alpha", "beta"])
        self.assertEqual(code, 0)
        self.assertEqual(self.rows_by_word(), {})
        self.assertIn("alpha: removed", out)
        self.assertIn("beta: removed", out)

    def test_remove_reports_unknown_per_word(self):
        vocab.add("alpha", "а")
        code, out = run_main(["remove", "alpha", "ghost"])
        self.assertEqual(code, 0)
        self.assertIn("alpha: removed", out)
        self.assertIn("ghost: not found", out)


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
        self._set("beta", status="learned")
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
        self.assertEqual(self.rows_by_word()["throughput"]["remaining"], 9)

    def test_scan_ignores_absent_word(self):
        vocab.add("throughput", "п")
        tpath = make_transcript("Nothing relevant here.")
        try:
            changed = vocab.scan(self._stdin(tpath))
        finally:
            os.remove(tpath)
        self.assertEqual(changed, [])
        self.assertEqual(self.rows_by_word()["throughput"]["remaining"], 10)

    def test_scan_graduates_at_zero(self):
        vocab.add("throughput", "п")
        self._set("throughput", remaining=1)
        tpath = make_transcript("throughput throughput")  # still one decrement
        try:
            vocab.scan(self._stdin(tpath))
        finally:
            os.remove(tpath)
        row = self.rows_by_word()["throughput"]
        self.assertEqual(row["remaining"], 0)
        self.assertEqual(row["status"], "learned")

    def test_scan_skips_learned_words(self):
        vocab.add("throughput", "п")
        self._set("throughput", status="learned", remaining=0)
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
        a = {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "throughput here"}],
            },
        }
        b = {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "no vocab word now"}],
            },
        }
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
        self.assertEqual(
            vocab.scan(json.dumps({"transcript_path": "/no/such.jsonl"})), []
        )

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
        self.assertEqual(data["hookSpecificOutput"]["hookEventName"], "SessionStart")
        ctx = data["hookSpecificOutput"]["additionalContext"]
        self.assertIn("throughput", ctx)
        self.assertIn("пропускна здатність", ctx)  # utf-8 preserved
        self.assertIn("first", ctx.lower())  # instruction present

    def test_inject_excludes_learned_words(self):
        vocab.add("alpha", "а")
        vocab.add("beta", "б")
        self._set("beta", status="learned")
        ctx = json.loads(vocab.inject())["hookSpecificOutput"]["additionalContext"]
        self.assertIn("alpha", ctx)
        self.assertNotIn("beta", ctx)

    def test_inject_defaults_to_sessionstart(self):
        vocab.add("throughput", "п")
        data = json.loads(vocab.inject())
        self.assertEqual(data["hookSpecificOutput"]["hookEventName"], "SessionStart")

    def test_inject_accepts_custom_event_name(self):
        vocab.add("throughput", "п")
        data = json.loads(vocab.inject("UserPromptSubmit"))
        self.assertEqual(
            data["hookSpecificOutput"]["hookEventName"], "UserPromptSubmit"
        )
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

    def test_inject_uses_configured_first_language(self):
        core.save_config({"first_language": "Spanish"})
        vocab.add("throughput", "rendimiento")
        ctx = json.loads(vocab.inject())["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Spanish", ctx)


class InjectMisconfigTest(VocabTestBase):
    """Incomplete config: inject surfaces the load_config notice (the only
    user-visible hook) naming the unset keys, rather than silently going dark."""

    def _partial_config(self, data):
        with open(core.config_path(), "w", encoding="utf-8") as f:
            json.dump(data, f)

    def test_inject_emits_notice_when_required_key_missing(self):
        self._partial_config(
            {"first_language": "Ukrainian", "explanation_language": "English"}
        )
        data = json.loads(vocab.inject("UserPromptSubmit"))
        self.assertEqual(
            data["hookSpecificOutput"]["hookEventName"], "UserPromptSubmit"
        )
        ctx = data["hookSpecificOutput"]["additionalContext"]
        self.assertIn("learning_language", ctx)
        self.assertIn("setup", ctx.lower())

    def test_inject_notice_names_every_missing_key(self):
        self._partial_config({"first_language": "Ukrainian"})
        ctx = json.loads(vocab.inject())["hookSpecificOutput"]["additionalContext"]
        self.assertIn("learning_language", ctx)
        self.assertIn("explanation_language", ctx)

    def test_inject_notice_when_config_completely_empty(self):
        self._partial_config({})
        ctx = json.loads(vocab.inject())["hookSpecificOutput"]["additionalContext"]
        self.assertIn("not fully configured", ctx)


class DataDirTest(unittest.TestCase):
    def setUp(self):
        self._home = os.environ.pop("SHADOWLING_HOME", None)

    def tearDown(self):
        if self._home is None:
            os.environ.pop("SHADOWLING_HOME", None)
        else:
            os.environ["SHADOWLING_HOME"] = self._home

    def test_default_data_dir_is_dot_shadowling(self):
        self.assertEqual(core.data_dir(), os.path.expanduser("~/.shadowling"))
        self.assertEqual(
            core.config_path(), os.path.expanduser("~/.shadowling/config.json")
        )

    def test_env_home_overrides_everything(self):
        os.environ["SHADOWLING_HOME"] = "/tmp/shadowling_home"
        self.assertEqual(core.data_dir(), "/tmp/shadowling_home")
        self.assertEqual(core.config_path(), "/tmp/shadowling_home/config.json")


class GateTest(VocabTestBase):
    def _unconfigure(self):
        os.remove(os.path.join(self.home, "config.json"))

    def test_add_refuses_without_config(self):
        self._unconfigure()
        code, _ = run_main(["add", "hello", "привіт"])
        self.assertEqual(code, 1)
        self.assertEqual(self.rows_by_word(), {})

    def test_add_emits_notice_without_config(self):
        self._unconfigure()
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = vocab.main(["add", "hello", "привіт"])
        self.assertEqual(code, 1)
        self.assertIn("not fully configured", err.getvalue())

    def test_inject_notices_without_config(self):
        # inject is the one user-visible hook, so an absent config is reported
        # here (capture/scan/add stay silently gated) rather than going dark.
        vocab.add("hello", "привіт")
        self._unconfigure()
        ctx = json.loads(vocab.inject())["hookSpecificOutput"]["additionalContext"]
        self.assertIn("not fully configured", ctx)

    def test_scan_noop_without_config(self):
        vocab.add("throughput", "пропускна здатність")
        self._unconfigure()
        tpath = os.path.join(self.home, "t.jsonl")
        with open(tpath, "w", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {
                        "type": "assistant",
                        "message": {
                            "content": [
                                {"type": "text", "text": "improved throughput a lot"}
                            ]
                        },
                    }
                )
                + "\n"
            )
        self.assertEqual(vocab.scan(json.dumps({"transcript_path": tpath})), [])
        self.assertEqual(self.rows_by_word()["throughput"]["remaining"], 10)


if __name__ == "__main__":
    unittest.main()
