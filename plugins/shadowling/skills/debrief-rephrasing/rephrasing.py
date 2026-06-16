#!/usr/bin/env python3
"""skills/debrief-rephrasing/rephrasing.py - entrypoint: record / select / messages."""

import json
import os
import sys


def main(argv):
    sys.path.insert(
        0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
    )
    from models import rephrasing
    from models.messages import Messages
    from skillio import TEXT, parse_message_slice_args, read_fields, render

    if not argv:
        print("usage: rephrasing.py {record|select|messages} ...", file=sys.stderr)
        return 1
    op, args = argv[0], argv[1:]
    if op == "record":
        try:
            f = read_fields(
                {
                    "slug": TEXT,
                    "problem": TEXT,
                    "learner_wrote": TEXT,
                    "native_phrase": TEXT,
                    "why": TEXT,
                }
            )
            print(
                rephrasing.record(
                    f["slug"],
                    f["problem"],
                    f["learner_wrote"],
                    f["native_phrase"],
                    f["why"],
                )
            )
        except ValueError as e:
            print("error: " + str(e), file=sys.stderr)
            return 1
        return 0
    if op == "select":
        if args:
            row = rephrasing.Rephrasing.select(args[0])
            if row is not None:
                print(json.dumps(row, ensure_ascii=False))
        else:
            for row in rephrasing.Rephrasing.select():
                print(json.dumps(row, ensure_ascii=False))
        return 0
    if op == "messages":
        try:
            kwargs = parse_message_slice_args(args)
        except ValueError as e:
            print(str(e), file=sys.stderr)
            return 1
        block = render(Messages.list(**kwargs), fields=["id", "text"])
        print(f"<messages>{block}</messages>")
        return 0
    print("unknown op: " + op, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
