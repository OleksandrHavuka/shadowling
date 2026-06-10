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
import os
import re
import sqlite3
import sys
from contextlib import closing
from datetime import datetime

from core import config_ready, data_dir, last_user_text

MIN_LETTERS = 8  # below this it's not analyzable prose / not worth logging

# Claude Code wraps slash-command / local-command turns in these tags. Such turns
# are not the user's own writing, so they must never be captured for analysis.
COMMAND_WRAPPERS = ("<command-", "<local-command-")

LANG_CODE = re.compile(r"^[a-z]{2,3}$")  # ISO-style; "und" fits too


def db_path():
    return os.path.join(data_dir(), "shadowling.db")


def _now():
    return datetime.now().isoformat(timespec="seconds")


def _migrate_legacy(con):
    """One-time import of the pre-sqlite JSONL files, then remove them."""
    from jsonl import read as jsonl_read
    legacy_corpus = os.path.join(data_dir(), "messages.log.jsonl")
    legacy_buffer = os.path.join(data_dir(), "buffer.jsonl")
    if os.path.exists(legacy_corpus):  # already-debriefed history
        stamp = _now()
        for rec in jsonl_read(legacy_corpus):
            con.execute(
                "INSERT INTO messages(ts, text, processed_at) VALUES (?, ?, ?)",
                (rec.get("ts", ""), rec.get("text", ""), stamp))
        os.remove(legacy_corpus)
    if os.path.exists(legacy_buffer):  # still awaiting a debrief
        for rec in jsonl_read(legacy_buffer):
            con.execute("INSERT INTO messages(ts, text) VALUES (?, ?)",
                        (rec.get("ts", ""), rec.get("text", "")))
        os.remove(legacy_buffer)


def _db():
    path = db_path()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    fresh = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                        "AND name='messages'").fetchone() is None
    con.execute("""CREATE TABLE IF NOT EXISTS messages(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT NOT NULL,
        text TEXT NOT NULL,
        langs TEXT CHECK (langs IS NULL OR json_valid(langs)),
        processed_at TEXT)""")
    if fresh:
        with con:
            _migrate_legacy(con)
    return con


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
    with closing(_db()) as con, con:
        last = con.execute(
            "SELECT text FROM messages ORDER BY id DESC LIMIT 1").fetchone()
        if last is not None and last["text"] == text:
            return False  # guard against repeated Stop on the same turn
        con.execute("INSERT INTO messages(ts, text) VALUES (?, ?)",
                    (_now(), text))
    return True


# --- working-batch reads (processed_at IS NULL) ------------------------------

def pending_count():
    with closing(_db()) as con:
        return con.execute("SELECT COUNT(*) FROM messages "
                           "WHERE processed_at IS NULL").fetchone()[0]


def _xml(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;")
             .replace(">", "&gt;").replace('"', "&quot;"))


def messages(lang=None, untagged=False, limit=None):
    """Unprocessed rows as an XML block; optionally sliced."""
    sql = ("SELECT id, ts, text, langs FROM messages "
           "WHERE processed_at IS NULL")
    params = []
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
    with closing(_db()) as con:
        rows = con.execute(sql, params).fetchall()
    if not rows:
        return "<messages></messages>"
    out = ["<messages>"]
    for r in rows:
        out.append('  <m id="{0}" ts="{1}" langs="{2}">{3}</m>'.format(
            r["id"], _xml(r["ts"]), _xml(r["langs"] or ""), _xml(r["text"])))
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
    with closing(_db()) as con, con:
        for langs_json, mid in updates:
            cur = con.execute("UPDATE messages SET langs=? WHERE id=?",
                              (langs_json, mid))
            if cur.rowcount == 0:
                errors.append("unknown id: {0}".format(mid))
            else:
                ok += 1
    return ok, errors


def mark_processed():
    """Stamp tagged+unprocessed rows; untagged rows stay for the next batch."""
    with closing(_db()) as con, con:
        cur = con.execute("UPDATE messages SET processed_at=? "
                          "WHERE langs IS NOT NULL AND processed_at IS NULL",
                          (_now(),))
        kept = con.execute("SELECT COUNT(*) FROM messages "
                           "WHERE processed_at IS NULL").fetchone()[0]
    return "processed {0}, kept {1} untagged".format(cur.rowcount, kept)


# --- escape hatch -------------------------------------------------------------

def query(sql):
    """Run a SELECT against a READ-ONLY connection; returns a list of dicts."""
    with closing(_db()):  # ensure the store + schema exist before opening ro
        pass
    uri = "file:{0}?mode=ro".format(db_path())
    with closing(sqlite3.connect(uri, uri=True)) as con:
        con.row_factory = sqlite3.Row
        return [dict(r) for r in con.execute(sql)]


def paths():
    return "db: " + db_path()


def main(argv):
    if not argv:
        print("usage: capture.py {capture|pending-count|messages|tag|"
              "mark-processed|query|paths} ...", file=sys.stderr)
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
        lang, untagged, limit = None, False, None
        args, i = argv[1:], 0
        while i < len(args):
            if args[i] == "--untagged":
                untagged, i = True, i + 1
            elif args[i] == "--lang" and i + 1 < len(args):
                lang, i = args[i + 1], i + 2
            elif args[i] == "--limit" and i + 1 < len(args) and args[i + 1].isdigit():
                limit, i = int(args[i + 1]), i + 2
            else:
                print("unknown option: " + args[i], file=sys.stderr)
                return 1
        print(messages(lang=lang, untagged=untagged, limit=limit))
        return 0
    if cmd == "tag":
        if not argv[1:]:
            print('usage: capture.py tag "<id>=<code[,code]>" ...', file=sys.stderr)
            return 1
        ok, errors = tag(argv[1:])
        print("tagged {0}".format(ok))
        for e in errors:
            print(e, file=sys.stderr)
        return 1 if errors else 0
    if cmd == "mark-processed":
        print(mark_processed())
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
