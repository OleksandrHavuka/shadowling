#!/usr/bin/env python3
"""skills/debrief-idioms/idioms.py - thin entrypoint: record / select / messages."""

import json
import os
import sys


def main(argv):
    sys.path.insert(
        0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
    )
    from cliutil import parse_message_slice_args
    from models import idioms
    from models.messages import Messages
    from skillio import TEXT, read_fields

    if not argv:
        print("usage: idioms.py {record|select|messages} ...", file=sys.stderr)
        return 1
    op, args = argv[0], argv[1:]
    if op == "record":
        try:
            f = read_fields(
                {
                    "idiom": TEXT,
                    "meaning": TEXT,
                    "context": TEXT,
                    "learner_wrote": TEXT,
                }
            )
            print(
                idioms.record(
                    f["idiom"], f["meaning"], f["context"], f["learner_wrote"]
                )
            )
        except ValueError as e:
            print("error: " + str(e), file=sys.stderr)
            return 1
        return 0
    if op == "select":
        if args:
            row = idioms.Idioms.select(args[0])
            if row is not None:
                print(json.dumps(row, ensure_ascii=False))
        else:
            for row in idioms.Idioms.select():
                print(json.dumps(row, ensure_ascii=False))
        return 0
    if op == "messages":
        try:
            kwargs = parse_message_slice_args(args)
        except ValueError as e:
            print(str(e), file=sys.stderr)
            return 1
        print(Messages.list(**kwargs))
        return 0
    print("unknown op: " + op, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
