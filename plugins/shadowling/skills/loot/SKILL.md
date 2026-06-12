---
name: loot
description: "Add words/terms you're learning, auto-translated into your native language. Comma-separated for several at once. Usage: /loot <word>[, <word2>, ...]"
context: fork
agent: claude
model: sonnet
allowed-tools: Bash(python3 */config.py*) Bash(python3 */vocab.py*)
---

You translate the given terms and add them to the vocab store. Add everything you
are given — do NOT ask, do NOT block on typos.

The plugin's scripts live at `${CLAUDE_SKILL_DIR}/../..`; invoke them directly so
each command starts with `python3` (e.g.
`python3 "${CLAUDE_SKILL_DIR}/../../config.py" get first_language`).

Terms (comma-separated): `$ARGUMENTS`

Steps:

1. Run `python3 "${CLAUDE_SKILL_DIR}/../../config.py" get first_language`. If it
   FAILS (non-zero exit), reply that shadowling is not configured — tell the user
   to run `/shadowling:setup` first — and stop.
2. Split `$ARGUMENTS` on commas, trim each, drop empties. Keep multi-word phrases
   whole (`machine learning` is one term).
3. Translate each term INTO the language from step 1 — one short word or phrase,
   in the target language only, never explanation or transliteration. Use natural,
   standard usage in that language; prefer the common dictionary form over calques,
   loanwords, slang, or other non-standard variants. Near-synonyms may share the
   same translation — do NOT invent an artificial variant just to make entries
   differ. The translation MUST differ from the source term; never echo the term back.
4. One call: `python3 "${CLAUDE_SKILL_DIR}/../../vocab.py" add "<term1>" "<tr1>" "<term2>" "<tr2>" ...`.
   When interpolating a value into the quoted args, backslash-escape any `\`, `"`,
   `` ` `` or `$` it contains so bash passes it literally.
5. Report the per-word results (the script prints `add`/`refresh`/`relearn`; it
   prints `untranslated` and skips a row if a translation was missing/identical —
   if so, say it couldn't be translated and suggest re-running).
6. For any term that looks like an OBVIOUS misspelling of a common word (be
   conservative — don't flag intentional phrases, technical/proper nouns, or real
   but uncommon words), append a hint AFTER the results, e.g.:
   "⚠️ `asesome` looks like a typo of `awesome`. To fix it:
   `/drop asesome` then `/loot awesome`."
   This is only a hint — the term was still added.

Do NOT gloss anything in your reply.
