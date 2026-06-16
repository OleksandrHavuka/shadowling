"""cliutil.py - shared helpers for the thin skill entrypoints (stdlib only,
Python 3.9+). Imported after each entrypoint's sys.path bootstrap to the plugin
root, so one definition serves every entrypoint instead of being copy-pasted.

Holds no SQL and no I/O: it only formats result lines. The entrypoints keep their
own stderr-print + `return 1` contract.
"""


def format_loot_line(action, row):
    """One result line for a /loot (or friction auto-loot) vocab add. `action`
    is the Vocab.add verb (add/relearn/refresh/untranslated); `row` is the
    returned vocab dict. Kept here so /loot and the friction loop print one shape.
    """
    return "{}: {} = {} (remaining {}, {})".format(
        action, row["word"], row["translation"], row["remaining"], row["status"]
    )
