---
name: debrief
description: "Review your buffered writing into per-category frequency docs (grammar / rephrasings / idioms / verbs). Usage: /debrief"
allowed-tools: Bash(python3 */debrief.py*)
---

Run the deterministic debrief driver as a SINGLE Bash call that begins with
`python3` and the full path — the only shape the granted `Bash(python3 …)`
permission matches (so nothing before it and no chaining):

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/debrief.py"
```

The driver does everything itself — marks drills, triages each session's
languages, runs the five analytical specialists per session, and persists each
session's findings atomically. It streams progress live (flushed) so the run
never goes dark: a `marked N drill(s); reviewing N session(s)` header, then one
`[i/N] <session> … OK` / `[i/N] <session> … OK (empty)` / `[i/N] <session> …
ERROR <categories>` line per session as each completes, then a totals line.

Relay that summary to the user as-is. If any session shows `ERROR`, tell the user
that a re-run of `/debrief` retries only the failed sessions. If the driver exits
non-zero with a config notice, point the user at `/shadowling:setup`. Do not add
analysis or doc contents of your own — the driver is the source of truth.
