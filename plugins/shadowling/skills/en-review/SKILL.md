---
name: en-review
description: "Analyze your buffered English messages into personal learning docs (grammar / rephrasings / idioms / irregular verbs). Usage: /en-review"
context: fork
agent: claude
model: sonnet
allowed-tools: Bash(python3 *)
---

You run as an isolated subagent, so the buffer, the existing-doc keys, and your
analysis reasoning stay out of the main conversation — only your final summary
returns. Do the whole analysis here yourself.

Resolve the plugin script dir once:

```
DIR="$(dirname "$(cat "${SHADOWLING_HOME:-$HOME/.shadowling}/.script_path" 2>/dev/null)")"
```

Steps:

1. Run `python3 "$DIR/capture.py" pending-count`. If it prints `0`, tell the user
   there's nothing to review and STOP.

2. Get `native_language` via `python3 "$DIR/config.py" lang` (default `Ukrainian`
   if it prints nothing), and today's date via `date +%F`.

3. Run `python3 "$DIR/capture.py" dump` to read `<pending>` (messages to analyze)
   and `<existing>` (keys already recorded per doc).

4. Analyze each pending entry. For every finding **whose normalized key is not
   already in `<existing>`**, append a row via
   `python3 "$DIR/capture.py" add-row <doc> <col1> <col2> ...` with columns in this
   order (`date` = today's date). Only write categories that have findings:
   - `grammar` — date, original, fixed, rule  *(also articles, prepositions, false friends)*
   - `rephrasings` — date, "yours", "natural", why  *(natural-sounding native phrasing / collocations; add a `native_language` gloss in `why` if helpful)*
   - `idioms` — date, context, idiom, meaning (in `native_language`), "you wrote"
   - `irregular_verbs` — base, past, past-participle, example-fix, date  *(when a misused or noteworthy irregular verb appears)*
   `add-row` already skips exact-key duplicates; `<existing>` is so you avoid
   proposing near-duplicates too. Don't invent corrections — only record real
   issues or genuinely apt idioms.

5. Run `python3 "$DIR/capture.py" clear`.

6. Return ONLY a compact summary: how many entries were processed and the
   `added`/`dup` counts per doc. No reasoning, no doc contents, no gloss.
