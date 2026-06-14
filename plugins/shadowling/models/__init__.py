"""models package - product registry (REGISTRY) + record recorders (RECORDERS).

Each category module exports its product Model and a `record` fan-out function.
These two name-keyed catalogs are no longer a runtime dispatch path (db.py is
gone); they exist so traceability.py can enumerate every category to prove the
schema <-> models <-> skill contract. Per-skill entrypoints import their own
category module directly (e.g. `from models import grammar`)."""

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
