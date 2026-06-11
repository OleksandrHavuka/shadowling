import contextlib
import io
import json
import os
import shutil
import sqlite3
import stat
import tempfile
import unittest

import appdb
import sql


def run_main(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = sql.main(argv)
    return code, out.getvalue(), err.getvalue()


class SqlTestBase(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        os.environ["SHADOWLING_HOME"] = self.home

    def tearDown(self):
        os.environ.pop("SHADOWLING_HOME", None)
        shutil.rmtree(self.home, ignore_errors=True)

    def seed(self, *slugs):
        con = appdb.connect()
        try:
            with con:
                for s in slugs:
                    con.execute(
                        "INSERT INTO grammar(date, slug, problem, original,"
                        " fixed, rule) VALUES ('2026-06-11', ?, 'p', 'a', 'b', 'r')",
                        (s,))
        finally:
            con.close()

    def backups(self):
        bdir = os.path.join(self.home, "backups")
        return sorted(os.listdir(bdir)) if os.path.isdir(bdir) else []

    def count(self, table="grammar"):
        return appdb.query("SELECT COUNT(*) AS n FROM {0}".format(table))[0]["n"]


class ReadOnlyTest(SqlTestBase):
    def test_select_prints_json_per_row(self):
        self.seed("s1", "s2")
        code, out, _ = run_main(["SELECT slug FROM grammar ORDER BY id"])
        self.assertEqual(code, 0)
        lines = out.strip().splitlines()
        self.assertEqual([json.loads(l)["slug"] for l in lines], ["s1", "s2"])

    def test_params_bind(self):
        self.seed("s1", "s2")
        code, out, _ = run_main(["SELECT slug FROM grammar WHERE slug = ?", "s2"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out.strip()), {"slug": "s2"})

    def test_empty_result_prints_nothing(self):
        code, out, _ = run_main(["SELECT * FROM grammar"])
        self.assertEqual((code, out), (0, ""))

    def test_mutation_without_write_flag_fails_and_changes_nothing(self):
        self.seed("s1")
        code, _, err = run_main(["DELETE FROM grammar"])
        self.assertEqual(code, 1)
        self.assertIn("error:", err)
        self.assertEqual(self.count(), 1)
        self.assertEqual(self.backups(), [])  # no snapshot on the ro path


class MdTest(SqlTestBase):
    def test_md_renders_table(self):
        self.seed("s1")
        code, out, _ = run_main(["--md", "SELECT slug, problem FROM grammar"])
        self.assertEqual(code, 0)
        lines = out.strip().splitlines()
        self.assertEqual(lines[0], "| slug | problem |")
        self.assertTrue(lines[1].startswith("| ---"))
        self.assertIn("| s1 | p |", lines[2])

    def test_md_empty(self):
        code, out, _ = run_main(["--md", "SELECT * FROM grammar"])
        self.assertEqual((code, out.strip()), (0, "(empty)"))


class UsageTest(SqlTestBase):
    def test_no_args_is_error(self):
        self.assertEqual(run_main([])[0], 1)

    def test_flag_without_sql_is_error(self):
        self.assertEqual(run_main(["--md"])[0], 1)
        self.assertEqual(run_main(["--write"])[0], 1)

    def test_two_flags_is_error(self):
        self.assertEqual(run_main(["--md", "--write", "SELECT 1"])[0], 1)

    def test_invalid_sql_is_error(self):
        code, _, err = run_main(["SELEKT oops"])
        self.assertEqual(code, 1)
        self.assertIn("error:", err)


if __name__ == "__main__":
    unittest.main()
