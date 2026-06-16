---
name: debrief-triage
description: "Specialist: tag the language(s) of each unprocessed message in the store. Usually invoked by /debrief before the analytical specialists."
context: fork
agent: claude
model: haiku
allowed-tools: Bash(python3 */triage.py*)
---

You tag the LANGUAGES of the user's captured messages so the other debrief
specialists can read deterministic slices. You only DECIDE the codes — the
script stamps them. Never rewrite, quote back, or "fix" message text.

This skill's entrypoint is `${CLAUDE_SKILL_DIR}/triage.py` (in this skill dir).
Invoke it as a single Bash call that begins with `python3` and the full path —
the only shape the granted `Bash(python3 …)` permission matches (so nothing
before it and no chaining).

The session to analyze arrives as your invocation argument — a session id
string. Use it as `<session-id>` in the commands below; analyze ONLY that
session.

Loop until done:

1. Run `python3 "${CLAUDE_SKILL_DIR}/triage.py" messages --session "<session-id>" --untagged --limit 200`.
   If it prints `<messages></messages>`, the loop is DONE.
2. The slice comes back as `<messages><row><id>N</id><text>…</text></row>…</messages>`.
   For EACH `<row>` decide the language code(s) of its `<text>` PROSE as lowercase ISO-ish
   codes (`en`, `uk`, `de`, ...). Code snippets, file paths, CLI commands, and
   tech identifiers do NOT count as prose — judge only the language of the human
   prose around them. A message mixing two languages gets both codes (e.g. `en,uk`).
   If there is no judgeable prose, use `und`.
3. ONE batch call tagging everything you just read:
   `python3 "${CLAUDE_SKILL_DIR}/triage.py" tag "<id>=<code[,code]>" "<id>=<code[,code]>" ...`
4. Go back to step 1.

If any command exits non-zero, print exactly one line
`ERROR triage: <short reason>` and STOP. Otherwise, when the loop is done,
print exactly one line: `OK triage: <total messages tagged> tagged`.
Never print anything else — the orchestrator keys off the `OK `/`ERROR ` prefix.
