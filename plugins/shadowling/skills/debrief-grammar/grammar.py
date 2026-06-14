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
    from tagio import TEXT, read_fields

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
        lang, untagged, limit, session = None, False, None, None
        i = 0
        while i < len(args):
            if args[i] == "--untagged":
                untagged, i = True, i + 1
            elif args[i] == "--lang" and i + 1 < len(args):
                lang, i = args[i + 1], i + 2
            elif args[i] == "--session" and i + 1 < len(args):
                session, i = args[i + 1], i + 2
            elif args[i] == "--limit" and i + 1 < len(args) and args[i + 1].isdigit():
                limit, i = int(args[i + 1]), i + 2
            else:
                print("unknown option: " + args[i], file=sys.stderr)
                return 1
        print(Messages.list(lang=lang, untagged=untagged, limit=limit, session=session))
        return 0
    print("unknown op: " + op, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
