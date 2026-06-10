---
name: drop
description: "Remove words/terms from your vocab list. Comma-separated for several at once. Usage: /drop <word>[, <word2>, ...]"
context: fork
agent: claude
model: haiku
allowed-tools: Bash(python3 */vocab.py*)
---

Remove the given terms from the vocab store.

The plugin's scripts live at `${CLAUDE_SKILL_DIR}/../..`; invoke them directly so
each command starts with `python3` (e.g.
`python3 "${CLAUDE_SKILL_DIR}/../../vocab.py" remove ...`).

Terms (comma-separated): `$ARGUMENTS`

Split `$ARGUMENTS` on commas, trim each, drop empties, then one call:
`python3 "${CLAUDE_SKILL_DIR}/../../vocab.py" remove "<term1>" "<term2>" ...`. Report what was removed
and what was not found.

Do NOT gloss anything in your reply.
