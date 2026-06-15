#!/usr/bin/env python3
"""appdb.py - the single sqlite home for all shadowling data (stdlib only).

Everything lives in ~/.shadowling/shadowling.db: the message store, six
append-only incident tables (grammar, rephrasing, idioms, verbs, decode,
friction), and the mutable vocab state. Products are NOT stored — they are
computed views (*_ranked), ensured current on every connect. Schema history
is linear: PRAGMA user_version + the ordered MIGRATIONS list. To change
schema, APPEND a migration — never edit a shipped one (see the
shadowling-db project skill).
"""

import contextlib
import os
import shutil
import sqlite3

from core import data_dir


def db_path():
    return os.path.join(data_dir(), "shadowling.db")


@contextlib.contextmanager
def tx(con):
    """Atomic, write-locked transaction. Unlike `with con:`, this is safe for
    DDL and for read-then-write: isolation_level=None disables sqlite3's
    implicit COMMIT-before-DDL, and BEGIN IMMEDIATE takes the write lock up
    front so a read-then-write sequence is serialized. Restores the prior
    isolation_level in finally, leaving the rest of the app's `with con:`
    semantics unchanged."""
    prev = con.isolation_level
    con.isolation_level = None  # manual control; no implicit COMMIT-before-DDL
    try:
        con.execute("BEGIN IMMEDIATE")
        yield con
        con.execute("COMMIT")
    except BaseException:
        con.execute("ROLLBACK")
        raise
    finally:
        con.isolation_level = prev  # restore default for the rest of the app


# --- migrations ---------------------------------------------------------------


def _migration_1(con):
    """Initial consolidated schema. Legacy md/jsonl/csv files are deleted
    UNIMPORTED (pre-consolidation data was explicitly waived by the user)."""
    statements = [
        "CREATE TABLE IF NOT EXISTS messages("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " ts TEXT NOT NULL, text TEXT NOT NULL,"
        " langs TEXT CHECK (langs IS NULL OR json_valid(langs)),"
        " processed_at TEXT)",
        "CREATE TABLE IF NOT EXISTS grammar("
        " id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT NOT NULL,"
        " slug TEXT NOT NULL, problem TEXT, original TEXT, fixed TEXT,"
        " rule TEXT)",
        "CREATE TABLE IF NOT EXISTS rephrasing("
        " id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT NOT NULL,"
        ' slug TEXT NOT NULL, problem TEXT, yours TEXT, "natural" TEXT,'
        " why TEXT)",
        "CREATE TABLE IF NOT EXISTS idioms("
        " id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT NOT NULL,"
        " idiom TEXT NOT NULL, meaning TEXT, context TEXT, you_wrote TEXT)",
        "CREATE TABLE IF NOT EXISTS verbs("
        " id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT NOT NULL,"
        " verb TEXT NOT NULL, past TEXT, participle TEXT, example_fix TEXT)",
        "CREATE TABLE IF NOT EXISTS decode("
        " id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT NOT NULL,"
        " slug TEXT NOT NULL, type TEXT, expression TEXT, meaning TEXT,"
        " takeaway TEXT, your_read TEXT, context TEXT)",
        "CREATE TABLE IF NOT EXISTS friction("
        " id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT NOT NULL,"
        " slug TEXT NOT NULL, type TEXT, zone TEXT, you_reached_for TEXT,"
        " natural_english TEXT, context TEXT)",
        "CREATE TABLE IF NOT EXISTS vocab("
        " word TEXT PRIMARY KEY, translation TEXT NOT NULL,"
        " remaining INTEGER NOT NULL, status TEXT NOT NULL)",
    ]
    for stmt in statements:
        con.execute(stmt)
    legacy = [
        "grammar.md",
        "rephrasings.md",
        "idioms.md",
        "irregular_verbs.md",
        "decode.md",
        "friction.md",
        "grammar.log.jsonl",
        "rephrasings.log.jsonl",
        "idioms.log.jsonl",
        "irregular_verbs.log.jsonl",
        "decode.log.jsonl",
        "friction.log.jsonl",
        "words.csv",
        "buffer.jsonl",
        "messages.log.jsonl",
    ]
    for name in legacy:
        path = os.path.join(data_dir(), name)
        if os.path.exists(path):
            os.remove(path)


