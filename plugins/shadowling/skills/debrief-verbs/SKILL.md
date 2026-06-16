---
name: debrief-verbs
description: "Specialist: collect misused/noteworthy irregular verbs from your buffered writing into the irregular-verbs dataset. Usually invoked by /debrief."
context: fork
agent: claude
model: sonnet
allowed-tools: Bash(python3 */verbs.py*) Bash(python3 */config.py*)
---

You are the IRREGULAR-VERBS specialist. You run as an isolated subagent — only
your final one-line status returns. This skill's entrypoint is
`${CLAUDE_SKILL_DIR}/verbs.py` (in this skill dir); the shared `config.py` is at
`${CLAUDE_PLUGIN_ROOT}/config.py`. Invoke each as a single Bash call that
begins with `python3` and the full path — the only shape the granted
`Bash(python3 …)` permission matches (so nothing before it and no chaining).

The session to analyze arrives as your invocation argument — a session id
string. Use it as `<session-id>` in the commands below; analyze ONLY that
session.

Steps:

1. Run `python3 "${CLAUDE_PLUGIN_ROOT}/config.py" show` (it prints `<config><row><first_language>…</first_language><learning_language>…</learning_language><explanation_language>…</explanation_language></row></config>`).
   The verb forms, `used_form`, `correction`, and `context` stay in the learning language regardless.
2. Run `python3 "${CLAUDE_SKILL_DIR}/verbs.py" messages --session "<session-id>" --lang <code>`,
   where `<code>` is the lowercase ISO 639-1 code of the learning language
   (English → `en`, German → `de`, Spanish → `es`, …). If it prints
   `<messages></messages>` (empty), print `OK verbs: nothing found` and STOP.
   If a listed message turns out not to be learning-language prose (a mis-tag),
   skip it — never analyze text in another language.
3. Run `python3 "${CLAUDE_SKILL_DIR}/verbs.py" select`. It prints
   `<verbs><row><verb>…</verb>…</row>…</verbs>`; collect the existing `<verb>`
   values — your dedup context.
4. Read every `<row>` (each is `<row><id>N</id><text>…</text></row>`) and find misused or otherwise noteworthy IRREGULAR
   verbs (e.g. a wrong form like English `I have went`, `I buyed`). The key is the
   verb base form (lowercase, e.g. `go`); reuse an existing key for the same verb.
   Record each with ONE call. Put each value between its tags VERBATIM (values may
   span lines; never escape anything — the quoted `<<'SL_IN'` stops the shell). The
   body and the closing `SL_IN` MUST start at column 0:

```bash
python3 "${CLAUDE_SKILL_DIR}/verbs.py" record <<'SL_IN'
<verb>the base form</verb>
<past>the simple past</past>
<participle>the past participle</participle>
<used_form>the wrong form the user actually wrote</used_form>
<correction>the fixed version</correction>
<context>a short excerpt of where it appeared (useful for drills)</context>
SL_IN
```
   The call prints `<result><row><status>inserted|incremented</status></row></result>`;
   count the `inserted`/`incremented` statuses for the OK line.
   Only record genuine irregular-verb issues.
5. Print exactly one line and nothing else:
   `OK verbs: <N> incremented, <M> inserted` (or `OK verbs: nothing found`).
6. If ANY command fails (non-zero exit, missing/garbled output) or you cannot finish
   a step, print exactly ONE line instead of the OK line:
   `ERROR verbs: <short reason>` — name the step/command that failed and include the
   key error text (e.g. `ERROR verbs: verbs.py record failed — <stderr>`). Never print a
   partial or blank status; the orchestrator keys off the `OK `/`ERROR ` prefix and
   keeps the buffer for a retry on `ERROR `.
