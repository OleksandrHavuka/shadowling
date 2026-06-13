# Development

Local dev notes for working on the shadowling plugin.

## Layout

```
plugins/shadowling/
  core.py            # shared: data dir, config load/save, transcript reading
  config.py          # plugin-wide language config CLI (get / set)
  vocab.py           # vocab store (add / remove / list-active) + glossing hooks (inject / scan)
  capture.py         # message capture + sqlite store (tag / slices / mark-processed / ro query)
  appdb.py           # single sqlite home: connect(), MIGRATIONS (user_version), ranked views, ro query
  db.py              # CLI over models/ (record / select / export / drop)
  sql.py             # dev console: arbitrary SQL — ro by default, --write + auto-snapshot, backup verb
  tutor.py           # spaced repetition: deck (due+new+hot-zone boost) / record (Leitner) / stats
  traceability.py    # enforce the schema <-> models <-> skills <-> PROMPT_SQL field-name contract (CLI / test / hook)
  models/            # incident models + record fan-out (grammar, rephrasing, idioms, verbs, decode, friction)
  skills/            # skill bodies:
                     #   loot/, drop/          — fork: translate+add / remove terms
                     #   setup/                — main: ask + set the three plugin languages
                     #   debrief/              — main: orchestrate triage + five specialists
                     #   debrief-triage/       — fork: tag each message's language(s)
                     #   debrief-{grammar,rephrasing,idioms,verbs,friction}/ — fork: analyze batch slice → datasets
                     #   aha/                  — main: explain expressions you can't read literally
                     #   vipe/                 — dev: drop the six category datasets for a clean test run
  hooks/hooks.json   # UserPromptSubmit (inject) + Stop (scan, capture)
  test_*.py          # appdb, capture, config, core, db, models, record, sql, traceability, tutor, vocab
```

## Apply local changes

Hooks and commands run from the **installed cache copy**
(`~/.claude/plugins/cache/shadowling-lab/shadowling/<version>/`), not the working
tree. After editing, reinstall so the cache is refreshed:

```
/plugin uninstall shadowling@shadowling-lab
/plugin install shadowling@shadowling-lab
/reload-plugins
```

If the cache does not refresh for the same version, bump `version` in
`plugins/shadowling/.claude-plugin/plugin.json`, then reinstall.

First-time marketplace setup (local path):

```
/plugin marketplace add /Users/oleksandr/projects/shadowling
/plugin install shadowling@shadowling-lab
/reload-plugins
```

## Tests

```
cd plugins/shadowling
python3 -m unittest discover -p 'test_*.py' -v    # full suite, stdlib only
```

## Data-structure traceability

`traceability.py` enforces the field-name contract end-to-end — schema →
`models/*.insert_cols` → skill `record "<…>"` placeholders → `tutor.PROMPT_SQL` —
so a rename that drifts any layer fails loudly instead of silently. One `check()`,
three surfaces:

```
python3 plugins/shadowling/traceability.py    # dev CLI: exit 1 + the offending mismatch on drift, else "OK"
```

- **test** — `test_traceability.py`, part of the suite above (and the pre-push hook);
- **hook** — `.claude/settings.json` re-runs it (PostToolUse) after any edit to
  `appdb.py`, `tutor.py`, `models/`, or `skills/`, surfacing a break in-session (exit 2);
- view aliases (`learner_wrote AS "you wrote"`) are a display layer and are not asserted.

## Git hooks

Shared hooks in `.githooks/` gate every commit and push (dev-only — ruff never ships
with the plugin). Activate once per clone:

```
git config core.hooksPath .githooks
```

- **pre-commit** — `ruff format` + `ruff check` on the staged `*.py` (re-stages the
  formatting), then the traceability check (always, since skill `.md` edits can break
  the contract too). Blocks the commit on any lint or traceability failure.
- **pre-push** — the full `python3 -m unittest` suite + traceability, run before
  sharing. Tests live here (not pre-commit) so the commit loop stays fast and they run
  against the pushed history rather than the staged-vs-worktree mix.

ruff is resolved as `ruff` on PATH, else `uvx ruff`; a missing dev tool skips the
format/lint step rather than blocking the commit.

## Manual CLI smoke

All scripts are stdlib-only and runnable directly. Point the data dir at a temp
home so you never touch real data. Language now lives in `config.py`:

