---
name: loot
description: "Add words/terms you're learning, enriched (translation, alternative translations, examples, synonyms, definition) into your native/learning languages. Comma-separated for several at once. Usage: /loot <word>[, <word2>, ...]"
agent: claude
allowed-tools: Bash(python3 */loot.py*)
---

You enrich the given terms and add them to the vocab store. Add everything you are
given — do NOT ask, do NOT block on typos. This skill runs in the MAIN context so
you can read the conversation: that is where each word's real usage context lives.

The driver is `${CLAUDE_PLUGIN_ROOT}/loot.py`. Invoke it directly so the command
starts with `python3`. It gates on config itself — if config is missing it prints a
setup notice and exits non-zero; just relay that (step 4).

Terms (comma-separated): `$ARGUMENTS`

Steps:

1. Split `$ARGUMENTS` on commas, trim each, drop empties. Keep multi-word phrases
   whole (`machine learning` is one term). Lowercase each term.
2. For EACH term separately, decide its **micro-context** `<ctx>` — a short real
   snippet from THIS conversation that *illustrates how that term was actually used*
   (enough to show its meaning in this context), authored fresh per term. Include
   `<ctx>` ONLY when the conversation genuinely holds such a usage for that specific
   term; a sentence that merely contains the token, or no real encounter at all,
   does NOT qualify. When in doubt, or for an ad-hoc add, OMIT the `<ctx>` tag
   entirely — the driver then generates a generic example.
3. ONE call. Pipe the words as a tagged `<items>` block on stdin via a quoted
   heredoc. One `<row>` per term: `<word>` is the term; add a `<ctx>` child ONLY
   when you have a genuine usage snippet for it, otherwise omit the tag. The body is
   **well-formed XML** — escape `&` as `&amp;`, `<` as `&lt;`, `>` as `&gt;` inside
   values; the quoted `<<'SL_IN'` handles quotes/`$`/backticks. The body and the
   closing `SL_IN` MUST start at column 0:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/loot.py" <<'SL_IN'
   <items>
   <row><word>throughput</word><ctx>We boosted throughput under load.</ctx></row>
   <row><word>idempotent</word></row>
   </items>
   SL_IN
   ```
4. Relay the driver's summary line verbatim (`N/M enriched; re-run /loot to retry …`
   if any stayed pending). If it printed a config notice instead, point the user at
   `/shadowling:setup`.

Do NOT gloss anything in your reply.
