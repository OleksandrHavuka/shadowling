---
name: shadowling-db
description: Use when changing shadowling's sqlite schema or data layer — adding tables, columns, views, or migrations, storing data for a new feature, or touching shadowling.db, appdb.py, models/, or capture.py storage code.
---

# shadowling DB conventions

One sqlite database (`~/.shadowling/shadowling.db`), stdlib `sqlite3` only.
`plugins/shadowling/appdb.py` owns the connection (`connect()`: WAL,
`busy_timeout=5000`, `row_factory=Row`, migration runner, view recreation).
Never open the DB another way; ad-hoc read-only analysis goes through
`capture.py query "<SELECT …>"`.

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

`*_ranked` views are dropped and recreated on EVERY `connect()`. Changing a
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
