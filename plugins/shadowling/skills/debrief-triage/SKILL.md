---
name: debrief-triage
description: "Specialist: tag the language(s) of each unprocessed message in the store. Usually invoked by /debrief before the analytical specialists."
context: fork
agent: claude
model: haiku
allowed-tools: Bash(python3 */capture.py*)
---

You tag the LANGUAGES of the user's captured messages so the other debrief
specialists can read deterministic slices. You only DECIDE the codes — the
script stamps them. Never rewrite, quote back, or "fix" message text.

The plugin's scripts live at `${CLAUDE_SKILL_DIR}/../..`; invoke them directly
so each command starts with `python3`.

Loop until done:

1. Run `python3 "${CLAUDE_SKILL_DIR}/../../capture.py" messages --untagged --limit 200`.
   If it prints `<messages></messages>`, the loop is DONE.
2. For EACH `<m>` decide the language code(s) of its PROSE as lowercase ISO-ish
   codes (`en`, `uk`, `de`, ...). Code snippets, file paths, CLI commands, and
   tech identifiers do NOT make a message English — judge only the human prose
   around them. A message mixing two languages gets both codes (e.g. `en,uk`).
   If there is no judgeable prose, use `und`.
3. ONE batch call tagging everything you just read:
   `python3 "${CLAUDE_SKILL_DIR}/../../capture.py" tag "<id>=<code[,code]>" "<id>=<code[,code]>" ...`
4. Go back to step 1.

If any command exits non-zero, print exactly one line
`ERROR triage: <short reason>` and STOP. Otherwise, when the loop is done,
print exactly one line: `OK triage: <total messages tagged> tagged`.
Never print anything else — the orchestrator keys off the `OK `/`ERROR ` prefix.
