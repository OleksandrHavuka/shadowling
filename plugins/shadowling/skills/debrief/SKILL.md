---
name: debrief
description: "Review your buffered writing into per-category frequency docs (grammar / rephrasings / idioms / verbs). Usage: /debrief"
allowed-tools: Bash(python3 */debrief.py*) Skill(shadowling:debrief-triage) Skill(shadowling:debrief-grammar) Skill(shadowling:debrief-rephrasing) Skill(shadowling:debrief-idioms) Skill(shadowling:debrief-verbs) Skill(shadowling:debrief-friction)
---

You orchestrate the per-session debrief: triage + five per-category
specialists run once PER SESSION. You run in the MAIN agent (this
is not a `context: fork` skill), so you can invoke other skills with the Skill
tool. This skill's entrypoint is `${CLAUDE_SKILL_DIR}/debrief.py` (in this skill
dir). Invoke it as a single Bash call that begins with `python3` and the full
path — the only shape the granted `Bash(python3 …)` permission matches (so
nothing before it and no chaining).

Steps:

1. Run `python3 "${CLAUDE_SKILL_DIR}/debrief.py" mark-drills` — ONCE,
   before anything else (it fences off tutor answers). It prints
   `<result><row><marked>N</marked></row></result>`; keep N for the final summary.
2. Run `python3 "${CLAUDE_SKILL_DIR}/debrief.py" sessions`. It prints
   `<sessions><row><session>ID</session><pending>N</pending></row>…</sessions>`;
   if it prints `<sessions></sessions>` (no rows), tell the user there's nothing
   to review and STOP.
3. FOR EACH `<row>`'s `<session>` id from step 2, SEQUENTIALLY (finish one session before
   starting the next):
   a. Invoke `debrief-triage` with the session id as the argument and WAIT
      for its status line. On `ERROR ` (or no line): report it, SKIP this
      session (do NOT mark it), and continue with the next session.
   b. Invoke ALL FIVE analytical specialists IN PARALLEL — five Skill calls
      in a SINGLE message, each with the SAME session id as the argument:
      `debrief-grammar`, `debrief-rephrasing`, `debrief-idioms`,
      `debrief-verbs`, `debrief-friction`. Each returns exactly one
      `OK <cat>: …` or `ERROR <cat>: <reason>` line.
   c. ONLY if all six lines for this session were `OK `: run
      `python3 "${CLAUDE_SKILL_DIR}/debrief.py" mark-processed --session <id>`
      (it prints `<result><row><processed>N</processed><kept>M</kept></row></result>` —
      informational; the gate is still "all six OK").
      Otherwise leave the session pending — it will be retried by the next
      /debrief — and continue with the next session.
4. Print a compact final summary: the mark-drills line, then one line per
   session (`<id>: OK` or `<id>: ERROR <failed categories>`), then totals.
   If anything failed, tell the user a re-run of /debrief retries only the
   failed sessions. No analysis, no doc contents.
