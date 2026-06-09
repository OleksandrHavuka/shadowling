#!/usr/bin/env python3
"""jsonl.py - append-only JSONL log helper (stdlib only, Python 3.9+).

One JSON object per line. Backs the buffer and every `.log.jsonl` (the raw corpus
and the per-instance findings). True O(1) append; lossless (newlines/pipes survive
JSON escaping); corrupt lines are skipped on read.
"""
import json
import os


def append(path, obj):
    """Append one object as a JSON line, creating the parent dir if needed."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def read(path):
    """Return a list of objects; [] if the file is missing. Bad lines are skipped."""
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows
