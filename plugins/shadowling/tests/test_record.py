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
        # record() stamps the ambient session via core.session_id() (mandatory)
        os.environ["CLAUDE_CODE_SESSION_ID"] = "sess-test"

    def tearDown(self):
        os.environ.pop("SHADOWLING_HOME", None)
        os.environ.pop("CLAUDE_CODE_SESSION_ID", None)
        shutil.rmtree(self.home, ignore_errors=True)

    def _incidents(self, table):
        return appdb.query(f"SELECT * FROM {table} ORDER BY id")


class GrammarRecordTest(RecordTestBase):
    def test_first_record_inserts_incident_and_view_row(self):
        from models.grammar import Grammar

        self.assertEqual(
            models.RECORDERS["grammar"](
                "article-omission-before-countable",
                "drops 'the' before nouns",
                "I went to store",
                "I went to the store",
                "use the before specific nouns",
            ),
            1,
        )
        row = Grammar.select("article-omission-before-countable")
        self.assertEqual(row["counter"], 1)
        self.assertEqual(row["problem"], "drops 'the' before nouns")
        self.assertEqual(row["original"], "I went to store")
        self.assertEqual(row["fixed"], "I went to the store")
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
        self.assertEqual(models.RECORDERS["grammar"]("s1", "p", "c", "d", "r"), 2)
        row = Grammar.select("s1")
        self.assertEqual(row["counter"], 2)
        self.assertEqual(row["original"], "c")  # latest incident wins
        self.assertEqual(row["fixed"], "d")
        self.assertEqual(len(self._incidents("grammar")), 2)

    def test_slug_normalized_dedups_across_formatting(self):
        from models.grammar import Grammar

        self.assertEqual(
            models.RECORDERS["grammar"]("Word Choice Plural", "p", "a", "b", "r"),
            1,
        )
        self.assertEqual(
            models.RECORDERS["grammar"]("word-choice-plural", "p", "c", "d", "r"),
            2,
        )
        self.assertEqual(
            models.RECORDERS["grammar"]("  word_choice  plural ", "p", "e", "f", "r"),
            3,
        )
        self.assertEqual(Grammar.select("word-choice-plural")["counter"], 3)
        self.assertTrue(
            all(r["slug"] == "word-choice-plural" for r in self._incidents("grammar"))
        )


class RephrasingRecordTest(RecordTestBase):
    def test_record_inserts_incident_and_view_row(self):
        from models.rephrasing import Rephrasing

        self.assertEqual(
            models.RECORDERS["rephrasing"](
                "collocation-make-vs-take-photo",
                "wrong verb with photo",
                "make a photo",
                "take a photo",
                "English uses 'take' with photo",
            ),
            1,
        )
        row = Rephrasing.select("collocation-make-vs-take-photo")
        self.assertEqual(row["counter"], 1)
        self.assertEqual(row["learner_wrote"], "make a photo")
        self.assertEqual(row["native_phrase"], "take a photo")
        incidents = self._incidents("rephrasing")
        self.assertEqual(incidents[0]["learner_wrote"], "make a photo")
        self.assertEqual(incidents[0]["native_phrase"], "take a photo")
        self.assertEqual(incidents[0]["why"], "English uses 'take' with photo")


class IdiomsRecordTest(RecordTestBase):
    def test_record_uses_natural_key_and_logs(self):
        from models.idioms import Idioms

        self.assertEqual(
            models.RECORDERS["idioms"](
                "break the ice",
                "почати розмову",
                "at a party",
                "I wanted to broke the ice",
            ),
            1,
        )
        row = Idioms.select("break the ice")
        self.assertEqual(row["counter"], 1)
        self.assertEqual(row["meaning"], "почати розмову")
        self.assertEqual(row["learner_wrote"], "I wanted to broke the ice")
        self.assertEqual(self._incidents("idioms")[0]["context"], "at a party")

    def test_same_idiom_case_and_spacing_increment(self):
        models.RECORDERS["idioms"]("break the ice", "m", "c", "y1")
        self.assertEqual(
            models.RECORDERS["idioms"]("Break  the Ice", "m", "c", "y2"), 2
        )  # natural key normalized: casefold + space collapse
        from models.idioms import Idioms

        self.assertEqual(Idioms.select("break the ice")["counter"], 2)


