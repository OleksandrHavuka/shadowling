# Development

Local dev notes for working on the shadowling plugin.

## Layout

```
plugins/shadowling/
  core.py            # shared: data dir, config load/save, transcript reading
  config.py          # plugin-wide language CLI (lang / set-lang / explanation-lang / set-explanation-lang)
  vocab.py           # vocab store (add / remove / list-active) + glossing hooks (inject / scan)
  capture.py         # English-message capture for /debrief (buffer + raw corpus)
  jsonl.py           # append-only JSONL helper
  mddb.py            # markdown-table CRUD primitives
  db.py              # CLI over models/ (e.g. `db.py decode record ...`)
  models/            # product models + record fan-out (grammar, rephrasing, idioms, verbs, decode)
  skills/            # skill bodies:
                     #   loot/, drop/          — fork: translate+add / remove terms
                     #   setup/                — main: ask + set the plugin language
                     #   debrief/              — main: orchestrate the four specialists
                     #   debrief-{grammar,rephrasing,idioms,verbs}/ — fork: analyze buffer → docs
                     #   aha/                  — main: explain expressions you can't read literally
                     #   vipe/                 — dev: wipe debrief docs for a clean test run
  hooks/hooks.json   # UserPromptSubmit (inject) + Stop (scan, capture)
  test_*.py          # capture, config, core, db, jsonl, mddb, models, record, vocab
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

## Manual CLI smoke

All scripts are stdlib-only and runnable directly. Point the data dir at a temp
home so you never touch real data. Language now lives in `config.py`:

```
export SHADOWLING_HOME=/tmp/sl
python3 plugins/shadowling/config.py set-lang Spanish
python3 plugins/shadowling/config.py lang                  # native language, empty if unset
python3 plugins/shadowling/config.py set-explanation-lang Spanish
python3 plugins/shadowling/config.py explanation-lang      # always prints one (default English)
python3 plugins/shadowling/vocab.py add hello hola "machine learning" "aprendizaje automatico"
python3 plugins/shadowling/vocab.py list-active
python3 plugins/shadowling/vocab.py remove hello ghost
```

`/debrief` buffer (Stop hook feeds this; inspect/clear by hand):

```
python3 plugins/shadowling/capture.py paths          # show buffer + corpus paths
python3 plugins/shadowling/capture.py pending-count  # how many messages await /debrief
python3 plugins/shadowling/capture.py messages       # dump the raw corpus
python3 plugins/shadowling/capture.py clear          # clear the buffer
```

`/aha` and `/debrief` products go through the `db.py` record CLI:

```
python3 plugins/shadowling/db.py decode record "<slug>" "<type>" "<expression>" "<meaning>" "<takeaway>" "<your hunch>" "<context>"
```

## Data & env overrides

Real data lives in `~/.shadowling/`:

| File                  | What                                                                       |
| --------------------- | -------------------------------------------------------------------------- |
| `config.json`         | `native_language` / `explanation_language` (`learning_language` is cosmetic)|
| `words.csv`           | vocab list (word, translation, remaining, status)                          |
| `buffer.jsonl`        | buffered English messages awaiting `/debrief`                              |
| `messages.log.jsonl`  | permanent raw corpus of every captured English message                     |
| `grammar.md` etc.     | `/debrief` correction products (+ matching `*.log.jsonl` findings)          |
| `decode.md`           | `/aha` comprehension product (+ `decode.log.jsonl`)                        |

Env overrides (used by tests and smoke runs):

| Var                   | Overrides                       |
| --------------------- | ------------------------------- |
| `SHADOWLING_HOME`     | the whole data dir              |
| `SHADOWLING_CONFIG`   | path to `config.json`           |
| `SHADOWLING_CSV`      | path to `words.csv`             |
| `SHADOWLING_BUFFER`   | path to the buffer (`buffer.jsonl`) |

## Notes

- stdlib only (Python 3.9+), no third-party deps.
- `/loot` runs as a forked subagent (`context: fork`): translation happens off
  the main context; deterministic work lives in `vocab.py`.
- `/aha` runs in the **main** agent (it needs the live conversation for context);
  `/debrief` runs in main but forks the four specialists into their own windows.
- Hooks must never crash the session — `scan` and `capture` swallow exceptions.
