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
import os
import shutil
import sqlite3

from core import data_dir


def db_path():
    return os.path.join(data_dir(), "shadowling.db")


# --- migrations ---------------------------------------------------------------

def _migration_1(con):
    """Initial consolidated schema. Legacy md/jsonl/csv files are deleted
    UNIMPORTED (pre-consolidation data was explicitly waived by the user)."""
    con.executescript("""
        CREATE TABLE IF NOT EXISTS messages(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            text TEXT NOT NULL,
            langs TEXT CHECK (langs IS NULL OR json_valid(langs)),
            processed_at TEXT);
        CREATE TABLE IF NOT EXISTS grammar(
            id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT NOT NULL,
            slug TEXT NOT NULL, problem TEXT, original TEXT, fixed TEXT,
            rule TEXT);
        CREATE TABLE IF NOT EXISTS rephrasing(
            id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT NOT NULL,
            slug TEXT NOT NULL, problem TEXT, yours TEXT, "natural" TEXT,
            why TEXT);
        CREATE TABLE IF NOT EXISTS idioms(
            id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT NOT NULL,
            idiom TEXT NOT NULL, meaning TEXT, context TEXT, you_wrote TEXT);
        CREATE TABLE IF NOT EXISTS verbs(
            id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT NOT NULL,
            verb TEXT NOT NULL, past TEXT, participle TEXT, example_fix TEXT);
        CREATE TABLE IF NOT EXISTS decode(
            id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT NOT NULL,
            slug TEXT NOT NULL, type TEXT, expression TEXT, meaning TEXT,
            takeaway TEXT, your_read TEXT, context TEXT);
        CREATE TABLE IF NOT EXISTS friction(
            id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT NOT NULL,
            slug TEXT NOT NULL, type TEXT, zone TEXT, you_reached_for TEXT,
            natural_english TEXT, context TEXT);
        CREATE TABLE IF NOT EXISTS vocab(
            word TEXT PRIMARY KEY,
            translation TEXT NOT NULL,
            remaining INTEGER NOT NULL,
            status TEXT NOT NULL);
    """)
    legacy = ["grammar.md", "rephrasings.md", "idioms.md", "irregular_verbs.md",
              "decode.md", "friction.md",
              "grammar.log.jsonl", "rephrasings.log.jsonl", "idioms.log.jsonl",
              "irregular_verbs.log.jsonl", "decode.log.jsonl",
              "friction.log.jsonl",
              "words.csv", "buffer.jsonl", "messages.log.jsonl"]
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
    con.executescript("""
        DELETE FROM messages;
        CREATE TABLE IF NOT EXISTS attempts(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            session_id TEXT,
            item_kind TEXT NOT NULL,
            item_key TEXT NOT NULL,
            exercise TEXT NOT NULL,
            answer TEXT NOT NULL,
            verdict TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS mastery(
            item_kind TEXT NOT NULL,
            item_key TEXT NOT NULL,
            box INTEGER NOT NULL,
            due_date TEXT NOT NULL,
            last_verdict TEXT NOT NULL,
            counter_seen INTEGER,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (item_kind, item_key));
    """)


MIGRATIONS = [_migration_1, _migration_2]

# --- views: derived code, never migrated --------------------------------------
# The MAX(id) bare-column idiom makes non-aggregated columns come from the
# group's latest row, so "last example" fields are the newest incident's.

VIEWS = {
    "grammar_ranked": (
        ' SELECT slug, problem,'
        ' original || \' → \' || fixed AS "last example",'
        ' MIN(date) AS created_at, MAX(date) AS updated_at,'
        ' COUNT(*) AS counter, MAX(id) AS last_id'
        ' FROM grammar GROUP BY slug ORDER BY counter DESC, last_id DESC'),
    "rephrasing_ranked": (
        ' SELECT slug, problem, yours AS "your phrasing",'
        ' "natural" AS "natural phrasing",'
        ' MIN(date) AS created_at, MAX(date) AS updated_at,'
        ' COUNT(*) AS counter, MAX(id) AS last_id'
        ' FROM rephrasing GROUP BY slug ORDER BY counter DESC, last_id DESC'),
    "idioms_ranked": (
        ' SELECT idiom, meaning, you_wrote AS "last example",'
        ' MIN(date) AS created_at, MAX(date) AS updated_at,'
        ' COUNT(*) AS counter, MAX(id) AS last_id'
        ' FROM idioms GROUP BY idiom ORDER BY counter DESC, last_id DESC'),
    "verbs_ranked": (
        ' SELECT verb, past, participle AS "past participle",'
        ' example_fix AS "last example",'
        ' MIN(date) AS created_at, MAX(date) AS updated_at,'
        ' COUNT(*) AS counter, MAX(id) AS last_id'
        ' FROM verbs GROUP BY verb ORDER BY counter DESC, last_id DESC'),
    "decode_ranked": (
        ' SELECT slug, type, expression, meaning, takeaway,'
        ' MIN(date) AS created_at, MAX(date) AS updated_at,'
        ' COUNT(*) AS counter, MAX(id) AS last_id'
        ' FROM decode GROUP BY slug ORDER BY counter DESC, last_id DESC'),
    "friction_ranked": (
        ' SELECT slug, type, zone, you_reached_for AS "you reached for",'
        ' natural_english AS "natural english",'
        ' MIN(date) AS created_at, MAX(date) AS updated_at,'
        ' COUNT(*) AS counter, MAX(id) AS last_id'
        ' FROM friction GROUP BY slug ORDER BY counter DESC, last_id DESC'),
}


def _ensure_views(con):
    """Recreate a view ONLY when the definition in code differs from the one
    stored in sqlite_master — steady-state connects write nothing, so the five
    parallel debrief specialists can't race each other's DROP/SELECT."""
    for name, body in VIEWS.items():
        stmt = "CREATE VIEW {0} AS{1}".format(name, body)
        row = con.execute(
            "SELECT sql FROM sqlite_master WHERE type='view' AND name=?",
            (name,)).fetchone()
        if row is None or row["sql"] != stmt:
            with con:
                con.execute("DROP VIEW IF EXISTS {0}".format(name))
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
            with con:  # step + version bump are atomic; a failed step retries
                MIGRATIONS[i](con)
                con.execute("PRAGMA user_version = {0}".format(i + 1))
    _ensure_views(con)
    _chmod_private(path)
    return con


def query(sql, params=()):
    """Escape hatch: run a statement on a READ-ONLY connection (URI mode=ro);
    any write fails at the connection level. Returns a list of dicts. The DB is
    materialized first (connect) so a read on a never-opened home still works."""
    connect().close()  # ensure the store + schema exist before opening ro
    uri = "file:{0}?mode=ro".format(db_path())
    con = sqlite3.connect(uri, uri=True)
    try:
        con.row_factory = sqlite3.Row
        return [dict(r) for r in con.execute(sql, params)]
    finally:
        con.close()
