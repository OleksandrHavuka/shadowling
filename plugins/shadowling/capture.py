#!/usr/bin/env python3
"""capture.py - shadowling message collector + sqlite store (stdlib only, 3.9+).

The Stop hook silently captures the user's messages (ANY language) from the
chat transcript into the sqlite message store (~/.shadowling/shadowling.db,
table `messages`). Rows are never deleted: a successful /debrief marks the
analyzed batch processed (`processed_at`), so the table doubles as the
permanent, language-tagged message log. The debrief triage sub-skill stamps
language tags (`langs`, JSON array of codes) via the batch `tag` verb;
specialists read deterministic slices via `messages --lang/--untagged`. The
read-only `query` verb is the escape hatch for ad-hoc analysis.
"""
import json
import re
import sqlite3
import sys
from contextlib import closing
from datetime import datetime
from difflib import SequenceMatcher

from appdb import (  # noqa: F401  (query re-exported for CLI/tests)
    connect,
    db_path,
    query,
)
from core import config_ready, last_user_text

MIN_LETTERS = 8  # below this it's not analyzable prose / not worth logging

# Claude Code wraps slash-command / local-command turns in these tags. Such turns
# are not the user's own writing, so they must never be captured for analysis.
COMMAND_WRAPPERS = ("<command-", "<local-command-")

LANG_CODE = re.compile(r"^[a-z]{2,3}$")  # ISO-style; "und" fits too


def _now():
    return datetime.now().isoformat(timespec="seconds")


def _enough_letters(text):
    return sum(1 for c in text if c.isalpha()) >= MIN_LETTERS


def capture(stdin_text):
    """Stop-hook entry: store the last user message, any language. Never raises."""
    if not config_ready():
        return False
    try:
        data = json.loads(stdin_text) if stdin_text.strip() else {}
    except (json.JSONDecodeError, AttributeError, TypeError):
        return False
    text = (last_user_text(data.get("transcript_path", "")) or "").strip()
    if not text or text.startswith("/"):
        return False
    if text.startswith(COMMAND_WRAPPERS):  # command echoes, not prose
        return False
    if not _enough_letters(text):
        return False
    with closing(connect()) as con, con:
        last = con.execute(
            "SELECT text FROM messages ORDER BY id DESC LIMIT 1").fetchone()
        if last is not None and last["text"] == text:
            return False  # guard against repeated Stop on the same turn
        con.execute(
            "INSERT INTO messages(created_at, text, session_id)"
            " VALUES (?, ?, ?)", (_now(), text, data.get("session_id")))
    return True


# --- working-batch reads (processed_at IS NULL) ------------------------------

def pending_count():
    with closing(connect()) as con:
        return con.execute("SELECT COUNT(*) FROM messages "
                           "WHERE processed_at IS NULL AND kind IS NULL"
                           ).fetchone()[0]


def sessions():
    """Sessions that still need analysis (pending = unprocessed non-drill)."""
    with closing(connect()) as con:
        rows = con.execute(
            "SELECT session_id AS session, COUNT(*) AS pending FROM messages "
            "WHERE processed_at IS NULL AND kind IS NULL "
            "GROUP BY session_id ORDER BY MIN(id)").fetchall()
    return [dict(r) for r in rows]


def _xml(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;")
             .replace(">", "&gt;").replace('"', "&quot;"))


def messages(lang=None, untagged=False, limit=None, session=None):
    """Unprocessed rows as an XML block; optionally sliced."""
    sql = ("SELECT id, created_at, text, langs FROM messages "
           "WHERE processed_at IS NULL AND kind IS NULL")
    params = []
    if session:
        sql += " AND session_id = ?"
        params.append(session)
    if untagged:
        sql += " AND langs IS NULL"
    elif lang:
        sql += (" AND EXISTS (SELECT 1 FROM json_each(messages.langs) "
                "WHERE json_each.value = ?)")
        params.append(lang)
    sql += " ORDER BY id"
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    with closing(connect()) as con:
        rows = con.execute(sql, params).fetchall()
    if not rows:
        return "<messages></messages>"
    out = ["<messages>"]
    for r in rows:
        out.append('  <m id="{}" created_at="{}" langs="{}">{}</m>'.format(
            r["id"], _xml(r["created_at"]), _xml(r["langs"] or ""),
            _xml(r["text"])))
    out.append("</messages>")
    return "\n".join(out)


# --- writes driven by the debrief pipeline -----------------------------------

