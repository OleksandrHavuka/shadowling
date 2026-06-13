---
name: shadowling-db
description: Use whenever you read, query, or mutate shadowling's sqlite database (shadowling.db) — any SELECT/INSERT/UPDATE/DELETE, ad-hoc SQL, dropping/clearing/resetting rows, inspecting data, or checking a migration's result. All DB access goes through sql.py or the data-layer verbs (db.py / vocab.py / capture.py), never raw sqlite3. Schema/data-layer changes are NOT made here — they go through an appended migration in appdb.py; this skill only documents that rule and verifies the outcome.
---

# shadowling DB conventions

One sqlite database (`~/.shadowling/shadowling.db`), stdlib `sqlite3` only.
`plugins/shadowling/appdb.py` owns the connection (`connect()`: WAL,
`busy_timeout=5000`, `row_factory=Row`, migration runner, view recreation).
Never open the DB another way; ad-hoc reads and dev surgery go through
`sql.py` (capture.py's `query` verb remains for the debrief pipeline).

## Schema changes: MIGRATIONS only

Versioning = `PRAGMA user_version` + the ordered `MIGRATIONS` list in
`appdb.py`. To change schema, APPEND one new migration entry. The runner
backs up the file (`.bak`), applies pending steps each in its own
transaction, and bumps `user_version` atomically.

**Never:**
- edit an already-shipped migration or a `CREATE TABLE` in place — fresh
  installs replay the SAME migration chain old installs took; there is one
  schema history, not two;
- run ad-hoc `ALTER`/"add column if missing" checks at connect time;
- add a migrations table, alembic, aiosqlite, or any ORM (stdlib-only rule).

## Views are derived code, not schema

`*_ranked` views are ensured current on EVERY `connect()` (recreated whenever
the definition in code differs from `sqlite_master`). Changing a
ranking/aggregation = edit the view definition in `appdb.py`; no migration,
no version bump. Products (counters, created/updated, latest example) are
COMPUTED from incident rows — never stored.

## Data doctrine

- Category tables (grammar, friction, …) are **append-only event logs**: one
  INSERT per incident; never UPDATE/DELETE recorded text. Uniqueness lives in
  `GROUP BY` (keys pre-normalized: slugify / casefold).
- Mutable state is the explicit exception: `vocab.remaining/status`,
  `messages.langs/processed_at/kind`, and the tutor's `mastery` table
  (box/due_date — scheduling state). `attempts` is append-only like the
  incident tables; its `answer` is stored VERBATIM (it doubles as the
  mark-drills registry).

## Column naming convention (since migration 3)

- **`created_at`** is the row-creation column on EVERY table — full ISO
  datetime on the event logs (`messages`, `attempts`) and on `vocab`/`mastery`;
  **date-only** (`YYYY-MM-DD`, via `core.today()`) on the six daily incident
  tables, whose frequency product wants days, not seconds.
- **`updated_at`** is STORED only where a row mutates: `vocab` and `mastery`.
  The incident tables expose it as the view's `MAX(created_at)` (a product, not
  a stored column — see the doctrine above); `messages` uses `processed_at` for
  its one lifecycle event; append-only `attempts` has no `updated_at`.
- **`learner_wrote`** is the canonical "what the learner produced" column on
  `rephrasing`/`idioms`/`decode`/`friction` (the views still alias it to a
  category-readable header: "you wrote" / "you reached for"). `grammar` keeps
  its matched `original`/`fixed` pair.
- Suffix rule: `_at` = full ISO datetime, a bare date (`due_date`) = `YYYY-MM-DD`.
  The retired names `ts` and `date` must not come back.
- IDs: semantic slugs where meaning matters, bare `INTEGER PRIMARY KEY`
  where mechanics matter. No readable-ID generators.
- Always parameterized queries (`?`), transactions via `with con:`.

**Enforced — run after any rename.** `traceability.py` proves the field-name
contract end-to-end (schema → `models/*.insert_cols` → skill `record "<…>"`
placeholders → `tutor.PROMPT_SQL`) as a test, a CLI (`python3 traceability.py`),
and a PostToolUse hook. It names the exact layer that drifted.

## Ad-hoc queries & dev surgery (sql.py)

`plugins/shadowling/sql.py` is the dev console — the replacement for any DB
MCP / raw `sqlite3` use. Raw `sqlite3` against the live db is forbidden
(WAL-consistency + perms).

- Prefer data-layer verbs first: `db.py <cat> record/select/export/drop`,
  `vocab.py add/remove`, `capture.py tag/mark-processed`.
- Any read: `python3 sql.py "<SELECT …>" [param …]` (JSON per row) or
  `--md` (markdown table). Params bind to `?` — never inline values.
- Mutations: `python3 sql.py --write "<SQL>" [param …]` — LAST resort for
  surgery (deduping a corrupted row, fixing a bad tag). Auto-snapshots to
  `<data_dir>/backups/` (keep last 10) before executing.
- Manual snapshot before risky experiments: `python3 sql.py backup`.
- Temp-home testing: `export SHADOWLING_HOME=$(mktemp -d)` and EVERY command
  that depends on it MUST run in the SAME Bash invocation — env vars do not
  survive across calls; a lost SHADOWLING_HOME silently retargets every
  command at the real `~/.shadowling`. `sql.py --write` announces its target
  (`db: <path>` on stderr) — verify it before trusting a destructive demo.
- Restore: `cp <data_dir>/backups/<snap>.db <data_dir>/shadowling.db`
  (remove the `-wal`/`-shm` siblings first).
