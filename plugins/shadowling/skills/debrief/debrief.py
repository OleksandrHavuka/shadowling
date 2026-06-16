#!/usr/bin/env python3
"""skills/debrief/debrief.py - thin entrypoint for the /debrief orchestrator:
sessions / pending-count / mark-processed / mark-drills over the Messages
repository. No SQL."""

import os
import sys


def main(argv):
    sys.path.insert(
        0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
    )
    from models.messages import Messages
    from skillio import parse_session_arg, render

    if not argv:
        print(
            "usage: debrief.py {sessions|pending-count|"
            "mark-processed [--session <id>]|mark-drills}",
            file=sys.stderr,
        )
        return 1
    cmd, args = argv[0], argv[1:]
    if cmd == "sessions":
        print(f"<sessions>{render(Messages.sessions())}</sessions>")
        return 0
    if cmd == "pending-count":
        print(Messages.pending_count())
        return 0
    if cmd == "mark-drills":
        print(f"<result>{render([{'marked': Messages.mark_drills()}])}</result>")
        return 0
    if cmd == "mark-processed":
        result = Messages.mark_processed(session=parse_session_arg(args))
        print(f"<result>{render([result])}</result>")
        return 0
    print("unknown command: " + cmd, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
