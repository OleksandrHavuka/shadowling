#!/usr/bin/env python3
"""mddb.py - markdown table as a tiny keyed store: low-level engine.

Domain-agnostic. Parses/serializes a markdown table and exposes the violation
types that the Model layer raises. Knows nothing about schemas or constraints.
Standard library only, Python 3.9+.
"""
import os
import re


class UniqueViolation(Exception):
    """Raised when inserting a row whose key already exists."""


class NotFound(Exception):
    """Raised when updating/deleting a key that does not exist."""


def norm_key(s):
    """Normalized dedup key: collapse whitespace, trim, lowercase."""
    return re.sub(r"\s+", " ", s).strip().lower()


def _escape_cell(s):
    return s.replace("|", "\\|").replace("\r", " ").replace("\n", " ").strip()


def _split_row(line):
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    parts = re.split(r"(?<!\\)\|", line)
    return [p.strip() for p in parts]


def _is_separator(cells):
    return all(c and set(c) <= set("-: ") for c in cells)


def read_table(path):
    """Return (headers, rows). rows are dicts keyed by header. ([], []) if missing.

    The first markdown table line is the header; the separator line is skipped.
    Short rows pad to empty trailing cells; extra cells are dropped.
    """
    if not os.path.exists(path):
        return [], []
    headers = None
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f.read().splitlines():
            if not line.strip().startswith("|"):
                continue
            cells = _split_row(line)
            if headers is None:
                headers = cells
                continue
            if _is_separator(cells):
                continue
            cells = [c.replace("\\|", "|") for c in cells]
            rows.append({h: (cells[i] if i < len(cells) else "")
                         for i, h in enumerate(headers)})
    if headers is None:
        return [], []
    return headers, rows


def write_table(path, headers, rows):
    """Rewrite the whole file: header, separator, then rows in header order.

    Cells are single-space padded (no column alignment) to keep diffs minimal.
    """
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    lines = ["| " + " | ".join(headers) + " |",
             "| " + " | ".join("---" for _ in headers) + " |"]
    for row in rows:
        lines.append(
            "| " + " | ".join(_escape_cell(str(row.get(h, ""))) for h in headers) + " |")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