class VerbsRecordTest(RecordTestBase):
    def test_record_uses_verb_key_and_logs(self):
        from models.verbs import Verbs

        self.assertEqual(
            models.RECORDERS["verbs"](
                "go",
                "went",
                "gone",
                "I have went",
                "I have gone",
                "I have went to the store yesterday",
            ),
            1,
        )
        row = Verbs.select("go")
        self.assertEqual(row["counter"], 1)
        self.assertEqual(row["past"], "went")
        self.assertEqual(row["participle"], "gone")
        self.assertEqual(row["used_form"], "I have went")
        self.assertEqual(row["correction"], "I have gone")
        self.assertEqual(row["context"], "I have went to the store yesterday")
        incident = self._incidents("verbs")[0]
        self.assertEqual(incident["used_form"], "I have went")
        self.assertEqual(incident["correction"], "I have gone")
        self.assertEqual(incident["context"], "I have went to the store yesterday")

    def test_verb_key_normalized(self):
        from models.verbs import Verbs

        models.RECORDERS["verbs"]("Go", "went", "gone", "u1", "c1", "ctx1")
        self.assertEqual(
            models.RECORDERS["verbs"](" go ", "went", "gone", "u2", "c2", "ctx2"),
            2,
        )
        self.assertEqual(Verbs.select("go")["counter"], 2)


class DecodeRecordTest(RecordTestBase):
    def test_fixed_record_inserts_incident_and_view_row(self):
        from models.decode import Decode

        self.assertEqual(
            models.RECORDERS["decode"](
                "break-the-ice",
                "fixed",
                "break the ice",
                "to start a conversation in an awkward situation",
                "memorize: set phrase",
                "maybe physically break ice?",
                "at a party someone said it",
            ),
            1,
        )
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

        self.assertEqual(
            models.RECORDERS["decode"](
                "Present Perfect Passive",
                "method",
                "it has been done",
                "a completed action where the doer is unimportant",
                "rule: has/have + been + V3",
                "thought it was 'has did'",
                "ctx1",
            ),
            1,
        )
        self.assertEqual(
            models.RECORDERS["decode"](
                "present-perfect-passive",
                "method",
                "the form has been submitted",
                "a completed action where the doer is unimportant",
                "rule: has/have + been + V3",
                "thought 'has submit'",
                "ctx2",
            ),
            2,
        )
        row = Decode.select("present-perfect-passive")
        self.assertEqual(row["counter"], 2)
        self.assertEqual(row["expression"], "the form has been submitted")


class FrictionRecordTest(RecordTestBase):
    def test_record_inserts_incident_and_view_row(self):
        from models.friction import Friction

        self.assertEqual(
            models.RECORDERS["friction"](
                "polite-pushback",
                "register",
                "disagreeing politely in reviews",
                "та ну, це ж очевидно неправильно",
                "I see it differently — here's my concern",
                "review thread, switched mid-discussion",
            ),
            1,
        )
        row = Friction.select("polite-pushback")
        self.assertEqual(row["counter"], 1)
        self.assertEqual(row["type"], "register")
        self.assertEqual(row["learner_wrote"], "та ну, це ж очевидно неправильно")
        self.assertEqual(
            row["native_phrase"], "I see it differently — here's my concern"
        )
        self.assertEqual(
            self._incidents("friction")[0]["context"],
            "review thread, switched mid-discussion",
        )

    def test_same_zone_increments_across_fragments(self):
        from models.friction import Friction

        models.RECORDERS["friction"](
            "Polite Pushback",
            "register",
            "disagreeing politely",
            "ну такое",
            "I'm not convinced",
            "ctx1",
        )
        self.assertEqual(
            models.RECORDERS["friction"](
                "polite-pushback",
                "register",
                "disagreeing politely",
                "та ви шо",
                "with respect, I disagree",
                "ctx2",
            ),
            2,
        )
        row = Friction.select("polite-pushback")
        self.assertEqual(row["counter"], 2)
        self.assertEqual(row["learner_wrote"], "та ви шо")


if __name__ == "__main__":
    unittest.main()
