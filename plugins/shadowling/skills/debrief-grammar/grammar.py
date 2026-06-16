#!/usr/bin/env python3
"""skills/debrief-grammar/grammar.py - thin entrypoint: record / select / messages.
Parses stdin tags, calls the grammar + messages repositories, formats output.
No SQL. Imports are inside main() after a sys.path bootstrap to the plugin root
(keeps them at function scope -> no E402)."""

import json
import os
import sys


def main(argv):
    sys.path.insert(
        0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
    )
    from models import grammar
    from models.messages import Messages
    from skillio import TEXT, parse_message_slice_args, read_fields, render

    if not argv:
        print("usage: grammar.py {record|select|messages} ...", file=sys.stderr)
        return 1
    op, args = argv[0], argv[1:]
    if op == "record":
        try:
            f = read_fields(
                {
                    "slug": TEXT,
                    "problem": TEXT,
                    "original": TEXT,
                    "fixed": TEXT,
                    "rule": TEXT,
                }
            )
            print(
                grammar.record(
                    f["slug"], f["problem"], f["original"], f["fixed"], f["rule"]
                )
            )
        except ValueError as e:
            print("error: " + str(e), file=sys.stderr)
            return 1
        return 0
    if op == "select":
        if args:
            row = grammar.Grammar.select(args[0])
            if row is not None:
                print(json.dumps(row, ensure_ascii=False))
        else:
            for row in grammar.Grammar.select():
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
