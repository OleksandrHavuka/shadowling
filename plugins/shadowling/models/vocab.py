"""models/vocab.py - vocabulary glossing store (mutable state) over appdb.

The vocab table is the one sanctioned mutable incident store: each word carries a
`remaining` exposure budget that `scan_decrement` lowers until the word graduates
(status 'learned'). All vocab SQL lives here. `word_in_text`/`build_pattern` are
pure matching helpers (no DB), kept module-level like models/base.norm_key.
"""

import re

import core
from appdb import connect, tx

START_REMAINING = 10
STEM_MIN_LEN = 4


def _norm(s):
    return re.sub(r"\s+", " ", s).strip().lower()


def build_pattern(word):
    word = word.strip().lower()
    esc = re.escape(word)
    left = r"(?<!\w)"
    right = r"(?!\w)"
    if len(word) >= STEM_MIN_LEN and word[-1:].isalnum():
        # The bare 'd' is for '-e' stems (care -> cared). Applying it to any word
        # over-matches (bear -> "beard", boar -> "board", bran -> "brand") and
        # decrements the wrong vocab entry, so gate it on an '-e' ending.
        tail = "s|es|ed|ing|d" if word.endswith("e") else "s|es|ed|ing"
        body = esc + f"(?:{tail})?"
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
        # back untranslated). Never persist such a row — signal the caller with a
        # None row (no fabricated "-" presentation placeholders).
        if not translation or _norm(translation) == _norm(word):
            return "untranslated", None
        now = core.now()
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
            with tx(con):  # vocab delete + orphan-mastery cleanup, atomic
                cur = con.execute("DELETE FROM vocab WHERE word = ?", (word,))
                con.execute(
                    "DELETE FROM mastery WHERE item_kind = 'vocab' AND item_key = ?",
                    (word,),
                )
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
    def relearn(word, con=None):
        """Reset a graduated word back into the active glossing loop
        (remaining -> START_REMAINING, status 'active'). Pass an open `con` to run
        the reset inside the caller's transaction (Tutor.record committing a vocab
        `fail`) so it commits atomically with their writes; with no `con` it opens
        and commits its own."""
        sql = "UPDATE vocab SET remaining = ?, status = 'active' WHERE word = ?"
        params = (START_REMAINING, word)
        if con is not None:
            con.execute(sql, params)  # the caller's `with con:` commits it
            return
        con = connect()
        try:
            with con:
                con.execute(sql, params)
        finally:
            con.close()

    @staticmethod
    def scan_decrement(text):
        """Decrement every active word that appears in `text`; graduate at 0.
        Returns the list of changed words. `text` is the assistant reply being
        scanned for exposures.

        One atomic statement, no read-then-write: the decrement is RELATIVE
        (`remaining - 1`), so concurrent scans from independent Stop hooks compose
        correctly instead of both writing an absolute value from a stale read.
        `word_matches` mirrors the registered-function pattern in
        `Messages.mark_drills`. Requires SQLite >= 3.35 for RETURNING (see DEV.md)."""
        now = core.now()
        con = connect()
        try:
            con.create_function("word_matches", 2, word_in_text)
            with con:
                # In SQLite an UPDATE's SET/WHERE expressions read the PRE-update
                # row value regardless of assignment order, so the CASE sees the
                # old `remaining` even though `remaining` is assigned above it.
                return [
                    r["word"]
                    for r in con.execute(
                        "UPDATE vocab SET remaining = MAX(remaining - 1, 0),"
                        " status = CASE WHEN remaining - 1 <= 0 THEN 'learned'"
                        " ELSE 'active' END, updated_at = ?"
                        " WHERE status = 'active' AND word_matches(word, ?)"
                        " RETURNING word",
                        (now, text),
                    )
                ]
        finally:
            con.close()
