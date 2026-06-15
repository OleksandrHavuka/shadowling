"""models/rephrasing.py - naturalness incidents (append-only) + record fan-out."""

from .base import Model


class Rephrasing(Model):
    table = "rephrasing"
    view = "rephrasing_ranked"
    key = "slug"
    insert_cols = ["slug", "problem", "learner_wrote", "native_phrase", "why"]


def record(slug, problem, learner_wrote, native_phrase, why):
    n = Rephrasing.insert(
        {
            "slug": slug,
            "problem": problem,
            "learner_wrote": learner_wrote,
            "native_phrase": native_phrase,
            "why": why,
        }
    )
    return "inserted" if n == 1 else "incremented"
