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
`python3 "${CLAUDE_SKILL_DIR}/../../config.py" show`).

Terms (comma-separated): `$ARGUMENTS`

Steps:

1. Run `python3 "${CLAUDE_SKILL_DIR}/../../config.py" show`. You translate the
   terms into `first_language`.
2. Split `$ARGUMENTS` on commas, trim each, drop empties. Keep multi-word phrases
   whole (`machine learning` is one term).
3. Translate each term INTO the language from step 1 — one short word or phrase,
   in the target language only, never explanation or transliteration. Use natural,
   standard usage in that language; prefer the common dictionary form over calques,
   loanwords, slang, or other non-standard variants. Near-synonyms may share the
   same translation — do NOT invent an artificial variant just to make entries
   differ. The translation MUST differ from the source term; never echo the term back.
4. One call. One pair per line, the two columns separated by a single TAB
   (column 1 = the term, column 2 = its translation) — never escape anything, the
   quoted `<<'SL_IN'` passes every char literally. The body and the closing `SL_IN`
   MUST start at column 0:

```bash
python3 "${CLAUDE_SKILL_DIR}/../../vocab.py" add <<'SL_IN'
<items>
the term	its translation
another term	its translation
</items>
SL_IN
```
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
