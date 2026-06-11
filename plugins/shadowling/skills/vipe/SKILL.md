---
name: vipe
description: "Dev: wipe the six category datasets (incident tables) for a clean test run; keeps config, vocab, and the message store. Usage: /vipe"
disable-model-invocation: true
allowed-tools: Bash(python3 */db.py*)
---

Dev utility — empties the six category incident tables so you can re-test from
a clean slate. Keeps `config.json`, the `vocab` table, and the `messages`
store. Deletion goes through the data layer only — never touch files or run
raw SQL.

Run EXACTLY these six commands and print their combined output, then STOP:

```
python3 "${CLAUDE_SKILL_DIR}/../../db.py" grammar drop
python3 "${CLAUDE_SKILL_DIR}/../../db.py" rephrasing drop
python3 "${CLAUDE_SKILL_DIR}/../../db.py" idioms drop
python3 "${CLAUDE_SKILL_DIR}/../../db.py" verbs drop
python3 "${CLAUDE_SKILL_DIR}/../../db.py" decode drop
python3 "${CLAUDE_SKILL_DIR}/../../db.py" friction drop
```
