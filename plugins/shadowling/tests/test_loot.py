import json
import os
import shutil
import tempfile
import unittest

import appdb
import core
import loot


def _event_array(structured_output, subtype="success", is_error=False):
    return json.dumps(
        [
            {"type": "system", "subtype": "init"},
            {
                "type": "result",
                "subtype": subtype,
                "is_error": is_error,
                "structured_output": structured_output,
            },
        ]
    )


def _item(word, **over):
    base = {
        "word": word,
        "translation": "переклад-" + word,
        "examples": [f"A sentence using {word} here."],
        "synonyms": ["syn"],
        "definition": "a definition",
        "source_context": f"context for {word}",
    }
    base.update(over)
    return base


def echo_runner(by_word, *, fail=False, capture=None):
    """Fake runner: returns enrichment for whichever input words appear in `data`.
    fail=True emits an is_error result (-> HeadlessError every attempt)."""

    def runner(argv, data):
        if capture is not None:
            capture.append(data)
        if fail:
            return _event_array({}, subtype="error_max_turns", is_error=True)
        present = [w for w in by_word if f"<word>{w}</word>" in data]
        return _event_array({"words": [by_word[w] for w in present]})

    return runner


class LootDriverBase(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        os.environ["SHADOWLING_HOME"] = self.home
        core.save_config(
            {
                "first_language": "Ukrainian",
                "learning_language": "English",
                "explanation_language": "English",
            }
        )

    def tearDown(self):
        os.environ.pop("SHADOWLING_HOME", None)
        shutil.rmtree(self.home, ignore_errors=True)

    def rows_by_word(self):
        return {r["word"]: r for r in appdb.query("SELECT * FROM vocab")}


class PromptTest(LootDriverBase):
    def test_prompt_loads_and_nonempty(self):
        self.assertTrue(loot._loot_prompt().strip())


class EnrichTest(LootDriverBase):
    def test_new_word_is_enriched_and_persisted(self):
        cfg = core.load_config()
        runner = echo_runner({"throughput": _item("throughput")})
        summary = loot.run({"throughput": "We boosted throughput."}, cfg, runner=runner)
        self.assertEqual(summary["enriched"], 1)
        self.assertEqual(summary["pending"], [])
        r = self.rows_by_word()["throughput"]
        self.assertEqual(
            json.loads(r["examples"]), ["A sentence using throughput here."]
        )
        self.assertEqual(r["definition"], "a definition")
        self.assertEqual(r["source_context"], "context for throughput")

    def test_example_must_contain_word_else_word_pending(self):
        cfg = core.load_config()
        bad = _item("throughput", examples=["this example omits the term"])
        runner = echo_runner({"throughput": bad})
        summary = loot.run({"throughput": "ctx"}, cfg, runner=runner)
        self.assertEqual(summary["enriched"], 0)
        self.assertEqual(summary["pending"], ["throughput"])
        self.assertNotIn("throughput", self.rows_by_word())

    def test_case_insensitive_word_containment_is_valid(self):
        cfg = core.load_config()
        item = _item("throughput", examples=["Throughput leads the sentence."])
        runner = echo_runner({"throughput": item})
        summary = loot.run({"throughput": "ctx"}, cfg, runner=runner)
        self.assertEqual(summary["enriched"], 1)

    def test_pre_read_feeds_existing_record_to_the_model(self):
        from models.vocab import Vocab

        Vocab.add(
            "throughput",
            "old",
            examples=["old grounded throughput line"],
            source_context="old ctx",
        )
        cfg = core.load_config()
        captured = []
        runner = echo_runner({"throughput": _item("throughput")}, capture=captured)
        loot.run({"throughput": ""}, cfg, runner=runner)
        self.assertTrue(captured)
        # the stored known_examples is forwarded to the model
        self.assertIn("old grounded throughput line", captured[0])

    def test_chunk_failure_leaves_words_pending(self):
        cfg = core.load_config()
        runner = echo_runner({}, fail=True)
        summary = loot.run({"throughput": "ctx"}, cfg, runner=runner)
        self.assertEqual(summary["enriched"], 0)
        self.assertEqual(summary["pending"], ["throughput"])

    def test_partial_success_persists_valid_only(self):
        cfg = core.load_config()
        runner = echo_runner(
            {
                "alpha": _item("alpha"),
                "beta": _item("beta", examples=["missing the term entirely"]),
            }
        )
        summary = loot.run({"alpha": "a", "beta": "b"}, cfg, runner=runner)
        self.assertEqual(summary["enriched"], 1)
        self.assertEqual(summary["pending"], ["beta"])
        self.assertIn("alpha", self.rows_by_word())
        self.assertNotIn("beta", self.rows_by_word())

    def test_identity_translation_goes_pending_not_silently_lost(self):
        # LLM echoed the term as its own translation -> _add_on no-ops (untranslated).
        # The word must surface as pending, never vanish: enriched + pending == total.
        cfg = core.load_config()
        item = _item("throughput", translation="throughput")
        runner = echo_runner({"throughput": item})
        summary = loot.run({"throughput": "ctx"}, cfg, runner=runner)
        self.assertEqual(summary["enriched"], 0)
        self.assertEqual(summary["pending"], ["throughput"])
        self.assertNotIn("throughput", self.rows_by_word())

    def test_reloot_overwrites_examples(self):
        from models.vocab import Vocab

        Vocab.add("throughput", "t", examples=["stale throughput line"])
        cfg = core.load_config()
        fresh = _item("throughput", examples=["fresh throughput line"])
        runner = echo_runner({"throughput": fresh})
        loot.run({"throughput": "new ctx"}, cfg, runner=runner)
        r = self.rows_by_word()["throughput"]
        self.assertEqual(json.loads(r["examples"]), ["fresh throughput line"])


if __name__ == "__main__":
    unittest.main()
