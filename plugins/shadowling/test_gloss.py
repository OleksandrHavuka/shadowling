import json
import os
import shutil
import tempfile
import unittest

import appdb
import core
import gloss
from models.vocab import Vocab


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
        Vocab.add("throughput", "п")
        tpath = make_transcript("This improves throughput under load.")
        try:
            changed = gloss.scan(self._stdin(tpath))
        finally:
            os.remove(tpath)
        self.assertEqual(changed, ["throughput"])
        self.assertEqual(self.rows_by_word()["throughput"]["remaining"], 9)

    def test_scan_ignores_absent_word(self):
        Vocab.add("throughput", "п")
        tpath = make_transcript("Nothing relevant here.")
        try:
            changed = gloss.scan(self._stdin(tpath))
        finally:
            os.remove(tpath)
        self.assertEqual(changed, [])
        self.assertEqual(self.rows_by_word()["throughput"]["remaining"], 10)

    def test_scan_graduates_at_zero(self):
        Vocab.add("throughput", "п")
        self._set("throughput", remaining=1)
        tpath = make_transcript("throughput throughput")  # still one decrement
        try:
            gloss.scan(self._stdin(tpath))
        finally:
            os.remove(tpath)
        row = self.rows_by_word()["throughput"]
        self.assertEqual(row["remaining"], 0)
        self.assertEqual(row["status"], "learned")

    def test_scan_skips_learned_words(self):
        Vocab.add("throughput", "п")
        self._set("throughput", status="learned", remaining=0)
        tpath = make_transcript("throughput throughput")
        try:
            changed = gloss.scan(self._stdin(tpath))
        finally:
            os.remove(tpath)
        self.assertEqual(changed, [])

    def test_scan_uses_last_assistant_message_only(self):
        Vocab.add("throughput", "п")
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
            changed = gloss.scan(self._stdin(tpath))
        finally:
            os.remove(tpath)
        self.assertEqual(changed, [])  # last message has no match

    def test_scan_bad_stdin_never_raises(self):
        self.assertEqual(gloss.scan("not json"), [])
        self.assertEqual(gloss.scan(""), [])

    def test_scan_missing_transcript_path_returns_empty(self):
        self.assertEqual(
            gloss.scan(json.dumps({"transcript_path": "/no/such.jsonl"})), []
        )

    def test_scan_main_bad_stdin_returns_zero(self):
        # Hook path must never crash even on completely invalid stdin
        import io

        old_stdin = gloss.sys.stdin
        gloss.sys.stdin = io.StringIO("not json at all")
        try:
            ret = gloss.main(["scan"])
        finally:
            gloss.sys.stdin = old_stdin
        self.assertEqual(ret, 0)


class InjectTest(VocabTestBase):
    def test_inject_empty_when_no_active_words(self):
        self.assertEqual(gloss.inject(), "")

    def test_inject_emits_sessionstart_json_with_words(self):
        Vocab.add("throughput", "пропускна здатність")
        out = gloss.inject()
        data = json.loads(out)
        self.assertEqual(data["hookSpecificOutput"]["hookEventName"], "SessionStart")
        ctx = data["hookSpecificOutput"]["additionalContext"]
        self.assertIn("throughput", ctx)
        self.assertIn("пропускна здатність", ctx)  # utf-8 preserved
        self.assertIn("first", ctx.lower())  # instruction present

    def test_inject_excludes_learned_words(self):
        Vocab.add("alpha", "а")
        Vocab.add("beta", "б")
        self._set("beta", status="learned")
        ctx = json.loads(gloss.inject())["hookSpecificOutput"]["additionalContext"]
        self.assertIn("alpha", ctx)
        self.assertNotIn("beta", ctx)

    def test_inject_defaults_to_sessionstart(self):
        Vocab.add("throughput", "п")
        data = json.loads(gloss.inject())
        self.assertEqual(data["hookSpecificOutput"]["hookEventName"], "SessionStart")

    def test_inject_accepts_custom_event_name(self):
        Vocab.add("throughput", "п")
        data = json.loads(gloss.inject("UserPromptSubmit"))
        self.assertEqual(
            data["hookSpecificOutput"]["hookEventName"], "UserPromptSubmit"
        )
        # word list still present regardless of event
        self.assertIn("throughput", data["hookSpecificOutput"]["additionalContext"])

    def test_inject_includes_remaining_count(self):
        Vocab.add("throughput", "пропускна здатність")
        ctx = json.loads(gloss.inject())["hookSpecificOutput"]["additionalContext"]
        self.assertIn("remaining 10", ctx)

    def test_inject_instruction_has_summary_footer_rule(self):
        Vocab.add("throughput", "п")
        ctx = json.loads(gloss.inject())["hookSpecificOutput"]["additionalContext"]
        self.assertIn("summary", ctx.lower())
        self.assertIn("Vocabulary", ctx)

    def test_inject_instruction_has_anti_bias_rule(self):
        Vocab.add("throughput", "п")
        ctx = json.loads(gloss.inject())["hookSpecificOutput"]["additionalContext"]
        self.assertIn("naturally", ctx.lower())
        self.assertIn("influence", ctx.lower())

    def test_inject_wraps_in_xml_block(self):
        Vocab.add("throughput", "пропускна здатність")
        ctx = json.loads(gloss.inject())["hookSpecificOutput"]["additionalContext"]
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
        Vocab.add("throughput", "rendimiento")
        ctx = json.loads(gloss.inject())["hookSpecificOutput"]["additionalContext"]
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
        data = json.loads(gloss.inject("UserPromptSubmit"))
        self.assertEqual(
            data["hookSpecificOutput"]["hookEventName"], "UserPromptSubmit"
        )
        ctx = data["hookSpecificOutput"]["additionalContext"]
        self.assertIn("learning_language", ctx)
        self.assertIn("setup", ctx.lower())

    def test_inject_notice_names_every_missing_key(self):
        self._partial_config({"first_language": "Ukrainian"})
        ctx = json.loads(gloss.inject())["hookSpecificOutput"]["additionalContext"]
        self.assertIn("learning_language", ctx)
        self.assertIn("explanation_language", ctx)

    def test_inject_notice_when_config_completely_empty(self):
        self._partial_config({})
        ctx = json.loads(gloss.inject())["hookSpecificOutput"]["additionalContext"]
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

    def test_inject_notices_without_config(self):
        # inject is the one user-visible hook, so an absent config is reported
        # here (capture/scan stay silently gated) rather than going dark.
        Vocab.add("hello", "привіт")
        self._unconfigure()
        ctx = json.loads(gloss.inject())["hookSpecificOutput"]["additionalContext"]
        self.assertIn("not fully configured", ctx)

    def test_scan_noop_without_config(self):
        Vocab.add("throughput", "пропускна здатність")
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
        self.assertEqual(gloss.scan(json.dumps({"transcript_path": tpath})), [])
        self.assertEqual(self.rows_by_word()["throughput"]["remaining"], 10)


if __name__ == "__main__":
    unittest.main()
