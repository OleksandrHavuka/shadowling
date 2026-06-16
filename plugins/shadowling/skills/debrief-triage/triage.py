#!/usr/bin/env python3
"""skills/debrief-triage/triage.py - thin entrypoint: messages / tag.
Reads untagged message slices and writes language tags via the Messages
repository. No SQL here."""

import os
import sys


def main(argv):
    sys.path.insert(
        0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
    )
    from models.messages import Messages
    from skillio import parse_message_slice_args, render

    if not argv:
        print("usage: triage.py {messages|tag} ...", file=sys.stderr)
        return 1
    op, args = argv[0], argv[1:]
    if op == "messages":
        try:
            kwargs = parse_message_slice_args(args)
        except ValueError as e:
            print(str(e), file=sys.stderr)
            return 1
        block = render(Messages.list(**kwargs), fields=["id", "text"])
        print(f"<messages>{block}</messages>")
        return 0
    if op == "tag":
        if not args:
            print('usage: triage.py tag "<id>=<code[,code]>" ...', file=sys.stderr)
            return 1
        ok, errors = Messages.tag(args)
        print(f"tagged {ok}")
        for e in errors:
            print(e, file=sys.stderr)
        return 1 if errors else 0
    print("unknown op: " + op, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
