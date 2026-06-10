---
name: debrief
description: "Review your buffered English into per-category frequency docs (grammar / rephrasings / idioms / verbs). Usage: /debrief"
allowed-tools: Bash(python3 */capture.py*) Skill(shadowling:debrief-triage) Skill(shadowling:debrief-grammar) Skill(shadowling:debrief-rephrasing) Skill(shadowling:debrief-idioms) Skill(shadowling:debrief-verbs) Skill(shadowling:debrief-friction)
---

You orchestrate the four per-category specialists. You run in the MAIN agent (this
is not a `context: fork` skill), so you can invoke other skills with the Skill
tool. The plugin's scripts live at `${CLAUDE_SKILL_DIR}/../..`; invoke them
directly so each command starts with `python3`.

Steps:

1. Run `python3 "${CLAUDE_SKILL_DIR}/../../capture.py" pending-count`. If it prints
   `0`, tell the user there's nothing to review and STOP — do not invoke anything.
2. Invoke `debrief-triage` ALONE and WAIT for its status line — the language
   slices everyone else reads depend on it. If it returns an `ERROR ` line (or
   no line), STOP: report it and tell the user to re-run `/debrief`.
3. Invoke ALL FIVE analytical specialists IN PARALLEL — five Skill calls in a
   SINGLE message (five tool_use blocks at once), NOT one after another:
   `debrief-grammar`, `debrief-rephrasing`, `debrief-idioms`, `debrief-verbs`,
   `debrief-friction`. They write to different files, so running them
   concurrently is safe. Each returns exactly one `OK <cat>: …` or
   `ERROR <cat>: <reason>` line.
4. Mark the batch ONLY if ALL SIX status lines (triage + five) were `OK `: run
   `python3 "${CLAUDE_SKILL_DIR}/../../capture.py" mark-processed` — processed
   messages stay in the store as history; messages captured while the debrief
   ran stay unprocessed for the next batch. If ANY specialist returned an
   `ERROR ` line (or none), do NOT mark — the batch stays intact for a retry.
5. Print a compact combined summary: one line per category (its `OK `/`ERROR `
   line), then the `mark-processed` output (or that the batch was kept). If
   anything failed, name the failed category(ies), quote their `ERROR ` reason,
   and tell the user they can re-run `/debrief`. No analysis, no doc contents.
