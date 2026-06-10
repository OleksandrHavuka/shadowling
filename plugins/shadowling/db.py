#!/usr/bin/env python3
"""db.py - generic CLI over the model repositories (markdown data layer).

  python3 db.py <repo> select [<key>]
  python3 db.py <repo> {insert|update|upsert} <col> <col> ...   # positional, in
                                                                # column order,
                                                                # skipping `counter`
  python3 db.py <repo> delete <key>
  python3 db.py <repo> drop

<repo> is looked up in models.REGISTRY. Constraint violations print to stderr and
exit nonzero. `select` prints one JSON object per row.
"""
import json
import sys

import models
from mddb import NotFound, UniqueViolation


def main(argv):
    if len(argv) < 2:
        print("usage: db.py <repo> {select|insert|update|upsert|delete|drop} [args]",
              file=sys.stderr)
        return 1
    name, op = argv[0], argv[1]
    args = argv[2:]
    if op == "record":
        recorder = models.RECORDERS.get(name)
        if recorder is None:
            print("unknown recorder: " + name, file=sys.stderr)
            return 1
        try:
            print(recorder(*args))
        except (UniqueViolation, NotFound, ValueError, TypeError) as e:
            print("error: " + str(e), file=sys.stderr)
            return 1
        return 0
    model = models.REGISTRY.get(name)
    if model is None:
        print("unknown repo: " + name, file=sys.stderr)
        return 1
    try:
        if op == "select":
            key = args[0] if args else None
            result = model.select(key)
            if key is None:
                for row in result:
                    print(json.dumps(row, ensure_ascii=False))
            elif result is not None:
                print(json.dumps(result, ensure_ascii=False))
            return 0
        if op in ("insert", "update", "upsert"):
            input_cols = [c for c in model.columns if c != model.counter]
            print(getattr(model, op)(dict(zip(input_cols, args))))
            return 0
        if op == "delete":
            if not args:
                print("delete needs a key", file=sys.stderr)
                return 1
            print(model.delete(args[0]))
            return 0
        if op == "drop":
            print(model.drop())
            return 0
        print("unknown op: " + op, file=sys.stderr)
        return 1
    except (UniqueViolation, NotFound, ValueError) as e:
        print("error: " + str(e), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
