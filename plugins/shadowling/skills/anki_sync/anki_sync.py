#!/usr/bin/env python3
"""skills/anki_sync/anki_sync.py - thin entrypoint for /anki-sync.

Bootstraps the plugin root onto sys.path and delegates to anki.main(); no logic
or SQL here (the AnkiConnect transport + sync orchestration live in anki.py at the
root, where they're importable and unit-tested). Mirrors skills/drop/drop.py."""

import os
import sys


def main(argv):
    sys.path.insert(
        0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
    )
    from anki import main as anki_main

    return anki_main()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
