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


def _migration_6(con):
    """Mandatory per-session provenance + clean regen. Add a NOT NULL session_id to
    the six incident tables so the tutor can pick context per-session (DEFAULT ''
    only satisfies SQLite's "a NOT NULL ADD COLUMN needs a non-null default" rule;
    the model always stamps a real session, so '' is never written). Existing
    findings carry no session, so WIPE the incident tables; DELETE messages with no
    session_id (unattributable, pre-tutor rows); reset messages.processed_at so the
    next /debrief re-runs every session and re-persists with session_id (langs kept
    -> no re-triage). Non-vocab mastery is wiped (regenerated slugs are
    LLM-nondeterministic and would orphan SR rows). vocab untouched. decode is wiped
    with the rest (debrief never regenerates it; /aha repopulates going forward)."""
    incident = ("grammar", "rephrasing", "idioms", "verbs", "friction", "decode")
    for tbl in incident:
        con.execute(f"ALTER TABLE {tbl} ADD COLUMN session_id TEXT NOT NULL DEFAULT ''")
        con.execute(f"DELETE FROM {tbl}")
    con.execute("DELETE FROM messages WHERE session_id IS NULL")
    con.execute("UPDATE messages SET processed_at = NULL")
    con.execute("DELETE FROM mastery WHERE item_kind != 'vocab'")


def _migration_7(con):
    """Fat /loot enrichment columns on vocab (append-only). Two scalar fields
    (definition, source_context) plus two JSON-array fields (examples, synonyms)
    guarded by json_valid. source_context non-NULL is the sole grounding signal
    (no separate flag). Existing rows backfill NULL (not yet enriched)."""
    statements = [
        "ALTER TABLE vocab ADD COLUMN definition TEXT",
        "ALTER TABLE vocab ADD COLUMN source_context TEXT",
        "ALTER TABLE vocab ADD COLUMN examples TEXT"
        " CHECK (examples IS NULL OR json_valid(examples))",
        "ALTER TABLE vocab ADD COLUMN synonyms TEXT"
        " CHECK (synonyms IS NULL OR json_valid(synonyms))",
    ]
    for stmt in statements:
        con.execute(stmt)


def _migration_8(con):
    """Rename vocab.source_context -> ctx so ONE name carries the field end-to-end:
    the /loot heredoc <ctx>, the enrichment <ctx>/<known_ctx> wire, and this column
    all read `ctx` (traceable parse -> table -> render). No view references it, so
    none is dropped first; rows are preserved (RENAME keeps data)."""
    con.execute("ALTER TABLE vocab RENAME COLUMN source_context TO ctx")


def _migration_9(con):
    """Add vocab.alt_translations: a JSON array of alternative first_language
    renderings of the SAME primary sense as `translation` (0-N), parallel to the
    examples/synonyms JSON columns and guarded by json_valid. A different axis from
    `synonyms` (learning_language synonyms). Write-only storage for now (no gloss/
    tutor read); existing rows backfill NULL (not yet enriched)."""
    con.execute(
        "ALTER TABLE vocab ADD COLUMN alt_translations TEXT"
        " CHECK (alt_translations IS NULL OR json_valid(alt_translations))"
    )


def _migration_10(con):
    """Create anki_link: a flat mirror of Anki's per-word review progress inside
    shadowling.db (Spec 2 / Variant B). `word` is a logical ref to vocab.word —
    always present (words are soft-deleted, never removed), so the row is never
    orphaned and needs no FK. The progress columns are a known, finite set, so no
    JSON. Fresh installs replay this same step."""
    con.execute(
        "CREATE TABLE IF NOT EXISTS anki_link("
        " word TEXT PRIMARY KEY, note_id INTEGER, card_id INTEGER,"
        " deck TEXT, due INTEGER, interval INTEGER, reps INTEGER,"
        " lapses INTEGER, synced_at TEXT)"
    )


def _migration_11(con):
    """Add vocab.forms and vocab.lemma for language-agnostic Anki cloze matching.
    `forms` is a JSON array of the OTHER learning_language surface forms of the same
    lexeme that may appear in examples (the lemma's surface if it differs from
    `word`; `[]` for invariant words) — read only by the Anki push's cloze matcher,
    guarded by json_valid like the sibling enrichment columns. `lemma` is the
    canonical base form (plain TEXT), stored for future grouping/search (no consumer
    yet). Both mirror the alt_translations plumbing (migration 9); existing rows
    backfill NULL (not yet re-looted)."""
    con.execute(
        "ALTER TABLE vocab ADD COLUMN forms TEXT"
        " CHECK (forms IS NULL OR json_valid(forms))"
    )
    con.execute("ALTER TABLE vocab ADD COLUMN lemma TEXT")


MIGRATIONS = [
    _migration_1,
    _migration_2,
    _migration_3,
    _migration_4,
    _migration_5,
    _migration_6,
    _migration_7,
    _migration_8,
    _migration_9,
    _migration_10,
    _migration_11,
]

