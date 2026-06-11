import os
import shutil
import sqlite3
import stat
import tempfile
import unittest

import appdb


class AppDbTestBase(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        os.environ["SHADOWLING_HOME"] = self.home

    def tearDown(self):
        os.environ.pop("SHADOWLING_HOME", None)
        shutil.rmtree(self.home, ignore_errors=True)


class MigrationRunnerTest(AppDbTestBase):
    def test_fresh_db_reaches_current_version(self):
        con = appdb.connect()
        try:
            self.assertEqual(con.execute("PRAGMA user_version").fetchone()[0],
                             len(appdb.MIGRATIONS))
        finally:
            con.close()

    def test_reconnect_is_idempotent(self):
        appdb.connect().close()
        con = appdb.connect()
        try:
            self.assertEqual(con.execute("PRAGMA user_version").fetchone()[0],
                             len(appdb.MIGRATIONS))
            tables = {r["name"] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            for t in ("messages", "grammar", "rephrasing", "idioms", "verbs",
                      "decode", "friction", "vocab"):
                self.assertIn(t, tables)
        finally:
            con.close()

    def test_existing_nonempty_db_backed_up_and_kept(self):
        # simulate a pre-consolidation 0.6.0 db: messages table, user_version 0
        con = sqlite3.connect(appdb.db_path())
        con.execute("CREATE TABLE messages(id INTEGER PRIMARY KEY AUTOINCREMENT,"
                    " ts TEXT NOT NULL, text TEXT NOT NULL, langs TEXT,"
                    " processed_at TEXT)")
        con.execute("INSERT INTO messages(ts, text) VALUES ('t', 'hello there')")
        con.commit()
        con.close()
        appdb.connect().close()
        self.assertTrue(os.path.exists(appdb.db_path() + ".bak"))
        self.assertEqual(appdb.query("SELECT text FROM messages"),
                         [{"text": "hello there"}])

    def test_legacy_files_deleted_unimported(self):
        for name in ("grammar.md", "grammar.log.jsonl", "words.csv",
                     "buffer.jsonl", "messages.log.jsonl"):
            with open(os.path.join(self.home, name), "w", encoding="utf-8") as f:
                f.write("legacy")
        appdb.connect().close()
        for name in ("grammar.md", "grammar.log.jsonl", "words.csv",
                     "buffer.jsonl", "messages.log.jsonl"):
            self.assertFalse(os.path.exists(os.path.join(self.home, name)), name)
        self.assertEqual(appdb.query("SELECT COUNT(*) AS n FROM grammar"),
                         [{"n": 0}])

    def test_db_file_is_owner_only(self):
        appdb.connect().close()
        self.assertEqual(stat.S_IMODE(os.stat(appdb.db_path()).st_mode), 0o600)


class ViewsTest(AppDbTestBase):
    def test_all_views_exist_and_query(self):
        con = appdb.connect()
        try:
            for view in appdb.VIEWS:
                con.execute("SELECT * FROM {0}".format(view)).fetchall()
        finally:
            con.close()

    def test_changed_view_definition_is_refreshed(self):
        appdb.connect().close()
        con = sqlite3.connect(appdb.db_path())
        con.execute("DROP VIEW grammar_ranked")
        con.execute("CREATE VIEW grammar_ranked AS SELECT 1 AS stale")
        con.commit()
        con.close()
        con = appdb.connect()  # stored sql differs from code → recreated
        try:
            cols = [d[0] for d in
                    con.execute("SELECT * FROM grammar_ranked").description]
            self.assertIn("counter", cols)
            self.assertNotIn("stale", cols)
        finally:
            con.close()


class QueryTest(AppDbTestBase):
    def test_query_is_read_only(self):
        appdb.connect().close()
        with self.assertRaises(sqlite3.Error):
            appdb.query("DELETE FROM grammar")


if __name__ == "__main__":
    unittest.main()
