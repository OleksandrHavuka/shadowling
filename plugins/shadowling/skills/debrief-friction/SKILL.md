---
name: debrief-friction
description: "Specialist: turn code-switching (bailing from the learning language into the native language) into the friction dataset, auto-looting vocabulary gaps. Usually invoked by /debrief."
context: fork
agent: claude
allowed-tools: Bash(python3 */capture.py*) Bash(python3 */db.py*) Bash(python3 */config.py*) Bash(python3 */vocab.py*)
---

You analyze WHERE the user's learning language fails them: the moments they bail
into their native language. You read the full tagged batch (you are the one
specialist that needs the timeline), record friction zones, and auto-add
clean vocabulary gaps.

The plugin's scripts live at `${CLAUDE_SKILL_DIR}/../..`; invoke them directly
so each command starts with `python3`.

The session to analyze arrives as your invocation argument — a session id
string. Use it as `<session-id>` in the commands below; analyze ONLY that
session.

Steps:

1. Run `python3 "${CLAUDE_SKILL_DIR}/../../config.py" get learning_language` (the
   language the user is writing in — and bailing OUT of) and
   `python3 "${CLAUDE_SKILL_DIR}/../../config.py" get explanation_language`
   for the language to WRITE the `zone` descriptions IN. If EITHER FAILS (non-zero
   exit), print `ERROR friction: not configured (missing: <keys>) — run /shadowling:setup`
   and STOP, filling `<keys>` from config.py's `Missing required setting(s):` line.
   Refer to the learning language by its ISO 639-1 code (English → `en`,
   German → `de`, …) when reading the `langs` attributes below.
2. Run `python3 "${CLAUDE_SKILL_DIR}/../../capture.py" messages --session "<session-id>"` — the full
   batch with `langs` attributes. If empty, print `OK friction: nothing found`
   and STOP.
3. Run `python3 "${CLAUDE_SKILL_DIR}/../../db.py" friction select` (existing
   zones — your dedup context) and `python3 "${CLAUDE_SKILL_DIR}/../../db.py" grammar select`
   (for cross-correlation).
4. Find friction incidents (let `<L>` be the learning-language code):
   - a MIXED message (langs has `<L>` + another code): the native fragments are
     the signal;
   - a message NOT in the learning language that BREAKS a run of learning-language
     messages: the user bailed on that thought;
   - a non-learning-language message inside a steadily non-learning-language
     stretch is PREFERENCE, not friction — ignore it;
   - ignore `und` rows and rows with an empty `langs` attribute (not yet
     triaged — next batch's business).
5. Classify each incident's `type`:
   `lexical` (one missing word) / `phrasal` (missing idiom or collocation) /
   `structural` (sentence broke at a grammar construction — name it) /
   `topical` (whole messages flip on a recurring subject) /
   `register` (flip where tone was needed: polite pushback, humor, nuance).
   For `structural` zones, check the grammar slugs from step 3 — if the same
   construction already has a high counter there, say so in the `zone` text
   ("also a frequent grammar error — confirmed avoidance").
6. For EACH incident, ONE call:
   `python3 "${CLAUDE_SKILL_DIR}/../../db.py" friction record "<slug>" "<type>" "<zone>" "<learner_wrote>" "<native_phrase>" "<context>"`
   where `slug` is the ZONE (kebab-case, stable across phrasings — the same
   zone must hit the same slug); `zone` a one-line description (in the explanation
   language); `learner_wrote` the verbatim native fragment/message the user
   reached for; `native_phrase` how a native speaker of the learning language
   would put it; `context` what was going on. Backslash-escape `\`, `"`, `` ` ``
   and `$` inside quoted args.
7. Vocabulary auto-loot: for native fragments from MIXED messages that are
   1–3 words with a CLEAN learning-language equivalent (skip idiomatic or diffuse
   ones), make ONE batch call:
   `python3 "${CLAUDE_SKILL_DIR}/../../vocab.py" add "<word>" "<translation>" ...`
   — the learning-language equivalent as the `word`, the user's native word as the
   `translation`.
   The script prints `add`/`refresh`/`relearn` per word; `relearn` means the
   user had "learned" that word but doesn't produce it — report those.
8. If any command exits non-zero, print exactly one line
   `ERROR friction: <short reason>` and STOP. Otherwise print exactly one line:
   `OK friction: <N> recorded (<by-type counts>; <recurring zone slugs, if any
   record returned "incremented">; <K> words looted, <R> relearned)`.
   Never print anything else — the orchestrator keys off the prefix.
