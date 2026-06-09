"""models/rephrasing.py - rephrasing product (Tier 2) + record fan-out (Tier 1).

CLI/registry name is `rephrasing`; the files are `rephrasings.md` /
`rephrasings.log.jsonl`.
"""
import os

from core import data_dir, slugify, today
from jsonl import append as jsonl_append

from . import register
from .base import Model


class Rephrasing(Model):
    file = "rephrasings.md"
    columns = ["slug", "problem", "your phrasing", "natural phrasing",
               "created_at", "updated_at", "counter"]
    key = "slug"
    counter = "counter"
    created = "created_at"
    updated = "updated_at"


def record(slug, problem, yours, natural, why):
    slug = slugify(slug)
    result = Rephrasing.upsert({"slug": slug, "problem": problem,
                                "your phrasing": yours, "natural phrasing": natural})
    jsonl_append(os.path.join(data_dir(), "rephrasings.log.jsonl"),
                 {"date": today(), "slug": slug,
                  "yours": yours, "natural": natural, "why": why})
    return result


register("rephrasing", Rephrasing, record)