def _migration_2(con):
    """Tutor v1 + debrief 2.0. The legacy message corpus is wiped UNIMPORTED
    (pre-prod; user explicitly waived it — same as words.csv in 0.7.0); every
    row from now on carries the session it came from. The two ADD COLUMNs are
    guarded so a replay against an already-migrated messages table (sqlite has
    no ALTER … ADD COLUMN IF NOT EXISTS) doesn't raise 'duplicate column'."""
    cols = {r["name"] for r in con.execute("PRAGMA table_info(messages)")}
    if "session_id" not in cols:
        con.execute("ALTER TABLE messages ADD COLUMN session_id TEXT")
    if "kind" not in cols:
        con.execute("ALTER TABLE messages ADD COLUMN kind TEXT")
    statements = [
        "DELETE FROM messages",
        "CREATE TABLE IF NOT EXISTS attempts("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " created_at TEXT NOT NULL, session_id TEXT,"
        " item_kind TEXT NOT NULL, item_key TEXT NOT NULL,"
        " exercise TEXT NOT NULL, answer TEXT NOT NULL,"
        " verdict TEXT NOT NULL)",
        "CREATE TABLE IF NOT EXISTS mastery("
        " item_kind TEXT NOT NULL, item_key TEXT NOT NULL,"
        " box INTEGER NOT NULL, due_date TEXT NOT NULL,"
        " last_verdict TEXT NOT NULL, counter_seen INTEGER,"
        " created_at TEXT NOT NULL, updated_at TEXT NOT NULL,"
        " PRIMARY KEY (item_kind, item_key))",
    ]
    for stmt in statements:
        con.execute(stmt)


def _migration_3(con):
    """Column-naming unification. One creation-time column name (created_at)
    across every table; the learner's-version column unified to learner_wrote;
    vocab gains audit stamps. The views are dropped first so RENAME COLUMN can't
    trip on a view reference — _ensure_views() rebuilds them from code on the
    same connect. Incident + vocab data is preserved (RENAME/ADD keep rows)."""
    statements = [
        "DROP VIEW IF EXISTS grammar_ranked",
        "DROP VIEW IF EXISTS rephrasing_ranked",
        "DROP VIEW IF EXISTS idioms_ranked",
        "DROP VIEW IF EXISTS verbs_ranked",
        "DROP VIEW IF EXISTS decode_ranked",
        "DROP VIEW IF EXISTS friction_ranked",
        "ALTER TABLE messages RENAME COLUMN ts TO created_at",
        "ALTER TABLE grammar RENAME COLUMN date TO created_at",
        "ALTER TABLE rephrasing RENAME COLUMN date TO created_at",
        "ALTER TABLE idioms RENAME COLUMN date TO created_at",
        "ALTER TABLE verbs RENAME COLUMN date TO created_at",
        "ALTER TABLE decode RENAME COLUMN date TO created_at",
        "ALTER TABLE friction RENAME COLUMN date TO created_at",
        "ALTER TABLE rephrasing RENAME COLUMN yours TO learner_wrote",
        "ALTER TABLE idioms RENAME COLUMN you_wrote TO learner_wrote",
        "ALTER TABLE decode RENAME COLUMN your_read TO learner_wrote",
        "ALTER TABLE friction RENAME COLUMN you_reached_for TO learner_wrote",
        "ALTER TABLE vocab ADD COLUMN created_at TEXT",
        "ALTER TABLE vocab ADD COLUMN updated_at TEXT",
    ]
    for stmt in statements:
        con.execute(stmt)


def _migration_4(con):
    """Unify the "native-speaker / model phrasing" column. It was spelled two
    ways — rephrasing."natural" (a SQL keyword) and friction.natural_english
    (hardcodes a language) — both holding the same thing: how a native speaker
    of the target language would say it. Now `native_phrase` in both. Views are
    dropped first so RENAME can't trip on them; _ensure_views() rebuilds."""
    statements = [
        "DROP VIEW IF EXISTS rephrasing_ranked",
        "DROP VIEW IF EXISTS friction_ranked",
        'ALTER TABLE rephrasing RENAME COLUMN "natural" TO native_phrase',
        "ALTER TABLE friction RENAME COLUMN natural_english TO native_phrase",
    ]
    for stmt in statements:
        con.execute(stmt)


def _migration_5(con):
    """Verbs redesign. `example_fix` crammed the learner's wrong usage and the
    correction into one "wrong → right" string; split it so verbs match every
    other incident table (an explicit learner column) and gain a drillable
    context excerpt. `example_fix` → `correction` (now just the fixed side);
    `used_form` (what the learner actually wrote) and `context` are new. The view
    is dropped first so RENAME can't trip on it; _ensure_views() rebuilds. Legacy
    rows keep their old "wrong → right" text under `correction`; used_form/context
    backfill NULL (pre-prod, append-only — no rewrite of recorded text)."""
    statements = [
        "DROP VIEW IF EXISTS verbs_ranked",
        "ALTER TABLE verbs RENAME COLUMN example_fix TO correction",
        "ALTER TABLE verbs ADD COLUMN used_form TEXT",
        "ALTER TABLE verbs ADD COLUMN context TEXT",
    ]
    for stmt in statements:
        con.execute(stmt)


MIGRATIONS = [_migration_1, _migration_2, _migration_3, _migration_4, _migration_5]

