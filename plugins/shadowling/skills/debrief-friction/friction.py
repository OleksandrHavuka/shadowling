#!/usr/bin/env python3
"""skills/debrief-friction/friction.py - thin entrypoint:
record / select / grammar-select / loot / messages. Friction is cross-domain:
it reads grammar (correlation) and writes vocab (auto-loot) via their
repositories. No SQL here."""

import json
import os
import sys


def main(argv):
    sys.path.insert(
        0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
    )
    from models import friction, grammar
    from models.messages import Messages
    from models.vocab import Vocab
    from tagio import TEXT, read_fields, rows

    if not argv:
        print(
            "usage: friction.py {record|select|grammar-select|loot|messages} ...",
            file=sys.stderr,
        )
        return 1
    op, args = argv[0], argv[1:]
    if op == "record":
        try:
            f = read_fields(
                {
                    "slug": TEXT,
                    "type": TEXT,
                    "zone": TEXT,
                    "learner_wrote": TEXT,
                    "native_phrase": TEXT,
                    "context": TEXT,
                }
            )
            print(
                friction.record(
                    f["slug"],
                    f["type"],
                    f["zone"],
                    f["learner_wrote"],
                    f["native_phrase"],
                    f["context"],
                )
            )
        except ValueError as e:
            print("error: " + str(e), file=sys.stderr)
            return 1
        return 0
    if op == "select":
        if args:
            row = friction.Friction.select(args[0])
            if row is not None:
                print(json.dumps(row, ensure_ascii=False))
        else:
            for row in friction.Friction.select():
                print(json.dumps(row, ensure_ascii=False))
        return 0
    if op == "grammar-select":
        for row in grammar.Grammar.select():
            print(json.dumps(row, ensure_ascii=False))
        return 0
    if op == "loot":
        try:
            looted = read_fields({"items": rows("word", "translation")})["items"]
        except ValueError as e:
            print("error: " + str(e), file=sys.stderr)
            return 1
        if not looted:
            print(
                "usage: friction.py loot (word<TAB>translation lines in an "
                "<items>...</items> tag on stdin)",
                file=sys.stderr,
            )
            return 1
        for item in looted:
            action, row = Vocab.add(item["word"], item["translation"])
            print(
                "{}: {} = {} (remaining {}, {})".format(
                    action,
                    row["word"],
                    row["translation"],
                    row["remaining"],
                    row["status"],
                )
            )
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
