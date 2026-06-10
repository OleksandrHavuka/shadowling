"""models/friction.py - friction product (Tier 2) + record fan-out (Tier 1).

Code-switching analysis: places where the user bails from English into their
native language. The product (friction.md) is the deduped "where my English
fails me" ranking, keyed by zone slug and classified by a five-value taxonomy
(lexical/phrasal/structural/topical/register); the log (friction.log.jsonl)
keeps every incident verbatim.
"""
import os

from core import data_dir, slugify, today
from jsonl import append as jsonl_append

from . import register
from .base import Model


class Friction(Model):
    file = "friction.md"
    columns = ["slug", "type", "zone", "you reached for", "natural english",
               "created_at", "updated_at", "counter"]
    key = "slug"
    counter = "counter"
    created = "created_at"
    updated = "updated_at"


def record(slug, kind, zone, you_reached_for, natural_english, context):
    slug = slugify(slug)
    result = Friction.upsert({"slug": slug, "type": kind, "zone": zone,
                              "you reached for": you_reached_for,
                              "natural english": natural_english})
    jsonl_append(os.path.join(data_dir(), "friction.log.jsonl"),
                 {"date": today(), "slug": slug, "type": kind, "zone": zone,
                  "you_reached_for": you_reached_for,
                  "natural_english": natural_english, "context": context})
    return result


register("friction", Friction, record)
