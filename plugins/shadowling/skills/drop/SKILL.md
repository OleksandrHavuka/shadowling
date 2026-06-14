---
name: drop
description: "Remove words/terms from your vocab list. Comma-separated for several at once. Usage: /drop <word>[, <word2>, ...]"
context: fork
agent: claude
model: haiku
allowed-tools: Bash(python3 */drop.py*)
---

Remove the given terms from the vocab store.

This skill's entrypoint is `${CLAUDE_SKILL_DIR}/drop.py` (in this skill dir);
invoke it directly so the command starts with `python3` (e.g.
`python3 "${CLAUDE_SKILL_DIR}/drop.py" remove ...`).

Terms (comma-separated): `$ARGUMENTS`

Split `$ARGUMENTS` on commas, trim each, drop empties, then one call:
`python3 "${CLAUDE_SKILL_DIR}/drop.py" remove "<term1>" "<term2>" ...`. Report what was removed
and what was not found.

Do NOT gloss anything in your reply.
