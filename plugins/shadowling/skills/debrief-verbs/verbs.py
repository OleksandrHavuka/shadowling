#!/usr/bin/env python3
"""skills/debrief-verbs/verbs.py - thin entrypoint: record / select / messages."""

import json
import os
import sys


def main(argv):
    sys.path.insert(
        0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
    )
    from models import verbs
    from models.messages import Messages
    from skillio import TEXT, parse_message_slice_args, read_fields

    if not argv:
        print("usage: verbs.py {record|select|messages} ...", file=sys.stderr)
        return 1
    op, args = argv[0], argv[1:]
    if op == "record":
        try:
            f = read_fields(
                {
                    "verb": TEXT,
                    "past": TEXT,
                    "participle": TEXT,
                    "used_form": TEXT,
                    "correction": TEXT,
                    "context": TEXT,
                }
            )
            print(
                verbs.record(
                    f["verb"],
                    f["past"],
                    f["participle"],
                    f["used_form"],
                    f["correction"],
                    f["context"],
                )
            )
        except ValueError as e:
            print("error: " + str(e), file=sys.stderr)
            return 1
        return 0
    if op == "select":
        if args:
            row = verbs.Verbs.select(args[0])
            if row is not None:
                print(json.dumps(row, ensure_ascii=False))
        else:
            for row in verbs.Verbs.select():
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
