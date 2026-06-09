---
name: debrief-verbs
description: "Specialist: collect misused/noteworthy irregular verbs from the buffered English into irregular_verbs.md + irregular_verbs.log.jsonl. Usually invoked by /debrief."
context: fork
agent: claude
model: sonnet
allowed-tools: Bash(python3 */capture.py*) Bash(python3 */db.py*) Bash(python3 */config.py*)
---

You are the IRREGULAR-VERBS specialist. You run as an isolated subagent — only
your final one-line status returns. The plugin's scripts live at
`${CLAUDE_SKILL_DIR}/../..`; invoke them directly so each command starts with
`python3`.

Steps:

1. Run `python3 "${CLAUDE_SKILL_DIR}/../../capture.py" messages`. If it prints
   `<messages></messages>` (empty), print `OK verbs: nothing found` and STOP.
2. Run `python3 "${CLAUDE_SKILL_DIR}/../../config.py" explanation-lang` for the
   language to write any explanation in (it always prints one; default `English`).
   The verb forms and `example fix` stay in English regardless.
3. Run `python3 "${CLAUDE_SKILL_DIR}/../../db.py" verbs select`. Collect the
   existing `verb` values — your dedup context.
4. Read every `<m>` message and find misused or otherwise noteworthy IRREGULAR
   verbs (e.g. `I have went`, `I buyed`). The key is the verb base form (lowercase,
   e.g. `go`); reuse an existing key for the same verb. Record each with ONE call:
   `python3 "${CLAUDE_SKILL_DIR}/../../db.py" verbs record "<verb>" "<past>" "<participle>" "<example fix>"`
   where `verb` is the base form, `past` the simple past, `participle` the past
   participle, `example fix` a short `wrong → right` example. Only record genuine
   irregular-verb issues. Backslash-escape `\`, `"`, `` ` `` or `$` inside the
   quoted args.
5. Print exactly one line and nothing else:
   `OK verbs: <N> incremented, <M> inserted` (or `OK verbs: nothing found`).
