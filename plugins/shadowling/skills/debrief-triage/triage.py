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
    from skillio import parse_message_slice_args, read_fields, render, rows

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
        try:
            tags = read_fields({"items": rows("id", "langs")})["items"]
        except ValueError as e:
            print("error: " + str(e), file=sys.stderr)
            return 1
        if not tags:
            print(
                "usage: triage.py tag (id<TAB>code[,code] lines in an "
                "<items>...</items> tag on stdin)",
                file=sys.stderr,
            )
            return 1
        n = Messages.tag(tags)
        print(f"<result>{render([{'tagged': n}])}</result>")
        return 0
    print("unknown op: " + op, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
