"""models/verbs.py - irregular-verb incidents (append-only) + record fan-out."""

from .base import Model, norm_key


class Verbs(Model):
    table = "verbs"
    view = "verbs_ranked"
    key = "verb"
    insert_cols = ["verb", "past", "participle", "used_form", "correction", "context"]


def record(verb, past, participle, used_form, correction, context):
    n = Verbs.insert(
        {
            "verb": norm_key(verb),
            "past": past,
            "participle": participle,
            "used_form": used_form,
            "correction": correction,
            "context": context,
        }
    )
    return "inserted" if n == 1 else "incremented"
