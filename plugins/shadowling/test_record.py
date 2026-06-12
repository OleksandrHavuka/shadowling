import os
import shutil
import tempfile
import unittest

import appdb
import models


class RecordTestBase(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        os.environ["SHADOWLING_HOME"] = self.home

    def tearDown(self):
        os.environ.pop("SHADOWLING_HOME", None)
        shutil.rmtree(self.home, ignore_errors=True)

    def _incidents(self, table):
        return appdb.query("SELECT * FROM {0} ORDER BY id".format(table))


class GrammarRecordTest(RecordTestBase):
    def test_first_record_inserts_incident_and_view_row(self):
        from models.grammar import Grammar
        self.assertEqual(models.RECORDERS["grammar"](
            "article-omission-before-countable", "drops 'the' before nouns",
            "I went to store", "I went to the store", "use the before specific nouns"),
            "inserted")
        row = Grammar.select("article-omission-before-countable")
        self.assertEqual(row["counter"], 1)
        self.assertEqual(row["problem"], "drops 'the' before nouns")
        self.assertEqual(row["last example"], "I went to store → I went to the store")
        self.assertTrue(row["created_at"])
        self.assertEqual(row["created_at"], row["updated_at"])
        incidents = self._incidents("grammar")
        self.assertEqual(len(incidents), 1)
        self.assertEqual(incidents[0]["original"], "I went to store")
        self.assertEqual(incidents[0]["fixed"], "I went to the store")
        self.assertEqual(incidents[0]["rule"], "use the before specific nouns")
        self.assertTrue(incidents[0]["created_at"])

    def test_second_record_increments_and_appends(self):
        from models.grammar import Grammar
        models.RECORDERS["grammar"]("s1", "p", "a", "b", "r")
        self.assertEqual(
            models.RECORDERS["grammar"]("s1", "p", "c", "d", "r"), "incremented")
        row = Grammar.select("s1")
        self.assertEqual(row["counter"], 2)
        self.assertEqual(row["last example"], "c → d")  # latest incident wins
        self.assertEqual(len(self._incidents("grammar")), 2)

    def test_slug_normalized_dedups_across_formatting(self):
        from models.grammar import Grammar
        self.assertEqual(
            models.RECORDERS["grammar"]("Word Choice Plural", "p", "a", "b", "r"),
            "inserted")
        self.assertEqual(
            models.RECORDERS["grammar"]("word-choice-plural", "p", "c", "d", "r"),
            "incremented")
        self.assertEqual(
            models.RECORDERS["grammar"]("  word_choice  plural ", "p", "e", "f", "r"),
            "incremented")
        self.assertEqual(Grammar.select("word-choice-plural")["counter"], 3)
        self.assertTrue(all(r["slug"] == "word-choice-plural"
                            for r in self._incidents("grammar")))


class RephrasingRecordTest(RecordTestBase):
    def test_record_inserts_incident_and_view_row(self):
        from models.rephrasing import Rephrasing
        self.assertEqual(models.RECORDERS["rephrasing"](
            "collocation-make-vs-take-photo", "wrong verb with photo",
            "make a photo", "take a photo", "English uses 'take' with photo"),
            "inserted")
        row = Rephrasing.select("collocation-make-vs-take-photo")
        self.assertEqual(row["counter"], 1)
        self.assertEqual(row["you wrote"], "make a photo")
        self.assertEqual(row["natural phrasing"], "take a photo")
        incidents = self._incidents("rephrasing")
        self.assertEqual(incidents[0]["learner_wrote"], "make a photo")
        self.assertEqual(incidents[0]["natural"], "take a photo")
        self.assertEqual(incidents[0]["why"], "English uses 'take' with photo")


class IdiomsRecordTest(RecordTestBase):
    def test_record_uses_natural_key_and_logs(self):
        from models.idioms import Idioms
        self.assertEqual(models.RECORDERS["idioms"](
            "break the ice", "почати розмову", "at a party",
            "I wanted to broke the ice"), "inserted")
        row = Idioms.select("break the ice")
        self.assertEqual(row["counter"], 1)
        self.assertEqual(row["meaning"], "почати розмову")
        self.assertEqual(row["you wrote"], "I wanted to broke the ice")
        self.assertEqual(self._incidents("idioms")[0]["context"], "at a party")

    def test_same_idiom_case_and_spacing_increment(self):
        models.RECORDERS["idioms"]("break the ice", "m", "c", "y1")
        self.assertEqual(
            models.RECORDERS["idioms"]("Break  the Ice", "m", "c", "y2"),
            "incremented")  # natural key normalized: casefold + space collapse
        from models.idioms import Idioms
        self.assertEqual(Idioms.select("break the ice")["counter"], 2)


class VerbsRecordTest(RecordTestBase):
    def test_record_uses_verb_key_and_logs(self):
        from models.verbs import Verbs
        self.assertEqual(models.RECORDERS["verbs"](
            "go", "went", "gone", "I have went → I have gone"), "inserted")
        row = Verbs.select("go")
        self.assertEqual(row["counter"], 1)
        self.assertEqual(row["past"], "went")
        self.assertEqual(row["past participle"], "gone")
        self.assertEqual(row["example fix"], "I have went → I have gone")
        self.assertEqual(self._incidents("verbs")[0]["example_fix"],
                         "I have went → I have gone")

    def test_verb_key_normalized(self):
        from models.verbs import Verbs
        models.RECORDERS["verbs"]("Go", "went", "gone", "e1")
        self.assertEqual(
            models.RECORDERS["verbs"](" go ", "went", "gone", "e2"),
            "incremented")
        self.assertEqual(Verbs.select("go")["counter"], 2)


class DecodeRecordTest(RecordTestBase):
    def test_fixed_record_inserts_incident_and_view_row(self):
        from models.decode import Decode
        self.assertEqual(models.RECORDERS["decode"](
            "break-the-ice", "fixed", "break the ice",
            "to start a conversation in an awkward situation",
            "memorize: set phrase", "maybe physically break ice?",
            "at a party someone said it"), "inserted")
        row = Decode.select("break-the-ice")
        self.assertEqual(row["counter"], 1)
        self.assertEqual(row["type"], "fixed")
        self.assertEqual(row["expression"], "break the ice")
        self.assertEqual(row["takeaway"], "memorize: set phrase")
        incidents = self._incidents("decode")
        self.assertEqual(incidents[0]["learner_wrote"], "maybe physically break ice?")
        self.assertEqual(incidents[0]["context"], "at a party someone said it")

    def test_method_increments_by_rule_across_phrases(self):
        from models.decode import Decode
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
        self.assertEqual(row["counter"], 2)
        self.assertEqual(row["expression"], "the form has been submitted")


class FrictionRecordTest(RecordTestBase):
    def test_record_inserts_incident_and_view_row(self):
        from models.friction import Friction
        self.assertEqual(models.RECORDERS["friction"](
            "polite-pushback", "register", "disagreeing politely in reviews",
            "та ну, це ж очевидно неправильно",
            "I see it differently — here's my concern",
            "review thread, switched mid-discussion"), "inserted")
        row = Friction.select("polite-pushback")
        self.assertEqual(row["counter"], 1)
        self.assertEqual(row["type"], "register")
        self.assertEqual(row["you reached for"], "та ну, це ж очевидно неправильно")
        self.assertEqual(row["natural english"],
                         "I see it differently — here's my concern")
        self.assertEqual(self._incidents("friction")[0]["context"],
                         "review thread, switched mid-discussion")

    def test_same_zone_increments_across_fragments(self):
        from models.friction import Friction
        models.RECORDERS["friction"]("Polite Pushback", "register",
                                     "disagreeing politely", "ну такое",
                                     "I'm not convinced", "ctx1")
        self.assertEqual(models.RECORDERS["friction"](
            "polite-pushback", "register", "disagreeing politely",
            "та ви шо", "with respect, I disagree", "ctx2"), "incremented")
        row = Friction.select("polite-pushback")
        self.assertEqual(row["counter"], 2)
        self.assertEqual(row["you reached for"], "та ви шо")


if __name__ == "__main__":
    unittest.main()