def tag(pairs):
    """pairs: 'id=code[,code]' strings. Returns (ok_count, errors)."""
    updates, errors = [], []
    for p in pairs:
        id_part, eq, langs_part = p.partition("=")
        codes = [c.strip() for c in langs_part.split(",") if c.strip()]
        if (not eq or not id_part.isdigit() or not codes
                or not all(LANG_CODE.match(c) for c in codes)):
            errors.append("malformed pair: " + p)
            continue
        updates.append((json.dumps(codes), int(id_part)))
    ok = 0
    with closing(connect()) as con, con:
        for langs_json, mid in updates:
            cur = con.execute("UPDATE messages SET langs=? WHERE id=?",
                              (langs_json, mid))
            if cur.rowcount == 0:
                errors.append(f"unknown id: {mid}")
            else:
                ok += 1
    return ok, errors


def mark_processed(session=None):
    """Stamp tagged+unprocessed rows (and drill rows — they are excluded from
    analysis but must not stay pending forever); untagged natural rows stay."""
    sql = ("UPDATE messages SET processed_at=? WHERE processed_at IS NULL "
           "AND (langs IS NOT NULL OR kind = 'drill')")
    params = [_now()]
    if session:
        sql += " AND session_id = ?"
        params.append(session)
    with closing(connect()) as con, con:
        cur = con.execute(sql, params)
        kept = con.execute("SELECT COUNT(*) FROM messages "
                           "WHERE processed_at IS NULL AND kind IS NULL"
                           ).fetchone()[0]
    return f"processed {cur.rowcount}, kept {kept} untagged"


# --- drill filtering (tutor answers must not enter the analysis corpus) -----

DRILL_SIMILARITY = 0.90  # gate threshold; width characterized in MarkDrillsTest


def _similarity(a, b):
    # casefold: ratio() is case-sensitive. " ".join(split()) collapses every
    # whitespace run (incl. newlines/tabs) to a single space and strips the
    # ends, so spacing drift in a re-typed answer doesn't sink the score.
    # autojunk=False: the default heuristic degrades on long strings (frequent
    # chars become junk).
    a = " ".join(a.casefold().split())
    b = " ".join(b.casefold().split())
    return SequenceMatcher(None, a, b, autojunk=False).ratio()


def mark_drills():
    """Stamp unprocessed messages that match a recorded tutor answer for the
    SAME session (kind='drill'). Deterministic: machine-recorded session ids +
    a fixed similarity threshold; no LLM judgment, no prose markers."""
    with closing(connect()) as con:
        con.create_function("similarity", 2, _similarity)
        with con:
            cur = con.execute(
                "UPDATE messages SET kind = 'drill' "
                "WHERE processed_at IS NULL AND kind IS NULL "
                "AND session_id IS NOT NULL "
                "AND EXISTS (SELECT 1 FROM attempts a "
                "            WHERE a.session_id = messages.session_id "
                "              AND similarity(a.answer, messages.text) >= ?)",
                (DRILL_SIMILARITY,))
            marked = cur.rowcount
        unmatched = con.execute(
            "SELECT COUNT(*) FROM attempts a "
            "WHERE a.session_id IS NOT NULL "
            "AND NOT EXISTS (SELECT 1 FROM messages m "
            "                WHERE m.session_id = a.session_id "
            "                  AND similarity(a.answer, m.text) >= ?)",
            (DRILL_SIMILARITY,)).fetchone()[0]
    return f"marked {marked} drill answer(s); {unmatched} attempt(s) unmatched"


# --- escape hatch -------------------------------------------------------------

def paths():
    return "db: " + db_path()


def main(argv):
    if not argv:
        print("usage: capture.py {capture|pending-count|sessions|messages|tag|"
              "mark-processed|mark-drills|query|paths} ...", file=sys.stderr)
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
    if cmd == "sessions":
        for row in sessions():
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
        print(messages(lang=lang, untagged=untagged, limit=limit, session=session))
        return 0
    if cmd == "tag":
        if not argv[1:]:
            print('usage: capture.py tag "<id>=<code[,code]>" ...', file=sys.stderr)
            return 1
        ok, errors = tag(argv[1:])
        print(f"tagged {ok}")
        for e in errors:
            print(e, file=sys.stderr)
        return 1 if errors else 0
    if cmd == "mark-processed":
        session = None
        if len(argv) >= 3 and argv[1] == "--session":
            session = argv[2]
        print(mark_processed(session=session))
        return 0
    if cmd == "mark-drills":
        print(mark_drills())
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
        print(paths())
        return 0
    print("unknown command: " + cmd, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
