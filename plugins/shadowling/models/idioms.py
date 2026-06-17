"""models/idioms.py - idiom incidents (append-only) + record fan-out.

Natural key: the idiom phrase, normalized (casefold + whitespace collapse)."""

import core

from .base import Model, norm_key


class Idioms(Model):
    table = "idioms"
    view = "idioms_ranked"
    key = "idiom"
    insert_cols = ["idiom", "meaning", "context", "learner_wrote"]

    @staticmethod
    def key_norm(s: str) -> str:
        return norm_key(s)


def record(idiom, meaning, context, learner_wrote):
    return Idioms.insert(
        {
            "idiom": idiom,
            "meaning": meaning,
            "context": context,
            "learner_wrote": learner_wrote,
        },
        session=core.session_id(),
    )
