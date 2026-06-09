"""models/verbs.py - irregular-verbs product (Tier 2) + record fan-out (Tier 1).

Natural key: the verb base form. Files: irregular_verbs.md / irregular_verbs.log.jsonl.
"""
import os

from core import data_dir, today
from jsonl import append as jsonl_append

from . import register
from .base import Model


class Verbs(Model):
    file = "irregular_verbs.md"
    columns = ["verb", "past", "past participle", "last example",
               "created_at", "updated_at", "counter"]
    key = "verb"
    counter = "counter"
    created = "created_at"
    updated = "updated_at"


def record(verb, past, participle, example_fix):
    result = Verbs.upsert({"verb": verb, "past": past, "past participle": participle,
                           "last example": example_fix})
    jsonl_append(os.path.join(data_dir(), "irregular_verbs.log.jsonl"),
                 {"date": today(), "base": verb, "past": past,
                  "participle": participle, "example_fix": example_fix})
    return result


register("verbs", Verbs, record)
