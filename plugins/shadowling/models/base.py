"""models/base.py - base repository: a markdown table with declarative constraints.

A model declares its shape (`file`, `columns`) and constraints (`key` =
uniqueness, `counter` = auto-increment). The base enforces them: strict `insert`
(UniqueViolation on dup), strict `update`/`delete` (NotFound on miss), lenient
`upsert` (insert-or-bump) and `select`. A model with no `key` is append-only.
"""
import os

from core import data_dir, today
from mddb import NotFound, UniqueViolation, norm_key, read_table, write_table


def _to_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


class Model:
    file = None              # filename under data_dir()
    columns = []             # ordered headers (also the validation set)
    key = None               # primary-key column (uniqueness); None => append-only
    counter = None           # auto-increment tally column; None => none
    created = None           # date-stamped once on insert; None => none
    updated = None           # date-stamped on every write; None => none

    # --- internals -------------------------------------------------------
    @classmethod
    def _path(cls):
        return os.path.join(data_dir(), cls.file)

    @classmethod
    def _rows(cls):
        return read_table(cls._path())[1]

    @classmethod
    def _write(cls, rows):
        write_table(cls._path(), cls.columns, rows)

    @classmethod
    def _blank(cls):
        return {c: "" for c in cls.columns}

    @classmethod
    def _touch(cls, rec, is_new):
        """Stamp the lifecycle dates: `created` once on insert, `updated` every write."""
        now = today()
        if is_new and cls.created:
            rec[cls.created] = now
        if cls.updated:
            rec[cls.updated] = now

    @classmethod
    def _validate(cls, row):
        unknown = [c for c in row if c not in cls.columns]
        if unknown:
            raise ValueError("{0}: unknown column(s) {1}".format(cls.__name__, unknown))

    @classmethod
    def _index(cls, rows, key):
        nk = norm_key(str(key))
        for i, r in enumerate(rows):
            if norm_key(r.get(cls.key, "")) == nk:
                return i
        return -1

    # --- CRUD ------------------------------------------------------------
    @classmethod
    def select(cls, key=None):
        rows = cls._rows()
        if key is None:
            return rows
        i = cls._index(rows, key)
        return rows[i] if i >= 0 else None

    @classmethod
    def insert(cls, row):
        cls._validate(row)
        rows = cls._rows()
        if cls.key is not None and cls._index(rows, row.get(cls.key, "")) >= 0:
            raise UniqueViolation(
                "{0}: {1}={2} exists".format(cls.__name__, cls.key, row.get(cls.key)))
        new = cls._blank()
        new.update(row)
        if cls.counter:
            new[cls.counter] = "1"
        cls._touch(new, is_new=True)
        rows.append(new)
        cls._write(rows)
        return "inserted"

    @classmethod
    def update(cls, row):
        cls._validate(row)
        if cls.key is None:
            raise ValueError("{0}: update needs a key".format(cls.__name__))
        rows = cls._rows()
        i = cls._index(rows, row.get(cls.key, ""))
        if i < 0:
            raise NotFound("{0}: {1}={2}".format(cls.__name__, cls.key, row.get(cls.key)))
        rows[i].update(row)
        cls._touch(rows[i], is_new=False)
        cls._write(rows)
        return "updated"

    @classmethod
    def upsert(cls, row):
        cls._validate(row)
        if cls.key is None:
            raise ValueError("{0}: upsert needs a key".format(cls.__name__))
        rows = cls._rows()
        i = cls._index(rows, row.get(cls.key, ""))
        if i >= 0:
            rows[i].update(row)
            if cls.counter:
                rows[i][cls.counter] = str(_to_int(rows[i].get(cls.counter)) + 1)
            cls._touch(rows[i], is_new=False)
            result = "incremented"
        else:
            new = cls._blank()
            new.update(row)
            if cls.counter:
                new[cls.counter] = "1"
            cls._touch(new, is_new=True)
            rows.append(new)
            result = "inserted"
        cls._write(rows)
        return result

    @classmethod
    def delete(cls, key):
        rows = cls._rows()
        i = cls._index(rows, key)
        if i < 0:
            raise NotFound("{0}: {1}={2}".format(cls.__name__, cls.key, key))
        rows.pop(i)
        cls._write(rows)
        return "deleted"

    @classmethod
    def drop(cls):
        path = cls._path()
        if os.path.exists(path):
            os.remove(path)
        return "dropped"
