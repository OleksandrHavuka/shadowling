#!/usr/bin/env python3
"""db.py - CLI over the category repositories (sqlite data layer).

  python3 db.py <repo> record <args…>   # append one incident (category recorder)
  python3 db.py <repo> select [<key>]   # ranked view: JSON per row / one object
  python3 db.py <repo> export           # ranked view as a markdown table (stdout)
  python3 db.py <repo> drop             # delete ALL of the category's incidents

<repo> is looked up in models.REGISTRY. Repos: grammar, rephrasing, idioms,
verbs, decode, friction.
"""
import json
import sys

import models


def _cell(value):
    return str(value).replace("|", "\\|").replace("\n", " ")


def export_md(model):
    rows = model.select()
    if not rows:
        return "(empty)"
    headers = list(rows[0].keys())
    out = ["| " + " | ".join(headers) + " |",
           "| " + " | ".join("---" for _ in headers) + " |"]
    for r in rows:
        out.append("| " + " | ".join(_cell(r[h]) for h in headers) + " |")
    return "\n".join(out)


def main(argv):
    if len(argv) < 2:
        print("usage: db.py <repo> {record|select|export|drop} [args]",
              file=sys.stderr)
        return 1
    name, op, args = argv[0], argv[1], argv[2:]
    if op == "record":
        recorder = models.RECORDERS.get(name)
        if recorder is None:
            print("unknown recorder: " + name, file=sys.stderr)
            return 1
        try:
            print(recorder(*args))
        except (TypeError, ValueError, KeyError) as e:
            print("error: " + str(e), file=sys.stderr)
            return 1
        return 0
    model = models.REGISTRY.get(name)
    if model is None:
        print("unknown repo: " + name, file=sys.stderr)
        return 1
    if op == "select":
        if args:
            row = model.select(args[0])
            if row is not None:
                print(json.dumps(row, ensure_ascii=False))
        else:
            for row in model.select():
                print(json.dumps(row, ensure_ascii=False))
        return 0
    if op == "export":
        print(export_md(model))
        return 0
    if op == "drop":
        print(model.drop())
        return 0
    print("unknown op: " + op, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
