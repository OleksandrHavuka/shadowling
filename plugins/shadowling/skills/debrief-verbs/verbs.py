#!/usr/bin/env python3
"""skills/debrief-verbs/verbs.py - thin entrypoint: record / select / messages."""

import os
import sys


def main(argv):
    sys.path.insert(
        0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
    )
    from models import verbs
    from models.messages import Messages
    from skillio import TEXT, parse_message_slice_args, read_fields, render

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
            n = verbs.record(
                f["verb"],
                f["past"],
                f["participle"],
                f["used_form"],
                f["correction"],
                f["context"],
            )
        except ValueError as e:
            print("error: " + str(e), file=sys.stderr)
            return 1
        status = "inserted" if n == 1 else "incremented"
        print(f"<result>{render([{'status': status}])}</result>")
        return 0
    if op == "select":
        if args:
            row = verbs.Verbs.select(args[0])
            selected = [row] if row is not None else []
        else:
            selected = verbs.Verbs.select()
        print(f"<verbs>{render(selected)}</verbs>")
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
