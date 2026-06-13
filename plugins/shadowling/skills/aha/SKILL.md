---
name: aha
description: "Explain an expression in the language you're learning that you can't read literally — get a verdict (memorize vs learnable rule) + how to read it, saved to the decode dataset. Usage: /aha <phrase> [+ your hunch]"
allowed-tools: Bash(python3 */db.py*) Bash(python3 */config.py*)
---

You help the user EXPLAIN a phrase in the language they're learning that they
can't read literally (something with a non-literal / idiomatic meaning). You run
in the MAIN agent, so you already see this
conversation — use it for context. The plugin's scripts live at
`${CLAUDE_SKILL_DIR}/../..`; invoke them directly so each command starts with
`python3`.

Input: the user passes, in free text, one or more expressions in the language they
are learning that they couldn't read, optionally with their own hunch at the
meaning (e.g.
`/aha "it cost an arm and a leg" — I thought it's about an arm and a leg`). Parse
out each phrase and the user's hunch yourself.

Steps:

1. Run `python3 "${CLAUDE_SKILL_DIR}/../../config.py" get learning_language` (the
   language the expression is in) and `python3 "${CLAUDE_SKILL_DIR}/../../config.py" get explanation_language`
   for the language to WRITE EXPLANATIONS IN. If EITHER FAILS (non-zero exit), relay
   the notice config.py printed (it names the missing setting) and tell the user to
   run `/shadowling:setup` first, then STOP. Write `meaning` and
   `takeaway` in the explanation language.
2. For EACH expression the user brought:
   a. If it is literal / there is nothing to explain → say so to the user and DO NOT
      record it.
   b. If it is just an unknown single word (not an idiom, not a grammar pattern) →
      explain it and suggest `/loot <word>`; DO NOT record a decode row.
   c. Otherwise classify it:
      - `fixed` — a set expression whose meaning is NOT compositional → the action is
        "memorize". The slug is the canonical phrase, lowercase (e.g. `break the ice`).
      - `method` — it IS derivable via a grammar pattern / part of speech the user is
        missing → the action is "learn the rule". The slug is the RULE, not the phrase
        (e.g. `present-perfect-passive`), so the same rule aggregates across phrases.
      Teach it INLINE: the verdict, the real meaning, for `method` the rule and how it
      is derived, and — comparing with the user's hunch — exactly where their read
      went wrong.
   d. Record it with ONE call:
      `python3 "${CLAUDE_SKILL_DIR}/../../db.py" decode record "<slug>" "<type>" "<expression>" "<meaning>" "<takeaway>" "<learner_wrote>" "<context>"`
      where `type` is `fixed` or `method`; `expression` the phrase; `meaning` the real
      meaning; `takeaway` the action (`fixed` → `memorize: set phrase`; `method` →
      `rule: <how>`); `learner_wrote` the user's guess/hunch (empty string `""` if none given);
      `context` where it appeared (from this conversation or the user). When a value
      contains `\`, `"`, `` ` `` or `$`, backslash-escape it inside the quoted arg so
      bash passes it literally.
   e. If the command exits non-zero, tell the user that item failed to save (show the
      error) but keep your inline explanation — the teaching is not lost.
3. Close with a one-line note of what was saved (e.g. `saved: 2 (1 fixed, 1 method)`),
   or say nothing was saved if every item was literal / a vocab word.
