"""models/rephrasing.py - naturalness incidents (append-only) + record fan-out."""
from core import slugify

from . import register
from .base import Model


class Rephrasing(Model):
    table = "rephrasing"
    view = "rephrasing_ranked"
    key = "slug"
    insert_cols = ["slug", "problem", "yours", "natural", "why"]


def record(slug, problem, yours, natural, why):
    n = Rephrasing.insert({"slug": slugify(slug), "problem": problem,
                           "yours": yours, "natural": natural, "why": why})
    return "inserted" if n == 1 else "incremented"


register("rephrasing", Rephrasing, record)
