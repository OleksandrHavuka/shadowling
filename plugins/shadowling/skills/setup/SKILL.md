---
name: setup
description: "Set up shadowling's three languages — native (translations), learning (what you study), and explanation (corrections). Required before first use. Usage: /shadowling:setup"
allowed-tools: Bash(python3 */config.py*)
---

Configure the three plugin-wide languages. ALL are required — the plugin refuses
to work until they are set.

The plugin's scripts live at `${CLAUDE_PLUGIN_ROOT}`; invoke them directly so
each command starts with `python3`.

Steps:

1. Ask the user with `AskUserQuestion`: "What's your native language — the one
   words and corrections are translated INTO?"
2. Run `python3 "${CLAUDE_PLUGIN_ROOT}/config.py" set first_language "<answer>"`.
3. Ask the user with `AskUserQuestion`: "What language are you learning? — the
   one your messages get analyzed and drilled in." Do NOT offer a default; let
   the user name it.
4. Run `python3 "${CLAUDE_PLUGIN_ROOT}/config.py" set learning_language "<answer>"`.
5. Ask the user with `AskUserQuestion`: "What language should explanations
   (meanings, rules, takeaways) be written in?" Offer the answer from step 3
   (learning language) and the answer from step 1 (native language) as options.
6. Run `python3 "${CLAUDE_PLUGIN_ROOT}/config.py" set explanation_language "<answer>"`.
7. Confirm all three saved values to the user.

Do NOT gloss anything in your reply.
