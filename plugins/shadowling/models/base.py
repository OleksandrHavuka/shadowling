"""models/base.py - base repository over the sqlite incident tables.

A model declares its append-only incident `table`, its computed ranking
`view`, the grouping `key` column, and the ordered `insert_cols`. Writes are
INSERTs (date-stamped); reads go to the view, whose computed columns
(counter, created_at, updated_at, latest-example fields) replicate the old
markdown product headers exactly. No updates, no deletes of incident text.
"""
from appdb import connect
from core import today


def norm_key(s):
    """Natural-key normalization (idiom/verb): casefold + whitespace collapse —
    preserves the old md layer's dedup semantics under exact SQL GROUP BY."""
    return " ".join(s.split()).lower()


class Model:
    table = None        # incident table name
    view = None         # ranking view name
    key = None          # grouping/key column (same name in table and view)
    insert_cols = []    # ordered columns set by insert() (besides date)

    @classmethod
    def insert(cls, values):
        """values: dict over insert_cols. Returns the incident count for the
        record's key AFTER the insert (1 = first occurrence)."""
        cols = ["created_at"] + list(cls.insert_cols)
        row = [today()] + [values[c] for c in cls.insert_cols]
        sql = "INSERT INTO {0}({1}) VALUES ({2})".format(
            cls.table,
            ", ".join('"{0}"'.format(c) for c in cols),
            ", ".join("?" for _ in cols))
        con = connect()
        try:
            with con:
                con.execute(sql, row)
            return con.execute(
                'SELECT COUNT(*) FROM {0} WHERE "{1}" = ?'.format(
                    cls.table, cls.key),
                (values[cls.key],)).fetchone()[0]
        finally:
            con.close()

    @classmethod
    def select(cls, key=None):
        con = connect()
        try:
            if key is None:
                rows = con.execute(
                    "SELECT * FROM {0}".format(cls.view)).fetchall()
                return [cls._public(r) for r in rows]
            r = con.execute(
                'SELECT * FROM {0} WHERE "{1}" = ?'.format(cls.view, cls.key),
                (key,)).fetchone()
            return cls._public(r) if r is not None else None
        finally:
            con.close()

    @staticmethod
    def _public(row):
        d = dict(row)
        d.pop("last_id", None)  # internal ordering plumbing
        return d

    @classmethod
    def drop(cls):
        con = connect()
        try:
            with con:
                con.execute("DELETE FROM {0}".format(cls.table))
            return "dropped"
        finally:
            con.close()
