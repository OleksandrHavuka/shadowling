"""models/idioms.py - idioms product (Tier 2) + record fan-out (Tier 1).

Natural key: the idiom phrase (normalized by the data layer's norm_key).
"""
import os

from core import data_dir, today
from jsonl import append as jsonl_append

from . import register
from .base import Model


class Idioms(Model):
    file = "idioms.md"
    columns = ["idiom", "counter", "meaning", "last example", "last_seen"]
    key = "idiom"
    counter = "counter"


def record(idiom, meaning, context, you_wrote):
    result = Idioms.upsert({"idiom": idiom, "meaning": meaning,
                            "last example": you_wrote, "last_seen": today()})
    jsonl_append(os.path.join(data_dir(), "idioms.log.jsonl"),
                 {"date": today(), "context": context, "idiom": idiom,
                  "meaning": meaning, "you_wrote": you_wrote})
    return result


register("idioms", Idioms, record)
