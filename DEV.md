# Development

Local dev notes for working on the shadowling plugin.

## Layout

```
plugins/shadowling/
  core.py            # shared: data dir, config load/save, transcript, .script_path
  config.py          # plugin-wide language CLI (lang / set-lang)
  vocab.py           # vocab store (add / remove / list-active) + glossing hooks (inject / scan)
  capture.py         # /en-review buffer + markdown tables
  skills/            # skill bodies:
                     #   vocab-add/    — fork (haiku): translate + add terms, hint typos
                     #   vocab-remove/ — fork (haiku): remove terms
                     #   setup/        — main: ask + set the plugin language
                     #   en-review/    — fork (sonnet): analyze buffer into docs
  hooks/hooks.json   # UserPromptSubmit (inject) + Stop (scan, capture)
  test_vocab.py  test_config.py  test_capture.py
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
python3 -m unittest test_vocab.py test_capture.py -v
```

## Manual CLI smoke

All scripts are stdlib-only and runnable directly. Point the data dir at a temp
home so you never touch real data:

```
export SHADOWLING_HOME=/tmp/sl
python3 plugins/shadowling/vocab.py set-lang Spanish
python3 plugins/shadowling/vocab.py add hello hola "machine learning" "aprendizaje automatico"
python3 plugins/shadowling/vocab.py list-active
python3 plugins/shadowling/vocab.py remove hello ghost
python3 plugins/shadowling/vocab.py lang        # prints native language, empty if unset
```

en-review buffer (Stop hook feeds this; inspect/dump/clear by hand):

```
python3 plugins/shadowling/capture.py paths      # show buffer + doc paths
python3 plugins/shadowling/capture.py dump        # what /en-review would analyze
python3 plugins/shadowling/capture.py clear
```

## Data & env overrides

Real data lives in `~/.shadowling/`:

| File              | What                                         |
| ----------------- | -------------------------------------------- |
| `config.json`     | `native_language` / `learning_language`      |
| `words.csv`       | vocab list (word, translation, remaining, status) |
| `en_buffer.jsonl` | buffered English messages awaiting `/en-review` |
| `grammar.md` etc. | generated correction docs                    |
| `.script_path`    | abs path to a script, so command bodies locate the plugin |

Env overrides (used by tests and smoke runs):

| Var                   | Overrides                  |
| --------------------- | -------------------------- |
| `SHADOWLING_HOME`     | the whole data dir         |
| `SHADOWLING_CONFIG`   | path to `config.json`      |
| `SHADOWLING_CSV`      | path to `words.csv`        |
| `SHADOWLING_EN_BUFFER`| path to `en_buffer.jsonl`  |

## Notes

- stdlib only (Python 3.9+), no third-party deps.
- `/vocab` runs as a forked subagent (`context: fork`): translation happens off
  the main context; deterministic work lives in `vocab.py`.
- Hooks must never crash the session — `scan` and `capture` swallow exceptions.
```
