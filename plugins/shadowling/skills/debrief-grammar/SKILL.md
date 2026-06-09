---
name: debrief-grammar
description: "Specialist: extract grammar errors from the buffered English into grammar.md + grammar.log.jsonl. Usually invoked by /debrief."
context: fork
agent: claude
model: sonnet
allowed-tools: Bash(python3 */capture.py*) Bash(python3 */db.py*) Bash(python3 */config.py*)
---

You are the GRAMMAR specialist. You run as an isolated subagent — only your final
one-line status returns to the caller. The plugin's scripts live at
`${CLAUDE_SKILL_DIR}/../..`; invoke them directly so each command starts with
`python3` (e.g. `python3 "${CLAUDE_SKILL_DIR}/../../capture.py" messages`).

Steps:

1. Run `python3 "${CLAUDE_SKILL_DIR}/../../capture.py" messages`. If it prints
   `<messages></messages>` (empty), print `OK grammar: nothing found` and STOP.
2. Run `python3 "${CLAUDE_SKILL_DIR}/../../config.py" explanation-lang` for the
   language to WRITE EXPLANATIONS IN (it always prints one; default `English`).
   Write `problem` and `rule` in THAT language only — no other-language glosses.
3. Run `python3 "${CLAUDE_SKILL_DIR}/../../db.py" grammar select`. Collect the
   existing `slug` values — this is your dedup context.
4. Read every `<m>` message and find GRAMMAR errors only (articles, prepositions,
   agreement, tense, word order, etc. — not naturalness / idioms / verb forms
   unless they are a grammar error). For each real error, derive a slug:
   - Slug format (HARD): the slug is ONE kebab-case token matching
     `^[a-z0-9]+(-[a-z0-9]+)*$` — all lowercase ASCII, words joined by single
     hyphens, NO spaces and NO underscores anywhere. Shape it as
     `<area>-<phenomenon>[-<refinement>]` (the area is one token from the list
     below, joined to the rest with a hyphen, never a space).
     Good: `article-omission-before-countable`, `preposition-wrong-after-verb`,
     `subject-verb-agreement-plural`.
     Bad: `article omission before countable` (spaces), `Article_Omission`
     (caps + underscore), `-tense-shift-` (leading/trailing hyphen).
   - Match first: if the error is the same CLASS as an existing slug, REUSE it
     verbatim; mint a new slug only if none fits. Prefer these areas (mint a new
     one only if none truly fits): `article preposition agreement tense modal
     conditional verb-complement word-form word-order countability pronoun
     conjunction negation comparison possessive punctuation`.
   Then record it with ONE call:
   `python3 "${CLAUDE_SKILL_DIR}/../../db.py" grammar record "<slug>" "<problem>" "<original>" "<fixed>" "<rule>"`
   where `problem` is a short description of the error class, `original` the user's
   wording, `fixed` the correction, `rule` the short rule. Don't invent errors —
   only record genuine ones. When a value contains `\`, `"`, `` ` `` or `$`,
   backslash-escape it inside the quoted arg so bash passes it literally.
5. Print exactly one line and nothing else:
   `OK grammar: <N> incremented, <M> inserted` — counting the `incremented` /
   `inserted` results from step 4 (or `OK grammar: nothing found` if there were no
   findings).
