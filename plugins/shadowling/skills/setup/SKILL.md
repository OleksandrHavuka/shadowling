---
name: setup
description: "Set up shadowling's two languages — native (translations) and explanation (corrections). Required before first use. Usage: /shadowling:setup"
allowed-tools: Bash(python3 */config.py*)
---

Configure the two plugin-wide languages. BOTH are required — the plugin refuses
to work until they are set.

The plugin's scripts live at `${CLAUDE_SKILL_DIR}/../..`; invoke them directly so
each command starts with `python3`.

Steps:

1. Ask the user with `AskUserQuestion`: "What's your native language — the one
   words and corrections are translated INTO?"
2. Run `python3 "${CLAUDE_SKILL_DIR}/../../config.py" set first_language "<answer>"`.
3. Ask the user with `AskUserQuestion`: "What language should explanations
   (meanings, rules, takeaways) be written in?" Offer `English` and the answer
   from step 1 as the options.
4. Run `python3 "${CLAUDE_SKILL_DIR}/../../config.py" set explanation_language "<answer>"`.
5. Confirm both saved values to the user.

Do NOT gloss anything in your reply.
