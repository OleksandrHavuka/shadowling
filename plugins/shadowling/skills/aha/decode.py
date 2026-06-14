#!/usr/bin/env python3
"""skills/aha/decode.py - thin entrypoint for /aha: record one decode incident.
Parses stdin tags, calls the decode repository, prints inserted/incremented. No
SQL. The plugin imports (models/tagio) are inside main() after a sys.path
bootstrap to the plugin root: the script's own dir is on sys.path[0] when run, so
`models` is not importable until the bootstrap runs (keeps them at function scope
-> no E402). The <type> tag maps to the recorder's `kind` param locally here."""

import os
import sys


def main(argv):
    sys.path.insert(
        0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
    )
    from models import decode
    from tagio import TEXT, read_fields

    if not argv or argv[0] != "record":
        print("usage: decode.py record  (tags on stdin)", file=sys.stderr)
        return 1
    try:
        f = read_fields(
            {
                "slug": TEXT,
                "type": TEXT,
                "expression": TEXT,
                "meaning": TEXT,
                "takeaway": TEXT,
                "learner_wrote": TEXT,
                "context": TEXT,
            }
        )
        print(
            decode.record(
                f["slug"],
                f["type"],
                f["expression"],
                f["meaning"],
                f["takeaway"],
                f["learner_wrote"],
                f["context"],
            )
        )
    except ValueError as e:
        print("error: " + str(e), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
