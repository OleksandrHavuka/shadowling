"""models/idioms.py - idiom incidents (append-only) + record fan-out.

Natural key: the idiom phrase, normalized (casefold + whitespace collapse)."""
from .base import Model, norm_key


class Idioms(Model):
    table = "idioms"
    view = "idioms_ranked"
    key = "idiom"
    insert_cols = ["idiom", "meaning", "context", "learner_wrote"]


def record(idiom, meaning, context, learner_wrote):
    n = Idioms.insert({"idiom": norm_key(idiom), "meaning": meaning,
                       "context": context, "learner_wrote": learner_wrote})
    return "inserted" if n == 1 else "incremented"
