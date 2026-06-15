#!/usr/bin/env python3
"""skills/loot/loot.py - thin entrypoint for /loot: add vocab pairs.
Reads an <items> TSV (word<TAB>translation per line) from stdin and adds each via
the Vocab repository. The /loot skill gates on config (config.py show) before
calling this. No SQL here."""

import os
import sys


def main(argv):
    sys.path.insert(
        0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
    )
    from cliutil import format_loot_line
    from models.vocab import Vocab
    from tagio import read_fields, rows

    if not argv or argv[0] != "add":
        print(
            "usage: loot.py add (word<TAB>translation lines in an "
            "<items>...</items> tag on stdin)",
            file=sys.stderr,
        )
        return 1
    try:
        looted = read_fields({"items": rows("word", "translation")})["items"]
    except ValueError as e:
        print("error: " + str(e), file=sys.stderr)
        return 1
    if not looted:
        print(
            "usage: loot.py add (word<TAB>translation lines in an "
            "<items>...</items> tag on stdin)",
            file=sys.stderr,
        )
        return 1
    for item in looted:
        action, row = Vocab.add(item["word"], item["translation"])
        print(format_loot_line(action, row))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
