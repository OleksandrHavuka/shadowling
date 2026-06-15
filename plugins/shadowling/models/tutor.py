"""models/tutor.py - spaced-repetition repository over the incident datasets.

attempts is the append-only event log of drill answers — stored VERBATIM, with
the session id from CLAUDE_CODE_SESSION_ID so a later drill-match can find them;
mastery is the mutable Leitner scheduling state. `deck` is cross-domain — it
reads the incident *_ranked views and learned vocab — so it imports those
repositories for their table/key/view names. All tutor SQL lives here.

Leitner: 5 boxes, intervals 1/3/7/16/35 days. pass -> box+1 (cap 5),
partial -> box stays, fail -> box 1.
"""

import os
from datetime import date, timedelta

import core
from appdb import connect

from . import friction, grammar, verbs
from .vocab import Vocab

INTERVALS = {1: 1, 2: 3, 3: 7, 4: 16, 5: 35}
VERDICTS = ("pass", "partial", "fail")
SIZE_DEFAULT = 8

# item_kind -> (incident table, key column, ranked view) ; vocab is special.
# Sourced from the incident repositories so the names live in exactly one place.
KINDS = {
    "friction": (
        friction.Friction.table,
        friction.Friction.key,
        friction.Friction.view,
    ),
    "grammar": (grammar.Grammar.table, grammar.Grammar.key, grammar.Grammar.view),
    "verbs": (verbs.Verbs.table, verbs.Verbs.key, verbs.Verbs.view),
    "vocab": (None, "word", None),
}

EXERCISES = {
    "friction": "production",
    "grammar": "fix",
    "verbs": "forms",
    "vocab": "reverse",
}

PROMPT_SQL = {
    "friction": "SELECT type, zone, learner_wrote, native_phrase, context"
    " FROM friction WHERE slug = ? ORDER BY id DESC LIMIT 1",
    "grammar": "SELECT problem, original, fixed, rule"
    " FROM grammar WHERE slug = ? ORDER BY id DESC LIMIT 1",
    "verbs": "SELECT past, participle, used_form, correction, context"
    " FROM verbs WHERE verb = ? ORDER BY id DESC LIMIT 1",
    "vocab": "SELECT translation FROM vocab WHERE word = ?",
}


def _today():
    from core import today

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
    _table, keycol, view = KINDS[kind]
    if view is None:
        return None
    row = con.execute(
        f'SELECT counter FROM {view} WHERE "{keycol}" = ?', (key,)
    ).fetchone()
    return row["counter"] if row else None


def _card(con, kind, key):
    row = con.execute(PROMPT_SQL[kind], (key,)).fetchone()
    if row is None:  # hollow: the source incident/vocab row is gone (e.g. dropped)
        return None
    return {
        "item_kind": kind,
        "item_key": key,
        "exercise": EXERCISES[kind],
        "prompt_data": dict(row),
    }


class Tutor:
    @staticmethod
    def record(kind, key, exercise, verdict, answer):
        if kind not in KINDS:
            raise ValueError("unknown item_kind: " + kind)
        if verdict not in VERDICTS:
            raise ValueError("unknown verdict: " + verdict)
        t = _today()
        now = core.now()
        con = connect()
        try:
            with con:
                con.execute(
                    "INSERT INTO attempts(created_at, session_id, item_kind,"
                    " item_key, exercise, answer, verdict)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        now,
                        os.environ.get("CLAUDE_CODE_SESSION_ID"),
                        kind,
                        key,
                        exercise,
                        answer,
                        verdict,
                    ),
                )
                row = con.execute(
                    "SELECT box FROM mastery WHERE item_kind=? AND item_key=?",
                    (kind, key),
                ).fetchone()
                box = _next_box(row["box"] if row else 1, verdict)
                counter = _counter(con, kind, key)  # one ranked-view read, reused below
                con.execute(
                    "INSERT INTO mastery(item_kind, item_key, box, due_date,"
                    " last_verdict, counter_seen, created_at, updated_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
                    " ON CONFLICT(item_kind, item_key) DO UPDATE SET box=?,"
                    " due_date=?, last_verdict=?, counter_seen=?, updated_at=?",
                    (
                        kind,
                        key,
                        box,
                        _due(box, t),
                        verdict,
                        counter,
                        now,
                        now,
                        box,
                        _due(box, t),
                        verdict,
                        counter,
                        now,
                    ),
                )
            if kind == "vocab" and verdict == "fail":
                Vocab.relearn(key)  # back into the glossing loop
            return f"recorded {kind}/{key}: {verdict} -> box {box}"
        finally:
            con.close()

    @staticmethod
    def deck(size=SIZE_DEFAULT):
        t = _today()
        con = connect()
        try:
            due = con.execute(
                "SELECT item_kind, item_key, due_date, counter_seen FROM mastery"
                " WHERE due_date <= ? ORDER BY due_date",
                (t,),
            ).fetchall()
            boosted: list[tuple[str, str]] = []
            plain: list[tuple[str, str]] = []
            for r in due:  # hot-zone boost: re-caught since the last drill
                cur = _counter(con, r["item_kind"], r["item_key"])
                hot = (
                    cur is not None
                    and r["counter_seen"] is not None
                    and cur > r["counter_seen"]
                )
                (boosted if hot else plain).append((r["item_kind"], r["item_key"]))
            picked = boosted + plain
            # new items: in the ranked views / learned vocab, never attempted
            new: list[tuple[str, str]] = []
            for kind, (_table, keycol, view) in KINDS.items():
                if view is not None:
                    rows = con.execute(
                        f'SELECT "{keycol}" AS k FROM {view} WHERE "{keycol}" NOT IN'
                        " (SELECT item_key FROM mastery WHERE item_kind = ?)"
                        " ORDER BY counter DESC",
                        (kind,),
                    ).fetchall()
                else:
                    rows = con.execute(
                        "SELECT word AS k FROM vocab WHERE status = 'learned'"
                        " AND word NOT IN (SELECT item_key FROM mastery"
                        " WHERE item_kind = 'vocab')"
                    ).fetchall()
                new.extend((kind, r["k"]) for r in rows)
            cards: list[dict] = []
            per_kind: dict[str, int] = {}
            pool = picked + new
            cap = max(size // 2, 1)  # no kind hogs more than half the deck
            taken = [False] * len(pool)
            # Pass 1: respect the per-kind cap as a soft diversity preference.
            for i, (kind, key) in enumerate(pool):
                if len(cards) >= size:
                    break
                if per_kind.get(kind, 0) >= cap:
                    continue
                card = _card(con, kind, key)
                taken[i] = True
                if card is None:
                    continue
                per_kind[kind] = per_kind.get(kind, 0) + 1
                cards.append(card)
            # Pass 2: if the cap left the deck short, backfill the remaining
            # pool ignoring the cap until full or exhausted.
            if len(cards) < size:
                for i, (kind, key) in enumerate(pool):
                    if len(cards) >= size:
                        break
                    if taken[i]:
                        continue
                    taken[i] = True
                    card = _card(con, kind, key)
                    if card is None:
                        continue
                    cards.append(card)
            return cards
        finally:
            con.close()

    @staticmethod
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
            return {
                "due_today": due_today,
                "due_tomorrow": due_tomorrow,
                "tracked": tracked,
            }
        finally:
            con.close()
