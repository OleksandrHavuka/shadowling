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
import langcodes
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
    "Forms",
    "Lemma",
    "Typed",
]


def _truthy(value):
    """Coerce a config value to a bool. config.json values written via the CLI are
    strings, but a hand-edited file may hold a real JSON bool — accept both. Only an
    explicit affirmative ("1"/"true"/"yes"/"on") is True; blank/absent/anything else
    is False (so the typed-answer stays opt-in)."""
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


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
    inflection in the example clozes even when `word` is the lemma. Loot's _valid
    uses the SAME matcher to gate every stored example, so a looted example always
    yields ≥1 deletion here."""
    return cloze_pattern(word, forms).sub(
        lambda m: "{{c1::" + m.group(0) + "}}", sentence
    )


def _json_list(value):
    """A JSON-array TEXT column -> Python list; NULL/empty -> []."""
    return json.loads(value) if value else []


def _build_fields(row, typed=False):
    """Map a vocab row (dict from Vocab.list()) to the Shadowling Cloze note
    fields. Each example is wrapped via the shared {word}∪forms matcher (loot's
    _valid guarantees every stored example clozes). List columns render `·`-joined;
    empty enrichment renders '' (never None). `Lemma` shows only when it differs
    from `Word` (case-insensitive); `Typed` is the gate field for the optional
    typed-answer ("1" on, "" off). Word and Translation are always present."""
    forms = _json_list(row.get("forms"))
    examples = [
        _wrap_cloze(s, row["word"], forms) for s in _json_list(row.get("examples"))
    ]
    lemma = (row.get("lemma") or "").strip()
    show_lemma = lemma if lemma and lemma.lower() != row["word"].strip().lower() else ""
    return {
        "Word": row["word"],
        "Examples": "|".join(examples),
        "Translation": row["translation"],
        "AltTranslations": " · ".join(_json_list(row.get("alt_translations"))),
        "Synonyms": " · ".join(_json_list(row.get("synonyms"))),
        "Definition": row.get("definition") or "",
        "Context": row.get("ctx") or "",
        "Forms": " · ".join(forms),
        "Lemma": show_lemma,
        "Typed": "1" if typed else "",
    }


# learning_language NAME -> a concrete TTS locale. langcodes gives the ISO-639-1
# code ("English" -> "en"); this map upgrades the common ones to a region locale a
# platform voice is likely to match ("en" -> "en_US"). Codes absent here fall back
# to the bare two-letter code (a valid BCP-47 language subtag), and an entirely
# unknown name falls back to en_US. {{tts}} is silent when no voice matches, so a
# wrong/loose tag is harmless, never fatal.
_TTS_LOCALE = {
    "en": "en_US",
    "uk": "uk_UA",
    "es": "es_ES",
    "de": "de_DE",
    "fr": "fr_FR",
    "it": "it_IT",
    "pt": "pt_PT",
    "nl": "nl_NL",
    "pl": "pl_PL",
    "cs": "cs_CZ",
    "sv": "sv_SE",
    "da": "da_DK",
    "fi": "fi_FI",
    "el": "el_GR",
    "tr": "tr_TR",
    "ja": "ja_JP",
    "ko": "ko_KR",
    "zh": "zh_CN",
    "ar": "ar_SA",
    "hi": "hi_IN",
}


def _tts_lang(cfg):
    """Map the configured learning_language NAME to a TTS locale for {{tts}}.
    Never raises: unknown language -> en_US (the most commonly installed voice).
    Pure lookup over the langcodes table — no LLM, no network."""
    name = ((cfg or {}).get("learning_language") or "").strip().lower()
    code = langcodes.NAME_TO_CODE.get(name)
    if not code:
        return "en_US"
    return _TTS_LOCALE.get(code, code)


def _deck_name(cfg):
    return f"shadowling::{cfg['learning_language']}"


# --- note type: a randomized cloze. The Examples field holds all example segments
# joined by '|', each carrying the same {{c1::word}} deletion. The template JS
# splits the rendered field on '|' and shows ONE random segment per review; the
# chosen index is stashed in sessionStorage so the back shows the same segment
# (now revealed). One note = one card = one FSRS schedule. No add-ons; the JS runs
# in AnkiDroid's webview too.

_FRONT_TEMPLATE = """<div class="sl-card sl-front">
  <div id="sl-ex" class="sl-example">{{cloze:Examples}}</div>
  {{#Typed}}<div class="sl-type">{{type:Word}}</div>{{/Typed}}
  <div class="sl-hint">{{hint:Translation}}</div>
</div>
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

_BACK_TEMPLATE = """<div class="sl-card sl-back">
  <div id="sl-status"></div>
  {{#Typed}}
  <div class="sl-type-cmp">{{type:Word}}</div>
  <span id="sl-answer">{{Word}}</span>
  {{/Typed}}
  <div id="sl-ex" class="sl-context">{{cloze:Examples}}</div>

  <div class="sl-hero">
    <div class="sl-word">
      {{Word}} <span class="sl-tts">{{tts __TTS_LANG__:Word}}</span>
    </div>
    <div class="sl-translation">{{Translation}}</div>
  </div>

  {{#Definition}}<div class="sl-sec">
    <div class="sl-label">meaning</div>
    <div class="sl-body">{{Definition}}</div>
  </div>{{/Definition}}
  {{#AltTranslations}}<div class="sl-sec">
    <div class="sl-label">also</div>
    <div class="sl-body">{{AltTranslations}}</div>
  </div>{{/AltTranslations}}
  {{#Synonyms}}<div class="sl-sec">
    <div class="sl-label">synonyms</div>
    <div class="sl-body">{{Synonyms}}</div>
  </div>{{/Synonyms}}
  {{#Forms}}<div class="sl-sec">
    <div class="sl-label">forms</div>
    <div class="sl-body">{{Forms}}</div>
  </div>{{/Forms}}
  {{#Lemma}}<div class="sl-sec">
    <div class="sl-label">base form</div>
    <div class="sl-body">{{Lemma}}</div>
  </div>{{/Lemma}}
  {{#Context}}<div class="sl-sec">
    <div class="sl-label">seen in</div>
    <div class="sl-body sl-ctx">{{Context}}</div>
  </div>{{/Context}}
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
  <script>
  (function () {
    var ta = document.getElementById('typeans');
    var st = document.getElementById('sl-status');
    var ansEl = document.getElementById('sl-answer');
    if (!ta || !st || !ansEl) return;
    var firstLine = ta.innerHTML.split(/<br\\s*\\/?>/i)[0];
    var tmp = document.createElement('div');
    tmp.innerHTML = firstLine;
    var spans = tmp.querySelectorAll('.typeGood, .typeBad');
    var typed = '';
    for (var i = 0; i < spans.length; i++) typed += spans[i].textContent;
    typed = typed.trim();
    if (!typed) return;
    var ok = typed.toLowerCase() === ansEl.textContent.trim().toLowerCase();
    st.textContent = ok ? '✓  correct' : '✕  try again';
    st.className = 'sl-status ' + (ok ? 'sl-ok' : 'sl-err');
  })();
  </script>
</div>"""


def _back_template(cfg):
    """The back template with the TTS locale resolved from cfg (Task 1). The
    template is otherwise static; only the {{tts}} locale depends on config."""
    return _BACK_TEMPLATE.replace("__TTS_LANG__", _tts_lang(cfg))


_MODEL_CSS = """.card {
  background:#0b0b0d; color:#e9e9ec;
  font-family:-apple-system, system-ui, Roboto, sans-serif;
}
.sl-card {
  padding:22px 22px 28px; box-sizing:border-box;
  max-width:680px; margin:0 auto;
}
.sl-front {
  min-height:86vh; display:flex; flex-direction:column;
  justify-content:center; align-items:center; text-align:center; gap:30px;
}
.sl-example { font-size:27px; line-height:1.55; font-weight:500; }
.cloze { color:#7db1ff; font-weight:700; }
.hint {
  display:inline-block; color:#9aa0aa; background:#15161a;
  border:1px solid #2c2f36; border-radius:999px; padding:8px 18px;
  font-size:15px; text-decoration:none;
}
.hint::before { content:"\\01F4A1  "; }
#typeans {
  font-size:20px; padding:12px 16px; border-radius:12px;
  border:1px solid #2c2f36; background:#15161a; color:#e9e9ec;
  text-align:center; width:80%; max-width:420px; outline:none;
}
#typeans:focus { border-color:#7db1ff; }
.sl-type-cmp { display:none; }
#sl-answer { display:none; }
.mobile .sl-type { display:none; }
.sl-context {
  font-size:16px; color:#7c818c; line-height:1.45;
  text-align:center; margin-bottom:18px;
}
.sl-context .cloze { color:#7db1ff; }
.sl-hero {
  text-align:center; background:#15161a; border:1px solid #23252b;
  border-radius:16px; padding:20px 16px; margin-bottom:8px;
}
.sl-word { font-size:32px; font-weight:800; color:#f3f4f6; }
.sl-tts { font-size:20px; vertical-align:middle; }
.sl-translation { font-size:23px; font-weight:700; color:#7db1ff; margin-top:8px; }
.sl-sec { margin:18px 4px 0; }
.sl-label {
  font-size:12px; letter-spacing:.14em; text-transform:uppercase;
  color:#6e7480; margin-bottom:5px;
}
.sl-body { font-size:18px; line-height:1.5; color:#c7ccd4; }
.sl-ctx { font-style:italic; color:#9aa0aa; }
.sl-status {
  display:flex; align-items:center; justify-content:center; gap:8px;
  font-size:15px; font-weight:700; letter-spacing:.02em;
  padding:9px 14px; border-radius:10px; margin:0 0 14px;
}
.sl-ok  { background:#13301c; color:#7ee787; }
.sl-err { background:#3a1c1c; color:#ff9a92; }"""


def update_model(invoke=_invoke, cfg=None):
    """Bring the Shadowling Cloze note type up to date — idempotent and
    additive-only. Creates it if absent; otherwise adds any missing fields and
    rewrites templates/CSS only when the current value differs (a no-op when
    already current). NEVER removes, renames, reorders fields or deletes a card
    template — scheduling lives on the card, so additive changes never touch review
    history. shadowling OWNS the templates/CSS (manual edits are overwritten next
    sync; documented in docs/ANKI.md)."""
    front = _FRONT_TEMPLATE
    back = _back_template(cfg)
    if MODEL_NAME not in invoke("modelNames"):
        invoke(
            "createModel",
            modelName=MODEL_NAME,
            inOrderFields=FIELDS,
            isCloze=True,
            css=_MODEL_CSS,
            cardTemplates=[{"Name": "Cloze", "Front": front, "Back": back}],
        )
        return
    have = invoke("modelFieldNames", modelName=MODEL_NAME) or []
    for field in FIELDS:
        if field not in have:
            invoke("modelFieldAdd", modelName=MODEL_NAME, fieldName=field)
    current = (invoke("modelTemplates", modelName=MODEL_NAME) or {}).get("Cloze") or {}
    if current.get("Front") != front or current.get("Back") != back:
        invoke(
            "updateModelTemplates",
            model={
                "name": MODEL_NAME,
                "templates": {"Cloze": {"Front": front, "Back": back}},
            },
        )
    css = (invoke("modelStyling", modelName=MODEL_NAME) or {}).get("css")
    if css != _MODEL_CSS:
        invoke("updateModelStyling", model={"name": MODEL_NAME, "css": _MODEL_CSS})


def suspend(card_id, invoke=_invoke):
    """Suspend one card (a dropped word's card stops being scheduled)."""
    invoke("suspend", cards=[card_id])


def _push_row(row, deck, invoke, typed=False):
    """Push one enriched vocab row: update if it already has a note, else add and
    store the new note_id/card_id in anki_link. Returns 'updated' or 'added'."""
    fields = _build_fields(row, typed)
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
    collected, not fatal. Returns a summary dict."""
    invoke("version")  # reachability; AnkiError aborts BEFORE any write
    update_model(invoke=invoke, cfg=cfg)
    deck = _deck_name(cfg)
    invoke("createDeck", deck=deck)
    typed = _truthy(core.raw_config().get("anki_typed"))
    counts = {"added": 0, "updated": 0, "suspended": 0, "skipped": 0}
    errors = []
    for row in Vocab.list():
        try:
            if row["status"] == "dropped":
                action = _suspend_dropped(row, invoke)
            elif _json_list(row.get("examples")):
                action = _push_row(row, deck, invoke, typed)
            else:
                action = "skipped"  # active/learned but not yet enriched
            counts[action] += 1
        except AnkiError as e:
            errors.append({"word": row["word"], "error": str(e)})
    pulled, relearned = pull_progress(invoke=invoke)
    return {
        **counts,
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
        f"{s['pulled']} pulled, {len(s['relearned'])} relearned, "
        f"{len(s['errors'])} errors",
        flush=True,
    )
    return 1 if s["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
