# Engineering notes

How shadowling is built, and how to verify each claim — every principle below names
the code that enforces it and the test that guards it.

---

## Architecture at a glance

One sqlite database (`~/.shadowling/shadowling.db`), standard-library Python only,
no dependencies. Data lives **outside** the plugin directory (which is ephemeral on
plugin updates); the location is `$SHADOWLING_HOME` or `~/.shadowling` (`core.data_dir`).

```
config.py    ── plugin-wide language config (3 mandatory keys), the whole-plugin gate
appdb.py     ── the single owner of the connection: WAL, migrations, ranked views, RO escape hatch
models/      ── the repository layer: each module owns its table and ALL its SQL
               (6 incident repos + vocab / messages / tutor)
gloss.py     ── glossing hooks (inject / scan) over models/vocab
capture.py   ── Stop-hook message capture over models/messages
sql.py       ── dev console: arbitrary SQL, read-only by default, snapshot-before-write, paths
skills/      ── LLM workflows, each with a thin entrypoint .py (skillio parse → repository → output)
```

The dividing line that matters: **`appdb.py` + `models/` + the entrypoints are deterministic
code**; **`skills/` SKILL.md are instructions a model follows.** See
[The deterministic boundary](#the-deterministic-boundary) below.

---

## Design principles (each with evidence)

### 1. Schema changes are append-only migrations — never edits

Versioning is `PRAGMA user_version` plus the ordered `MIGRATIONS` list in `appdb.py`.
A schema change **appends** one migration; shipped migrations are never edited, so a
fresh install replays the exact same history an old install took. The runner copies
the file to `.bak` (only when the DB is non-empty), then applies each pending step
and bumps the version **atomically** (via `tx()` / `BEGIN IMMEDIATE`; a failed step
rolls back and the next connect resumes).

- Enforced by: `appdb.connect()` (backup + atomic step+bump loop), the `MIGRATIONS` list.
- **Proof it is followed:** migration 1's `CREATE TABLE` statements still contain the
  *original* column names (`yours`, `you_wrote`, `example_fix`, `natural_english`) —
  later renames are separate `ALTER … RENAME` migrations, not in-place edits.
- Guarded by: `test_appdb.py` — `test_reconnect_is_idempotent`,
  `test_existing_nonempty_db_backed_up_then_wiped`, `test_fresh_db_makes_no_backup`,
  and one upgrade-preserves-data test per migration (`…preserves_incident_and_vocab_data`,
  `…preserves_native_phrase_data`, `…renames_example_fix_keeps_data`).

### 2. Products are computed, never stored

Frequency counters, `updated_at`, and "latest example" fields are **computed on read**
by the `*_ranked` views — never stored on the incident tables. A view is recreated
only when its definition in code drifts from `sqlite_master` (`appdb._ensure_views`),
so steady-state connects write nothing and parallel readers cannot race.

- Verified: none of the six incident tables (`grammar`, `rephrasing`, `idioms`,
  `verbs`, `decode`, `friction`) has a stored `counter` or `updated_at` column. The
  only stored `updated_at` columns are on `vocab` and `mastery` — sanctioned mutable
  state (scheduling / glossing progress).
- Guarded by: `test_appdb.py::test_changed_view_definition_is_refreshed`, and the
  record tests that read computed columns (`counter`, `original`/`fixed`) from the views.

### 3. Every field name traces end-to-end (no name drift)

A column has **one name** from schema → repository → SQL consumer → skill. The ranked
views expose **machine column names** (`learner_wrote`, `native_phrase`, `used_form`,
`participle`, `original`/`fixed`) — no display-header aliases and no `→` concat; any
label the LLM sees is composed at the boundary, not baked into a view. Each incident
skill's entrypoint reads each field from a `<tag>` on stdin (a `<<'SL_IN'` heredoc —
zero shell escaping), so a skill's tag at position *i* must name the column the value
lands in.

