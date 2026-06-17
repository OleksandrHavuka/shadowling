"""models/verbs.py - irregular-verb incidents (append-only) + record fan-out."""

import core

from .base import Model, norm_key


class Verbs(Model):
    table = "verbs"
    view = "verbs_ranked"
    key = "verb"
    insert_cols = ["verb", "past", "participle", "used_form", "correction", "context"]

    @staticmethod
    def key_norm(s: str) -> str:
        return norm_key(s)


def record(verb, past, participle, used_form, correction, context):
    return Verbs.insert(
        {
            "verb": verb,
            "past": past,
            "participle": participle,
            "used_form": used_form,
            "correction": correction,
            "context": context,
        },
        session=core.session_id(),
    )
