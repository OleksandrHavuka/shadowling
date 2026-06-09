"""models/grammar.py - grammar product (Tier 2, markdown) + record fan-out.

`record` writes the deduped product row (grammar.md) and appends the verbatim
instance to the per-instance findings dataset (grammar.log.jsonl, Tier 1).
"""
import os

from core import data_dir, slugify, today
from jsonl import append as jsonl_append

from . import register
from .base import Model


class Grammar(Model):
    file = "grammar.md"
    columns = ["slug", "counter", "problem", "last example", "last_seen"]
    key = "slug"
    counter = "counter"


def record(slug, problem, original, fixed, rule):
    slug = slugify(slug)
    result = Grammar.upsert({"slug": slug, "problem": problem,
                             "last example": "{0} → {1}".format(original, fixed),
                             "last_seen": today()})
    jsonl_append(os.path.join(data_dir(), "grammar.log.jsonl"),
                 {"date": today(), "slug": slug,
                  "original": original, "fixed": fixed, "rule": rule})
    return result


register("grammar", Grammar, record)
