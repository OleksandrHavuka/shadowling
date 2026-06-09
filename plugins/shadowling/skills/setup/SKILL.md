---
name: setup
description: "Set up shadowling's language — the native language words and corrections are translated into. Usage: /shadowling:setup"
allowed-tools: Bash(python3 */config.py*)
---

Configure the plugin-wide language (used by vocab glossing, debrief, and other
features).

The plugin's scripts live at `${CLAUDE_SKILL_DIR}/../..`; invoke them directly so
each command starts with `python3` (e.g.
`python3 "${CLAUDE_SKILL_DIR}/../../config.py" set-lang "<answer>"`).

Steps:

1. Ask the user with `AskUserQuestion`: "What's your native language — the one to
   translate words and corrections INTO?"
2. Run `python3 "${CLAUDE_SKILL_DIR}/../../config.py" set-lang "<answer>"`.
3. Confirm the language that was set.

Do NOT gloss anything in your reply.
