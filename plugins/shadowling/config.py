#!/usr/bin/env python3
"""config.py - plugin-wide language config CLI for shadowling (stdlib only).

Verbs:

  config.py show                 all keys as one <config> block (exit 1 + notice when
                                 unconfigured) — a skill reads every field it needs
                                 in ONE call instead of one `get` per field
  config.py get <key>            single value on stdout, or exit 1 when unconfigured
  config.py set <key> <value>

`show`/`get` double as the whole-plugin gate: a skill makes its one call and, on
failure, tells the user to run /shadowling:setup and stops.
"""

import sys

from core import CONFIG_KEYS, load_config, save_config
from skillio import render

USAGE = (
    "usage: config.py show | get <key> | set <key> <value>  (key: "
    + "|".join(CONFIG_KEYS)
    + ")"
)


def config_block(cfg):
    """The <config> block: every CONFIG_KEYS value rendered once inside
    <config>…</config>. The single shape both `config.py show` and the debrief
    driver emit, so a prompt's 'read the config languages' maps to one format."""
    return f"<config>{render([{k: cfg[k] for k in CONFIG_KEYS}])}</config>"


def main(argv):
    if argv and argv[0] == "show":
        cfg = load_config()
        if cfg["missing"]:  # same whole-plugin gate as `get`
            print(cfg["notice"], file=sys.stderr)
            return 1
        print(config_block(cfg))
        return 0
    if len(argv) < 2 or argv[0] not in ("get", "set") or argv[1] not in CONFIG_KEYS:
        print(USAGE, file=sys.stderr)
        return 1
    cmd, key = argv[0], argv[1]
    if cmd == "get":
        cfg = load_config()
        if cfg["missing"]:  # whole-plugin gate; the notice names the unset key(s)
            print(cfg["notice"], file=sys.stderr)
            return 1
        print(f"<config>{render([{key: cfg[key]}])}</config>")
        return 0
    if len(argv) != 3 or not argv[2].strip():
        print(USAGE, file=sys.stderr)
        return 1
    cfg = save_config({key: argv[2]})
    print(f"<config>{render([{key: cfg[key]}])}</config>")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
