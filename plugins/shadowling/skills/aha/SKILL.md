---
name: aha
description: "Explain an expression in the language you're learning that you can't read literally — get a verdict (memorize vs learnable rule) + how to read it, saved to the decode dataset. Usage: /aha <phrase> [+ your hunch]"
allowed-tools: Bash(python3 */decode.py*) Bash(python3 */config.py*)
---

You help the user EXPLAIN a phrase in the language they're learning that they
can't read literally (something with a non-literal / idiomatic meaning). You run
in the MAIN agent, so you already see this
conversation — use it for context. This skill's entrypoint is
`${CLAUDE_SKILL_DIR}/decode.py` (in this skill dir); the shared `config.py` is at
`${CLAUDE_PLUGIN_ROOT}/config.py`. Invoke each directly so the command starts
with `python3` (e.g. `python3 "${CLAUDE_SKILL_DIR}/decode.py" record …`,
`python3 "${CLAUDE_PLUGIN_ROOT}/config.py" show`).

Input: the user passes, in free text, one or more expressions in the language they
are learning that they couldn't read, optionally with their own hunch at the
meaning (e.g.
`/aha "it cost an arm and a leg" — I thought it's about an arm and a leg`). Parse
out each phrase and the user's hunch yourself.

Steps:

1. Run `python3 "${CLAUDE_PLUGIN_ROOT}/config.py" show`. The expression is in
   `learning_language`; write `meaning` and `takeaway` in `explanation_language`.
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
   d. Record it with ONE call. Put each field's value between its tags VERBATIM —
      values may span lines; never escape anything (the quoted `<<'SL_IN'` stops the
      shell from touching it). The body and the closing `SL_IN` MUST start at
      column 0 (an indented `SL_IN` will not close the heredoc):

```bash
python3 "${CLAUDE_SKILL_DIR}/decode.py" record <<'SL_IN'
<slug>the canonical slug</slug>
<type>fixed or method</type>
<expression>the phrase</expression>
<meaning>the real meaning</meaning>
<takeaway>fixed → memorize: set phrase; method → rule: how</takeaway>
<learner_wrote>the user's guess/hunch (empty if none given)</learner_wrote>
<context>where it appeared (from this conversation or the user)</context>
SL_IN
```
   e. If the command exits non-zero, tell the user that item failed to save (show the
      error) but keep your inline explanation — the teaching is not lost.
3. Close with a one-line note of what was saved (e.g. `saved: 2 (1 fixed, 1 method)`),
   or say nothing was saved if every item was literal / a vocab word.
