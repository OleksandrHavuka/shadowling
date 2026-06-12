---
name: tutor
description: "Drill your recorded English pains (friction phrasings, grammar fixes, irregular verbs, learned vocab) with spaced repetition. Usage: /tutor [size]"
disable-model-invocation: true
allowed-tools: Bash(python3 */tutor.py*) Bash(python3 */config.py*)
---

You run an interactive tutoring session IN THIS conversation (you deal a card,
the user answers, you judge, repeat). The plugin's scripts live at
`${CLAUDE_SKILL_DIR}/../..`; invoke them directly so each command starts with
`python3`.

Steps:

1. Run `python3 "${CLAUDE_SKILL_DIR}/../../config.py" get explanation_language`.
   If it FAILS (non-zero exit), tell the user to run `/shadowling:setup` and
   STOP. Write all feedback in THAT language.
2. Run `python3 "${CLAUDE_SKILL_DIR}/../../tutor.py" deck` (add `--size <N>` if
   the user passed a number). If it prints nothing: say there is nothing due
   and nothing new — come back after a /debrief — and STOP.
3. For EACH card, one at a time: print the exercise (number it `[i/N]`), WAIT
   for the user's reply, judge it, then record with ONE call feeding the
   user's reply to stdin VERBATIM (do not re-quote, trim, or fix it):
   `printf '%s' "<their reply>" | python3 "${CLAUDE_SKILL_DIR}/../../tutor.py" record <item_kind> <item_key> <exercise> <verdict>`
   Exercises and verdicts:
   - `friction`/`production` — ask: how would you say (prompt_data
     `you_reached_for`, mention the zone)? PASS = conveys the meaning of
     `natural_english` in a natural register (word-for-word identity NOT
     required); PARTIAL = understandable but unnatural; FAIL = bailed, empty,
     or wrong meaning. Always show `natural_english` after judging.
   - `grammar`/`fix` — ask to correct `original`. PASS = the error class from
     `rule` is fixed (other phrasing variance is fine); PARTIAL = fixed but a
     new error introduced; FAIL = the error remains. Show `fixed` + `rule`.
   - `verbs`/`forms` — ask for past + past participle of `item_key`. PASS =
     both exact; PARTIAL = one correct. Show the forms from `prompt_data`.
   - `vocab`/`reverse` — ask: what is the English word for `translation`?
     PASS = the word; PARTIAL = minor misspelling. Show the word. (On FAIL
     the script auto-resets the word into glossing — mention it relearns.)
   Give ONE line of feedback per card, then move on. If the user asks to stop,
   stop immediately (skip the remaining cards, no records for unseen cards).
4. After the last card: print a summary — pass/partial/fail counts, items that
   fell back to box 1, then run
   `python3 "${CLAUDE_SKILL_DIR}/../../tutor.py" stats` and report due_today /
   due_tomorrow. Nothing else.
