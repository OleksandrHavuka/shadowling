#!/usr/bin/env python3
"""validator.py - validate a formed Python value against a literal schema (stdlib).

The schema language is plain Python literals:
  * TEXT          -> a leaf; the value must be a str.
  * {tag: sub}    -> an object; a dict carrying each `tag`, each matching `sub`.
  * [sub]         -> a list; every element matches `sub`.
  * OPTIONAL(sub) -> as a dict VALUE, marks that key optional: validated against
                    `sub` when present, omitted from the output when absent. Every
                    other dict key is required — its presence is checked first,
                    then its value validated.

`validate(data, schema)` returns `data` (shaped to the schema, extra keys dropped)
when it conforms, else raises `SchemaError` whose message names the offending path
AND shows the expected shape, so an LLM that produced the data can self-correct and
retry. The validator is XML-agnostic: it does not know where `data` came from
(skillio's XML reader, a JSON load, a test). One responsibility: schema conformance.
"""

TEXT = object()  # sentinel: a leaf (string) field


class OPTIONAL:
    """Wrap a dict VALUE to mark its key optional: the value is validated against the
    inner schema when the key is present, and the key is omitted from the shaped
    output when absent. Required keys (every key NOT wrapped) are presence-checked
    first, then validated. Use as a dict value, e.g.
    {"word": TEXT, "ctx": OPTIONAL(TEXT)}."""

    __slots__ = ("schema",)

    def __init__(self, schema):
        self.schema = schema


class SchemaError(ValueError):
    """`data` does not conform to `schema`; message = the path + the expected shape."""


def _template(schema):
    """Compact rendering of `schema` embedded in error messages so the producer sees
    the exact expected shape. Optional keys render with a trailing `?`."""
    if isinstance(schema, OPTIONAL):
        return _template(schema.schema)
    if schema is TEXT:
        return "<text>"
    if isinstance(schema, list):
        return "[" + _template(schema[0]) + ", ...]"
    if isinstance(schema, dict):
        parts = (
            f"{k}{'?' if isinstance(v, OPTIONAL) else ''}: {_template(v)}"
            for k, v in schema.items()
        )
        return "{" + ", ".join(parts) + "}"
    return "?"


def validate(data, schema, _path="root"):
    """Check `data` against `schema`; return it shaped to the schema on success, raise
    `SchemaError` on mismatch. `_path` tracks location for the message (internal)."""
    if schema is TEXT:
        if not isinstance(data, str):
            raise SchemaError(
                f"{_path}: expected text, got {type(data).__name__}; "
                f"expected {_template(schema)}"
            )
        return data
    if isinstance(schema, list):
        if data == "":
            data = []  # an empty element (skillio renders it as "") is an empty list
        if not isinstance(data, list):
            raise SchemaError(
                f"{_path}: expected a list, got {type(data).__name__}; "
                f"expected {_template(schema)}"
            )
        sub = schema[0]
        return [validate(v, sub, f"{_path}[{i}]") for i, v in enumerate(data)]
    if isinstance(schema, dict):
        if not isinstance(data, dict):
            raise SchemaError(
                f"{_path}: expected an object, got {type(data).__name__}; "
                f"expected {_template(schema)}"
            )
        out = {}
        for key, sub in schema.items():
            required = not isinstance(sub, OPTIONAL)
            if not required:
                sub = sub.schema
            if key not in data:
                if required:  # presence is checked before the value, per the schema
                    raise SchemaError(
                        f"{_path}: missing key {key!r}; expected {_template(schema)}"
                    )
                continue  # optional + absent -> the key is dropped from the output
            out[key] = validate(data[key], sub, f"{_path}.{key}")
        return out
    raise SchemaError(f"{_path}: invalid schema node {schema!r}")
