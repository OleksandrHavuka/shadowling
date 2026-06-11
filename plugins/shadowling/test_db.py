import contextlib
import io
import os
import shutil
import tempfile
import unittest

import db


def run_main(argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = db.main(argv)
    return code, buf.getvalue()


class DbCliTestBase(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        os.environ["SHADOWLING_HOME"] = self.home

    def tearDown(self):
        os.environ.pop("SHADOWLING_HOME", None)
        shutil.rmtree(self.home, ignore_errors=True)


class RecordSelectTest(DbCliTestBase):
    def test_record_then_select_roundtrip(self):
        code, out = run_main(["grammar", "record", "s1", "p", "a", "b", "r"])
        self.assertEqual((code, out.strip()), (0, "inserted"))
        code, out = run_main(["grammar", "select", "s1"])
        self.assertEqual(code, 0)
        self.assertIn('"counter": 1', out)
        self.assertIn('"last example": "a → b"', out)

    def test_record_wrong_arity_is_error(self):
        code, _ = run_main(["grammar", "record", "only-one-arg"])
        self.assertEqual(code, 1)

    def test_select_all_prints_one_json_per_row(self):
        run_main(["grammar", "record", "s1", "p", "a", "b", "r"])
        run_main(["grammar", "record", "s2", "p", "c", "d", "r"])
        code, out = run_main(["grammar", "select"])
        self.assertEqual(code, 0)
        self.assertEqual(len(out.strip().splitlines()), 2)


class ExportTest(DbCliTestBase):
    def test_export_renders_markdown_table(self):
        run_main(["grammar", "record", "s1", "p", "a", "b", "r"])
        code, out = run_main(["grammar", "export"])
        self.assertEqual(code, 0)
        lines = out.strip().splitlines()
        self.assertTrue(lines[0].startswith("| slug |"))
        self.assertTrue(lines[1].startswith("| ---"))
        self.assertIn("| s1 |", lines[2])

    def test_export_escapes_pipes_and_newlines(self):
        run_main(["grammar", "record", "s1", "p | q", "a\nb", "c", "r"])
        _, out = run_main(["grammar", "export"])
        self.assertIn("p \\| q", out)
        self.assertNotIn("a\nb", out)

    def test_export_empty(self):
        code, out = run_main(["grammar", "export"])
        self.assertEqual((code, out.strip()), (0, "(empty)"))


class DropAndErrorsTest(DbCliTestBase):
    def test_drop(self):
        run_main(["grammar", "record", "s1", "p", "a", "b", "r"])
        self.assertEqual(run_main(["grammar", "drop"])[1].strip(), "dropped")
        self.assertEqual(run_main(["grammar", "select"])[1].strip(), "")

    def test_unknown_repo_and_op(self):
        self.assertEqual(run_main(["nosuch", "select"])[0], 1)
        self.assertEqual(run_main(["grammar", "bogus"])[0], 1)
        self.assertEqual(run_main([])[0], 1)


if __name__ == "__main__":
    unittest.main()
