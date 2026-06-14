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
  check.sh           # one-command dev gate: ruff + tach + mypy + tests (see Guardrails)
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
                     #   test_models*, test_sql, test_properties) — `python3 -m unittest` discovers it
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
python3 -m unittest discover -p 'test_*.py' -v                     # full suite, stdlib only
uvx --with hypothesis python3 -m unittest discover -p 'test_*.py'  # + property tests (else skipped)
```

## Code-quality & architecture guardrails

Dev-only gates that give the agent (and you) machine-readable feedback when an edit
drifts off-canon. All run via `uvx` — ephemeral, nothing ships with the plugin. If a
tool is reachable by neither its binary nor `uvx`, the gate FAILS with an install hint
(never a silent skip, so a missing dependency can't masquerade as a pass). One command
runs the lot (the definition-of-done; exits non-zero on any failure or missing tool):

```
./check.sh        # ruff + tach + mypy + the test suite (+ property tests when uvx is present)
```

Or run a single gate from `plugins/shadowling`:

```
uvx ruff format --check . && uvx ruff check .   # style + lint (E/F)
uvx tach check                                  # import architecture: the clean dependency tree
uvx mypy --check-untyped-defs ./*.py models/    # type contract on the library modules
```

- **tach** — enforces `tach.toml`: the declared dependency tree (high → low, siblings
  independent), so no branch pulls a sibling and the leaves (`core`, `tagio`) pull
  nothing. A forbidden import fails with `file:line` + the offending symbol. The flat,
  bare-import layout rules out import-linter (grimp needs packages); Tach maps by path.
- **mypy** — `--check-untyped-defs` type-checks every function body without forcing full
  annotations; the contract surfaces (`models/base.py`, `core.py`) carry real types.
- **hypothesis** — property tests for the pure cores (tagio round-trip, Leitner math,
  vocab matching, slug/key normalizers). The import is guarded so a bare `unittest` run
  skips them, but `check.sh` provides hypothesis via `uvx` (and fails if it can't), so the
  gate always runs them. See the Tests section.

## Git hooks

Shared hooks in `.githooks/` close the feedback loop — both call `check.sh`, so the gate
definitions live in one place. Activate once per clone:

```
git config core.hooksPath .githooks
```

- **pre-commit** — runs `check.sh` (ruff + tach + mypy + the test suite). Blocks the
  commit on any gate failure. The whole run is ~instant, so there's no fast/full split.
- **pre-push** — runs `check.sh` again before sharing: a safety net in case a commit used
  `--no-verify` or was amended.

`check.sh` resolves each tool to its binary, else `uvx`; if neither is available the gate
FAILS with an install hint rather than skipping. It checks the working tree, not the
staged snapshot — fine for whole-file commits; review if you `git add -p`.

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
