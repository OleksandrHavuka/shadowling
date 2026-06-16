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
    from cliutil import format_loot_line
    from models import friction, grammar
    from models.messages import Messages
    from models.vocab import Vocab
    from skillio import TEXT, parse_message_slice_args, read_fields, render, rows

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
            print(format_loot_line(action, row))
        return 0
    if op == "messages":
        try:
            kwargs = parse_message_slice_args(args)
        except ValueError as e:
            print(str(e), file=sys.stderr)
            return 1
        block = render(Messages.list(**kwargs), fields=["id", "text", "langs"])
        print(f"<messages>{block}</messages>")
        return 0
    print("unknown op: " + op, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
