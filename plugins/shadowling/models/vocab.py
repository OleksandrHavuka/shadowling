"""models/vocab.py - vocabulary glossing store (mutable state) over appdb.

The vocab table is the one sanctioned mutable incident store: each word carries a
`remaining` exposure budget that `scan_decrement` lowers until the word graduates
(status 'learned'). All vocab SQL lives here. `word_in_text`/`build_pattern` are
pure matching helpers (no DB), kept module-level like models/base.norm_key.
"""

import re
from datetime import datetime

from appdb import connect, tx

START_REMAINING = 10
STEM_MIN_LEN = 4


def _now():
    # full ISO timestamp for the vocab audit stamps, matching messages._now().
    return datetime.now().isoformat(timespec="seconds")


def _norm(s):
    return re.sub(r"\s+", " ", s).strip().lower()


def build_pattern(word):
    word = word.strip().lower()
    esc = re.escape(word)
    left = r"(?<!\w)"
    right = r"(?!\w)"
    if len(word) >= STEM_MIN_LEN and word[-1:].isalnum():
        body = esc + r"(?:s|es|ed|ing|d)?"
    else:
        body = esc
    return re.compile(left + body + right, re.IGNORECASE)


def word_in_text(word, text):
    return build_pattern(word).search(text) is not None


class Vocab:
    @staticmethod
    def add(word, translation):
        word = word.strip().lower()
        translation = translation.strip()
        # Guard against a failed/identity translation (the LLM echoing the term
        # back untranslated). Never persist such a row — signal the caller.
        if not translation or _norm(translation) == _norm(word):
            return "untranslated", {
                "word": word,
                "translation": translation,
                "remaining": "-",
                "status": "-",
            }
        now = _now()
        con = connect()
        try:
            with tx(con):  # BEGIN IMMEDIATE serializes the existence-read + write
                row = con.execute(
                    "SELECT * FROM vocab WHERE word = ?", (word,)
                ).fetchone()
                if row is None:
                    con.execute(
                        "INSERT INTO vocab(word, translation, remaining, status,"
                        " created_at, updated_at) VALUES (?, ?, ?, 'active', ?, ?)",
                        (word, translation, START_REMAINING, now, now),
                    )
                    action = "add"
                elif row["status"] == "learned":
                    con.execute(
                        "UPDATE vocab SET translation = ?, remaining = ?,"
                        " status = 'active', updated_at = ? WHERE word = ?",
                        (translation, START_REMAINING, now, word),
                    )
                    action = "relearn"
                else:
                    con.execute(
                        "UPDATE vocab SET translation = ?, updated_at = ?"
                        " WHERE word = ?",
                        (translation, now, word),
                    )
                    action = "refresh"
            new = con.execute("SELECT * FROM vocab WHERE word = ?", (word,)).fetchone()
            return action, dict(new)
        finally:
            con.close()

    @staticmethod
    def remove(word):
        word = word.strip().lower()
        con = connect()
        try:
            with con:
                cur = con.execute("DELETE FROM vocab WHERE word = ?", (word,))
            return cur.rowcount > 0
        finally:
            con.close()

    @staticmethod
    def list_active():
        con = connect()
        try:
            return [
                dict(r)
                for r in con.execute(
                    "SELECT * FROM vocab WHERE status = 'active' ORDER BY rowid"
                )
            ]
        finally:
            con.close()

    @staticmethod
    def relearn(word):
        """Reset a graduated word back into the active glossing loop
        (remaining -> START_REMAINING, status 'active')."""
        con = connect()
        try:
            with con:
                con.execute(
                    "UPDATE vocab SET remaining = ?, status = 'active' WHERE word = ?",
                    (START_REMAINING, word),
                )
        finally:
            con.close()

    @staticmethod
    def scan_decrement(text):
        """Decrement every active word that appears in `text`; graduate at 0.
        Returns the list of changed words. `text` is the assistant reply being
        scanned for exposures."""
        changed = []
        now = _now()
        con = connect()
        try:
            rows = con.execute("SELECT * FROM vocab WHERE status = 'active'").fetchall()
            with con:
                for r in rows:
                    if not word_in_text(r["word"], text):
                        continue
                    remaining = max(r["remaining"] - 1, 0)
                    status = "learned" if remaining == 0 else "active"
                    con.execute(
                        "UPDATE vocab SET remaining = ?, status = ?,"
                        " updated_at = ? WHERE word = ?",
                        (remaining, status, now, r["word"]),
                    )
                    changed.append(r["word"])
            return changed
        finally:
            con.close()