# --- views: derived code, never migrated --------------------------------------
# The MAX(id) bare-column idiom makes non-aggregated columns come from the
# group's latest row, so "last example" fields are the newest incident's.

VIEWS = {
    "grammar_ranked": (
        " SELECT slug, problem,"
        " original || ' → ' || fixed AS \"last example\","
        " MIN(created_at) AS created_at, MAX(created_at) AS updated_at,"
        " COUNT(*) AS counter, MAX(id) AS last_id"
        " FROM grammar GROUP BY slug ORDER BY counter DESC, last_id DESC"
    ),
    "rephrasing_ranked": (
        ' SELECT slug, problem, learner_wrote AS "you wrote",'
        ' native_phrase AS "native phrase",'
        " MIN(created_at) AS created_at, MAX(created_at) AS updated_at,"
        " COUNT(*) AS counter, MAX(id) AS last_id"
        " FROM rephrasing GROUP BY slug ORDER BY counter DESC, last_id DESC"
    ),
    "idioms_ranked": (
        ' SELECT idiom, meaning, learner_wrote AS "you wrote",'
        " MIN(created_at) AS created_at, MAX(created_at) AS updated_at,"
        " COUNT(*) AS counter, MAX(id) AS last_id"
        " FROM idioms GROUP BY idiom ORDER BY counter DESC, last_id DESC"
    ),
    "verbs_ranked": (
        ' SELECT used_form AS "you used", correction, context,'
        ' verb, past, participle AS "past participle",'
        " MIN(created_at) AS created_at, MAX(created_at) AS updated_at,"
        " COUNT(*) AS counter, MAX(id) AS last_id"
        " FROM verbs GROUP BY verb ORDER BY counter DESC, last_id DESC"
    ),
    "decode_ranked": (
        " SELECT slug, type, expression, meaning, takeaway,"
        " MIN(created_at) AS created_at, MAX(created_at) AS updated_at,"
        " COUNT(*) AS counter, MAX(id) AS last_id"
        " FROM decode GROUP BY slug ORDER BY counter DESC, last_id DESC"
    ),
    "friction_ranked": (
        ' SELECT slug, type, zone, learner_wrote AS "you reached for",'
        ' native_phrase AS "native phrase",'
        " MIN(created_at) AS created_at, MAX(created_at) AS updated_at,"
        " COUNT(*) AS counter, MAX(id) AS last_id"
        " FROM friction GROUP BY slug ORDER BY counter DESC, last_id DESC"
    ),
}


def _ensure_views(con):
    """Recreate a view ONLY when the definition in code differs from the one
    stored in sqlite_master — steady-state connects write nothing, so the five
    parallel debrief specialists can't race each other's DROP/SELECT."""
    for name, body in VIEWS.items():
        stmt = f"CREATE VIEW {name} AS{body}"
        row = con.execute(
            "SELECT sql FROM sqlite_master WHERE type='view' AND name=?", (name,)
        ).fetchone()
        if row is None or row["sql"] != stmt:
            with con:
                con.execute(f"DROP VIEW IF EXISTS {name}")
                con.execute(stmt)


def _chmod_private(path):
    """Personal messages live here; default umask would leave them readable."""
    for suffix in ("", "-wal", "-shm", ".bak"):
        p = path + suffix
        if os.path.exists(p):
            try:
                os.chmod(p, 0o600)
            except OSError:
                pass


def connect():
    path = db_path()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    con = sqlite3.connect(path)
    # Size BEFORE WAL setup writes the header: 0 for a brand-new file, >0 only
    # for a pre-existing db that has real data worth protecting on upgrade.
    preexisting = os.path.getsize(path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=5000")
    version = con.execute("PRAGMA user_version").fetchone()[0]
    if version < len(MIGRATIONS):
        if preexisting > 0:
            shutil.copy(path, path + ".bak")  # one cheap insurance per upgrade
        for i in range(version, len(MIGRATIONS)):
            # tx() takes BEGIN IMMEDIATE with isolation_level=None, so the DDL
            # body AND the version bump commit/roll back together — unlike
            # `with con:`, which implicitly COMMITs before each DDL statement.
            with tx(con):  # step + version bump are atomic; a failed step retries
                MIGRATIONS[i](con)
                con.execute(f"PRAGMA user_version = {i + 1}")
    _ensure_views(con)
    _chmod_private(path)
    return con


def query(sql, params=()):
    """Escape hatch: run a statement on a READ-ONLY connection (URI mode=ro);
    any write fails at the connection level. Returns a list of dicts. The DB is
    materialized first (connect) so a read on a never-opened home still works."""
    connect().close()  # ensure the store + schema exist before opening ro
    uri = f"file:{db_path()}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    try:
        con.row_factory = sqlite3.Row
        return [dict(r) for r in con.execute(sql, params)]
    finally:
        con.close()
