---
name: shadowling-db
description: Use when changing shadowling's sqlite schema or data layer — adding tables, columns, views, or migrations, storing data for a new feature, or touching shadowling.db, appdb.py, models/, or capture.py storage code.
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
  `messages.langs/processed_at`.
- IDs: semantic slugs where meaning matters, bare `INTEGER PRIMARY KEY`
  where mechanics matter. No readable-ID generators.
- Always parameterized queries (`?`), transactions via `with con:`.

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
