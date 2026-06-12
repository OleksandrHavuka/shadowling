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
from datetime import date, datetime, timedelta

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


def _now():
    # full ISO timestamp for the event log (attempts) + mutable mastery stamps,
    # matching capture._now(); _today() stays for date-only scheduling math.
    return datetime.now().isoformat(timespec="seconds")


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
    now = _now()
    con = connect()
    try:
        with con:
            con.execute(
                "INSERT INTO attempts(created_at, session_id, item_kind,"
                " item_key, exercise, answer, verdict)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (now, os.environ.get("CLAUDE_CODE_SESSION_ID"), kind, key,
                 exercise, answer, verdict))
            row = con.execute(
                "SELECT box FROM mastery WHERE item_kind=? AND item_key=?",
                (kind, key)).fetchone()
            box = _next_box(row["box"] if row else 1,
                            verdict) if row else _next_box(1, verdict)
            con.execute(
                "INSERT INTO mastery(item_kind, item_key, box, due_date,"
                " last_verdict, counter_seen, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(item_kind, item_key) DO UPDATE SET box=?,"
                " due_date=?, last_verdict=?, counter_seen=?, updated_at=?",
                (kind, key, box, _due(box, t), verdict,
                 _counter(con, kind, key), now, now,
                 box, _due(box, t), verdict, _counter(con, kind, key), now))
            if kind == "vocab" and verdict == "fail":
                con.execute(  # relearn: back into the glossing loop
                    "UPDATE vocab SET remaining = 10, status = 'active'"
                    " WHERE word = ?", (key,))
        return "recorded {0}/{1}: {2} -> box {3}".format(
            kind, key, verdict, box)
    finally:
        con.close()


EXERCISES = {"friction": "production", "grammar": "fix",
             "verbs": "forms", "vocab": "reverse"}

PROMPT_SQL = {
    "friction": "SELECT type, zone, you_reached_for, natural_english, context"
                " FROM friction WHERE slug = ? ORDER BY id DESC LIMIT 1",
    "grammar": "SELECT problem, original, fixed, rule"
               " FROM grammar WHERE slug = ? ORDER BY id DESC LIMIT 1",
    "verbs": "SELECT past, participle, example_fix"
             " FROM verbs WHERE verb = ? ORDER BY id DESC LIMIT 1",
    "vocab": "SELECT translation FROM vocab WHERE word = ?",
}


def _card(con, kind, key):
    row = con.execute(PROMPT_SQL[kind], (key,)).fetchone()
    return {"item_kind": kind, "item_key": key,
            "exercise": EXERCISES[kind],
            "prompt_data": dict(row) if row else {}}


def deck(size=SIZE_DEFAULT):
    t = _today()
    con = connect()
    try:
        due = con.execute(
            "SELECT item_kind, item_key, due_date, counter_seen FROM mastery"
            " WHERE due_date <= ? ORDER BY due_date", (t,)).fetchall()
        boosted, plain = [], []
        for r in due:  # hot-zone boost: re-caught since the last drill
            cur = _counter(con, r["item_kind"], r["item_key"])
            hot = (cur is not None and r["counter_seen"] is not None
                   and cur > r["counter_seen"])
            (boosted if hot else plain).append((r["item_kind"], r["item_key"]))
        picked = boosted + plain
        # new items: in the ranked views / learned vocab, never attempted
        new = []
        for kind, (table, keycol, view) in KINDS.items():
            if view is not None:
                rows = con.execute(
                    'SELECT "{0}" AS k FROM {1} WHERE "{0}" NOT IN'
                    ' (SELECT item_key FROM mastery WHERE item_kind = ?)'
                    ' ORDER BY counter DESC'.format(keycol, view),
                    (kind,)).fetchall()
            else:
                rows = con.execute(
                    "SELECT word AS k FROM vocab WHERE status = 'learned'"
                    " AND word NOT IN (SELECT item_key FROM mastery"
                    " WHERE item_kind = 'vocab')").fetchall()
            new.extend((kind, r["k"]) for r in rows)
        cards, per_kind = [], {}
        pool = picked + new
        kinds_available = {k for k, _ in pool}
        cap = max(size // 2, 1)  # no kind hogs more than half the deck
        for kind, key in pool:
            if len(cards) >= size:
                break
            if per_kind.get(kind, 0) >= cap and len(kinds_available) > 1:
                continue
            per_kind[kind] = per_kind.get(kind, 0) + 1
            cards.append(_card(con, kind, key))
        return cards
    finally:
        con.close()


def stats():
    t = _today()
    tomorrow = (date.fromisoformat(t) + timedelta(days=1)).isoformat()
    con = connect()
    try:
        due_today = con.execute(
            "SELECT COUNT(*) FROM mastery WHERE due_date <= ?", (t,)
            ).fetchone()[0]
        due_tomorrow = con.execute(
            "SELECT COUNT(*) FROM mastery WHERE due_date = ?", (tomorrow,)
            ).fetchone()[0]
        tracked = con.execute("SELECT COUNT(*) FROM mastery").fetchone()[0]
        return {"due_today": due_today, "due_tomorrow": due_tomorrow,
                "tracked": tracked}
    finally:
        con.close()


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
