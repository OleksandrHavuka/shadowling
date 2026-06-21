#!/usr/bin/env python3
"""anki.py - AnkiConnect transport + sync orchestration for shadowling (Spec 2).

A peer of debrief.py / loot.py at the plugin root: it pushes enriched vocab rows
to Anki Desktop as randomized-cloze cards and pulls FSRS review progress back into
shadowling.db (Variant B — vocab is the word source, Anki the SR engine, anki_link
the mirror). Stdlib only: AnkiConnect over urllib. SQL-FREE — every DB read/write
goes through the models (Vocab, AnkiLink); anki.py only opens the pull transaction
so Vocab.relearn and AnkiLink.upsert commit together.
"""

import json
import re
import urllib.error
import urllib.request

ANKI_URL = "http://127.0.0.1:8765"
ANKI_VERSION = 6  # AnkiConnect API version
TIMEOUT = 10  # seconds

MODEL_NAME = "Shadowling Cloze"
TAG = "shadowling"
FIELDS = [
    "Word",
    "Examples",
    "Translation",
    "AltTranslations",
    "Synonyms",
    "Definition",
    "Context",
]


class AnkiError(Exception):
    """A transport failure (Anki/AnkiConnect unreachable) or an AnkiConnect-level
    error. Carries a user-facing message; sync_all/main turn it into a clean abort."""


def _invoke(action, **params):
    """One AnkiConnect JSON-RPC call over stdlib urllib. Returns the `result`
    field; raises AnkiError on a transport failure or an AnkiConnect error."""
    payload = json.dumps(
        {"action": action, "version": ANKI_VERSION, "params": params}
    ).encode("utf-8")
    req = urllib.request.Request(
        ANKI_URL, data=payload, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as e:
        raise AnkiError(
            f"cannot reach AnkiConnect at {ANKI_URL} — start Anki Desktop and "
            f"install the AnkiConnect add-on (code 2055492159). {e}"
        ) from e
    if not isinstance(body, dict) or "error" not in body or "result" not in body:
        raise AnkiError(f"unexpected AnkiConnect response: {body!r}")
    if body["error"] is not None:
        raise AnkiError(str(body["error"]))
    return body["result"]


def _wrap_cloze(sentence, word):
    """Wrap EVERY whole-word, case-insensitive occurrence of `word` as a c1 cloze
    deletion, preserving the matched casing. All occurrences share c1, so they
    hide/reveal together as one blank. Word boundaries (\\b) keep the deletion from
    splitting an unrelated word (clozing the 'w' inside 'two'); loot's containment
    guarantee still holds — if /loot accepted the example the target word appears,
    so push produces a cloze."""
    return re.sub(
        r"\b" + re.escape(word) + r"\b",
        lambda m: "{{c1::" + m.group(0) + "}}",
        sentence,
        flags=re.IGNORECASE,
    )


def _json_list(value):
    """A JSON-array TEXT column -> Python list; NULL/empty -> []."""
    return json.loads(value) if value else []


def _build_fields(row):
    """Map a vocab row (dict from Vocab.list()) to the Shadowling Cloze note
    fields. Examples become c1-clozed segments joined by '|'; JSON-array columns
    render comma-joined; empty enrichment renders as '' (never None). Word and
    Translation are always present."""
    segments = [_wrap_cloze(s, row["word"]) for s in _json_list(row.get("examples"))]
    return {
        "Word": row["word"],
        "Examples": "|".join(segments),
        "Translation": row["translation"],
        "AltTranslations": ", ".join(_json_list(row.get("alt_translations"))),
        "Synonyms": ", ".join(_json_list(row.get("synonyms"))),
        "Definition": row.get("definition") or "",
        "Context": row.get("ctx") or "",
    }


def _deck_name(cfg):
    return f"shadowling::{cfg['learning_language']}"


# --- note type: a randomized cloze. The Examples field holds all example segments
# joined by '|', each carrying the same {{c1::word}} deletion. The template JS
# splits the rendered field on '|' and shows ONE random segment per review; the
# chosen index is stashed in sessionStorage so the back shows the same segment
# (now revealed). One note = one card = one FSRS schedule. No add-ons; the JS runs
# in AnkiDroid's webview too.

_FRONT_TEMPLATE = """<div id="sl-ex">{{cloze:Examples}}</div>
<script>
(function () {
  var box = document.getElementById('sl-ex');
  if (!box) return;
  var parts = box.innerHTML.split('|');
  var i = Math.floor(Math.random() * parts.length);
  try { sessionStorage.setItem('slIdx', String(i)); } catch (e) {}
  box.innerHTML = parts[i];
})();
</script>"""

_BACK_TEMPLATE = """<div id="sl-ex">{{cloze:Examples}}</div>
<script>
(function () {
  var box = document.getElementById('sl-ex');
  if (!box) return;
  var parts = box.innerHTML.split('|');
  var i = 0;
  try { i = parseInt(sessionStorage.getItem('slIdx'), 10) || 0; } catch (e) {}
  if (i < 0 || i >= parts.length) i = 0;
  box.innerHTML = parts[i];
})();
</script>
<hr id="answer">
<div class="sl-translation">{{Translation}}</div>
{{#AltTranslations}}
<div class="sl-alt">also: {{AltTranslations}}</div>
{{/AltTranslations}}
{{#Synonyms}}<div class="sl-syn">syn: {{Synonyms}}</div>{{/Synonyms}}
{{#Definition}}<div class="sl-def">{{Definition}}</div>{{/Definition}}
{{#Context}}<div class="sl-ctx">seen in: {{Context}}</div>{{/Context}}"""

_MODEL_CSS = """.card {
  font-family: -apple-system, system-ui, sans-serif;
  font-size: 20px; text-align: center; color: #111; background: #fff;
}
.cloze { font-weight: bold; color: #1565c0; }
#answer { margin: 12px 0; }
.sl-translation { font-size: 22px; font-weight: bold; }
.sl-alt, .sl-syn, .sl-def, .sl-ctx { font-size: 16px; color: #555; margin-top: 6px; }"""


def ensure_model(invoke=_invoke):
    """Create the Shadowling Cloze note type if absent (idempotent)."""
    if MODEL_NAME in invoke("modelNames"):
        return
    invoke(
        "createModel",
        modelName=MODEL_NAME,
        inOrderFields=FIELDS,
        isCloze=True,
        css=_MODEL_CSS,
        cardTemplates=[
            {"Name": "Cloze", "Front": _FRONT_TEMPLATE, "Back": _BACK_TEMPLATE}
        ],
    )
