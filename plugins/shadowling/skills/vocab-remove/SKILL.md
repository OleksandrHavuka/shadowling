---
name: vocab-remove
description: "Remove words/terms from your vocab list. Comma-separated for several at once. Usage: /shadowling:vocab-remove <word>[, <word2>, ...]"
context: fork
agent: claude
model: haiku
allowed-tools: Bash(python3 *)
---

Remove the given terms from the vocab store.

Resolve the plugin script dir once:

```
DIR="$(dirname "$(cat "${SHADOWLING_HOME:-$HOME/.shadowling}/.script_path" 2>/dev/null)")"
```

Terms (comma-separated): `$ARGUMENTS`

Split `$ARGUMENTS` on commas, trim each, drop empties, then one call:
`python3 "$DIR/vocab.py" remove "<term1>" "<term2>" ...`. Report what was removed
and what was not found.

Do NOT gloss anything in your reply.
