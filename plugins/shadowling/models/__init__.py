"""models package - product registry (REGISTRY) + record recorders (RECORDERS).

Concrete category modules register their product Model and `record` fan-out here
on import, so the db.py CLI can drive them by name.
"""
REGISTRY = {}
RECORDERS = {}


def register(name, model, recorder=None):
    REGISTRY[name] = model
    if recorder is not None:
        RECORDERS[name] = recorder


from . import grammar  # noqa: E402,F401  (populates REGISTRY / RECORDERS on import)
from . import rephrasing  # noqa: E402,F401
from . import idioms  # noqa: E402,F401
from . import verbs  # noqa: E402,F401
from . import decode  # noqa: E402,F401
from . import friction  # noqa: E402,F401
