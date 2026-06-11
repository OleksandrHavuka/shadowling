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


class WriteTest(SqlTestBase):
    def test_delete_with_write_flag(self):
        self.seed("s1", "s2")
        code, out, _ = run_main(["--write", "DELETE FROM grammar WHERE slug = ?", "s1"])
        self.assertEqual(code, 0)
        self.assertEqual(out.strip(), "1 row(s) affected")
        self.assertEqual(self.count(), 1)

    def test_write_takes_snapshot_with_private_perms(self):
        self.seed("s1")
        run_main(["--write", "DELETE FROM grammar WHERE slug = ?", "s1"])
        snaps = self.backups()
        self.assertEqual(len(snaps), 1)
        bdir = os.path.join(self.home, "backups")
        self.assertEqual(stat.S_IMODE(os.stat(bdir).st_mode), 0o700)
        spath = os.path.join(bdir, snaps[0])
        self.assertEqual(stat.S_IMODE(os.stat(spath).st_mode), 0o600)
        # the snapshot is a valid db holding the PRE-write state
        con = sqlite3.connect(spath)
        try:
            self.assertEqual(
                con.execute("SELECT COUNT(*) FROM grammar").fetchone()[0], 1)
        finally:
            con.close()

    def test_write_announces_target_db_on_stderr(self):
        self.seed("s1")
        _, _, err = run_main(["--write", "DELETE FROM grammar WHERE slug = ?", "s1"])
        self.assertIn("db: " + os.path.join(self.home, "shadowling.db"), err)

    def test_returning_rows_printed_as_json(self):
        self.seed("s1")
        code, out, _ = run_main(
            ["--write", "DELETE FROM grammar WHERE slug = ? RETURNING slug", "s1"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out.strip()), {"slug": "s1"})

    def test_ddl_prints_ok(self):
        code, out, _ = run_main(["--write", "CREATE TABLE scratch(x)"])
        self.assertEqual((code, out.strip()), (0, "ok"))

    def test_failing_write_rolls_back_and_exits_1(self):
        self.seed("s1")
        code, _, err = run_main(
            ["--write", "INSERT INTO grammar(date, slug) VALUES (NULL, 'x')"])
        self.assertEqual(code, 1)
        self.assertIn("error:", err)
        self.assertEqual(self.count(), 1)            # rolled back
        self.assertEqual(len(self.backups()), 1)     # snapshot precedes execute


class RotationTest(SqlTestBase):
    def test_keeps_last_10(self):
        self.seed("s1")
        for _ in range(12):
            run_main(["backup"])
        self.assertEqual(len(self.backups()), 10)


class BackupVerbTest(SqlTestBase):
    def test_backup_prints_valid_snapshot_path(self):
        code, out, _ = run_main(["backup"])
        self.assertEqual(code, 0)
        path = out.strip()
        self.assertTrue(os.path.exists(path))
        con = sqlite3.connect(path)
        try:
            self.assertEqual(con.execute("PRAGMA user_version").fetchone()[0],
                             len(appdb.MIGRATIONS))
        finally:
            con.close()


if __name__ == "__main__":
    unittest.main()
