---
description: "Analyze your buffered English messages into personal learning docs (grammar / rephrasings / idioms / irregular verbs). Usage: /en-review"
---

Turn the user's buffered English messages into curated learning docs. The analysis
runs in a **subagent** so the buffer, the existing-doc keys, and the analysis
reasoning never enter this conversation's context — only a short summary returns.

Resolve the capture script path once (used below):
`CAP="$(dir="$(dirname "$(cat "${SHADOWLING_HOME:-$HOME/.shadowling}/.script_path" 2>/dev/null)")"; echo "${dir:-${CLAUDE_PLUGIN_ROOT}}/capture.py")"`

Follow these steps exactly:

1. **Cheap empty check (no context pollution).** Run:
   `python3 "$CAP" pending-count`
   If it prints `0`, tell the user there's nothing to review and STOP. Do **not**
   run `dump` yourself and do **not** launch a subagent.

2. Otherwise read `native_language` from
   `${SHADOWLING_HOME:-$HOME/.shadowling}/config.json` (default `Ukrainian` if missing),
   and get today's date (`date +%F`).

3. **Launch ONE subagent** (Task tool, `subagent_type: general-purpose`). Pass it
   ONLY these scalars in the prompt — never any message text, never run `dump`
   yourself:
   - the absolute path to `capture.py` (the resolved `$CAP`)
   - today's date (`YYYY-MM-DD`)
   - the user's `native_language`

   The subagent prompt MUST instruct it to:
   1. Run `python3 <capture.py> dump` to read `<pending>` (messages to analyze)
      and `<existing>` (keys already recorded per doc).
   2. Analyze each pending entry. For every finding **whose normalized key is not
      already in `<existing>`**, append a row via
      `python3 <capture.py> add-row <doc> <col1> <col2> ...` with columns in this
      order (`date` = the passed date). Only write categories that have findings:
      - `grammar` — date, original, fixed, rule  *(also articles, prepositions, false friends)*
      - `rephrasings` — date, "yours", "natural", why  *(natural-sounding native phrasing / collocations; add a `native_language` gloss in `why` if helpful)*
      - `idioms` — date, context, idiom, meaning (in `native_language`), "you wrote"
      - `irregular_verbs` — base, past, past-participle, example-fix, date  *(when a misused or noteworthy irregular verb appears)*
      `add-row` already skips exact-key duplicates; `<existing>` is so you avoid
      proposing near-duplicates too. Don't invent corrections — only record real
      issues or genuinely apt idioms.
   3. Run `python3 <capture.py> clear`.
   4. Return ONLY a compact summary: how many entries were processed and the
      `added`/`dup` counts per doc. No reasoning, no doc contents.

4. Relay the subagent's summary to the user verbatim-ish (brief). Do **not** gloss
   anything in this message — it's an operational report, not a normal reply.
