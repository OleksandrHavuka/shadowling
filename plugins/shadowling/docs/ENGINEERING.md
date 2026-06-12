# Engineering notes

An engineering due-diligence companion to the [README](../README.md). The README
explains *what shadowling does*; this document explains *how it is built*, what it
guarantees, and — crucially — **how to verify every claim here yourself**. Every
principle below names the code that enforces it and the test that guards it.

shadowling is a Claude Code plugin, but the parts worth reading as engineering are
platform-agnostic: a disciplined sqlite data layer, a linear migration history, and
a strict separation between what a script *guarantees* and what a language model
does *best-effort*.

---

## Architecture at a glance

One sqlite database (`~/.shadowling/shadowling.db`), standard-library Python only,
no dependencies. Data lives **outside** the plugin directory (which is ephemeral on
plugin updates); the location is `$SHADOWLING_HOME` or `~/.shadowling` (`core.data_dir`).

```
config.py    ── plugin-wide language config (3 mandatory keys), the whole-plugin gate
appdb.py     ── the single owner of the connection: WAL, migrations, ranked views, RO escape hatch
models/      ── one repository per incident category over appdb (append-only INSERT, read via view)
db.py        ── CLI over the repositories (record / select / export / drop)
vocab.py     ── vocabulary glossing store + hook entry points
capture.py   ── message collector (Stop hook) + debrief-pipeline read/write verbs
tutor.py     ── spaced-repetition engine (Leitner) over the datasets
sql.py       ── dev console: arbitrary SQL, read-only by default, snapshot-before-write
skills/      ── the LLM-driven workflows (/debrief, /aha, /tutor, /loot, setup, …)
```

The dividing line that matters: **`appdb.py` + `models/` + the CLIs are deterministic
code**; **`skills/` are instructions a model follows.** See
[The deterministic boundary](#the-deterministic-boundary) below.

---

## Design principles (each with evidence)

### 1. Schema changes are append-only migrations — never edits

Versioning is `PRAGMA user_version` plus the ordered `MIGRATIONS` list in `appdb.py`.
A schema change **appends** one migration; shipped migrations are never edited, so a
fresh install replays the exact same history an old install took. The runner copies
the file to `.bak` (only when the DB is non-empty), then applies each pending step
and bumps the version **atomically** (`with con:` — a failed step rolls back and
retries).

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
  record tests that read computed headers (`counter`, `last example`) from the views.

### 3. Every field name traces end-to-end (no name drift)

A column has **one name** from schema → repository → SQL consumer → skill. Views may
alias a column to a human-readable display header (`learner_wrote AS "you wrote"`) —
that is a documented presentation layer, not drift. The `db.py … record` CLI is
positional, so a skill's placeholder at position *i* must name the column the argument
lands in.

This is machine-checkable in both directions (see
[Verify it yourself](#verify-it-yourself)):

- every model's `insert_cols` ⊆ the real table columns;
- every skill's `record "<…>"` placeholder sequence **equals** the column sequence;
- every `tutor.PROMPT_SQL` statement selects only real columns.

- Convention documented in: the `shadowling-db` project skill (column naming, the
  retired names `ts`/`date` and the per-category learner columns).

### 4. Standard library only, Python 3.9+

No third-party imports, no `requirements.txt`/`pyproject.toml`, no ORM. This is a
deliberate portability/supply-chain constraint.

- Verified: the import graph is stdlib + local modules only; the suite **compiles and
  passes under Python 3.9.6**; no `match`/`case`, no PEP-604 (`X | Y`) annotations
  (the code uses no type annotations and `str.format` over f-strings, by choice).

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

What the script **guarantees** vs what the model does **best-effort** — stated plainly
because honesty about this line is the point:

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
python3 -m unittest                       # 183 tests, ~1s
# or: python3 -m unittest discover -p 'test_*.py' -v
```

**End-to-end traceability proof** (schema ↔ models ↔ skill placeholders):

```bash
export SHADOWLING_HOME=$(mktemp -d)
python3 - <<'PY'
import re, inspect, models, tutor, appdb
con = appdb.connect()
cols = lambda t: {r["name"] for r in con.execute("PRAGMA table_info(%s)" % t)}
MAP = {"kind": "type"}  # recorder's local param name -> the column it lands in
skill = {"grammar":"skills/debrief-grammar/SKILL.md","rephrasing":"skills/debrief-rephrasing/SKILL.md",
         "idioms":"skills/debrief-idioms/SKILL.md","verbs":"skills/debrief-verbs/SKILL.md",
         "friction":"skills/debrief-friction/SKILL.md","decode":"skills/aha/SKILL.md"}
ok = True
for cat, rec in models.RECORDERS.items():
    assert set(models.REGISTRY[cat].insert_cols) <= cols(models.REGISTRY[cat].table)
    expected = [MAP.get(p, p) for p in inspect.signature(rec).parameters]
    found = re.findall(r'<([^>]+)>',
            re.search(r'%s record ((?:"<[^>]+>" ?)+)' % cat, open(skill[cat]).read()).group(1))
    ok &= found == expected
    print(f"{cat:11} placeholders == columns: {found == expected}")
for kind, sql in tutor.PROMPT_SQL.items():
    m = re.search(r'SELECT (.+?) FROM (\w+)', sql)
    ok &= all(f.strip() in cols(m.group(2)) for f in m.group(1).split(','))
print("CONTRACT HOLDS:", ok)
PY
```

**Residual audit** — retired names appear only in schema *history*, never in a live consumer:

```bash
# retired column names: expect hits ONLY in appdb.py migrations + test_appdb.py migration tests
grep -rnwE 'yours|you_wrote|your_read|you_reached_for|natural_english|example_fix' --include='*.py' --include='*.md' .
# no hardcoded learning language: expect none
grep -rn -- '--lang en' skills/
```

---

## Known limitations & roadmap

Tracked honestly (full list in the local `TODO.md`):

- **Retry idempotency** — a debrief specialist records findings one at a time (each
  `db.py record` is its own committed transaction), so a mid-batch failure leaves the
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
