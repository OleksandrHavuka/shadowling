---
name: reinstall
description: "Dev: force-reinstall the shadowling plugin from the local working tree into the Claude Code cache so you can test it by hand. Usage: /reinstall"
allowed-tools: Bash(claude plugin*) Edit
---

Force a clean reinstall of the plugin from the local marketplace so the running
cache reflects the current working tree (including uncommitted changes), then
remind the user to reload.

Steps:

1. Refresh the local marketplace source and reinstall clean:
   ```
   claude plugin marketplace update shadowling-lab
   claude plugin uninstall shadowling
   claude plugin install shadowling@shadowling-lab
   ```
   `uninstall` may report "not installed" — that is fine; the install is what matters.
2. The cache is keyed by version. If `install` serves a stale same-version copy
   (the code you changed isn't reflected), bump the patch in
   `plugins/shadowling/.claude-plugin/plugin.json` and rerun step 1.
3. Run `claude plugin list` to confirm the installed version.

Print exactly one line: the installed version, then
`run /reload-plugins or restart Claude Code to apply`. Nothing else — no analysis.
