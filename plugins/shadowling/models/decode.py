"""models/decode.py - decode product (Tier 2) + record fan-out (Tier 1).

User-initiated `/decode`: a phrase you couldn't read literally, classified as a
`fixed` expression (memorize) or a `method`/grammar pattern (learnable). The product
(decode.md) is the deduped "what trips me most" ranking; the log (decode.log.jsonl)
keeps every verbatim submission (your hunch + context). For `method` the key is the
rule, so one rule aggregates across different phrases.
"""
import os

from core import data_dir, slugify, today
from jsonl import append as jsonl_append

from . import register
from .base import Model


class Decode(Model):
    file = "decode.md"
    columns = ["slug", "type", "expression", "meaning", "takeaway",
               "created_at", "updated_at", "counter"]
    key = "slug"
    counter = "counter"
    created = "created_at"
    updated = "updated_at"


def record(slug, kind, expression, meaning, takeaway, your_read, context):
    slug = slugify(slug)
    result = Decode.upsert({"slug": slug, "type": kind, "expression": expression,
                            "meaning": meaning, "takeaway": takeaway})
    jsonl_append(os.path.join(data_dir(), "decode.log.jsonl"),
                 {"date": today(), "slug": slug, "type": kind,
                  "expression": expression, "meaning": meaning,
                  "your_read": your_read, "context": context, "takeaway": takeaway})
    return result


register("decode", Decode, record)
