#!/usr/bin/env python3
"""tutor.py - SHIM (uniform-DB refactor). Engine lives in models/tutor.py; this
keeps the deck/record/stats CLI until skills/tutor/tutor.py takes over (phase 3).
PROMPT_SQL is re-exported for traceability until Task 8 repoints it."""

import json
import sys

from models.tutor import PROMPT_SQL, SIZE_DEFAULT, Tutor  # noqa: F401
from tagio import TEXT, read_fields


def main(argv):
    if not argv:
        print(
            "usage: tutor.py {deck [--size N]|record <kind> <key>"
            " <exercise> <verdict>|stats}",
            file=sys.stderr,
        )
        return 1
    cmd = argv[0]
    if cmd == "record":
        if len(argv) != 5:
            print(
                "usage: tutor.py record <kind> <key> <exercise> <verdict>"
                " (answer in an <answer>...</answer> tag on stdin)",
                file=sys.stderr,
            )
            return 1
        try:
            answer = read_fields({"answer": TEXT})["answer"]
            print(Tutor.record(argv[1], argv[2], argv[3], argv[4], answer))
        except ValueError as e:
            print("error: " + str(e), file=sys.stderr)
            return 1
        return 0
    if cmd == "deck":
        size = SIZE_DEFAULT
        if len(argv) == 3 and argv[1] == "--size" and argv[2].isdigit():
            size = int(argv[2])
        for card in Tutor.deck(size):
            print(json.dumps(card, ensure_ascii=False))
        return 0
    if cmd == "stats":
        print(json.dumps(Tutor.stats(), ensure_ascii=False))
        return 0
    print("unknown command: " + cmd, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
