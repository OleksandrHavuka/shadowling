"""models/anki_link.py - the anki_link mirror table (Spec 2 / Variant B).

anki_link holds Anki's per-word review progress (note/card ids + the FSRS-exposed
interval/reps/lapses/due) inside shadowling.db, so all progress lives in one
database. ALL anki_link SQL lives here; anki.py (the transport) stays SQL-free.
`word` is a logical ref to vocab.word — always present (soft-delete), never
orphaned. Mirrors the con= transaction-sharing pattern of models/vocab.py: the
pull phase shares one transaction with Vocab.relearn.
"""

from appdb import connect, tx

# The writable progress columns (everything but the `word` PK). upsert() writes
# only the ones a caller actually passes, so a partial pull never clobbers fields
# it didn't fetch.
COLS = ("note_id", "card_id", "deck", "due", "interval", "reps", "lapses", "synced_at")


class AnkiLink:
    @staticmethod
    def _upsert_on(con, word, fields):
        """Insert-or-update on an ALREADY-OPEN connection (opens no tx of its own).
        Writes only the provided COLS keys; unknown keys are ignored."""
        word = word.strip().lower()
        clean = {k: fields[k] for k in COLS if k in fields}
        row = con.execute(
            "SELECT word FROM anki_link WHERE word = ?", (word,)
        ).fetchone()
        if row is None:
            cols = ["word"] + list(clean)
            vals = [word] + [clean[c] for c in clean]
            placeholders = ", ".join("?" * len(cols))
            con.execute(
                f"INSERT INTO anki_link({', '.join(cols)}) VALUES ({placeholders})",
                vals,
            )
        elif clean:
            sets = ", ".join(f"{c} = ?" for c in clean)
            con.execute(
                f"UPDATE anki_link SET {sets} WHERE word = ?",
                [*clean.values(), word],
            )

    @staticmethod
    def upsert(word, con=None, **fields):
        """Insert or update the anki_link row for `word`, writing only the provided
        progress columns. With con=None opens its own immediate transaction; given
        a caller's open `con` the write commits atomically with it."""
        if con is not None:
            return AnkiLink._upsert_on(con, word, fields)
        con = connect()
        try:
            with tx(con):
                return AnkiLink._upsert_on(con, word, fields)
        finally:
            con.close()

    @staticmethod
    def get(word):
        con = connect()
        try:
            r = con.execute(
                "SELECT * FROM anki_link WHERE word = ?", (word.strip().lower(),)
            ).fetchone()
            return dict(r) if r is not None else None
        finally:
            con.close()

    @staticmethod
    def all():
        con = connect()
        try:
            return [
                dict(r) for r in con.execute("SELECT * FROM anki_link ORDER BY word")
            ]
        finally:
            con.close()

    @staticmethod
    def delete(word):
        con = connect()
        try:
            with tx(con):
                cur = con.execute(
                    "DELETE FROM anki_link WHERE word = ?", (word.strip().lower(),)
                )
            return cur.rowcount > 0
        finally:
            con.close()
