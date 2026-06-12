#!/usr/bin/env python3
"""tutor.py - spaced-repetition engine over the incident datasets (stdlib only).

  python3 tutor.py deck [--size N]                          # today's cards, JSON per card
  python3 tutor.py record <kind> <key> <exercise> <verdict> # answer on STDIN (verbatim)
  python3 tutor.py stats                                    # due counts, JSON

Leitner: 5 boxes, intervals 1/3/7/16/35 days. pass -> box+1 (cap 5),
partial -> box stays, fail -> box 1. `attempts` is the append-only log (and
the registry capture.py mark-drills joins against — answers stored VERBATIM
from stdin, session from CLAUDE_CODE_SESSION_ID); `mastery` is the mutable
scheduling state (sanctioned exception, like vocab).
"""
import json
import os
import sys
from datetime import date, timedelta

from appdb import connect, query
from core import today

INTERVALS = {1: 1, 2: 3, 3: 7, 4: 16, 5: 35}
VERDICTS = ("pass", "partial", "fail")
SIZE_DEFAULT = 8

# item_kind -> (incident table, key column, ranked view) ; vocab is special
KINDS = {
    "friction": ("friction", "slug", "friction_ranked"),
    "grammar": ("grammar", "slug", "grammar_ranked"),
    "verbs": ("verbs", "verb", "verbs_ranked"),
    "vocab": (None, "word", None),
}


def _today():
    return today()


def _due(box, today_str):
    d = date.fromisoformat(today_str) + timedelta(days=INTERVALS[box])
    return d.isoformat()


def _next_box(box, verdict):
    if verdict == "pass":
        return min(box + 1, 5)
    if verdict == "fail":
        return 1
    return box


def _counter(con, kind, key):
    table, keycol, view = KINDS[kind]
    if view is None:
        return None
    row = con.execute(
        'SELECT counter FROM {0} WHERE "{1}" = ?'.format(view, keycol),
        (key,)).fetchone()
    return row["counter"] if row else None


def record(kind, key, exercise, verdict, answer):
    if kind not in KINDS:
        raise ValueError("unknown item_kind: " + kind)
    if verdict not in VERDICTS:
        raise ValueError("unknown verdict: " + verdict)
    t = _today()
    con = connect()
    try:
        with con:
            con.execute(
                "INSERT INTO attempts(ts, session_id, item_kind, item_key,"
                " exercise, answer, verdict) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (t, os.environ.get("CLAUDE_CODE_SESSION_ID"), kind, key,
                 exercise, answer, verdict))
            row = con.execute(
                "SELECT box FROM mastery WHERE item_kind=? AND item_key=?",
                (kind, key)).fetchone()
            box = _next_box(row["box"] if row else 1,
                            verdict) if row else _next_box(1, verdict)
            con.execute(
                "INSERT INTO mastery(item_kind, item_key, box, due_date,"
                " last_verdict, counter_seen) VALUES (?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(item_kind, item_key) DO UPDATE SET box=?,"
                " due_date=?, last_verdict=?, counter_seen=?",
                (kind, key, box, _due(box, t), verdict,
                 _counter(con, kind, key),
                 box, _due(box, t), verdict, _counter(con, kind, key)))
            if kind == "vocab" and verdict == "fail":
                con.execute(  # relearn: back into the glossing loop
                    "UPDATE vocab SET remaining = 10, status = 'active'"
                    " WHERE word = ?", (key,))
        return "recorded {0}/{1}: {2} -> box {3}".format(
            kind, key, verdict, box)
    finally:
        con.close()


def deck(size=SIZE_DEFAULT):
    raise NotImplementedError  # Task 5


def stats():
    raise NotImplementedError  # Task 5


def main(argv):
    if not argv:
        print("usage: tutor.py {deck [--size N]|record <kind> <key>"
              " <exercise> <verdict>|stats}", file=sys.stderr)
        return 1
    cmd = argv[0]
    if cmd == "record":
        if len(argv) != 5:
            print("usage: tutor.py record <kind> <key> <exercise> <verdict>"
                  " (answer on stdin)", file=sys.stderr)
            return 1
        answer = sys.stdin.read()
        try:
            print(record(argv[1], argv[2], argv[3], argv[4], answer))
        except ValueError as e:
            print("error: " + str(e), file=sys.stderr)
            return 1
        return 0
    if cmd == "deck":
        size = SIZE_DEFAULT
        if len(argv) == 3 and argv[1] == "--size" and argv[2].isdigit():
            size = int(argv[2])
        for card in deck(size):
            print(json.dumps(card, ensure_ascii=False))
        return 0
    if cmd == "stats":
        print(json.dumps(stats(), ensure_ascii=False))
        return 0
    print("unknown command: " + cmd, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