# --- views: derived code, never migrated --------------------------------------
# Each *_ranked view splits true aggregates (MIN/MAX created_at, COUNT) from the
# display columns: the aggregate subquery yields per-group counts/dates plus the
# newest incident id (MAX(id) AS last_id), and the outer table is JOINed to that
# one row, so EVERY bare display column comes deterministically from the group's
# newest incident — not just one display column. `id` is a unique PK, so
# `g.id = agg.last_id` matches exactly one row per group.

VIEWS = {
    "grammar_ranked": (
        " SELECT g.slug, g.problem, g.original, g.fixed,"
        " agg.created_at, agg.updated_at, agg.counter, agg.last_id"
        " FROM grammar g"
        " JOIN (SELECT slug, MIN(created_at) AS created_at,"
        " MAX(created_at) AS updated_at, COUNT(*) AS counter, MAX(id) AS last_id"
        " FROM grammar GROUP BY slug) agg"
        " ON g.slug = agg.slug AND g.id = agg.last_id"
        " ORDER BY agg.counter DESC, agg.last_id DESC"
    ),
    "rephrasing_ranked": (
        " SELECT g.slug, g.problem, g.learner_wrote, g.native_phrase,"
        " agg.created_at, agg.updated_at, agg.counter, agg.last_id"
        " FROM rephrasing g"
        " JOIN (SELECT slug, MIN(created_at) AS created_at,"
        " MAX(created_at) AS updated_at, COUNT(*) AS counter, MAX(id) AS last_id"
        " FROM rephrasing GROUP BY slug) agg"
        " ON g.slug = agg.slug AND g.id = agg.last_id"
        " ORDER BY agg.counter DESC, agg.last_id DESC"
    ),
    "idioms_ranked": (
        " SELECT g.idiom, g.meaning, g.learner_wrote,"
        " agg.created_at, agg.updated_at, agg.counter, agg.last_id"
        " FROM idioms g"
        " JOIN (SELECT idiom, MIN(created_at) AS created_at,"
        " MAX(created_at) AS updated_at, COUNT(*) AS counter, MAX(id) AS last_id"
        " FROM idioms GROUP BY idiom) agg"
        " ON g.idiom = agg.idiom AND g.id = agg.last_id"
        " ORDER BY agg.counter DESC, agg.last_id DESC"
    ),
    "verbs_ranked": (
        " SELECT g.used_form, g.correction, g.context,"
        " g.verb, g.past, g.participle,"
        " agg.created_at, agg.updated_at, agg.counter, agg.last_id"
        " FROM verbs g"
        " JOIN (SELECT verb, MIN(created_at) AS created_at,"
        " MAX(created_at) AS updated_at, COUNT(*) AS counter, MAX(id) AS last_id"
        " FROM verbs GROUP BY verb) agg"
        " ON g.verb = agg.verb AND g.id = agg.last_id"
        " ORDER BY agg.counter DESC, agg.last_id DESC"
    ),
    "decode_ranked": (
        " SELECT g.slug, g.type, g.expression, g.meaning, g.takeaway,"
        " agg.created_at, agg.updated_at, agg.counter, agg.last_id"
        " FROM decode g"
        " JOIN (SELECT slug, MIN(created_at) AS created_at,"
        " MAX(created_at) AS updated_at, COUNT(*) AS counter, MAX(id) AS last_id"
        " FROM decode GROUP BY slug) agg"
        " ON g.slug = agg.slug AND g.id = agg.last_id"
        " ORDER BY agg.counter DESC, agg.last_id DESC"
    ),
    "friction_ranked": (
        " SELECT g.slug, g.type, g.zone, g.learner_wrote, g.native_phrase,"
        " agg.created_at, agg.updated_at, agg.counter, agg.last_id"
        " FROM friction g"
        " JOIN (SELECT slug, MIN(created_at) AS created_at,"
        " MAX(created_at) AS updated_at, COUNT(*) AS counter, MAX(id) AS last_id"
        " FROM friction GROUP BY slug) agg"
        " ON g.slug = agg.slug AND g.id = agg.last_id"
        " ORDER BY agg.counter DESC, agg.last_id DESC"
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
            # online backup, not shutil.copy: con sees the full WAL view, so the
            # .bak is a consistent snapshot and can't be a torn main-file copy
            # missing uncheckpointed -wal frames.
            dest = sqlite3.connect(path + ".bak")
            try:
                con.backup(dest)
            finally:
                dest.close()
        # Re-read user_version INSIDE each step's tx() instead of trusting the
        # pre-loop read. Two processes can connect during the same upgrade window;
        # without the re-read, the loser (released from BEGIN IMMEDIATE after the
        # winner committed) would replay already-applied steps — re-running
        # _migration_2's `DELETE FROM messages` and then crashing on _migration_3's
        # `RENAME COLUMN ts`. BEGIN IMMEDIATE takes the write lock before the read,
        # so read + migrate + bump are one serialized unit.
        while True:
            with tx(con):
                v = con.execute("PRAGMA user_version").fetchone()[0]
                if v >= len(MIGRATIONS):
                    break
                MIGRATIONS[v](con)
                con.execute(f"PRAGMA user_version = {v + 1}")
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
