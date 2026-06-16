#!/usr/bin/env python3
"""skillio.py - the single skill<->script I/O boundary (stdlib, py3.9+).

One responsibility: parse the invocation (heredoc free text + argv flags) and
render the one output format. Pure stdlib; no project imports; imported only by
entrypoints.

Skills feed model-authored values through a heredoc with a quoted delimiter
(`<<'SL_IN'`), so the shell does zero expansion and nothing needs escaping. This
module reads that body. There are exactly two flat field shapes, never nested:

  * TEXT        - a scalar value (may span lines) in `<name>...</name>`.
  * rows(*cols) - a list of short records as TSV in `<name>...</name>`: one record
                  per line, columns separated by a single TAB. TAB is the boundary
                  precisely so commas/quotes/`$`/spaces inside a value are free.

A schema is an ordered dict `{field_name: TEXT | rows(...)}`. `read_fields` returns
`{name: str}` for TEXT fields and `{name: list[dict]}` for rows fields.

Flat-field limitation (by design): each field is located independently from the
start of the text (not from a moving cursor), so a field body that contains the
LITERAL open tag of a *later* field — or a literal copy of its own close tag —
can contaminate or truncate extraction. Under the heredoc flat-field contract a
value holding literal `<field>` tokens is a corner case; a sequential-cursor
rewrite would forbid legitimate field reordering, so this is accepted and pinned
by FlatFieldLimitationTest, not rewritten.

The caller of these scripts is an LLM, so every failure raises a ValueError whose
message names the exact problem AND shows the expected syntax — so the model can
self-correct and retry the call instead of guessing.
"""

import sys

TEXT = object()  # sentinel marking a scalar prose field


class _Rows:
    __slots__ = ("cols",)

    def __init__(self, cols):
        self.cols = tuple(cols)


def rows(*cols):
    """Mark a field whose tag body is TSV -> list[dict] with these column keys."""
    if not cols:
        raise ValueError("rows() needs at least one column name")
    return _Rows(cols)


def _render_template(schema):
    """The correct stdin envelope for `schema`, shown to the LLM on any failure."""
    lines = []
    for name, kind in schema.items():
        if isinstance(kind, _Rows):
            lines.append(f"<{name}>")
            lines.append("<TAB>".join(kind.cols))
            lines.append("...")
            lines.append(f"</{name}>")
        else:
            lines.append(f"<{name}>...</{name}>")
    return "\n".join(lines)


def _fail(problem, schema):
    raise ValueError(problem + "\nexpected stdin format:\n" + _render_template(schema))


def _strip_layout_newlines(body):
    """Drop the single leading/trailing newline the heredoc layout adds, so a
    block-form `<a>\\nVALUE\\n</a>` yields VALUE verbatim while internal content
    (including newlines) is untouched."""
    if body.startswith("\n"):
        body = body[1:]
    if body.endswith("\n"):
        body = body[:-1]
    return body


def _extract(name, text, schema):
    """Inner body of `<name>...</name>` (nearest close), layout newlines stripped.

    Located from position 0, independent of other fields (so reordering is free).
    Trade-off: a literal `<name>`/`</name>` token inside another field's body can
    be matched here — the accepted flat-field limitation (see module docstring).
    """
    open_tag, close_tag = "<" + name + ">", "</" + name + ">"
    i = text.find(open_tag)
    if i == -1:
        _fail("missing required tag " + open_tag, schema)
    start = i + len(open_tag)
    j = text.find(close_tag, start)
    if j == -1:
        _fail(
            "tag " + open_tag + " is opened but never closed with " + close_tag,
            schema,
        )
    return _strip_layout_newlines(text[start:j])


def _parse_rows(name, body, cols, schema):
    out = []
    n = len(cols)
    for idx, line in enumerate(body.split("\n"), 1):
        if not line.strip():
            continue  # skip blank lines (e.g. a trailing heredoc newline)
        parts = line.rstrip("\r").split("\t")
        if len(parts) != n:
            _fail(
                "<{}> line {}: found {} tab-separated column(s), expected {}"
                " ({}); use exactly one TAB between columns, one record per"
                " line".format(name, idx, len(parts), n, ", ".join(cols)),
                schema,
            )
        out.append(dict(zip(cols, parts)))
    return out


def read_fields(schema, text=None):
    """Parse the heredoc body (stdin, or `text`) against `schema`.

    schema: ordered dict {field_name: TEXT | rows(...)}. Returns {name: str} for
    TEXT fields and {name: list[dict]} for rows fields. Unknown tags in the input
    are ignored. Raises ValueError (problem + expected-syntax template) on a
    missing tag, an unclosed tag, or a TSV row with the wrong column count.
    """
    if text is None:
        text = sys.stdin.read()
    result = {}
    for name, kind in schema.items():
        body = _extract(name, text, schema)
        if isinstance(kind, _Rows):
            result[name] = _parse_rows(name, body, kind.cols, schema)
        else:
            result[name] = body
    return result


# --- inbound: argv slice parsers (moved from cliutil / the entrypoints) --------


def parse_message_slice_args(args):
    """Parse the shared `messages`-op argv into kwargs for `Messages.list`.

    Accepts --untagged (flag), --lang <v>, --session <v>, --limit <n> (digits).
    Returns {"lang", "untagged", "limit", "session"}. Raises ValueError (whose
    message the caller prints to stderr before returning 1) on a bad --limit or
    any unrecognized token.
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


def parse_size_arg(args, default):
    """The tutor `deck [--size N]` flag. `args` is argv after the `deck` verb.
    Returns int(N) for an exact `--size <digits>`; otherwise `default` (lenient,
    matching the prior inline behavior)."""
    if len(args) == 2 and args[0] == "--size" and args[1].isdigit():
        return int(args[1])
    return default


def parse_session_arg(args):
    """The debrief `mark-processed [--session <id>]` flag. `args` is argv after
    the verb. Returns the id string for `--session <id>`, else None."""
    if len(args) >= 2 and args[0] == "--session":
        return args[1]
    return None
