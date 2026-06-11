"""models/verbs.py - irregular-verb incidents (append-only) + record fan-out."""
from . import register
from .base import Model, norm_key


class Verbs(Model):
    table = "verbs"
    view = "verbs_ranked"
    key = "verb"
    insert_cols = ["verb", "past", "participle", "example_fix"]


def record(verb, past, participle, example_fix):
    n = Verbs.insert({"verb": norm_key(verb), "past": past,
                      "participle": participle, "example_fix": example_fix})
    return "inserted" if n == 1 else "incremented"


register("verbs", Verbs, record)
