# Development

Local dev notes for working on the shadowling plugin.

## Layout

```
plugins/shadowling/
  core.py            # shared: data dir, config load/save, transcript reading
  config.py          # plugin-wide language config CLI (show / get / set)
  gloss.py           # glossing hooks (inject / scan) over models/vocab
  capture.py         # Stop-hook message capture over models/messages
  appdb.py           # single sqlite home: connect(), MIGRATIONS (user_version), ranked views, ro query
  sql.py             # dev console: arbitrary SQL — ro by default, --write + auto-snapshot, backup, paths
  traceability.py    # enforce the schema <-> models <-> skill record heredoc <-> tutor.PROMPT_SQL contract
  models/            # the repository layer — owns ALL SQL:
                     #   base.py + 6 incident repos (grammar, rephrasing, idioms, verbs, decode, friction)
                     #   vocab.py (Vocab), messages.py (Messages), tutor.py (Tutor)
  skills/            # skill bodies, each with its own thin entrypoint .py (tagio parse + repo call + output):
                     #   aha/decode.py                              — main: explain expressions; record decode
                     #   loot/loot.py, drop/drop.py                 — fork: add / remove vocab
                     #   setup/                                     — main: ask + set the three plugin languages
                     #   tutor/tutor.py                             — main: deck / record / stats
                     #   debrief/debrief.py                         — main: sessions / mark-processed / mark-drills
                     #   debrief-triage/triage.py                   — fork: messages / tag
                     #   debrief-{grammar,rephrasing,idioms,verbs,friction}/<cat>.py — fork: record / select / messages
                     #   vipe/                                      — dev: wipe incident tables via sql.py --write
  hooks/hooks.json   # UserPromptSubmit (gloss inject) + Stop (gloss scan, capture)
  tests/             # the unittest suite (test_appdb … test_entrypoints, test_gloss,
                     #   test_models*, test_sql, test_traceability) — `python3 -m unittest` discovers it
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

Same from a terminal (`claude plugin` CLI):

```
# install
claude plugin marketplace add /Users/oleksandr/projects/shadowling && claude plugin install shadowling@shadowling-lab
# update
claude plugin marketplace update shadowling-lab && claude plugin update shadowling
```

## Tests

```
cd plugins/shadowling
python3 -m unittest discover -p 'test_*.py' -v    # full suite, stdlib only
```

## Data-structure traceability

`traceability.py` enforces the field-name contract end-to-end — schema →
`models/*.insert_cols` → skill `record <<'SL_IN'` tags → `tutor.PROMPT_SQL` —
so a rename that drifts any layer fails loudly instead of silently. One `check()`,
three surfaces:

```
python3 plugins/shadowling/traceability.py    # dev CLI: exit 1 + the offending mismatch on drift, else "OK"
```

- **test** — `test_traceability.py`, part of the suite above (and the pre-push hook);
- **hook** — `.claude/settings.json` re-runs it (PostToolUse) after any edit to
  `appdb.py`, `models/`, or `skills/`, surfacing a break in-session (exit 2);
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
```

Vocab (loot/drop entrypoints):

```
python3 plugins/shadowling/skills/loot/loot.py add <<'SL_IN'
<items>
hello	hola
machine learning	aprendizaje automatico
</items>
SL_IN
python3 plugins/shadowling/skills/drop/drop.py remove hello ghost
python3 plugins/shadowling/sql.py "SELECT word, translation, remaining FROM vocab"
```

Message store + debrief plumbing (capture.py is the Stop hook; reads/admin via entrypoints + sql.py):

```
python3 plugins/shadowling/sql.py paths                     # show the sqlite db path
python3 plugins/shadowling/skills/debrief/debrief.py sessions
python3 plugins/shadowling/skills/debrief-triage/triage.py messages --untagged --limit 200
python3 plugins/shadowling/skills/debrief-triage/triage.py tag "1=en" "2=en,uk"
python3 plugins/shadowling/skills/debrief/debrief.py mark-processed --session <id>
python3 plugins/shadowling/sql.py "SELECT id, langs, processed_at FROM messages ORDER BY id DESC LIMIT 5"
```

`/aha` and `/debrief` incidents go through each skill's entrypoint
(`record`/`select`); any view is queryable read-only via `sql.py`:

```
python3 plugins/shadowling/skills/debrief-grammar/grammar.py record <<'SL_IN'
<slug>article-omission</slug>
<problem>drops 'the'</problem>
<original>I went to store</original>
<fixed>I went to the store</fixed>
<rule>use the</rule>
SL_IN
python3 plugins/shadowling/skills/debrief-grammar/grammar.py select        # ranked view, JSON per row
python3 plugins/shadowling/sql.py --md "SELECT * FROM grammar_ranked"      # same, markdown table
```

Ad-hoc SQL (dev console; ro unless `--write`, which snapshots first):

```
python3 plugins/shadowling/sql.py "SELECT slug, counter FROM grammar_ranked"
python3 plugins/shadowling/sql.py --md "SELECT * FROM vocab"
python3 plugins/shadowling/sql.py --write "DELETE FROM messages WHERE id = ?" 3
python3 plugins/shadowling/sql.py backup
```

Tutor + drills:

```
python3 plugins/shadowling/skills/tutor/tutor.py deck --size 4
python3 plugins/shadowling/skills/tutor/tutor.py record grammar article-omission fix pass <<'SL_IN'
<answer>
I went to the store
</answer>
SL_IN
python3 plugins/shadowling/skills/tutor/tutor.py stats
python3 plugins/shadowling/skills/debrief/debrief.py mark-drills
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
  the main context; deterministic work lives in `models/vocab.py` (called by `loot.py`).
- `/aha` runs in the **main** agent (it needs the live conversation for context);
  `/debrief` runs in main but forks triage + the five specialists into their own windows.
- Hooks must never crash the session — `scan` (in `gloss.py`) and `capture` swallow exceptions.
