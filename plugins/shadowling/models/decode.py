"""models/decode.py - comprehension-gap incidents (append-only) + record fan-out.

User-initiated /aha: a phrase that couldn't be read literally, classified as a
`fixed` expression (memorize) or a `method`/grammar pattern (learnable). For
`method` the key is the rule, so one rule aggregates across phrases."""

from core import slugify

from .base import Model


class Decode(Model):
    table = "decode"
    view = "decode_ranked"
    key = "slug"
    insert_cols = [
        "slug",
        "type",
        "expression",
        "meaning",
        "takeaway",
        "learner_wrote",
        "context",
    ]


def record(slug, kind, expression, meaning, takeaway, learner_wrote, context):
    n = Decode.insert(
        {
            "slug": slugify(slug),
            "type": kind,
            "expression": expression,
            "meaning": meaning,
            "takeaway": takeaway,
            "learner_wrote": learner_wrote,
            "context": context,
        }
    )
    return "inserted" if n == 1 else "incremented"
