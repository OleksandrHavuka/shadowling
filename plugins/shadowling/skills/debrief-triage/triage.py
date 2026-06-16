#!/usr/bin/env python3
"""skills/debrief-triage/triage.py - thin entrypoint: messages / tag.
Reads untagged message slices and writes language tags via the Messages
repository. No SQL here."""

import os
import re
import sys

# Validated HERE (the triage boundary), not in the persistence layer: the codes
# are domain knowledge that belongs to triage, and a bad code must be rejected
# before it reaches Messages.tag — otherwise an empty/garbage langs stamps the
# row non-NULL, hiding it from every --lang slice while mark_processed still
# sweeps it (silent message loss). Keeping this here leaves the repo
# persistence-only and the skillio parser generic.
LANG_CODE = re.compile(r"^[a-z]{2,3}$")  # ISO-style; "und" fits too


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
        clean = []
        for t in tags:
            codes = [c.strip() for c in t["langs"].split(",") if c.strip()]
            valid = bool(codes) and all(LANG_CODE.match(c) for c in codes)
            if not t["id"].isdigit() or not valid:
                # Self-correcting error (names the offender + the expected shape);
                # abort the WHOLE batch so nothing is persisted — every row stays
                # untagged and the next /debrief re-lists it. Exit 1 trips the
                # SKILL.md ERROR/STOP path.
                print(
                    f"error: bad tag for id {t['id']!r}: langs must be"
                    " comma-separated ISO-ish codes (2-3 lowercase letters,"
                    " e.g. en or en,uk); nothing was tagged",
                    file=sys.stderr,
                )
                return 1
            clean.append({"id": t["id"], "langs": ",".join(codes)})
        n = Messages.tag(clean)
        print(f"<result>{render([{'tagged': n}])}</result>")
        return 0
    print("unknown op: " + op, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
