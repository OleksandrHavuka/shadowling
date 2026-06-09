---
name: debrief
description: "Review your buffered English into per-category frequency docs (grammar / rephrasings / idioms / verbs). Usage: /debrief"
allowed-tools: Bash(python3 */capture.py*) Skill(shadowling:debrief-grammar) Skill(shadowling:debrief-rephrasing) Skill(shadowling:debrief-idioms) Skill(shadowling:debrief-verbs)
---

You orchestrate the four per-category specialists. You run in the MAIN agent (this
is not a `context: fork` skill), so you can invoke other skills with the Skill
tool. The plugin's scripts live at `${CLAUDE_SKILL_DIR}/../..`; invoke them
directly so each command starts with `python3`.

Steps:

1. Run `python3 "${CLAUDE_SKILL_DIR}/../../capture.py" pending-count`. If it prints
   `0`, tell the user there's nothing to review and STOP — do not invoke anything,
   do not clear.
2. Invoke ALL FOUR specialists IN PARALLEL — issue the four Skill calls in a SINGLE
   message (four tool_use blocks at once), NOT one after another: `debrief-grammar`,
   `debrief-rephrasing`, `debrief-idioms`, `debrief-verbs`. They each write to their
   own files, so running them concurrently is safe. Each returns exactly one status
   line: `OK <cat>: …` on success, or `ERROR <cat>: <reason>` on failure.
3. Clear ONLY if all four returned an `OK ` line: run
   `python3 "${CLAUDE_SKILL_DIR}/../../capture.py" clear` to empty the buffer (the
   raw corpus `messages.log.jsonl` was already written at capture time, so this only
   drops the processed batch). If ANY specialist returned an `ERROR ` line (or no
   line at all), do NOT clear — the buffer stays intact for a safe retry.
4. Print a compact combined summary: one line per category (its `OK `/`ERROR ` line),
   then whether the buffer was cleared. If anything failed, name the failed
   category(ies), quote their `ERROR ` reason, and tell the user they can re-run
   `/debrief`. No analysis, no doc contents.
