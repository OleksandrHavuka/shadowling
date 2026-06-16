---
name: debrief-rephrasing
description: "Specialist: extract naturalness/phrasing fixes from your buffered writing into the rephrasing dataset. Usually invoked by /debrief."
context: fork
agent: claude
model: sonnet
allowed-tools: Bash(python3 */rephrasing.py*) Bash(python3 */config.py*)
---

You are the REPHRASING specialist (naturalness, not grammar correctness). You run
as an isolated subagent — only your final one-line status returns. This skill's
entrypoint is `${CLAUDE_SKILL_DIR}/rephrasing.py` (in this skill dir); the shared
`config.py` is at `${CLAUDE_PLUGIN_ROOT}/config.py`. Invoke each as a single
Bash call that begins with `python3` and the full path — the only shape the
granted `Bash(python3 …)` permission matches (so nothing before it and no
chaining).

The session to analyze arrives as your invocation argument — a session id
string. Use it as `<session-id>` in the commands below; analyze ONLY that
session.

Steps:

1. Run `python3 "${CLAUDE_PLUGIN_ROOT}/config.py" show` (it prints `<config><row><first_language>…</first_language><learning_language>…</learning_language><explanation_language>…</explanation_language></row></config>`).
   Write `problem` and `why` in the explanation language only — no other-language glosses.
2. Run `python3 "${CLAUDE_SKILL_DIR}/rephrasing.py" messages --session "<session-id>" --lang <code>`,
   where `<code>` is the lowercase ISO 639-1 code of the learning language
   (English → `en`, German → `de`, Spanish → `es`, …). If it prints
   `<messages></messages>` (empty), print `OK rephrasing: nothing found` and STOP.
   If a listed message turns out not to be learning-language prose (a mis-tag),
   skip it — never analyze text in another language.
3. Run `python3 "${CLAUDE_SKILL_DIR}/rephrasing.py" select`. It prints
   `<rephrasing><row><slug>…</slug>…</row>…</rephrasing>`; collect the existing
   `<slug>` values — your dedup context.
4. Read every `<row>` (each is `<row><id>N</id><text>…</text></row>`) and find phrasing that is grammatical but UNNATURAL
   (awkward collocations, calques, wrong register, wordiness). For each, derive a
   slug:
   - Slug format (HARD): the slug is ONE kebab-case token matching
     `^[a-z0-9]+(-[a-z0-9]+)*$` — all lowercase ASCII, words joined by single
     hyphens, NO spaces and NO underscores anywhere. Shape it as
     `<area>-<phenomenon>[-<refinement>]` (the area is one token from the list
     below, joined to the rest with a hyphen, never a space).
     Good: `word-choice-demonstrative-plural`, `collocation-make-vs-take-photo`,
     `register-too-formal-email`.
     Bad: `word-choice demonstrative-plural` (space), `Word_Choice`
     (caps + underscore), `calque--literal-translation` (double hyphen).
   - Match first: reuse an existing slug for the same class; mint only if none
     fits. Prefer these areas (mint a new one only if none truly fits):
     `collocation word-choice register wordiness phrasing calque idiomaticity`.
   Then record it with ONE call. Put each value between its tags VERBATIM (values
   may span lines; never escape anything — the quoted `<<'SL_IN'` stops the shell).
   The body and the closing `SL_IN` MUST start at column 0:

```bash
python3 "${CLAUDE_SKILL_DIR}/rephrasing.py" record <<'SL_IN'
<slug>the canonical kebab-case slug</slug>
<problem>short description of the class</problem>
<learner_wrote>the user's wording</learner_wrote>
<native_phrase>how a native speaker of the learning language would phrase it</native_phrase>
<why>a short reason written in the explanation language</why>
SL_IN
```
   The call prints `<result><row><status>inserted|incremented</status></row></result>`;
   count the `inserted`/`incremented` statuses for the OK line.
   Don't invent issues.
5. Print exactly one line and nothing else:
   `OK rephrasing: <N> incremented, <M> inserted` (or `OK rephrasing: nothing found`).
6. If ANY command fails (non-zero exit, missing/garbled output) or you cannot finish
   a step, print exactly ONE line instead of the OK line:
   `ERROR rephrasing: <short reason>` — name the step/command that failed and include
   the key error text (e.g. `ERROR rephrasing: rephrasing.py record failed — <stderr>`).
   Never print a partial or blank status; the orchestrator keys off the
   `OK `/`ERROR ` prefix and keeps the buffer for a retry on `ERROR `.
