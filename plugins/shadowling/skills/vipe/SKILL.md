---
name: vipe
description: "Dev: wipe the six category datasets (incident tables) for a clean test run; keeps config, vocab, and the message store. Usage: /vipe"
disable-model-invocation: true
allowed-tools: Bash(python3 */sql.py*)
---

Dev utility — empties the six category incident tables so you can re-test from
a clean slate. Keeps `config.json`, the `vocab` table, and the `messages`
store. The wipe goes through `sql.py --write`, which snapshots the database
into `backups/` before each delete — so a mistaken run is always recoverable.

Run EXACTLY these six commands and print their combined output, then STOP:

```
python3 "${CLAUDE_PLUGIN_ROOT}/sql.py" --write "DELETE FROM grammar"
python3 "${CLAUDE_PLUGIN_ROOT}/sql.py" --write "DELETE FROM rephrasing"
python3 "${CLAUDE_PLUGIN_ROOT}/sql.py" --write "DELETE FROM idioms"
python3 "${CLAUDE_PLUGIN_ROOT}/sql.py" --write "DELETE FROM verbs"
python3 "${CLAUDE_PLUGIN_ROOT}/sql.py" --write "DELETE FROM decode"
python3 "${CLAUDE_PLUGIN_ROOT}/sql.py" --write "DELETE FROM friction"
```
