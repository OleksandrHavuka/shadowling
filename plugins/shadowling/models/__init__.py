"""models package - product registry (REGISTRY) + record recorders (RECORDERS).

Each category module exports its product Model and a `record` fan-out function.
This package builds the two name-keyed registries the db.py CLI drives by name —
explicitly, so the imports stay at the top and the category modules don't depend
back on the package.
"""
from . import decode, friction, grammar, idioms, rephrasing, verbs

REGISTRY = {
    "grammar": grammar.Grammar,
    "rephrasing": rephrasing.Rephrasing,
    "idioms": idioms.Idioms,
    "verbs": verbs.Verbs,
    "decode": decode.Decode,
    "friction": friction.Friction,
}

RECORDERS = {
    "grammar": grammar.record,
    "rephrasing": rephrasing.record,
    "idioms": idioms.record,
    "verbs": verbs.record,
    "decode": decode.record,
    "friction": friction.record,
}
