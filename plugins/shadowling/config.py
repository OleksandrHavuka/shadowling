#!/usr/bin/env python3
"""config.py - plugin-wide language/config CLI for shadowling (stdlib only).

Language is a cross-cutting concern (used by vocab glossing, en-review, and future
features), so it lives here at the plugin level rather than inside vocab.py.
Thin CLI over core.load_config / core.save_config.
"""
import sys

from core import raw_config, register_script_path, save_config


def main(argv):
    register_script_path()
    if not argv:
        print("usage: config.py {lang|set-lang} ...", file=sys.stderr)
        return 1
    cmd = argv[0]
    if cmd == "lang":
        # Print native_language only if it's EXPLICITLY set in the file (not the
        # built-in default). Empty output is the first-run signal callers rely on,
        # so a missing/empty/malformed config correctly triggers setup.
        value = raw_config().get("native_language")
        if isinstance(value, str) and value.strip():
            print(value.strip())
        return 0
    if cmd == "set-lang":
        if len(argv) < 2 or not argv[1].strip():
            print('usage: config.py set-lang "<language>"', file=sys.stderr)
            return 1
        cfg = save_config({"native_language": argv[1]})
        print("native_language = {0}".format(cfg["native_language"]))
        return 0
    print("unknown command: {0}".format(cmd), file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
