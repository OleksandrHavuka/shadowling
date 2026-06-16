#!/usr/bin/env python3
"""skills/tutor/tutor.py - thin entrypoint for /tutor: deck / record / stats.
deck and stats print JSON per row/object; record reads the learner's answer from
an <answer> tag on stdin (verbatim) and calls the Tutor repository. No SQL here."""

import json
import os
import sys


def main(argv):
    sys.path.insert(
        0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
    )
    from models.tutor import SIZE_DEFAULT, Tutor
    from skillio import TEXT, parse_size_arg, read_fields

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
        size = parse_size_arg(argv[1:], SIZE_DEFAULT)
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
