---
description: Add a word/term you're learning (auto-translated to your native language), or remove one. Usage: /vocab <word>  |  /vocab remove <word>
---

Manage the user's lexigloss vocabulary list. Raw arguments: `$ARGUMENTS`

Data lives in `~/.lexigloss/` (override with `VOCAB_HOME`). The bundled script's
path is recorded by the plugin's hooks at `~/.lexigloss/.script_path`; resolve it
inline in each command with:
`"$(cat "${VOCAB_HOME:-$HOME/.lexigloss}/.script_path" 2>/dev/null || echo "${CLAUDE_PLUGIN_ROOT}/vocab.py")"`

Follow these rules exactly:

1. **First-run language setup.** If `${VOCAB_HOME:-$HOME/.lexigloss}/config.json`
   does NOT exist, ask the user once: "What's your native language — the language
   to translate words INTO?" Then create the file with their answer:
   `mkdir -p "${VOCAB_HOME:-$HOME/.lexigloss}" && printf '{\n  "native_language": "<answer>"\n}\n' > "${VOCAB_HOME:-$HOME/.lexigloss}/config.json"`
   Then continue.

2. If `$ARGUMENTS` begins with `remove ` followed by a word, run:
   `python3 "$(cat "${VOCAB_HOME:-$HOME/.lexigloss}/.script_path" 2>/dev/null || echo "${CLAUDE_PLUGIN_ROOT}/vocab.py")" remove "<word>"`
   Then report whether it was removed.

3. Otherwise treat the ENTIRE `$ARGUMENTS` as one word/term the user wants to learn:
   a. Read `${VOCAB_HOME:-$HOME/.lexigloss}/config.json` for `native_language`.
   b. Produce a concise, natural translation of the word INTO that native language
      — one short word or phrase, no explanation, no transliteration.
   c. Run (quote both args; the translation may contain spaces and non-ASCII):
      `python3 "$(cat "${VOCAB_HOME:-$HOME/.lexigloss}/.script_path" 2>/dev/null || echo "${CLAUDE_PLUGIN_ROOT}/vocab.py")" add "<word>" "<translation>"`
   d. Confirm: show the stored word, its translation, and the remaining count.

Do NOT gloss anything in this confirmation message itself — this message is about
the word, not a normal reply.
