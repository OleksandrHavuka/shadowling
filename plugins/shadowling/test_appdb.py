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

    def test_existing_nonempty_db_backed_up_then_wiped(self):
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
        # migration 2 wipes the corpus; the pre-upgrade backup keeps the copy
        self.assertEqual(appdb.query("SELECT COUNT(*) AS n FROM messages"),
                         [{"n": 0}])
        bak_con = sqlite3.connect(appdb.db_path() + ".bak")
        try:
            self.assertEqual(
                bak_con.execute("SELECT text FROM messages").fetchall(),
                [("hello there",)])
        finally:
            bak_con.close()

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

    def test_fresh_db_makes_no_backup(self):
        # A brand-new db has no prior data — backing it up would be pointless.
        appdb.connect().close()
        self.assertFalse(os.path.exists(appdb.db_path() + ".bak"))


class Migration2Test(AppDbTestBase):
    def test_fresh_db_has_tutor_schema(self):
        con = appdb.connect()
        try:
            self.assertEqual(con.execute("PRAGMA user_version").fetchone()[0],
                             len(appdb.MIGRATIONS))
            tables = {r["name"] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertIn("attempts", tables)
            self.assertIn("mastery", tables)
            cols = {r["name"] for r in con.execute(
                "PRAGMA table_info(messages)")}
            self.assertIn("session_id", cols)
            self.assertIn("kind", cols)
            acols = {r["name"] for r in con.execute(
                "PRAGMA table_info(attempts)")}
            self.assertIn("created_at", acols)     # event-log creation stamp
            self.assertNotIn("ts", acols)          # renamed from ts
            mcols = {r["name"] for r in con.execute(
                "PRAGMA table_info(mastery)")}
            self.assertIn("created_at", mcols)
            self.assertIn("updated_at", mcols)     # mutable scheduling state
        finally:
            con.close()

    def test_upgrade_wipes_messages_keeps_other_data(self):
        # build a true v1 db (shipped 0.7.x schema) + legacy data, then let
        # connect() replay migrations 2 and 3 against it.
        con = sqlite3.connect(appdb.db_path())
        appdb._migration_1(con)
        con.execute("PRAGMA user_version = 1")
        con.execute("INSERT INTO messages(ts, text)"
                    " VALUES ('t', 'legacy message here')")
        con.execute("INSERT INTO grammar(date, slug) VALUES ('d', 's1')")
        con.commit()
        con.close()
        appdb.connect().close()  # replays migrations 2 + 3
        self.assertTrue(os.path.exists(appdb.db_path() + ".bak"))
        self.assertEqual(appdb.query("SELECT COUNT(*) AS n FROM messages"),
                         [{"n": 0}])     # corpus wiped (pre-prod waiver)
        self.assertEqual(appdb.query("SELECT COUNT(*) AS n FROM grammar"),
                         [{"n": 1}])     # everything else intact


class Migration3Test(AppDbTestBase):
    def test_fresh_db_unified_columns(self):
        con = appdb.connect()
        try:
            self.assertEqual(con.execute("PRAGMA user_version").fetchone()[0],
                             len(appdb.MIGRATIONS))

            def cols(t):
                return {r["name"] for r in con.execute(
                    f"PRAGMA table_info({t})")}
            # creation time unified to created_at; ts/date retired everywhere
            self.assertIn("created_at", cols("messages"))
            self.assertNotIn("ts", cols("messages"))
            for t in ("grammar", "rephrasing", "idioms", "verbs", "decode",
                      "friction"):
                self.assertIn("created_at", cols(t))
                self.assertNotIn("date", cols(t))
            # learner's-version unified to learner_wrote
            for t in ("rephrasing", "idioms", "decode", "friction"):
                self.assertIn("learner_wrote", cols(t))
            self.assertNotIn("yours", cols("rephrasing"))
            self.assertNotIn("you_wrote", cols("idioms"))
            self.assertNotIn("your_read", cols("decode"))
            self.assertNotIn("you_reached_for", cols("friction"))
            # vocab gains audit stamps
            self.assertIn("created_at", cols("vocab"))
            self.assertIn("updated_at", cols("vocab"))
        finally:
            con.close()

    def test_upgrade_preserves_incident_and_vocab_data(self):
        con = sqlite3.connect(appdb.db_path())
        appdb._migration_1(con)
        con.execute("PRAGMA user_version = 1")
        con.execute("INSERT INTO grammar(date, slug)"
                    " VALUES ('2026-06-01', 'g1')")
        con.execute("INSERT INTO rephrasing(date, slug, yours)"
                    " VALUES ('2026-06-01', 'r1', 'my clunky phrasing')")
        con.execute("INSERT INTO vocab(word, translation, remaining, status)"
                    " VALUES ('throughput', 'переклад', 5, 'active')")
        con.commit()
        con.close()
        appdb.connect().close()  # replays migrations 2 + 3 (RENAME preserves rows)
        self.assertEqual(
            appdb.query("SELECT created_at, slug FROM grammar"),
            [{"created_at": "2026-06-01", "slug": "g1"}])
        self.assertEqual(
            appdb.query("SELECT learner_wrote FROM rephrasing"),
            [{"learner_wrote": "my clunky phrasing"}])
        row = appdb.query("SELECT word, created_at FROM vocab")[0]
        self.assertEqual(row["word"], "throughput")
        self.assertIsNone(row["created_at"])  # added column backfills NULL


class Migration4Test(AppDbTestBase):
    def test_fresh_db_unifies_native_phrase(self):
        con = appdb.connect()
        try:
            self.assertEqual(con.execute("PRAGMA user_version").fetchone()[0],
                             len(appdb.MIGRATIONS))

            def cols(t):
                return {r["name"] for r in con.execute(
                    f"PRAGMA table_info({t})")}
            for t in ("rephrasing", "friction"):
                self.assertIn("native_phrase", cols(t))
            self.assertNotIn("natural", cols("rephrasing"))
            self.assertNotIn("natural_english", cols("friction"))
        finally:
            con.close()

    def test_upgrade_preserves_native_phrase_data(self):
        con = sqlite3.connect(appdb.db_path())
        appdb._migration_1(con)
        con.execute("PRAGMA user_version = 1")
        con.execute('INSERT INTO rephrasing(date, slug, "natural")'
                    " VALUES ('2026-06-01', 'r1', 'take a photo')")
        con.execute("INSERT INTO friction(date, slug, natural_english)"
                    " VALUES ('2026-06-01', 'f1', 'I see it differently')")
        con.commit()
        con.close()
        appdb.connect().close()  # replays migrations 2, 3, 4 (RENAME preserves rows)
        self.assertEqual(
            appdb.query("SELECT native_phrase FROM rephrasing"),
            [{"native_phrase": "take a photo"}])
        self.assertEqual(
            appdb.query("SELECT native_phrase FROM friction"),
            [{"native_phrase": "I see it differently"}])


class Migration5Test(AppDbTestBase):
    def test_fresh_db_has_verbs_redesign(self):
        con = appdb.connect()
        try:
            self.assertEqual(con.execute("PRAGMA user_version").fetchone()[0],
                             len(appdb.MIGRATIONS))
            cols = {r["name"] for r in con.execute("PRAGMA table_info(verbs)")}
            self.assertIn("correction", cols)   # renamed from example_fix
            self.assertIn("used_form", cols)     # new: the learner's wrong form
            self.assertIn("context", cols)       # new: drillable excerpt
            self.assertNotIn("example_fix", cols)
        finally:
            con.close()

    def test_upgrade_renames_example_fix_keeps_data(self):
        con = sqlite3.connect(appdb.db_path())
        appdb._migration_1(con)
        con.execute("PRAGMA user_version = 1")
        con.execute("INSERT INTO verbs(date, verb, example_fix)"
                    " VALUES ('2026-06-01', 'go', 'I have went -> I have gone')")
        con.commit()
        con.close()
        appdb.connect().close()  # replays migrations 2..5 (RENAME preserves rows)
        rows = appdb.query(
            "SELECT verb, correction, used_form, context FROM verbs")
        self.assertEqual(rows[0]["verb"], "go")
        # legacy example_fix text survives under the new name
        self.assertEqual(rows[0]["correction"], "I have went -> I have gone")
        self.assertIsNone(rows[0]["used_form"])   # added columns backfill NULL
        self.assertIsNone(rows[0]["context"])


class ViewsTest(AppDbTestBase):
    def test_all_views_exist_and_query(self):
        con = appdb.connect()
        try:
            for view in appdb.VIEWS:
                con.execute(f"SELECT * FROM {view}").fetchall()
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

    def test_query_binds_params(self):
        con = appdb.connect()
        try:
            with con:
                con.execute("INSERT INTO grammar(created_at, slug) VALUES ('d', 's1')")
                con.execute("INSERT INTO grammar(created_at, slug) VALUES ('d', 's2')")
        finally:
            con.close()
        rows = appdb.query("SELECT slug FROM grammar WHERE slug = ?", ("s2",))
        self.assertEqual(rows, [{"slug": "s2"}])


if __name__ == "__main__":
    unittest.main()
