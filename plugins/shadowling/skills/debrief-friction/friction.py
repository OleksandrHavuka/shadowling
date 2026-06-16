#!/usr/bin/env python3
"""skills/debrief-friction/friction.py - thin entrypoint:
record / select / grammar-select / loot / messages. Friction is cross-domain:
it reads grammar (correlation) and writes vocab (auto-loot) via their
repositories. No SQL here."""

import os
import sys


def main(argv):
    sys.path.insert(
        0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
    )
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
            n = friction.record(
                f["slug"],
                f["type"],
                f["zone"],
                f["learner_wrote"],
                f["native_phrase"],
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
            row = friction.Friction.select(args[0])
            selected = [row] if row is not None else []
        else:
            selected = friction.Friction.select()
        print(f"<friction>{render(selected)}</friction>")
        return 0
    if op == "grammar-select":
        print(f"<grammar>{render(grammar.Grammar.select())}</grammar>")
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
        out = [Vocab.add(item["word"], item["translation"]) for item in looted]
        print(f"<loot>{render(out)}</loot>")
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
