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
    columns = ["slug", "counter", "problem", "last example", "last_seen"]
    key = "slug"
    counter = "counter"


def record(slug, problem, yours, natural, why):
    slug = slugify(slug)
    result = Rephrasing.upsert({"slug": slug, "problem": problem,
                                "last example": "{0} → {1}".format(yours, natural),
                                "last_seen": today()})
    jsonl_append(os.path.join(data_dir(), "rephrasings.log.jsonl"),
                 {"date": today(), "slug": slug,
                  "yours": yours, "natural": natural, "why": why})
    return result


register("rephrasing", Rephrasing, record)
