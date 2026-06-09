---
name: debrief
description: "Review your buffered English into per-category frequency docs (grammar / rephrasings / idioms / verbs). Usage: /debrief"
allowed-tools: Bash(python3 */capture.py*)
---

You orchestrate the four per-category specialists. You run in the MAIN agent (this
is not a `context: fork` skill), so you can invoke other skills with the Skill
tool. The plugin's scripts live at `${CLAUDE_SKILL_DIR}/../..`; invoke them
directly so each command starts with `python3`.

Steps:

1. Run `python3 "${CLAUDE_SKILL_DIR}/../../capture.py" pending-count`. If it prints
   `0`, tell the user there's nothing to review and STOP — do not invoke anything,
   do not clear.
2. Invoke these four skills, ONE AT A TIME in this order, via the Skill tool:
   `debrief-grammar`, then `debrief-rephrasing`, then `debrief-idioms`, then
   `debrief-verbs`. Each returns a single status line starting with `OK `.
3. If ALL four returned a line starting with `OK `, run
   `python3 "${CLAUDE_SKILL_DIR}/../../capture.py" clear` to empty the buffer (the
   raw corpus `messages.log.jsonl` was already written at capture time, so this
   only drops the processed batch). If ANY specialist did NOT return an `OK ` line,
   do NOT clear — tell the user which one failed and that they can re-run
   `/debrief` (the buffer is intact for a safe retry).
4. Print a compact combined summary: one line per category (their `OK <cat>: …`)
   plus whether the buffer was cleared. No analysis, no doc contents.
