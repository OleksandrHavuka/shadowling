#!/usr/bin/env python3
"""validator.py - validate a formed Python value against a literal schema (stdlib).

The schema language is plain Python literals — no marker classes:
  * TEXT        -> a leaf; the value must be a str.
  * {tag: sub}  -> an object; a dict carrying each `tag`, each matching `sub`.
  * [sub]       -> a list; every element matches `sub`.

`validate(data, schema)` returns `data` (shaped to the schema, extra keys dropped)
when it conforms, else raises `SchemaError` whose message names the offending path
AND shows the expected shape, so an LLM that produced the data can self-correct and
retry. The validator is XML-agnostic: it does not know where `data` came from
(skillio's XML reader, a JSON load, a test). One responsibility: schema conformance.
"""

TEXT = object()  # sentinel: a leaf (string) field


class SchemaError(ValueError):
    """`data` does not conform to `schema`; message = the path + the expected shape."""


def _template(schema):
    """Compact rendering of `schema` embedded in error messages so the producer sees
    the exact expected shape."""
    if schema is TEXT:
        return "<text>"
    if isinstance(schema, list):
        return "[" + _template(schema[0]) + ", ...]"
    if isinstance(schema, dict):
        return "{" + ", ".join(f"{k}: {_template(v)}" for k, v in schema.items()) + "}"
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
            if key not in data:
                raise SchemaError(
                    f"{_path}: missing key {key!r}; expected {_template(schema)}"
                )
            out[key] = validate(data[key], sub, f"{_path}.{key}")
        return out
    raise SchemaError(f"{_path}: invalid schema node {schema!r}")
