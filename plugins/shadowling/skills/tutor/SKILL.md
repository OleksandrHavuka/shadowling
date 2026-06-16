---
name: tutor
description: "Drill your recorded pains (friction phrasings, grammar fixes, irregular verbs, learned vocab) with spaced repetition. Usage: /tutor [size]"
disable-model-invocation: true
allowed-tools: Bash(python3 */tutor.py*) Bash(python3 */config.py*)
---

You run an interactive tutoring session IN THIS conversation (you deal a card,
the user answers, you judge, repeat). This skill's entrypoint is
`${CLAUDE_SKILL_DIR}/tutor.py` (in this skill dir); the shared `config.py` is at
`${CLAUDE_PLUGIN_ROOT}/config.py`. Invoke each directly so the command starts
with `python3`.

Steps:

1. Run `python3 "${CLAUDE_PLUGIN_ROOT}/config.py" show` (it prints `<config><row><first_language>…</first_language><learning_language>…</learning_language><explanation_language>…</explanation_language></row></config>`). Write all feedback in
   `explanation_language`.
2. Run `python3 "${CLAUDE_SKILL_DIR}/tutor.py" deck` (add `--size <N>` if
   the user passed a number). It prints `<deck><row>…one card per <row>…</row></deck>`.
   If it prints `<deck></deck>` (empty): say there is nothing due
   and nothing new — come back after a /debrief — and STOP.
3. For EACH card, one at a time: print the exercise (number it `[i/N]`), WAIT
   for the user's reply, judge it, then record with ONE call. Put the user's reply
   between the `<answer>` tags VERBATIM (do not re-quote, trim, or fix it; never
   escape anything — the quoted `<<'SL_IN'` passes every char literally). The body
   and the closing `SL_IN` MUST start at column 0:

```bash
python3 "${CLAUDE_SKILL_DIR}/tutor.py" record <item_kind> <item_key> <exercise> <verdict> <<'SL_IN'
<answer>
their reply, verbatim
</answer>
SL_IN
```
   The call prints `<result><row><box>N</box></row></result>` (the card's new Leitner box).
   Exercises and verdicts:
   - `friction`/`production` — ask: how would you say (`learner_wrote`, mention
     the `zone`)? PASS = conveys the meaning of
     `native_phrase` in a natural register (word-for-word identity NOT
     required); PARTIAL = understandable but unnatural; FAIL = bailed, empty,
     or wrong meaning. Always show `native_phrase` after judging.
   - `grammar`/`fix` — ask to correct `original`. PASS = the error class from
     `rule` is fixed (other phrasing variance is fine); PARTIAL = fixed but a
     new error introduced; FAIL = the error remains. Show `fixed` + `rule`.
   - `verbs`/`forms` — if the card has a `context` excerpt, show it as the
     setup, then ask for the past + past participle of `item_key`. PASS = both
     exact; PARTIAL = one correct. Show the forms (and `correction`) from the card.
   - `vocab`/`reverse` — ask: what is the learning-language word for `translation`?
     PASS = the word; PARTIAL = minor misspelling. Show the word. (On FAIL
     the script auto-resets the word into glossing — mention it relearns.)
   Give ONE line of feedback per card, then move on. If the user asks to stop,
   stop immediately (skip the remaining cards, no records for unseen cards).
4. After the last card: print a summary — pass/partial/fail counts, items that
   fell back to box 1, then run
   `python3 "${CLAUDE_SKILL_DIR}/tutor.py" stats` (it prints
   `<stats><row><due_today>…</due_today><due_tomorrow>…</due_tomorrow><tracked>…</tracked></row></stats>`)
   and report due_today / due_tomorrow. Nothing else.
