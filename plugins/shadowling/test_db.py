import contextlib
import io
import os
import shutil
import tempfile
import unittest

import db


def run_main(argv, stdin_text=""):
    """Run db.main(argv) with stdin_text on stdin, returning (exit_code, stdout)."""
    buf = io.StringIO()
    old = db.sys.stdin
    db.sys.stdin = io.StringIO(stdin_text)
    try:
        with contextlib.redirect_stdout(buf):
            code = db.main(argv)
    finally:
        db.sys.stdin = old
    return code, buf.getvalue()


def tags(**fields):
    """Build a tag envelope; field order is irrelevant (read_fields keys by name)."""
    return "".join(f"<{k}>{v}</{k}>" for k, v in fields.items())


GRAMMAR = {"slug": "s1", "problem": "p", "original": "a", "fixed": "b", "rule": "r"}


class DbCliTestBase(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        os.environ["SHADOWLING_HOME"] = self.home

    def tearDown(self):
        os.environ.pop("SHADOWLING_HOME", None)
        shutil.rmtree(self.home, ignore_errors=True)


class RecordSelectTest(DbCliTestBase):
    def test_record_then_select_roundtrip(self):
        code, out = run_main(["grammar", "record"], tags(**GRAMMAR))
        self.assertEqual((code, out.strip()), (0, "inserted"))
        code, out = run_main(["grammar", "select", "s1"])
        self.assertEqual(code, 0)
        self.assertIn('"counter": 1', out)
        self.assertIn('"last example": "a → b"', out)

    def test_missing_field_is_error_with_guidance(self):
        # no longer arity: a missing tag fails loud, and the message must teach
        # the LLM the expected syntax so it can retry.
        err = io.StringIO()
        old = db.sys.stdin
        db.sys.stdin = io.StringIO("<slug>only</slug>")
        try:
            with contextlib.redirect_stderr(err):
                code = db.main(["grammar", "record"])
        finally:
            db.sys.stdin = old
        self.assertEqual(code, 1)
        self.assertIn("missing required tag <problem>", err.getvalue())
        self.assertIn("<fixed>...</fixed>", err.getvalue())  # template shown

    def test_select_all_prints_one_json_per_row(self):
        run_main(["grammar", "record"], tags(**GRAMMAR))
        run_main(
            ["grammar", "record"],
            tags(slug="s2", problem="p", original="c", fixed="d", rule="r"),
        )
        code, out = run_main(["grammar", "select"])
        self.assertEqual(code, 0)
        self.assertEqual(len(out.strip().splitlines()), 2)


class ExportTest(DbCliTestBase):
    def test_export_renders_markdown_table(self):
        run_main(["grammar", "record"], tags(**GRAMMAR))
        code, out = run_main(["grammar", "export"])
        self.assertEqual(code, 0)
        lines = out.strip().splitlines()
        self.assertTrue(lines[0].startswith("| slug |"))
        self.assertTrue(lines[1].startswith("| ---"))
        self.assertIn("| s1 |", lines[2])

    def test_export_escapes_pipes_and_newlines(self):
        run_main(
            ["grammar", "record"],
            tags(slug="s1", problem="p | q", original="a\nb", fixed="c", rule="r"),
        )
        _, out = run_main(["grammar", "export"])
        self.assertIn("p \\| q", out)
        self.assertNotIn("a\nb", out)

    def test_export_empty(self):
        code, out = run_main(["grammar", "export"])
        self.assertEqual((code, out.strip()), (0, "(empty)"))


class DropAndErrorsTest(DbCliTestBase):
    def test_drop(self):
        run_main(["grammar", "record"], tags(**GRAMMAR))
        self.assertEqual(run_main(["grammar", "drop"])[1].strip(), "dropped")
        self.assertEqual(run_main(["grammar", "select"])[1].strip(), "")

    def test_unknown_repo_and_op(self):
        self.assertEqual(run_main(["nosuch", "select"])[0], 1)
        self.assertEqual(run_main(["grammar", "bogus"])[0], 1)
        self.assertEqual(run_main([])[0], 1)

    def test_unknown_recorder_is_error(self):
        self.assertEqual(run_main(["nosuch", "record"], tags(slug="s"))[0], 1)


class AllRecordersTest(DbCliTestBase):
    """One happy-path per recorder through the tag path (kind->type included)."""

    def _roundtrip(self, cat, fields, key):
        code, out = run_main([cat, "record"], tags(**fields))
        self.assertEqual((code, out.strip()), (0, "inserted"), cat)
        code, out = run_main([cat, "select", key])
        self.assertEqual(code, 0, cat)
        self.assertTrue(out.strip(), cat)

    def test_grammar(self):
        self._roundtrip("grammar", GRAMMAR, "s1")

    def test_rephrasing(self):
        fields = {
            "slug": "word-choice",
            "problem": "p",
            "learner_wrote": "lw",
            "native_phrase": "np",
            "why": "w",
        }
        self._roundtrip("rephrasing", fields, "word-choice")

    def test_idioms(self):
        fields = {
            "idiom": "break the ice",
            "meaning": "m",
            "context": "c",
            "learner_wrote": "lw",
        }
        self._roundtrip("idioms", fields, "break the ice")

    def test_verbs(self):
        fields = {
            "verb": "go",
            "past": "went",
            "participle": "gone",
            "used_form": "goed",
            "correction": "went",
            "context": "c",
        }
        self._roundtrip("verbs", fields, "go")

    def test_decode(self):
        # 'type' is a tag here (recorder param is `kind`)
        fields = {
            "slug": "break-the-ice",
            "type": "fixed",
            "expression": "break the ice",
            "meaning": "m",
            "takeaway": "memorize",
            "learner_wrote": "lw",
            "context": "c",
        }
        self._roundtrip("decode", fields, "break-the-ice")

    def test_friction(self):
        fields = {
            "slug": "small-talk",
            "type": "lexical",
            "zone": "z",
            "learner_wrote": "lw",
            "native_phrase": "np",
            "context": "c",
        }
        self._roundtrip("friction", fields, "small-talk")

    def test_decode_type_lands_in_type_column(self):
        fields = {
            "slug": "s",
            "type": "method",
            "expression": "e",
            "meaning": "m",
            "takeaway": "t",
            "learner_wrote": "lw",
            "context": "c",
        }
        run_main(["decode", "record"], tags(**fields))
        _, out = run_main(["decode", "select", "s"])
        self.assertIn("method", out)


if __name__ == "__main__":
    unittest.main()
