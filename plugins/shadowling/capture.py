#!/usr/bin/env python3
"""capture.py - SHIM (uniform-DB refactor). Data lives in models/messages.py.
Keeps the Stop-hook `capture` write plus the debrief CLI verbs until triage.py /
debrief.py / the specialist entrypoints take over. In phase 3 this shrinks to
just the `capture` hook."""

import json
import sqlite3
import sys

from appdb import db_path, query
from core import config_ready, last_user_text
from models.messages import Messages


def capture(stdin_text):
    """Stop-hook entry: store the last user message, any language. Never raises."""
    if not config_ready():
        return False
    try:
        data = json.loads(stdin_text) if stdin_text.strip() else {}
    except (json.JSONDecodeError, AttributeError, TypeError):
        return False
    text = last_user_text(data.get("transcript_path", ""))
    return Messages.capture(text, data.get("session_id"))


def main(argv):
    if not argv:
        print(
            "usage: capture.py {capture|pending-count|sessions|messages|tag|"
            "mark-processed|mark-drills|query|paths} ...",
            file=sys.stderr,
        )
        return 1
    cmd = argv[0]
    if cmd == "capture":
        try:
            capture(sys.stdin.read())
        except Exception:  # the Stop hook must never crash the session
            pass
        return 0
    if cmd == "pending-count":
        print(Messages.pending_count())
        return 0
    if cmd == "sessions":
        for row in Messages.sessions():
            print(json.dumps(row, ensure_ascii=False))
        return 0
    if cmd == "messages":
        lang, untagged, limit, session = None, False, None, None
        args, i = argv[1:], 0
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
    if cmd == "tag":
        if not argv[1:]:
            print('usage: capture.py tag "<id>=<code[,code]>" ...', file=sys.stderr)
            return 1
        ok, errors = Messages.tag(argv[1:])
        print(f"tagged {ok}")
        for e in errors:
            print(e, file=sys.stderr)
        return 1 if errors else 0
    if cmd == "mark-processed":
        session = None
        if len(argv) >= 3 and argv[1] == "--session":
            session = argv[2]
        print(Messages.mark_processed(session=session))
        return 0
    if cmd == "mark-drills":
        print(Messages.mark_drills())
        return 0
    if cmd == "query":
        if len(argv) != 2:
            print('usage: capture.py query "<SELECT ...>"', file=sys.stderr)
            return 1
        try:
            for row in query(argv[1]):
                print(json.dumps(row, ensure_ascii=False))
        except sqlite3.Error as e:
            print("error: " + str(e), file=sys.stderr)
            return 1
        return 0
    if cmd == "paths":
        print("db: " + db_path())
        return 0
    print("unknown command: " + cmd, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
