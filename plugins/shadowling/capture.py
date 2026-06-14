#!/usr/bin/env python3
"""capture.py - shadowling Stop-hook message collector (stdlib only, py3.9+).

The Stop hook silently captures the user's last message (any language) from the
chat transcript into the message store, via models/messages.py. Rows are never
deleted; /debrief stamps the analyzed batch processed. Reads/admin moved to the
debrief entrypoints + sql.py; this file is now just the hook."""

import json
import sys

from core import last_user_text
from models.messages import Messages


def capture(stdin_text):
    """Stop-hook entry: store the last user message, any language. Never raises.

    NOT config-gated: messages are logged even before /setup so nothing is lost.
    Capture uses no config value (language matters only at analysis time). The
    glossing hook and the analysis skills (/debrief, /tutor, /loot) gate on config
    themselves and steer the user to /setup; the message log just keeps filling."""
    try:
        data = json.loads(stdin_text) if stdin_text.strip() else {}
    except (json.JSONDecodeError, AttributeError, TypeError):
        return False
    text = last_user_text(data.get("transcript_path", ""))
    return Messages.capture(text, data.get("session_id"))


def main(argv):
    if argv[:1] == ["capture"]:
        try:
            capture(sys.stdin.read())
        except Exception:  # the Stop hook must never crash the session
            pass
        return 0
    print("usage: capture.py capture", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
