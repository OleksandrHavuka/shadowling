"""models package - product registry (REGISTRY) + record recorders (RECORDERS).

Each category module exports its product Model and a `record` fan-out function.
These two name-keyed catalogs are a convenience index of the category submodules,
not a runtime dispatch path (db.py is gone). A category module can also be
imported on its own (e.g. `from models import grammar`)."""

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
