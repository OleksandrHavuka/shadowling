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
            self.assertEqual(
                con.execute("PRAGMA user_version").fetchone()[0], len(appdb.MIGRATIONS)
            )
        finally:
            con.close()

    def test_reconnect_is_idempotent(self):
        appdb.connect().close()
        con = appdb.connect()
        try:
            self.assertEqual(
                con.execute("PRAGMA user_version").fetchone()[0], len(appdb.MIGRATIONS)
            )
            tables = {
                r["name"]
                for r in con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            for t in (
                "messages",
                "grammar",
                "rephrasing",
                "idioms",
                "verbs",
                "decode",
                "friction",
                "vocab",
            ):
                self.assertIn(t, tables)
        finally:
            con.close()

    def test_existing_nonempty_db_backed_up_then_wiped(self):
        # simulate a pre-consolidation 0.6.0 db: messages table, user_version 0
        con = sqlite3.connect(appdb.db_path())
        con.execute(
            "CREATE TABLE messages(id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " ts TEXT NOT NULL, text TEXT NOT NULL, langs TEXT,"
            " processed_at TEXT)"
        )
        con.execute("INSERT INTO messages(ts, text) VALUES ('t', 'hello there')")
        con.commit()
        con.close()
        appdb.connect().close()
        self.assertTrue(os.path.exists(appdb.db_path() + ".bak"))
        # migration 2 wipes the corpus; the pre-upgrade backup keeps the copy
        self.assertEqual(appdb.query("SELECT COUNT(*) AS n FROM messages"), [{"n": 0}])
        bak_con = sqlite3.connect(appdb.db_path() + ".bak")
        try:
            self.assertEqual(
                bak_con.execute("SELECT text FROM messages").fetchall(),
                [("hello there",)],
            )
        finally:
            bak_con.close()

    def test_legacy_files_deleted_unimported(self):
        for name in (
            "grammar.md",
            "grammar.log.jsonl",
            "words.csv",
            "buffer.jsonl",
            "messages.log.jsonl",
        ):
            with open(os.path.join(self.home, name), "w", encoding="utf-8") as f:
                f.write("legacy")
        appdb.connect().close()
        for name in (
            "grammar.md",
            "grammar.log.jsonl",
            "words.csv",
            "buffer.jsonl",
            "messages.log.jsonl",
        ):
            self.assertFalse(os.path.exists(os.path.join(self.home, name)), name)
        self.assertEqual(appdb.query("SELECT COUNT(*) AS n FROM grammar"), [{"n": 0}])

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
            self.assertEqual(
                con.execute("PRAGMA user_version").fetchone()[0], len(appdb.MIGRATIONS)
            )
            tables = {
                r["name"]
                for r in con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            self.assertIn("attempts", tables)
            self.assertIn("mastery", tables)
            cols = {r["name"] for r in con.execute("PRAGMA table_info(messages)")}
            self.assertIn("session_id", cols)
            self.assertIn("kind", cols)
            acols = {r["name"] for r in con.execute("PRAGMA table_info(attempts)")}
            self.assertIn("created_at", acols)  # event-log creation stamp
            self.assertNotIn("ts", acols)  # renamed from ts
            mcols = {r["name"] for r in con.execute("PRAGMA table_info(mastery)")}
            self.assertIn("created_at", mcols)
            self.assertIn("updated_at", mcols)  # mutable scheduling state
        finally:
            con.close()

    def test_upgrade_wipes_messages_keeps_other_data(self):
        # Migration 2 wipes the message corpus (pre-prod waiver) but keeps the other
        # tables. Replay 2..5 on a raw connection and assert there: the terminal
        # migration 6 wipes the incident tables too, so "keeps grammar" is only
        # observable before it (migration 6's wipe + the .bak backup are their own
        # tests).
        con = sqlite3.connect(appdb.db_path())
        con.row_factory = sqlite3.Row  # _migration_2 reads PRAGMA rows by name
        appdb._migration_1(con)
        con.execute(
            "INSERT INTO messages(ts, text) VALUES ('t', 'legacy message here')"
        )
        con.execute("INSERT INTO grammar(date, slug) VALUES ('d', 's1')")
        for migration in appdb.MIGRATIONS[
            1:5
        ]:  # replay 2..5; skip the terminal wipe (6)
            migration(con)
        self.assertEqual(
            con.execute("SELECT COUNT(*) AS n FROM messages").fetchone()["n"], 0
        )  # corpus wiped by migration 2
        self.assertEqual(
            con.execute("SELECT COUNT(*) AS n FROM grammar").fetchone()["n"], 1
        )  # everything else intact at this point
        con.close()


class Migration3Test(AppDbTestBase):
    def test_fresh_db_unified_columns(self):
        con = appdb.connect()
        try:
            self.assertEqual(
                con.execute("PRAGMA user_version").fetchone()[0], len(appdb.MIGRATIONS)
            )

            def cols(t):
                return {r["name"] for r in con.execute(f"PRAGMA table_info({t})")}

            # creation time unified to created_at; ts/date retired everywhere
            self.assertIn("created_at", cols("messages"))
            self.assertNotIn("ts", cols("messages"))
            for t in ("grammar", "rephrasing", "idioms", "verbs", "decode", "friction"):
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
        # The rename migrations preserve rows; assert on a raw connection after
        # replaying 2..5 (the terminal migration 6 wipes incidents — its own test).
        con = sqlite3.connect(appdb.db_path())
        con.row_factory = sqlite3.Row
        appdb._migration_1(con)
        con.execute("INSERT INTO grammar(date, slug) VALUES ('2026-06-01', 'g1')")
        con.execute(
            "INSERT INTO rephrasing(date, slug, yours)"
            " VALUES ('2026-06-01', 'r1', 'my clunky phrasing')"
        )
        con.execute(
            "INSERT INTO vocab(word, translation, remaining, status)"
            " VALUES ('throughput', 'переклад', 5, 'active')"
        )
        for migration in appdb.MIGRATIONS[1:5]:  # replay 2..5 (renames); skip wipe (6)
            migration(con)
        self.assertEqual(
            [dict(r) for r in con.execute("SELECT created_at, slug FROM grammar")],
            [{"created_at": "2026-06-01", "slug": "g1"}],
        )
        self.assertEqual(
            [dict(r) for r in con.execute("SELECT learner_wrote FROM rephrasing")],
            [{"learner_wrote": "my clunky phrasing"}],
        )
        row = con.execute("SELECT word, created_at FROM vocab").fetchone()
        self.assertEqual(row["word"], "throughput")
        self.assertIsNone(row["created_at"])  # added column backfills NULL
        con.close()


class Migration4Test(AppDbTestBase):
    def test_fresh_db_unifies_native_phrase(self):
        con = appdb.connect()
        try:
            self.assertEqual(
                con.execute("PRAGMA user_version").fetchone()[0], len(appdb.MIGRATIONS)
            )

            def cols(t):
                return {r["name"] for r in con.execute(f"PRAGMA table_info({t})")}

            for t in ("rephrasing", "friction"):
                self.assertIn("native_phrase", cols(t))
            self.assertNotIn("natural", cols("rephrasing"))
            self.assertNotIn("natural_english", cols("friction"))
        finally:
            con.close()

    def test_upgrade_preserves_native_phrase_data(self):
        con = sqlite3.connect(appdb.db_path())
        con.row_factory = sqlite3.Row
        appdb._migration_1(con)
        con.execute(
            'INSERT INTO rephrasing(date, slug, "natural")'
            " VALUES ('2026-06-01', 'r1', 'take a photo')"
        )
        con.execute(
            "INSERT INTO friction(date, slug, natural_english)"
            " VALUES ('2026-06-01', 'f1', 'I see it differently')"
        )
        for migration in appdb.MIGRATIONS[1:5]:  # replay 2..5 (renames); skip wipe (6)
            migration(con)
        self.assertEqual(
            [dict(r) for r in con.execute("SELECT native_phrase FROM rephrasing")],
            [{"native_phrase": "take a photo"}],
        )
        self.assertEqual(
            [dict(r) for r in con.execute("SELECT native_phrase FROM friction")],
            [{"native_phrase": "I see it differently"}],
        )
        con.close()


class Migration5Test(AppDbTestBase):
    def test_fresh_db_has_verbs_redesign(self):
        con = appdb.connect()
        try:
            self.assertEqual(
                con.execute("PRAGMA user_version").fetchone()[0], len(appdb.MIGRATIONS)
            )
            cols = {r["name"] for r in con.execute("PRAGMA table_info(verbs)")}
            self.assertIn("correction", cols)  # renamed from example_fix
            self.assertIn("used_form", cols)  # new: the learner's wrong form
            self.assertIn("context", cols)  # new: drillable excerpt
            self.assertNotIn("example_fix", cols)
        finally:
            con.close()

    def test_upgrade_renames_example_fix_keeps_data(self):
        con = sqlite3.connect(appdb.db_path())
        con.row_factory = sqlite3.Row
        appdb._migration_1(con)
        con.execute(
            "INSERT INTO verbs(date, verb, example_fix)"
            " VALUES ('2026-06-01', 'go', 'I have went -> I have gone')"
        )
        for migration in appdb.MIGRATIONS[1:5]:  # replay 2..5 (rename); skip wipe (6)
            migration(con)
        row = con.execute(
            "SELECT verb, correction, used_form, context FROM verbs"
        ).fetchone()
        self.assertEqual(row["verb"], "go")
        # legacy example_fix text survives under the new name
        self.assertEqual(row["correction"], "I have went -> I have gone")
        self.assertIsNone(row["used_form"])  # added columns backfill NULL
        self.assertIsNone(row["context"])
        con.close()


class Migration6Test(AppDbTestBase):
    INCIDENT = ("grammar", "rephrasing", "idioms", "verbs", "friction", "decode")

    def test_fresh_db_has_session_id_not_null(self):
        con = appdb.connect()
        try:
            self.assertEqual(
                con.execute("PRAGMA user_version").fetchone()[0], len(appdb.MIGRATIONS)
            )
            for tbl in self.INCIDENT:
                info = {r["name"]: r for r in con.execute(f"PRAGMA table_info({tbl})")}
                self.assertIn("session_id", info, tbl)
                self.assertEqual(info["session_id"]["notnull"], 1, tbl)
        finally:
            con.close()

    def test_upgrade_wipes_incidents_deletes_null_session_keeps_vocab_mastery(self):
        con = sqlite3.connect(appdb.db_path())
        con.row_factory = sqlite3.Row  # _migration_2 reads PRAGMA rows by name
        for migration in appdb.MIGRATIONS[:5]:  # build a true pre-6 (v5) database
            migration(con)
        con.execute("PRAGMA user_version = 5")
        con.execute(
            "INSERT INTO grammar(created_at, slug, problem, original, fixed, rule)"
            " VALUES ('2026-06-01', 'art', 'p', 'a', 'b', 'r')"
        )
        con.execute(
            "INSERT INTO messages(created_at, text, session_id, processed_at)"
            " VALUES ('2026-06-01', 'a session-bearing sentence', 'sess-A', 'done')"
        )
        con.execute(
            "INSERT INTO messages(created_at, text, session_id, processed_at)"
            " VALUES ('2026-06-01', 'an unattributable pre-tutor row', NULL, 'done')"
        )
        for kind in ("grammar", "vocab"):
            con.execute(
                "INSERT INTO mastery(item_kind, item_key, box, due_date,"
                " last_verdict, counter_seen, created_at, updated_at)"
                " VALUES (?, 'k', 1, '2026-06-02', 'pass', 1, 'c', 'u')",
                (kind,),
            )
        con.commit()
        con.close()

        appdb.connect().close()  # replays _migration_6

        self.assertEqual(appdb.query("SELECT * FROM grammar"), [])  # incidents wiped
        self.assertEqual(appdb.query("SELECT * FROM decode"), [])
        msgs = appdb.query("SELECT session_id, processed_at FROM messages")
        self.assertEqual(len(msgs), 1)  # null-session row deleted
        self.assertEqual(msgs[0]["session_id"], "sess-A")
        self.assertIsNone(msgs[0]["processed_at"])  # processed_at reset
        kinds = {r["item_kind"] for r in appdb.query("SELECT item_kind FROM mastery")}
        self.assertEqual(kinds, {"vocab"})  # non-vocab mastery wiped, vocab kept


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
            cols = [
                d[0] for d in con.execute("SELECT * FROM grammar_ranked").description
            ]
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


class TxHelperTest(AppDbTestBase):
    def test_block_commits_atomically(self):
        con = appdb.connect()
        try:
            with appdb.tx(con):
                con.execute("INSERT INTO grammar(created_at, slug) VALUES ('d', 'a')")
                con.execute("INSERT INTO grammar(created_at, slug) VALUES ('d', 'b')")
        finally:
            con.close()
        self.assertEqual(
            appdb.query("SELECT slug FROM grammar ORDER BY slug"),
            [{"slug": "a"}, {"slug": "b"}],
        )

    def test_exception_inside_rolls_back(self):
        con = appdb.connect()
        try:
            with self.assertRaises(RuntimeError):
                with appdb.tx(con):
                    con.execute(
                        "INSERT INTO grammar(created_at, slug) VALUES ('d', 'x')"
                    )
                    raise RuntimeError("boom")
        finally:
            con.close()
        self.assertEqual(appdb.query("SELECT COUNT(*) AS n FROM grammar"), [{"n": 0}])

    def test_isolation_level_restored_on_success(self):
        con = appdb.connect()
        try:
            prev = con.isolation_level
            with appdb.tx(con):
                con.execute("INSERT INTO grammar(created_at, slug) VALUES ('d', 's')")
            self.assertEqual(con.isolation_level, prev)
        finally:
            con.close()

    def test_isolation_level_restored_on_exception(self):
        con = appdb.connect()
        try:
            prev = con.isolation_level
            with self.assertRaises(RuntimeError):
                with appdb.tx(con):
                    raise RuntimeError("boom")
            self.assertEqual(con.isolation_level, prev)
        finally:
            con.close()


class AtomicMigrationTest(AppDbTestBase):
    def test_failed_migration_rolls_back_version_and_schema(self):
        appdb.connect().close()  # reach current version cleanly
        baseline = len(appdb.MIGRATIONS)

        def bad_migration(con):
            con.execute("CREATE TABLE temp_marker(x INTEGER)")
            con.execute("THIS IS NOT VALID SQL")

        original = list(appdb.MIGRATIONS)
        appdb.MIGRATIONS.append(bad_migration)
        try:
            with self.assertRaises(sqlite3.Error):
                appdb.connect().close()
            con = sqlite3.connect(appdb.db_path())
            try:
                self.assertEqual(
                    con.execute("PRAGMA user_version").fetchone()[0], baseline
                )
                tables = {
                    r[0]
                    for r in con.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
                self.assertNotIn("temp_marker", tables)
            finally:
                con.close()
        finally:
            appdb.MIGRATIONS[:] = original

    def test_replay_after_fix_succeeds(self):
        appdb.connect().close()
        baseline = len(appdb.MIGRATIONS)

        def bad_migration(con):
            con.execute("CREATE TABLE temp_marker(x INTEGER)")
            con.execute("THIS IS NOT VALID SQL")

        def good_migration(con):
            con.execute("CREATE TABLE temp_marker(x INTEGER)")

        original = list(appdb.MIGRATIONS)
        appdb.MIGRATIONS.append(bad_migration)
        try:
            with self.assertRaises(sqlite3.Error):
                appdb.connect().close()
            appdb.MIGRATIONS[-1] = good_migration
            appdb.connect().close()  # must NOT raise (DB left at prior state)
            con = sqlite3.connect(appdb.db_path())
            try:
                self.assertEqual(
                    con.execute("PRAGMA user_version").fetchone()[0], baseline + 1
                )
                tables = {
                    r[0]
                    for r in con.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
                self.assertIn("temp_marker", tables)
            finally:
                con.close()
        finally:
            appdb.MIGRATIONS[:] = original


class WalSafeBackupTest(AppDbTestBase):
    def test_backup_is_a_consistent_sqlite_db(self):
        con = sqlite3.connect(appdb.db_path())
        appdb._migration_1(con)
        con.execute("PRAGMA user_version = 1")
        con.execute("INSERT INTO grammar(date, slug) VALUES ('2026-06-01', 'keepme')")
        con.commit()
        con.close()
        appdb.connect().close()  # triggers the pre-upgrade backup
        bak = appdb.db_path() + ".bak"
        self.assertTrue(os.path.exists(bak))
        bak_con = sqlite3.connect(bak)
        try:
            self.assertEqual(
                bak_con.execute("SELECT slug FROM grammar").fetchall(), [("keepme",)]
            )
            self.assertEqual(bak_con.execute("PRAGMA user_version").fetchone()[0], 1)
        finally:
            bak_con.close()


class Migration7Test(AppDbTestBase):
    def test_fresh_db_has_enrichment_columns(self):
        con = appdb.connect()
        try:
            self.assertEqual(
                con.execute("PRAGMA user_version").fetchone()[0], len(appdb.MIGRATIONS)
            )
            cols = {r["name"] for r in con.execute("PRAGMA table_info(vocab)")}
            # source_context is renamed to ctx by migration 8; a fresh db is the
            # full chain, so it carries the post-rename name. alt_translations is
            # added by migration 9; forms/lemma by migration 11.
            for c in (
                "definition",
                "ctx",
                "examples",
                "synonyms",
                "alt_translations",
                "forms",
                "lemma",
            ):
                self.assertIn(c, cols)
        finally:
            con.close()

    def test_upgrade_preserves_existing_vocab_rows(self):
        con = sqlite3.connect(appdb.db_path())
        con.row_factory = sqlite3.Row
        for migration in appdb.MIGRATIONS[:6]:  # build a pre-7 (v6) database
            migration(con)
        con.execute("PRAGMA user_version = 6")
        con.execute(
            "INSERT INTO vocab(word, translation, remaining, status, created_at,"
            " updated_at) VALUES ('kept', 'переклад', 5, 'active', 'c', 'u')"
        )
        appdb.MIGRATIONS[6](con)  # run ONLY _migration_7 and read the intermediate
        con.execute("PRAGMA user_version = 7")  # state here: the full chain's m12
        row = con.execute(  # would drop this examples-less row (its floor)
            "SELECT * FROM vocab WHERE word='kept'"
        ).fetchone()
        con.close()
        self.assertEqual(row["translation"], "переклад")
        self.assertIsNone(row["examples"])  # added column backfills NULL

    def test_examples_rejects_invalid_json(self):
        appdb.connect().close()
        con = sqlite3.connect(appdb.db_path())
        try:
            # the CHECK rejects at INSERT time (json_valid fails immediately)
            with self.assertRaises(sqlite3.IntegrityError):
                con.execute(
                    "INSERT INTO vocab(word, translation, remaining, status,"
                    " examples) VALUES ('w', 't', 10, 'active', 'not json')"
                )
        finally:
            con.close()


class Migration8Test(AppDbTestBase):
    def test_fresh_db_has_ctx_not_source_context(self):
        con = appdb.connect()
        try:
            cols = {r["name"] for r in con.execute("PRAGMA table_info(vocab)")}
            self.assertIn("ctx", cols)
            self.assertNotIn("source_context", cols)
        finally:
            con.close()

    def test_upgrade_renames_source_context_keeps_value(self):
        con = sqlite3.connect(appdb.db_path())
        con.row_factory = sqlite3.Row
        for migration in appdb.MIGRATIONS[:7]:  # build a pre-8 (v7) database
            migration(con)
        con.execute("PRAGMA user_version = 7")
        con.execute(
            "INSERT INTO vocab(word, translation, remaining, status, created_at,"
            " updated_at, source_context) VALUES"
            " ('kept', 'переклад', 5, 'active', 'c', 'u', 'grounding line')"
        )
        appdb.MIGRATIONS[7](con)  # run ONLY _migration_8 (the rename); read the
        con.execute("PRAGMA user_version = 8")  # intermediate state — the full
        row = con.execute(  # chain's m12 would drop this examples-less row
            "SELECT * FROM vocab WHERE word='kept'"
        ).fetchone()
        con.close()
        self.assertEqual(row["ctx"], "grounding line")  # value carried over
        self.assertNotIn("source_context", row.keys())  # old name gone


class Migration9Test(AppDbTestBase):
    def test_fresh_db_has_alt_translations(self):
        con = appdb.connect()
        try:
            cols = {r["name"] for r in con.execute("PRAGMA table_info(vocab)")}
            self.assertIn("alt_translations", cols)
        finally:
            con.close()

    def test_upgrade_preserves_rows_and_backfills_null(self):
        con = sqlite3.connect(appdb.db_path())
        con.row_factory = sqlite3.Row
        for migration in appdb.MIGRATIONS[:8]:  # build a pre-9 (v8) database
            migration(con)
        con.execute("PRAGMA user_version = 8")
        con.execute(
            "INSERT INTO vocab(word, translation, remaining, status, created_at,"
            " updated_at) VALUES ('kept', 'переклад', 5, 'active', 'c', 'u')"
        )
        appdb.MIGRATIONS[8](con)  # run ONLY _migration_9; read the intermediate
        con.execute("PRAGMA user_version = 9")  # state — the full chain's m12
        row = con.execute(  # would drop this examples-less row
            "SELECT * FROM vocab WHERE word='kept'"
        ).fetchone()
        con.close()
        self.assertEqual(row["translation"], "переклад")  # row preserved
        self.assertIsNone(row["alt_translations"])  # added column backfills NULL

    def test_alt_translations_rejects_invalid_json(self):
        appdb.connect().close()
        con = sqlite3.connect(appdb.db_path())
        try:
            # examples is supplied (valid) so the row fails ONLY on alt_translations
            with self.assertRaises(sqlite3.IntegrityError):
                con.execute(
                    "INSERT INTO vocab(word, translation, remaining, status,"
                    " examples, alt_translations) VALUES"
                    " ('w', 't', 10, 'active', '[\"a w line\"]', 'not json')"
                )
        finally:
            con.close()


class Migration10Test(AppDbTestBase):
    def test_fresh_db_has_anki_link_table(self):
        con = appdb.connect()
        try:
            tables = {
                r["name"]
                for r in con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            self.assertIn("anki_link", tables)
            cols = {r["name"] for r in con.execute("PRAGMA table_info(anki_link)")}
            self.assertEqual(
                cols,
                {
                    "word",
                    "note_id",
                    "card_id",
                    "deck",
                    "due",
                    "interval",
                    "reps",
                    "lapses",
                    "synced_at",
                },
            )
        finally:
            con.close()

    def test_upgrade_preserves_existing_vocab_rows(self):
        con = sqlite3.connect(appdb.db_path())
        con.row_factory = sqlite3.Row
        for migration in appdb.MIGRATIONS[:9]:  # build a pre-10 (v9) database
            migration(con)
        con.execute("PRAGMA user_version = 9")
        con.execute(
            "INSERT INTO vocab(word, translation, remaining, status, created_at,"
            " updated_at) VALUES ('kept', 'переклад', 5, 'active', 'c', 'u')"
        )
        appdb.MIGRATIONS[9](con)  # run ONLY _migration_10; read the intermediate
        con.execute("PRAGMA user_version = 10")  # state — the full chain's m12
        row = con.execute(  # would drop this examples-less row
            "SELECT * FROM vocab WHERE word='kept'"
        ).fetchone()
        anki = con.execute("SELECT * FROM anki_link").fetchall()
        con.close()
        self.assertEqual(row["translation"], "переклад")  # row preserved
        self.assertEqual(anki, [])  # new, empty


class Migration11Test(AppDbTestBase):
    def test_fresh_db_has_forms_and_lemma(self):
        con = appdb.connect()
        try:
            cols = {r["name"] for r in con.execute("PRAGMA table_info(vocab)")}
            self.assertIn("forms", cols)
            self.assertIn("lemma", cols)
        finally:
            con.close()

    def test_upgrade_preserves_rows_and_backfills_null(self):
        con = sqlite3.connect(appdb.db_path())
        con.row_factory = sqlite3.Row
        for migration in appdb.MIGRATIONS[:10]:  # build a pre-11 (v10) database
            migration(con)
        con.execute("PRAGMA user_version = 10")
        con.execute(
            "INSERT INTO vocab(word, translation, remaining, status, created_at,"
            " updated_at) VALUES ('kept', 'переклад', 5, 'active', 'c', 'u')"
        )
        appdb.MIGRATIONS[10](con)  # run ONLY _migration_11; read the intermediate
        con.execute("PRAGMA user_version = 11")  # state — the full chain's m12
        row = con.execute(  # would drop this examples-less row
            "SELECT * FROM vocab WHERE word='kept'"
        ).fetchone()
        con.close()
        self.assertEqual(row["translation"], "переклад")  # row preserved
        self.assertIsNone(row["forms"])  # added column backfills NULL
        self.assertIsNone(row["lemma"])  # added column backfills NULL

    def test_forms_rejects_invalid_json(self):
        appdb.connect().close()
        con = sqlite3.connect(appdb.db_path())
        try:
            # the CHECK rejects at INSERT time (json_valid fails immediately).
            # examples is supplied (and valid) so the row fails ONLY on forms.
            with self.assertRaises(sqlite3.IntegrityError):
                con.execute(
                    "INSERT INTO vocab(word, translation, remaining, status,"
                    " examples, forms) VALUES"
                    " ('w', 't', 10, 'active', '[\"a w line\"]', 'not json')"
                )
        finally:
            con.close()


class Migration12Test(AppDbTestBase):
    def test_fresh_db_enforces_translation_and_examples_floor(self):
        appdb.connect().close()
        con = sqlite3.connect(appdb.db_path())
        ins = (
            "INSERT INTO vocab(word, translation, remaining, status, examples)"
            " VALUES (?, ?, 10, 'active', ?)"
        )
        try:
            # a fully conforming row inserts fine
            con.execute(ins, ("alpha", "альфа", '["alpha here"]'))
            con.commit()
            # missing examples -> NOT NULL
            with self.assertRaises(sqlite3.IntegrityError):
                con.execute(
                    "INSERT INTO vocab(word, translation, remaining, status)"
                    " VALUES ('beta', 'бета', 10, 'active')"
                )
            # empty examples array -> CHECK (json_array_length >= 1)
            with self.assertRaises(sqlite3.IntegrityError):
                con.execute(ins, ("gamma", "гама", "[]"))
            # blank translation -> CHECK
            with self.assertRaises(sqlite3.IntegrityError):
                con.execute(ins, ("delta", "  ", '["delta here"]'))
            # echo translation (== word, case/space-insensitive) -> CHECK
            with self.assertRaises(sqlite3.IntegrityError):
                con.execute(ins, ("echo", " Echo ", '["echo here"]'))
        finally:
            con.close()

    def test_upgrade_copies_conforming_drops_nonconforming(self):
        con = sqlite3.connect(appdb.db_path())
        con.row_factory = sqlite3.Row
        for migration in appdb.MIGRATIONS[:11]:  # build a pre-12 (v11) database
            migration(con)
        con.execute("PRAGMA user_version = 11")
        # conforming: translation + >=1 example -> survives the rebuild
        con.execute(
            "INSERT INTO vocab(word, translation, remaining, status, created_at,"
            " updated_at, examples) VALUES"
            " ('good', 'добре', 5, 'active', 'c', 'u', '[\"a good line\"]')"
        )
        # non-conforming: no examples -> dropped (re-lootable, kept in .bak)
        con.execute(
            "INSERT INTO vocab(word, translation, remaining, status)"
            " VALUES ('bare', 'голе', 5, 'active')"
        )
        con.commit()
        con.close()
        appdb.connect().close()  # replays _migration_12
        rows = {r["word"]: r for r in appdb.query("SELECT * FROM vocab")}
        self.assertIn("good", rows)
        self.assertEqual(rows["good"]["translation"], "добре")
        self.assertEqual(rows["good"]["remaining"], 5)
        self.assertNotIn("bare", rows)  # dropped: violated the examples floor

    def test_fresh_db_keeps_optional_enrichment_nullable(self):
        # the floor is translation + examples ONLY; the rest may be NULL
        appdb.connect().close()
        con = sqlite3.connect(appdb.db_path())
        try:
            con.execute(
                "INSERT INTO vocab(word, translation, remaining, status, examples)"
                " VALUES ('w', 'переклад', 10, 'active', '[\"a w line\"]')"
            )
            con.commit()
        finally:
            con.close()
        row = appdb.query("SELECT * FROM vocab WHERE word='w'")[0]
        for col in ("definition", "ctx", "synonyms", "alt_translations", "lemma"):
            self.assertIsNone(row[col])


if __name__ == "__main__":
    unittest.main()