```
export SHADOWLING_HOME=/tmp/sl
python3 plugins/shadowling/config.py set first_language Spanish
python3 plugins/shadowling/config.py set learning_language English
python3 plugins/shadowling/config.py set explanation_language Spanish
python3 plugins/shadowling/config.py get first_language         # exit 1 + setup hint until ALL THREE keys are set
python3 plugins/shadowling/vocab.py add hello hola "machine learning" "aprendizaje automatico"
python3 plugins/shadowling/vocab.py list-active
python3 plugins/shadowling/vocab.py remove hello ghost
```

`/debrief` message store (Stop hook feeds this; inspect by hand):

```
python3 plugins/shadowling/capture.py paths            # show the sqlite db path
python3 plugins/shadowling/capture.py pending-count    # unprocessed messages
python3 plugins/shadowling/capture.py messages         # current batch as XML
python3 plugins/shadowling/capture.py tag "1=en" "2=en,uk"
python3 plugins/shadowling/capture.py mark-processed   # stamp tagged rows
python3 plugins/shadowling/capture.py query "SELECT id, langs, processed_at FROM messages ORDER BY id DESC LIMIT 5"
```

`/aha` and `/debrief` incidents go through the `db.py` CLI (record / select /
export), and any view is queryable read-only via `capture.py query`:

```
python3 plugins/shadowling/db.py grammar record "article-omission" "drops 'the'" "I went to store" "I went to the store" "use the"
python3 plugins/shadowling/db.py grammar select            # ranked view, JSON per row
python3 plugins/shadowling/db.py grammar export            # same, as a markdown table
python3 plugins/shadowling/capture.py query "SELECT slug, counter FROM grammar_ranked"
```

Ad-hoc SQL (dev console; ro unless `--write`, which snapshots first):

```
python3 plugins/shadowling/sql.py "SELECT slug, counter FROM grammar_ranked"
python3 plugins/shadowling/sql.py --md "SELECT * FROM vocab"
python3 plugins/shadowling/sql.py --write "DELETE FROM messages WHERE id = ?" 3
python3 plugins/shadowling/sql.py backup
```

Tutor + per-session debrief plumbing:

```
python3 plugins/shadowling/tutor.py deck --size 4          # today's cards, JSON per card
printf '%s' "I went to the store" | python3 plugins/shadowling/tutor.py record grammar article-omission fix pass
python3 plugins/shadowling/tutor.py stats
python3 plugins/shadowling/capture.py sessions             # debrief worklist
python3 plugins/shadowling/capture.py messages --session <id> --lang en
python3 plugins/shadowling/capture.py mark-drills          # fence tutor answers
python3 plugins/shadowling/capture.py mark-processed --session <id>
```

## Data & env overrides

Real data lives in `~/.shadowling/`:

| File                  | What                                                                       |
| --------------------- | -------------------------------------------------------------------------- |
| `shadowling.db`       | everything: message store (captured messages, language tags, processed stamps), the six category incident datasets + their `*_ranked` views, and the `vocab` table + tutor attempts/mastery |
| `config.json`         | `first_language` / `learning_language` / `explanation_language` — all three required (whole-plugin gate)|
| `backups/`            | rotating pre-write snapshots from `sql.py` (keep last 10, dev tool only) |

Env overrides (used by tests and smoke runs):

| Var                   | Overrides                       |
| --------------------- | ------------------------------- |
| `SHADOWLING_HOME`     | the whole data dir              |

## Schema changes

All data lives in `shadowling.db`, owned by `appdb.py`. To evolve the schema,
**append** a migration callable to `MIGRATIONS` — never edit a shipped one. The
runner keys off `PRAGMA user_version`, takes an automatic `.bak` backup before
upgrading, and applies each pending step in a transaction that also bumps the
version. The `*_ranked` views are derived code (not migrated): `connect()`
recreates a view only when its definition in code differs from the stored one.
See `.claude/skills/shadowling-db` for the full conventions.

## Notes

- stdlib only (Python 3.9+), no third-party deps.
- `/loot` runs as a forked subagent (`context: fork`): translation happens off
  the main context; deterministic work lives in `vocab.py`.
- `/aha` runs in the **main** agent (it needs the live conversation for context);
  `/debrief` runs in main but forks triage + the five specialists into their own windows.
- Hooks must never crash the session — `scan` and `capture` swallow exceptions.
