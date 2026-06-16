"""models/grammar.py - grammar incidents (append-only) + record fan-out."""

from .base import Model


class Grammar(Model):
    table = "grammar"
    view = "grammar_ranked"
    key = "slug"
    insert_cols = ["slug", "problem", "original", "fixed", "rule"]


def record(slug, problem, original, fixed, rule):
    return Grammar.insert(
        {
            "slug": slug,
            "problem": problem,
            "original": original,
            "fixed": fixed,
            "rule": rule,
        }
    )
