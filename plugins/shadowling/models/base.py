"""models/base.py - base repository over the sqlite incident tables.

A model declares its append-only incident `table`, its computed ranking
`view`, the grouping `key` column, and the ordered `insert_cols`. Writes are
INSERTs (date-stamped); reads go to the view, whose computed columns
(counter, created_at, updated_at, latest-example fields) replicate the old
markdown product headers exactly. No updates, no deletes of incident text.
"""

from __future__ import annotations

from typing import ClassVar

from appdb import connect
from core import slugify, today


def norm_key(s: str) -> str:
    """Natural-key normalization (idiom/verb): casefold + whitespace collapse —
    preserves the old md layer's dedup semantics under exact SQL GROUP BY."""
    return " ".join(s.split()).lower()


class Model:
    table: ClassVar[str]  # incident table name
    view: ClassVar[str]  # ranking view name
    key: ClassVar[str]  # grouping/key column (same name in table and view)
    insert_cols: ClassVar[list[str]]  # ordered columns set by insert() (besides date)
    # {column: allowed_values} for constrained text columns (the decode/friction
    # `type` taxonomy). Validated at insert() so a bad value can never persist.
    enums: ClassVar[dict] = {}

    # The single key normalizer for cls.key, applied AT insert() so every caller
    # (and any future one) gets it for free. Subclasses override per their key
    # kind: slugify for slug-keyed models, norm_key for natural idiom/verb keys.
    @staticmethod
    def key_norm(s: str) -> str:
        return slugify(s)

    @classmethod
    def _insert_on(cls, con, values):
        """The full insert body on an ALREADY-OPEN connection — opens no
        transaction of its own. Normalizes cls.key via cls.key_norm (rejecting a
        key that normalizes to empty/blank with ValueError), validates cls.enums,
        INSERTs the date-stamped row, then reads back the running incident count
        for the key (visible to this same connection inside the caller's
        transaction). The single chokepoint, now reusable both standalone
        (insert) and inside a caller's tx (insert_with_con)."""
        key = cls.key_norm(values[cls.key])
        if not key:
            raise ValueError(
                f"{cls.__name__}: key '{cls.key}' is empty after normalization "
                f"(got {values[cls.key]!r}); provide a non-blank value"
            )
        values = {**values, cls.key: key}
        for col, allowed in cls.enums.items():
            val = values[col]
            if val not in allowed:
                raise ValueError(
                    f"{cls.__name__}: {col}={val!r} is not one of {sorted(allowed)}"
                )
        cols = ["created_at"] + list(cls.insert_cols)
        row = [today()] + [values[c] for c in cls.insert_cols]
        sql = "INSERT INTO {}({}) VALUES ({})".format(
            cls.table, ", ".join(f'"{c}"' for c in cols), ", ".join("?" for _ in cols)
        )
        con.execute(sql, row)
        return con.execute(
            f'SELECT COUNT(*) FROM {cls.table} WHERE "{cls.key}" = ?',
            (key,),
        ).fetchone()[0]

    @classmethod
    def insert(cls, values):
        """values: dict over insert_cols. Returns the incident count for the
        record's key AFTER the insert (1 = first occurrence). Opens its own
        connection + transaction; the body lives in _insert_on (the count read
        now sits inside the commit block — same value, same-connection
        visibility). The entrypoint prints any ValueError to stderr so the LLM
        self-corrects — same contract as skillio."""
        con = connect()
        try:
            with con:
                return cls._insert_on(con, values)
        finally:
            con.close()

    @classmethod
    def insert_with_con(cls, values, con):
        """Like insert(), but runs on the caller's already-open connection so the
        write joins the caller's transaction (the debrief driver's per-session
        tx). The caller's `with tx(con):` commits or rolls back; a ValueError
        here (empty key / bad enum) rolls the WHOLE caller transaction back, so a
        partial session is never persisted. Returns the post-insert count (the
        driver ignores it)."""
        return cls._insert_on(con, values)

    @classmethod
    def select(cls, key=None):
        con = connect()
        try:
            if key is None:
                rows = con.execute(f"SELECT * FROM {cls.view}").fetchall()
                return [cls._public(r) for r in rows]
            r = con.execute(
                f'SELECT * FROM {cls.view} WHERE "{cls.key}" = ?', (key,)
            ).fetchone()
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
                cur = con.execute(f"DELETE FROM {cls.table}")
            return cur.rowcount
        finally:
            con.close()
