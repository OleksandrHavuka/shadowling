#!/usr/bin/env python3
"""skills/drop/drop.py - thin entrypoint for /drop: remove vocab words.
Each arg is a word to delete via the Vocab repository. No SQL here."""

import os
import sys


def main(argv):
    sys.path.insert(
        0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
    )
    from models.vocab import Vocab
    from skillio import render

    if not argv or argv[0] != "remove":
        print('usage: drop.py remove "<word>" ["<word>" ...]', file=sys.stderr)
        return 1
    words = argv[1:]
    if not words:
        print('usage: drop.py remove "<word>" ["<word>" ...]', file=sys.stderr)
        return 1
    out = [
        {"word": word, "outcome": "removed" if Vocab.remove(word) else "not found"}
        for word in words
    ]
    print(f"<result>{render(out)}</result>")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
