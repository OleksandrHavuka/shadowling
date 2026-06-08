---
name: setup
description: "Set up shadowling's language — the native language words and corrections are translated into. Usage: /shadowling:setup"
allowed-tools: Bash(python3 *)
---

Configure the plugin-wide language (used by vocab glossing, en-review, and other
features).

Resolve the plugin script dir once:

```
DIR="$(dirname "$(cat "${SHADOWLING_HOME:-$HOME/.shadowling}/.script_path" 2>/dev/null)")"
```

Steps:

1. Ask the user with `AskUserQuestion`: "What's your native language — the one to
   translate words and corrections INTO?"
2. Run `python3 "$DIR/config.py" set-lang "<answer>"`.
3. Confirm the language that was set.

Do NOT gloss anything in your reply.
