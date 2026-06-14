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

    if not argv:
        print("usage: triage.py {messages|tag} ...", file=sys.stderr)
        return 1
    op, args = argv[0], argv[1:]
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
