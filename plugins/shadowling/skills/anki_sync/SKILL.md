---
name: anki-sync
description: "Push enriched vocab to Anki Desktop as flashcards and pull review progress back. Usage: /anki-sync"
context: fork
agent: claude
model: haiku
allowed-tools: Bash(python3 */anki_sync.py*)
---

Sync the vocab store with Anki Desktop. Requires Anki Desktop running with the
AnkiConnect add-on (code 2055492159) installed.

This skill's entrypoint is `${CLAUDE_SKILL_DIR}/anki_sync.py` (in this skill dir);
invoke it directly so the command starts with `python3`:
`python3 "${CLAUDE_SKILL_DIR}/anki_sync.py"`.

It takes no arguments. Relay the summary line it prints verbatim. If it prints a
`<shadowling_misconfig>` notice instead, point the user at `/shadowling:setup`. If
it reports that AnkiConnect is unreachable, tell the user to start Anki Desktop and
install the AnkiConnect add-on.

Do NOT gloss anything in your reply.