This is machine-checkable in both directions (see
[Verify it yourself](#verify-it-yourself)):

- every model's `insert_cols` ⊆ the real table columns;
- every skill's `record <<'SL_IN'` tag sequence **equals** the column sequence its entrypoint's recorder writes;
- every `tutor.PROMPT_SQL` statement selects only real columns.

- Convention documented in: the `shadowling-db` project skill (column naming, the
  retired names `ts`/`date` and the per-category learner columns).

### 4. Standard library only, Python 3.9+

No third-party imports, no `requirements.txt`/`pyproject.toml`, no ORM. This is a
deliberate portability/supply-chain constraint.

- Verified: the import graph is stdlib + local modules only; the suite **compiles and
  passes under Python 3.9.6**; no `match`/`case`, no PEP-604 (`X | Y`) annotations.

### 5. Least privilege, read-only by default, parameterized always

- **File perms:** the DB (and its `-wal`/`-shm`/`.bak` siblings) are `chmod 0o600` —
  personal messages live here (`appdb._chmod_private`).
- **Read-only escape hatch:** ad-hoc reads go through `appdb.query`, which opens a
  `file:…?mode=ro` URI connection — any write fails at the connection level, not by
  SQL inspection. `sql.py` is the dev console; writes require an explicit `--write`
  and snapshot the DB first.
- **Parameterized queries:** every *value* binds to `?`. `str.format` appears in SQL
  only for *identifiers* (table / view / column names), all sourced from code
  constants (`insert_cols`, the `VIEWS` dict) — never from user input.
- **Concurrency:** `journal_mode=WAL` + `busy_timeout=5000` so the parallel debrief
  specialists don't block each other.
- Guarded by: `test_appdb.py::test_db_file_is_owner_only`, `…::test_query_is_read_only`,
  `…::test_query_binds_params`; `test_sql.py` (snapshot-before-write).

### 6. Data doctrine: append-only event logs

Category tables are append-only incident logs — one INSERT per occurrence, recorded
text is never UPDATEd or DELETEd. Uniqueness lives in the view's `GROUP BY` over a
pre-normalized key (slugify / casefold). The explicit, documented exceptions are
`vocab.remaining/status`, `messages.langs/processed_at/kind`, and the tutor's
`mastery` row — all genuinely mutable state. `attempts` is append-only and stores
the learner's answer verbatim (it doubles as the drill-filter registry).

---

## The deterministic boundary

What the script **guarantees** vs what the model does **best-effort**:

**One I/O module.** `skillio.py` is the single skill↔script boundary: it parses the
invocation (the `read_fields` heredoc + the argv slice/size/session parsers) and owns
the one output serializer, `render(rows, fields=None)`. `render` follows the
identifier-vs-value discipline — tag names are trusted column identifiers from code
(never escaped); only values pass through `_xml`. Repositories return plain data
(rows / counts / dicts), and each entrypoint frames `render`'s body with its dataset
tag (`f"<messages>{render(rows)}</messages>"`) and composes any status label from the
returned counts. The format is a simplified, LLM-oriented tag dialect (not strict XML;
never read by an XML parser) — chosen because records carry multiline free text and
Claude reads tag-delimited fields natively.

| Deterministic (Python) | Instruction-based (a model follows it) |
|---|---|
| storage, migrations, exposure counting, graduation, scheduling | the inline glossing of words in replies |
| frequency ranking, dedup by normalized key | the debrief specialists' linguistic analysis |
| message capture, drill filtering (fixed similarity threshold) | deriving a learning language's ISO code from its name |
| the read/write contract, file permissions | slug discipline / cross-category ownership calls |

The README mirrors this split ("Deterministic (in the script)" vs "Instruction-based").
Nothing that *can* be exact is left to the model.

---

## Verify it yourself

Everything below is reproducible from `plugins/shadowling/`.

**Full test suite (stdlib only):**

```bash
python3 -m unittest                       # 283 tests, ~1s
# or: python3 -m unittest discover -p 'test_*.py' -v
```

**Residual audit** — retired names appear only in schema *history*, never in a live consumer:

```bash
# retired column names: expect hits ONLY in appdb.py migrations + test_appdb.py migration tests
grep -rnwE 'yours|you_wrote|your_read|you_reached_for|natural_english|example_fix' --include='*.py' --include='*.md' .
# no hardcoded learning language: expect none
grep -rn -- '--lang en' skills/
# the old boundary names are fully retired: expect NO hits
grep -rn 'tagio\|cliutil\|format_loot_line' --include='*.py' .
```

---

## Known limitations & roadmap

Tracked honestly:

- **Retry idempotency** — a debrief specialist records findings one at a time (each
  entrypoint `record` is its own committed transaction), so a mid-batch failure leaves the
  earlier findings committed; the retry re-records them and inflates the counter. The
  clean fix rides on the headless-driver refactor (debrief 3.0): have the specialists
  *return* validated JSON findings instead of writing, and let the driver persist a
  session's findings **and** its processed-mark in one short, **per-session**
  transaction — a failure rolls back with no partial write, so the retry starts clean.
  The transaction must stay short (open it *after* the slow LLM analysis, not across
  it) and per-session (not per-run), or it blocks every other writer and rolls back
  already-good sessions. A content-key idempotent recorder is the fallback if the
  skills keep writing directly.
- **Centralized error logging** — scripts currently swallow or stderr-print errors; a
  single `errors.log` would make silent corpus-write failures visible.
- **Cross-platform** — hooks/commands hardcode `python3`; Windows needs detection.
- **CI** — no GitHub Actions matrix (3.9–3.13) yet.
- **Scale** — this is well-engineered *personal* infrastructure, pre-production; early
  migrations intentionally wiped the message corpus (the user waived that data).

---

## Appendix: schema reference

Final schema (after migration 5). Incident tables are append-only; `*_ranked` views
compute the products. Display headers (in quotes) are view aliases over the columns.

| Table | Columns |
|---|---|
| `messages` | id · created_at · text · langs · processed_at · session_id · kind |
| `grammar` | id · created_at · slug · problem · original · fixed · rule |
| `rephrasing` | id · created_at · slug · problem · learner_wrote · native_phrase · why |
| `idioms` | id · created_at · idiom · meaning · context · learner_wrote |
| `verbs` | id · created_at · verb · past · participle · used_form · correction · context |
| `decode` | id · created_at · slug · type · expression · meaning · takeaway · learner_wrote · context |
| `friction` | id · created_at · slug · type · zone · learner_wrote · native_phrase · context |
| `vocab` | word · translation · remaining · status · created_at · updated_at |
| `attempts` | id · created_at · session_id · item_kind · item_key · exercise · answer · verdict |
| `mastery` | item_kind · item_key · box · due_date · last_verdict · counter_seen · created_at · updated_at |

Views: `grammar_ranked`, `rephrasing_ranked`, `idioms_ranked`, `verbs_ranked`,
`decode_ranked`, `friction_ranked` — each a `GROUP BY` over the key column exposing
`counter`, `created_at` (`MIN`), `updated_at` (`MAX`), and the latest incident's
example fields.
