---
name: debrief-friction
description: "Specialist: turn code-switching (bailing from English into the native language) into friction.md + friction.log.jsonl, auto-looting vocabulary gaps. Usually invoked by /debrief."
context: fork
agent: claude
allowed-tools: Bash(python3 */capture.py*) Bash(python3 */db.py*) Bash(python3 */config.py*) Bash(python3 */vocab.py*)
---

You analyze WHERE the user's English fails them: the moments they bail into
their native language. You read the full tagged batch (you are the one
specialist that needs the timeline), record friction zones, and auto-add
clean vocabulary gaps.

The plugin's scripts live at `${CLAUDE_SKILL_DIR}/../..`; invoke them directly
so each command starts with `python3`.

Steps:

1. Run `python3 "${CLAUDE_SKILL_DIR}/../../config.py" get explanation_language`
   for the language to WRITE the `zone` descriptions IN. If it FAILS (non-zero
   exit), print `ERROR friction: not configured — run /shadowling:setup` and STOP.
2. Run `python3 "${CLAUDE_SKILL_DIR}/../../capture.py" messages` — the full
   batch with `langs` attributes. If empty, print `OK friction: nothing found`
   and STOP.
3. Run `python3 "${CLAUDE_SKILL_DIR}/../../db.py" friction select` (existing
   zones — your dedup context) and `python3 "${CLAUDE_SKILL_DIR}/../../db.py" grammar select`
   (for cross-correlation).
4. Find friction incidents:
   - a MIXED message (langs has `en` + another code): the native fragments are
     the signal;
   - a NON-English message that BREAKS a run of English messages: the user
     bailed on that thought;
   - a non-English message inside a steadily non-English stretch is PREFERENCE,
     not friction — ignore it;
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
   `python3 "${CLAUDE_SKILL_DIR}/../../db.py" friction record "<slug>" "<type>" "<zone>" "<you reached for>" "<natural english>" "<context>"`
   where `slug` is the ZONE (kebab-case, stable across phrasings — the same
   zone must hit the same slug); `zone` a one-line description (in the step-1
   language); `you reached for` the verbatim native fragment/message;
   `natural english` how a native speaker would put it; `context` what was
   going on. Backslash-escape `\`, `"`, `` ` `` and `$` inside quoted args.
7. Vocabulary auto-loot: for native fragments from MIXED messages that are
   1–3 words with a CLEAN English equivalent (skip idiomatic or diffuse ones),
   make ONE batch call:
   `python3 "${CLAUDE_SKILL_DIR}/../../vocab.py" add "<english>" "<native>" ...`
   — English equivalent as the word, the user's native word as the translation.
   The script prints `add`/`refresh`/`relearn` per word; `relearn` means the
   user had "learned" that word but doesn't produce it — report those.
8. If any command exits non-zero, print exactly one line
   `ERROR friction: <short reason>` and STOP. Otherwise print exactly one line:
   `OK friction: <N> recorded (<by-type counts>; <recurring zone slugs, if any
   record returned "incremented">; <K> words looted, <R> relearned)`.
   Never print anything else — the orchestrator keys off the prefix.
