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
    def insert(cls, values):
        """values: dict over insert_cols. Returns the incident count for the
        record's key AFTER the insert (1 = first occurrence).

        The chokepoint: normalizes cls.key via cls.key_norm and rejects a key
        that normalizes to empty/blank by raising ValueError (the entrypoint
        prints it to stderr so the LLM self-corrects — same contract as skillio)."""
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
        con = connect()
        try:
            with con:
                con.execute(sql, row)
            return con.execute(
                f'SELECT COUNT(*) FROM {cls.table} WHERE "{cls.key}" = ?',
                (key,),
            ).fetchone()[0]
        finally:
            con.close()

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
                con.execute(f"DELETE FROM {cls.table}")
            return "dropped"
        finally:
            con.close()
