#!/usr/bin/env python3
"""config.py - plugin-wide language config CLI for shadowling (stdlib only).

Two generic verbs over the two mandatory keys:

  config.py get <key>            value on stdout, or exit 1 when unconfigured
  config.py set <key> <value>

`get` doubles as the whole-plugin gate: a skill makes its one call and, on
failure, tells the user to run /shadowling:setup and stops.
"""
import sys

from core import CONFIG_KEYS, config_ready, load_config, save_config

USAGE = "usage: config.py {get|set} {" + "|".join(CONFIG_KEYS) + "} [<value>]"
NOT_CONFIGURED = "shadowling is not configured — run /shadowling:setup"


def main(argv):
    if len(argv) < 2 or argv[0] not in ("get", "set") or argv[1] not in CONFIG_KEYS:
        print(USAGE, file=sys.stderr)
        return 1
    cmd, key = argv[0], argv[1]
    if cmd == "get":
        cfg = load_config()
        if not config_ready(cfg):
            print(NOT_CONFIGURED, file=sys.stderr)
            return 1
        print(cfg[key])
        return 0
    if len(argv) != 3 or not argv[2].strip():
        print(USAGE, file=sys.stderr)
        return 1
    cfg = save_config({key: argv[2]})
    print("{0} = {1}".format(key, cfg[key]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
