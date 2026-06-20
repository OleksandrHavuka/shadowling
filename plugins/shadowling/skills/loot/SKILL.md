---
name: loot
description: "Add words/terms you're learning, enriched (translation, examples, synonyms, definition) into your native/learning languages. Comma-separated for several at once. Usage: /loot <word>[, <word2>, ...]"
agent: claude
model: sonnet
allowed-tools: Bash(python3 */config.py*) Bash(python3 */loot.py*)
---

You enrich the given terms and add them to the vocab store. Add everything you are
given — do NOT ask, do NOT block on typos. This skill runs in the MAIN context so
you can read the conversation: that is where each word's real usage context lives.

The driver is `${CLAUDE_PLUGIN_ROOT}/loot.py`; the shared `config.py` is at
`${CLAUDE_PLUGIN_ROOT}/config.py`. Invoke each directly so the command starts with
`python3`.

Terms (comma-separated): `$ARGUMENTS`

Steps:

1. Run `python3 "${CLAUDE_PLUGIN_ROOT}/config.py" show` to confirm config exists.
   If it prints a setup notice, tell the user to run `/shadowling:setup` and stop.
2. Split `$ARGUMENTS` on commas, trim each, drop empties. Keep multi-word phrases
   whole (`machine learning` is one term). Lowercase each term.
3. For EACH term, harvest its **micro-context**: the single real sentence from THIS
   conversation where the term appeared (a short snippet, not a summary). If the
   term did not come from the conversation (an explicit ad-hoc add), use an empty
   string — the driver will generate a generic example.
4. ONE call. Pipe the words as a tagged `<items>` block on stdin via a quoted
   heredoc. One `<row>` per term: `<word>` is the term, `<ctx>` is its micro-context
   (use `<ctx></ctx>` when the term is an ad-hoc add with no conversation context).
   The body is **well-formed XML** — escape `&` as `&amp;`, `<` as `&lt;`, `>` as
   `&gt;` inside values; the quoted `<<'SL_IN'` handles quotes/`$`/backticks. The
   body and the closing `SL_IN` MUST start at column 0:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/loot.py" <<'SL_IN'
   <items>
   <row><word>throughput</word><ctx>We boosted throughput under load.</ctx></row>
   <row><word>idempotent</word><ctx></ctx></row>
   </items>
   SL_IN
   ```
5. Relay the driver's summary line verbatim (`N/M enriched; re-run /loot to retry …`
   if any stayed pending). If it printed a config notice, point the user at
   `/shadowling:setup`.

Do NOT gloss anything in your reply.
