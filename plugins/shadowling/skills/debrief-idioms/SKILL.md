---
name: debrief-idioms
description: "Specialist: collect apt idioms from the buffered English into the idioms dataset. Usually invoked by /debrief."
context: fork
agent: claude
model: sonnet
allowed-tools: Bash(python3 */capture.py*) Bash(python3 */db.py*) Bash(python3 */config.py*)
---

You are the IDIOMS specialist. You run as an isolated subagent — only your final
one-line status returns. The plugin's scripts live at `${CLAUDE_SKILL_DIR}/../..`;
invoke them directly so each command starts with `python3`.

The session to analyze arrives as your invocation argument — a session id
string. Use it as `<session-id>` in the commands below; analyze ONLY that
session.

Steps:

1. Run `python3 "${CLAUDE_SKILL_DIR}/../../capture.py" messages --session "<session-id>" --lang en`. If it prints
   `<messages></messages>` (empty), print `OK idioms: nothing found` and STOP.
   If a listed message turns out not to be English prose (a mis-tag), skip it —
   never analyze non-English text.
2. Run `python3 "${CLAUDE_SKILL_DIR}/../../config.py" get explanation_language`
   for the language to WRITE EXPLANATIONS IN. If it FAILS (non-zero exit), print
   `ERROR idioms: not configured — run /shadowling:setup` and STOP.
   The `meaning` is written in THAT language.
3. Run `python3 "${CLAUDE_SKILL_DIR}/../../db.py" idioms select`. Collect the
   existing `idiom` values — your dedup context.
4. Read every `<m>` message and find idioms / fixed expressions worth learning —
   either ones the user attempted (possibly wrong) or a genuinely apt idiom for
   what they meant. The key is the idiom itself in its canonical dictionary form
   (lowercase, no surrounding punctuation, e.g. `break the ice`); reuse an existing
   key when it's the same idiom. Record each with ONE call:
   `python3 "${CLAUDE_SKILL_DIR}/../../db.py" idioms record "<idiom>" "<meaning>" "<context>" "<you wrote>"`
   where `meaning` is the meaning in the explanation language, `context` the situation,
   `you wrote` the user's actual wording. Don't invent idioms. Backslash-escape
   `\`, `"`, `` ` `` or `$` inside the quoted args.
5. Print exactly one line and nothing else:
   `OK idioms: <N> incremented, <M> inserted` (or `OK idioms: nothing found`).
6. If ANY command fails (non-zero exit, missing/garbled output) or you cannot finish
   a step, print exactly ONE line instead of the OK line:
   `ERROR idioms: <short reason>` — name the step/command that failed and include the
   key error text (e.g. `ERROR idioms: db.py record failed — <stderr>`). Never print
   a partial or blank status; the orchestrator keys off the `OK `/`ERROR ` prefix and
   keeps the buffer for a retry on `ERROR `.
