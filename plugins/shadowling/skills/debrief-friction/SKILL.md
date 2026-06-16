---
name: debrief-friction
description: "Specialist: turn code-switching (bailing from the learning language into the native language) into the friction dataset, auto-looting vocabulary gaps. Usually invoked by /debrief."
context: fork
agent: claude
allowed-tools: Bash(python3 */friction.py*) Bash(python3 */config.py*)
---

You analyze WHERE the user's learning language fails them: the moments they bail
into their native language. You read the full tagged batch (you are the one
specialist that needs the timeline), record friction zones, and auto-add
clean vocabulary gaps.

This skill's entrypoint is `${CLAUDE_SKILL_DIR}/friction.py` (in this skill dir);
the shared `config.py` is at `${CLAUDE_PLUGIN_ROOT}/config.py`. Invoke each as
a single Bash call that begins with `python3` and the full path — the only shape
the granted `Bash(python3 …)` permission matches (so nothing before it and no
chaining).

The session to analyze arrives as your invocation argument — a session id
string. Use it as `<session-id>` in the commands below; analyze ONLY that
session.

Steps:

1. Run `python3 "${CLAUDE_PLUGIN_ROOT}/config.py" show`.
   Refer to the learning language by its ISO 639-1 code (English → `en`,
   German → `de`, …) when reading the `<langs>` element below.
2. Run `python3 "${CLAUDE_SKILL_DIR}/friction.py" messages --session "<session-id>"` — the full
   batch as `<messages><row><id>N</id><text>…</text><langs>…</langs></row>…</messages>`
   (`<langs>` is the JSON array of language codes, with the quotes escaped as
   `[&quot;en&quot;,&quot;uk&quot;]`; empty when not yet triaged). If it
   prints `<messages></messages>`, print `OK friction: nothing found` and STOP.
3. Run `python3 "${CLAUDE_SKILL_DIR}/friction.py" select` (existing
   zones — your dedup context) and `python3 "${CLAUDE_SKILL_DIR}/friction.py" grammar-select`
   (for cross-correlation).
4. Find friction incidents (let `<L>` be the learning-language code):
   - a MIXED message (langs has `<L>` + another code): the native fragments are
     the signal;
   - a message NOT in the learning language that BREAKS a run of learning-language
     messages: the user bailed on that thought;
   - a non-learning-language message inside a steadily non-learning-language
     stretch is PREFERENCE, not friction — ignore it;
   - ignore `und` rows and rows with an empty `<langs>` element (not yet
     triaged — next batch's business).
5. Classify each incident's `type`:
   `lexical` (one missing word) / `phrasal` (missing idiom or collocation) /
   `structural` (sentence broke at a grammar construction — name it) /
   `topical` (whole messages flip on a recurring subject) /
   `register` (flip where tone was needed: polite pushback, humor, nuance).
   For `structural` zones, check the grammar slugs from step 3 — if the same
   construction already has a high counter there, say so in the `zone` text
   ("also a frequent grammar error — confirmed avoidance").
6. For EACH incident, ONE call. Put each value between its tags VERBATIM (values
   may span lines; never escape anything — the quoted `<<'SL_IN'` stops the shell).
   The body and the closing `SL_IN` MUST start at column 0:

```bash
python3 "${CLAUDE_SKILL_DIR}/friction.py" record <<'SL_IN'
<slug>the ZONE as a kebab-case slug, stable across phrasings</slug>
<type>lexical / phrasal / structural / topical / register</type>
<zone>a one-line description (in the explanation language)</zone>
<learner_wrote>the verbatim native fragment/message the user reached for</learner_wrote>
<native_phrase>how a native speaker of the learning language would put it</native_phrase>
<context>what was going on</context>
SL_IN
```
   The same zone must hit the same `slug`.
7. Vocabulary auto-loot: for native fragments from MIXED messages that are
   1–3 words with a CLEAN learning-language equivalent (skip idiomatic or diffuse
   ones), make ONE batch call. One pair per line, the two columns separated by a
   single TAB (column 1 = the learning-language equivalent, column 2 = the user's
   native word). The body and the closing `SL_IN` MUST start at column 0:

```bash
python3 "${CLAUDE_SKILL_DIR}/friction.py" loot <<'SL_IN'
<items>
learning-language word or phrase	the user's native-language word
another learning-language term	its native-language word
</items>
SL_IN
```
   The script prints `add`/`refresh`/`relearn` per word; `relearn` means the
   user had "learned" that word but doesn't produce it — report those.
8. If any command exits non-zero, print exactly one line
   `ERROR friction: <short reason>` and STOP. Otherwise print exactly one line:
   `OK friction: <N> recorded (<by-type counts>; <recurring zone slugs, if any
   record returned "incremented">; <K> words looted, <R> relearned)`.
   Never print anything else — the orchestrator keys off the prefix.
