#!/usr/bin/env python3
"""sql.py - dev CLI for arbitrary SQL against shadowling.db (stdlib only).

Read-only by default: the query runs on a URI mode=ro connection, so ANY
mutation fails at the connection level, not by SQL inspection. Writes need
the explicit --write flag and are preceded by an automatic consistent
snapshot (sqlite online backup API — a raw file copy of a WAL db can lose
unflushed -wal frames) into <data_dir>/backups/, keep-last-10. This is the
dev escape hatch BEHIND the data layer: prefer db.py / vocab.py / capture.py
verbs first (see the shadowling-db project skill).

  python3 sql.py "<SQL>" [param ...]          # ro; JSON object per row
  python3 sql.py --md "<SQL>" [param ...]     # ro; markdown table
  python3 sql.py --write "<SQL>" [param ...]  # rw: snapshot, then execute
  python3 sql.py backup                       # manual snapshot; prints path
"""
import json
import os
import sqlite3
import sys
from datetime import datetime

from appdb import connect, query
from core import data_dir
from db import render_md

KEEP = 10  # snapshots retained in <data_dir>/backups/

USAGE = "usage: sql.py [--md|--write] \"<SQL>\" [param ...] | sql.py backup"


def snapshot(con):
    raise NotImplementedError  # Task 3


def run_write(sql_text, params):
    raise NotImplementedError  # Task 3


def main(argv):
    if not argv:
        print(USAGE, file=sys.stderr)
        return 1
    if argv[0] == "backup":
        con = connect()
        try:
            print(snapshot(con))
        finally:
            con.close()
        return 0
    md = write = False
    if argv[0] == "--md":
        md, argv = True, argv[1:]
    elif argv[0] == "--write":
        write, argv = True, argv[1:]
    if not argv or argv[0].startswith("--"):
        print(USAGE, file=sys.stderr)
        return 1
    sql_text, params = argv[0], tuple(argv[1:])
    try:
        if write:
            return run_write(sql_text, params)
        rows = query(sql_text, params)
    except sqlite3.Error as e:
        print("error: " + str(e), file=sys.stderr)
        return 1
    if md:
        print(render_md(rows) if rows else "(empty)")
    else:
        for r in rows:
            print(json.dumps(r, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
