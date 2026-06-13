"""models/friction.py - code-switching incidents (append-only) + record fan-out.

Places where the user bails from the learning language into their native
language, keyed by zone slug and classified by the five-value taxonomy
(lexical/phrasal/structural/topical/register)."""
from core import slugify

from .base import Model


class Friction(Model):
    table = "friction"
    view = "friction_ranked"
    key = "slug"
    insert_cols = ["slug", "type", "zone", "learner_wrote",
                   "native_phrase", "context"]


def record(slug, kind, zone, learner_wrote, native_phrase, context):
    n = Friction.insert({"slug": slugify(slug), "type": kind, "zone": zone,
                         "learner_wrote": learner_wrote,
                         "native_phrase": native_phrase,
                         "context": context})
    return "inserted" if n == 1 else "incremented"
