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
        self.assertTrue(row["last_seen"])
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


if __name__ == "__main__":
    unittest.main()
