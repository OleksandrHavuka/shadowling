---
name: vocab
description: "Add words/terms you're learning, auto-translated into your native language. Comma-separated for several at once. Usage: /vocab <word>[, <word2>, ...]"
context: fork
agent: claude
model: haiku
allowed-tools: Bash(python3 *)
---

You translate the given terms and add them to the vocab store. Add everything you
are given — do NOT ask, do NOT block on typos.

Resolve the plugin script dir once:

```
DIR="$(dirname "$(cat "${SHADOWLING_HOME:-$HOME/.shadowling}/.script_path" 2>/dev/null)")"
```

Terms (comma-separated): `$ARGUMENTS`

Steps:

1. Run `python3 "$DIR/config.py" lang`. If it prints nothing, reply that no
   language is set — tell the user to run `/shadowling:setup` first — and stop.
2. Split `$ARGUMENTS` on commas, trim each, drop empties. Keep multi-word phrases
   whole (`machine learning` is one term).
3. Translate each term INTO the language from step 1 — one short word or phrase,
   in the target language only, never explanation or transliteration. The
   translation MUST differ from the source term; never echo the term back.
4. One call: `python3 "$DIR/vocab.py" add "<term1>" "<tr1>" "<term2>" "<tr2>" ...`.
5. Report the per-word results (the script prints `add`/`refresh`/`relearn`; it
   prints `untranslated` and skips a row if a translation was missing/identical —
   if so, say it couldn't be translated and suggest re-running).
6. For any term that looks like an OBVIOUS misspelling of a common word (be
   conservative — don't flag intentional phrases, technical/proper nouns, or real
   but uncommon words), append a hint AFTER the results, e.g.:
   "⚠️ `asesome` looks like a typo of `awesome`. To fix it:
   `/vocab-remove asesome` then `/vocab awesome`."
   This is only a hint — the term was still added.

Do NOT gloss anything in your reply.
