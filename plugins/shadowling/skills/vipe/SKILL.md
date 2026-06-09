---
name: vipe
description: "Dev: wipe all generated files from SHADOWLING_HOME for a clean test run, keeping only config.json + words.csv. Usage: /vipe"
disable-model-invocation: true
allowed-tools: Bash(rm -fv "${SHADOWLING_HOME:-$HOME/.shadowling}"/*)
---

Dev utility — clears every generated file so you can re-test from a clean slate. Keeps
ONLY `config.json` (language settings) and `words.csv` (your vocab). Deletion is an
explicit list of file names (brace expansion), never a wildcard or `rm -rf`.

Run EXACTLY this one command and print its output, then STOP:

```
rm -fv "${SHADOWLING_HOME:-$HOME/.shadowling}"/{buffer.jsonl,messages.log.jsonl,grammar.md,rephrasings.md,idioms.md,irregular_verbs.md,grammar.log.jsonl,rephrasings.log.jsonl,idioms.log.jsonl,irregular_verbs.log.jsonl,.script_path}
```

`-f` keeps it quiet on files that don't exist; `-v` lists what was actually removed.
To wipe a new generated file later, add its name to the brace list.
