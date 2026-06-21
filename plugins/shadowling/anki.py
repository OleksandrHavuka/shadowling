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
import sys
import urllib.error
import urllib.request

import core
from appdb import connect, tx
from models.anki_link import AnkiLink
from models.vocab import Vocab, cloze_pattern

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


def _wrap_cloze(sentence, word, forms):
    """Wrap every {word}∪forms match in `sentence` as one shared c1 deletion,
    preserving matched casing — all occurrences hide/reveal together as one blank.
    Matching is word-boundary + case-insensitive over {word} and the LLM-supplied
    surface `forms` (the shared, language-agnostic matcher in models.vocab), so an
    inflection in the example clozes even when `word` is the lemma. Returns the
    clozed sentence, or None when nothing matched (zero coverage) so the caller
    skips + reports the word instead of pushing a cloze-less, addNote-failing
    note."""
    clozed, n = cloze_pattern(word, forms).subn(
        lambda m: "{{c1::" + m.group(0) + "}}", sentence
    )
    return clozed if n else None


def _json_list(value):
    """A JSON-array TEXT column -> Python list; NULL/empty -> []."""
    return json.loads(value) if value else []


def _build_fields(row):
    """Map a vocab row (dict from Vocab.list()) to the Shadowling Cloze note
    fields, or None when the row has examples but NONE of them cloze (zero coverage
    — an un-re-looted or hand-inserted row). Each example is wrapped via the shared
    {word}∪forms matcher; un-clozable segments are dropped. Returning None lets push
    skip the row and name it in the sync summary instead of pushing a cloze-less,
    addNote-failing note. JSON-array columns render comma-joined; empty enrichment
    renders '' (never None). Word and Translation are always present."""
    examples = _json_list(row.get("examples"))
    forms = _json_list(row.get("forms"))
    segments = (_wrap_cloze(s, row["word"], forms) for s in examples)
    covered = [c for c in segments if c is not None]
    if examples and not covered:
        return None  # zero cloze coverage — caller skips + reports "re-loot <word>"
    return {
        "Word": row["word"],
        "Examples": "|".join(covered),
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


def suspend(card_id, invoke=_invoke):
    """Suspend one card (a dropped word's card stops being scheduled)."""
    invoke("suspend", cards=[card_id])


def _push_row(row, deck, invoke):
    """Push one enriched vocab row: update if it already has a note, else add and
    store the new note_id/card_id in anki_link. Returns 'updated' or 'added', or
    None when the row has examples but NONE of them cloze (_build_fields returned
    None — an un-re-looted/hand-inserted row); the caller records the word for
    re-loot instead of pushing a cloze-less, addNote-failing note."""
    fields = _build_fields(row)
    if fields is None:
        return None  # zero cloze coverage — caller adds word to "uncovered"
    word = row["word"]
    link = AnkiLink.get(word)
    if link and link.get("note_id"):
        invoke("updateNoteFields", note={"id": link["note_id"], "fields": fields})
        return "updated"
    note_id = invoke(
        "addNote",
        note={
            "deckName": deck,
            "modelName": MODEL_NAME,
            "fields": fields,
            "tags": [TAG],
            "options": {"allowDuplicate": False},
        },
    )
    cards = invoke("findCards", query=f"nid:{note_id}")
    AnkiLink.upsert(
        word, note_id=note_id, card_id=cards[0] if cards else None, deck=deck
    )
    return "added"


def _suspend_dropped(row, invoke):
    """A dropped word: suspend its card if we know one, else nothing to do."""
    link = AnkiLink.get(row["word"])
    if link and link.get("card_id"):
        suspend(link["card_id"], invoke=invoke)
        return "suspended"
    return "skipped"


def pull_progress(invoke=_invoke):
    """Read review progress for all shadowling notes back into anki_link. A word
    whose lapses increased re-enters glossing (Vocab.relearn) atomically with its
    anki_link upsert (shared transaction). Returns (pulled_count, relearned_words)."""
    note_ids = invoke("findNotes", query=f"tag:{TAG}")
    if not note_ids:
        return 0, []
    infos = invoke("notesInfo", notes=note_ids)
    word_by_note, card_by_note, card_ids = {}, {}, []
    for info in infos:
        nid = info.get("noteId")
        word = (
            (info.get("fields", {}).get("Word", {}).get("value") or "").strip().lower()
        )
        cards = info.get("cards") or []
        if not word or not cards:
            continue
        word_by_note[nid] = word
        card_by_note[nid] = cards[0]
        card_ids.append(cards[0])
    cinfos = (
        {c["cardId"]: c for c in invoke("cardsInfo", cards=card_ids)}
        if card_ids
        else {}
    )
    pulled, relearned = 0, []
    con = connect()
    try:
        for nid, word in word_by_note.items():
            c = cinfos.get(card_by_note[nid])
            if not c:
                continue
            prev = AnkiLink.get(word)
            prev_lapses = (prev or {}).get("lapses") or 0
            lapses = c.get("lapses") or 0
            with tx(con):  # relearn + upsert commit together
                if lapses > prev_lapses:
                    Vocab.relearn(word, con=con)
                    relearned.append(word)
                AnkiLink.upsert(
                    word,
                    con=con,
                    note_id=nid,
                    card_id=card_by_note[nid],
                    deck=c.get("deck"),
                    due=c.get("due"),
                    interval=c.get("interval"),
                    reps=c.get("reps"),
                    lapses=lapses,
                    synced_at=core.now(),
                )
            pulled += 1
    finally:
        con.close()
    return pulled, relearned


def sync_all(cfg, *, invoke=_invoke):
    """The /anki-sync logic: reachability check, ensure model + deck, push/suspend
    in one pass over Vocab.list(), then pull progress. Per-word push errors are
    collected, not fatal. A row with examples but no cloze coverage is added to
    `uncovered` (re-loot to fix), never pushed. Returns a summary dict."""
    invoke("version")  # reachability; AnkiError aborts BEFORE any write
    ensure_model(invoke=invoke)
    deck = _deck_name(cfg)
    invoke("createDeck", deck=deck)
    counts = {"added": 0, "updated": 0, "suspended": 0, "skipped": 0}
    uncovered = []
    errors = []
    for row in Vocab.list():
        try:
            if row["status"] == "dropped":
                action = _suspend_dropped(row, invoke)
            elif _json_list(row.get("examples")):
                action = _push_row(row, deck, invoke)
                if action is None:  # examples present but none cloze → re-loot
                    uncovered.append(row["word"])
                    continue
            else:
                action = "skipped"  # active/learned but not yet enriched
            counts[action] += 1
        except AnkiError as e:
            errors.append({"word": row["word"], "error": str(e)})
    pulled, relearned = pull_progress(invoke=invoke)
    return {
        **counts,
        "uncovered": uncovered,
        "errors": errors,
        "pulled": pulled,
        "relearned": relearned,
    }


def main(invoke=None):
    """Config-gate, sync, print a one-line summary. Exit 1 on a config error, an
    Anki-unreachable abort, or any per-word push error."""
    cfg = core.load_config()
    if not core.config_ready(cfg):
        print(cfg["notice"], file=sys.stderr)
        return 1
    kw = {} if invoke is None else {"invoke": invoke}
    try:
        s = sync_all(cfg, **kw)
    except AnkiError as e:
        print(f"anki-sync: {e}", file=sys.stderr)
        return 1
    print(
        f"anki-sync: +{s['added']} added, {s['updated']} updated, "
        f"{s['suspended']} suspended, {s['skipped']} skipped (not enriched), "
        f"{len(s['uncovered'])} uncovered, "
        f"{s['pulled']} pulled, {len(s['relearned'])} relearned, "
        f"{len(s['errors'])} errors",
        flush=True,
    )
    if s["uncovered"]:
        print(
            "  no cloze coverage — re-loot: " + ", ".join(s["uncovered"]),
            flush=True,
        )
    return 1 if s["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
