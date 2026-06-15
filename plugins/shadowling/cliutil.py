"""cliutil.py - shared helpers for the thin skill entrypoints (stdlib only,
Python 3.9+). Imported after each entrypoint's sys.path bootstrap to the plugin
root, so one definition serves every entrypoint instead of being copy-pasted.

Holds no SQL and no I/O: it only parses argv slices and formats result lines.
The entrypoints keep their own stderr-print + `return 1` contract; these helpers
signal a bad slice by raising ValueError with the user-facing message.
"""


def parse_message_slice_args(args):
    """Parse the shared `messages`-op argv into kwargs for `Messages.list`.

    Accepts --untagged (flag), --lang <v>, --session <v>, --limit <n> (digits).
    Returns {"lang", "untagged", "limit", "session"}. Raises ValueError (whose
    message the caller prints to stderr before returning 1) on a bad --limit or
    any unrecognized token, matching the previous inline parser's behavior.
    """
    lang, untagged, limit, session = None, False, None, None
    i = 0
    while i < len(args):
        if args[i] == "--untagged":
            untagged, i = True, i + 1
        elif args[i] == "--lang" and i + 1 < len(args):
            lang, i = args[i + 1], i + 2
        elif args[i] == "--session" and i + 1 < len(args):
            session, i = args[i + 1], i + 2
        elif args[i] == "--limit" and i + 1 < len(args) and args[i + 1].isdigit():
            limit, i = int(args[i + 1]), i + 2
        else:
            raise ValueError("unknown option: " + args[i])
    return {"lang": lang, "untagged": untagged, "limit": limit, "session": session}
