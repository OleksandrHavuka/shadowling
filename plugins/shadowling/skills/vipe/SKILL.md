---
name: vipe
description: "Dev: wipe the debrief product/log docs from SHADOWLING_HOME for a clean test run; keeps config.json, words.csv, and the sqlite message store. Usage: /vipe"
disable-model-invocation: true
allowed-tools: Bash(rm -fv "${SHADOWLING_HOME:-$HOME/.shadowling}"/*)
---

Dev utility — clears the debrief product/log docs so you can re-test from a clean
slate. Keeps `config.json`, `words.csv`, and the sqlite message store
`shadowling.db` (your captured-message history and processed flags survive).
Deletion is an explicit list of file names (brace expansion), never a wildcard
or `rm -rf`.

Run EXACTLY this one command and print its output, then STOP:

```
rm -fv "${SHADOWLING_HOME:-$HOME/.shadowling}"/{grammar.md,rephrasings.md,idioms.md,irregular_verbs.md,grammar.log.jsonl,rephrasings.log.jsonl,idioms.log.jsonl,irregular_verbs.log.jsonl,friction.md,friction.log.jsonl}
```

`-f` keeps it quiet on files that don't exist; `-v` lists what was actually removed.
To wipe a new generated file later, add its name to the brace list.
