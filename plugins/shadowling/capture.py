#!/usr/bin/env python3
"""capture.py - shadowling English-message collector (stdlib only, Python 3.9+).

The Stop hook silently captures the user's English messages from the chat
transcript. Each captured message is dual-written: appended to the transient
buffer (`~/.shadowling/buffer.jsonl`, the current unprocessed batch) AND to the
permanent raw corpus (`~/.shadowling/messages.log.jsonl`, Tier 0). On demand,
`/debrief` has the per-category specialists read the buffer (`messages`); the
orchestrator then `clear`s it. Nothing is printed into the chat by the hook.
"""
import json
import os
import sys
from datetime import datetime

from core import data_dir, last_user_text, today
from jsonl import append as jsonl_append, read as jsonl_read

MIN_LETTERS = 8  # below this we can't judge language reliably / not worth logging

# Claude Code wraps slash-command / local-command turns in these tags. Such turns
# are not the user's own writing, so they must never be captured for analysis.
COMMAND_WRAPPERS = ("<command-", "<local-command-")


def buffer_path():
    return os.environ.get("SHADOWLING_BUFFER") or os.path.join(
        data_dir(), "buffer.jsonl")


def messages_log_path():
    return os.path.join(data_dir(), "messages.log.jsonl")


def is_english(text):
    """Heuristic: enough letters AND latin script dominates over cyrillic."""
    letters = [c for c in text if c.isalpha()]
    if len(letters) < MIN_LETTERS:
        return False
    latin = sum(1 for c in letters if "a" <= c.lower() <= "z")
    cyrillic = sum(1 for c in letters if "Ѐ" <= c <= "ӿ")
    return latin > cyrillic and latin >= len(letters) * 0.6


# --- buffer + corpus -------------------------------------------------------

def _read_buffer():
    return jsonl_read(buffer_path())


def _append_buffer(record):
    jsonl_append(buffer_path(), record)


def capture(stdin_text):
    """Stop-hook entry: capture the last user message if English. Never raises.

    Dual-writes the transient buffer (current batch) and the permanent raw corpus
    messages.log.jsonl (Tier 0), so the corpus is complete regardless of whether a
    review ever runs.
    """
    try:
        data = json.loads(stdin_text) if stdin_text.strip() else {}
    except (json.JSONDecodeError, AttributeError, TypeError):
        return False
    text = (last_user_text(data.get("transcript_path", "")) or "").strip()
    if not text or text.startswith("/"):
        return False
    if text.startswith(COMMAND_WRAPPERS):  # slash/local command echoes, not prose
        return False
    if not is_english(text):
        return False
    existing = _read_buffer()
    if existing and existing[-1].get("text") == text:
        return False  # guard against repeated Stop on the same turn
    ts = datetime.now().isoformat(timespec="seconds")
    _append_buffer({"ts": ts, "text": text})
    jsonl_append(messages_log_path(), {"date": today(), "ts": ts, "text": text})
    return True


# --- commands --------------------------------------------------------------

def _xml(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def pending_count():
    return len(_read_buffer())


def messages():
    """Emit the buffered English messages for the specialists (read-only)."""
    pending = _read_buffer()
    if not pending:
        return "<messages></messages>"
    out = ["<messages>"]
    for rec in pending:
        out.append('  <m ts="{0}">{1}</m>'.format(
            _xml(rec.get("ts", "")), _xml(rec.get("text", ""))))
    out.append("</messages>")
    return "\n".join(out)


def clear():
    path = buffer_path()
    if os.path.exists(path):
        os.remove(path)
    return "cleared"


def paths():
    return "buffer: {0}\nmessages_log: {1}".format(
        buffer_path(), messages_log_path())


def main(argv):
    if not argv:
        print("usage: capture.py {capture|pending-count|messages|clear|paths} ...",
              file=sys.stderr)
        return 1
    cmd = argv[0]
    if cmd == "capture":
        try:
            capture(sys.stdin.read())
        except Exception:  # the Stop hook must never crash the session
            pass
        return 0
    if cmd == "pending-count":
        print(pending_count())
        return 0
    if cmd == "messages":
        print(messages())
        return 0
    if cmd == "clear":
        print(clear())
        return 0
    if cmd == "paths":
        print(paths())
        return 0
    print("unknown command: " + cmd, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
