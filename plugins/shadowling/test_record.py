import os
import shutil
import tempfile
import unittest

import jsonl
import models


class RecordTestBase(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        os.environ["SHADOWLING_HOME"] = self.home

    def tearDown(self):
        os.environ.pop("SHADOWLING_HOME", None)
        shutil.rmtree(self.home, ignore_errors=True)

    def _log(self, name):
        return jsonl.read(os.path.join(self.home, name))


class GrammarRecordTest(RecordTestBase):
    def test_first_record_inserts_product_and_log(self):
        from models.grammar import Grammar
        self.assertEqual(models.RECORDERS["grammar"](
            "article-omission-before-countable", "drops 'the' before nouns",
            "I went to store", "I went to the store", "use the before specific nouns"),
            "inserted")
        row = Grammar.select("article-omission-before-countable")
        self.assertEqual(row["counter"], "1")
        self.assertEqual(row["problem"], "drops 'the' before nouns")
        self.assertEqual(row["last example"], "I went to store → I went to the store")
        self.assertTrue(row["created_at"])
        self.assertTrue(row["updated_at"])
        log = self._log("grammar.log.jsonl")
        self.assertEqual(len(log), 1)
        self.assertEqual(log[0]["slug"], "article-omission-before-countable")
        self.assertEqual(log[0]["original"], "I went to store")
        self.assertEqual(log[0]["fixed"], "I went to the store")
        self.assertIn("date", log[0])

    def test_second_record_increments_and_appends(self):
        from models.grammar import Grammar
        models.RECORDERS["grammar"]("s1", "p", "a", "b", "r")
        self.assertEqual(
            models.RECORDERS["grammar"]("s1", "p", "c", "d", "r"), "incremented")
        self.assertEqual(Grammar.select("s1")["counter"], "2")
        self.assertEqual(len(self._log("grammar.log.jsonl")), 2)

    def test_slug_normalized_dedups_across_formatting(self):
        from models.grammar import Grammar
        # Same class, three different LLM formattings → one canonical row.
        self.assertEqual(
            models.RECORDERS["grammar"]("Word Choice Plural", "p", "a", "b", "r"),
            "inserted")
        self.assertEqual(
            models.RECORDERS["grammar"]("word-choice-plural", "p", "c", "d", "r"),
            "incremented")
        self.assertEqual(
            models.RECORDERS["grammar"]("  word_choice  plural ", "p", "e", "f", "r"),
            "incremented")
        self.assertEqual(Grammar.select("word-choice-plural")["counter"], "3")
        # The log slug is canonicalized too, so it joins to the product key.
        self.assertTrue(
            all(r["slug"] == "word-choice-plural"
                for r in self._log("grammar.log.jsonl")))


class RephrasingRecordTest(RecordTestBase):
    def test_record_inserts_product_and_log(self):
        from models.rephrasing import Rephrasing
        self.assertEqual(models.RECORDERS["rephrasing"](
            "collocation-make-vs-take-photo", "wrong verb with photo",
            "make a photo", "take a photo", "English uses 'take' with photo"),
            "inserted")
        row = Rephrasing.select("collocation-make-vs-take-photo")
        self.assertEqual(row["counter"], "1")
        self.assertEqual(row["your phrasing"], "make a photo")
        self.assertEqual(row["natural phrasing"], "take a photo")
        self.assertTrue(row["created_at"])
        self.assertTrue(row["updated_at"])
        log = self._log("rephrasings.log.jsonl")
        self.assertEqual(len(log), 1)
        self.assertEqual(log[0]["yours"], "make a photo")
        self.assertEqual(log[0]["natural"], "take a photo")
        self.assertIn("date", log[0])


class IdiomsRecordTest(RecordTestBase):
    def test_record_uses_natural_key_and_logs(self):
        from models.idioms import Idioms
        self.assertEqual(models.RECORDERS["idioms"](
            "break the ice", "почати розмову", "at a party",
            "I wanted to broke the ice"), "inserted")
        row = Idioms.select("break the ice")
        self.assertEqual(row["counter"], "1")
        self.assertEqual(row["meaning"], "почати розмову")
        self.assertEqual(row["last example"], "I wanted to broke the ice")
        log = self._log("idioms.log.jsonl")
        self.assertEqual(len(log), 1)
        self.assertEqual(log[0]["idiom"], "break the ice")
        self.assertEqual(log[0]["context"], "at a party")
        self.assertEqual(log[0]["you_wrote"], "I wanted to broke the ice")

    def test_same_idiom_increments(self):
        models.RECORDERS["idioms"]("break the ice", "m", "c", "y1")
        self.assertEqual(
            models.RECORDERS["idioms"]("Break the ice", "m", "c", "y2"),
            "incremented")  # natural key normalized


class VerbsRecordTest(RecordTestBase):
    def test_record_uses_verb_key_and_logs(self):
        from models.verbs import Verbs
        self.assertEqual(models.RECORDERS["verbs"](
            "go", "went", "gone", "I have went → I have gone"), "inserted")
        row = Verbs.select("go")
        self.assertEqual(row["counter"], "1")
        self.assertEqual(row["past"], "went")
        self.assertEqual(row["past participle"], "gone")
        self.assertEqual(row["last example"], "I have went → I have gone")
        log = self._log("irregular_verbs.log.jsonl")
        self.assertEqual(len(log), 1)
        self.assertEqual(log[0]["base"], "go")
        self.assertEqual(log[0]["participle"], "gone")
        self.assertEqual(log[0]["example_fix"], "I have went → I have gone")


class DecodeRecordTest(RecordTestBase):
    def test_fixed_record_inserts_product_and_log(self):
        from models.decode import Decode
        self.assertEqual(models.RECORDERS["decode"](
            "break-the-ice", "fixed", "break the ice",
            "to start a conversation in an awkward situation",
            "memorize: set phrase", "maybe physically break ice?",
            "at a party someone said it"), "inserted")
        row = Decode.select("break-the-ice")
        self.assertEqual(row["counter"], "1")
        self.assertEqual(row["type"], "fixed")
        self.assertEqual(row["expression"], "break the ice")
        self.assertEqual(row["meaning"],
                         "to start a conversation in an awkward situation")
        self.assertEqual(row["takeaway"], "memorize: set phrase")
        self.assertTrue(row["created_at"])
        self.assertTrue(row["updated_at"])
        log = self._log("decode.log.jsonl")
        self.assertEqual(len(log), 1)
        self.assertEqual(log[0]["your_read"], "maybe physically break ice?")
        self.assertEqual(log[0]["context"], "at a party someone said it")
        self.assertIn("date", log[0])

    def test_method_increments_by_rule_across_phrases(self):
        from models.decode import Decode
        # Different phrasings of the same rule slug → one row, counter climbs.
        self.assertEqual(models.RECORDERS["decode"](
            "Present Perfect Passive", "method", "it has been done",
            "a completed action where the doer is unimportant",
            "rule: has/have + been + V3", "thought it was 'has did'",
            "ctx1"), "inserted")
        self.assertEqual(models.RECORDERS["decode"](
            "present-perfect-passive", "method", "the form has been submitted",
            "a completed action where the doer is unimportant",
            "rule: has/have + been + V3", "thought 'has submit'",
            "ctx2"), "incremented")
        row = Decode.select("present-perfect-passive")
        self.assertEqual(row["counter"], "2")
        self.assertEqual(row["expression"], "the form has been submitted")  # latest
        self.assertEqual(len(self._log("decode.log.jsonl")), 2)


class FrictionRecordTest(RecordTestBase):
    def test_record_inserts_product_and_log(self):
        from models.friction import Friction
        self.assertEqual(models.RECORDERS["friction"](
            "polite-pushback", "register", "disagreeing politely in reviews",
            "та ну, це ж очевидно неправильно",
            "I see it differently — here's my concern",
            "review thread, switched mid-discussion"), "inserted")
        row = Friction.select("polite-pushback")
        self.assertEqual(row["counter"], "1")
        self.assertEqual(row["type"], "register")
        self.assertEqual(row["zone"], "disagreeing politely in reviews")
        self.assertEqual(row["you reached for"], "та ну, це ж очевидно неправильно")
        self.assertEqual(row["natural english"],
                         "I see it differently — here's my concern")
        self.assertTrue(row["created_at"])
        self.assertTrue(row["updated_at"])
        log = self._log("friction.log.jsonl")
        self.assertEqual(len(log), 1)
        self.assertEqual(log[0]["you_reached_for"],
                         "та ну, це ж очевидно неправильно")
        self.assertEqual(log[0]["context"], "review thread, switched mid-discussion")
        self.assertIn("date", log[0])

    def test_same_zone_increments_across_fragments(self):
        from models.friction import Friction
        self.assertEqual(models.RECORDERS["friction"](
            "Polite Pushback", "register", "disagreeing politely",
            "ну такое", "I'm not convinced", "ctx1"), "inserted")
        self.assertEqual(models.RECORDERS["friction"](
            "polite-pushback", "register", "disagreeing politely",
            "та ви шо", "with respect, I disagree", "ctx2"), "incremented")
        row = Friction.select("polite-pushback")
        self.assertEqual(row["counter"], "2")
        self.assertEqual(row["you reached for"], "та ви шо")  # latest example
        self.assertEqual(len(self._log("friction.log.jsonl")), 2)


if __name__ == "__main__":
    unittest.main()
