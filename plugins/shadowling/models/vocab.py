"""models/vocab.py - vocabulary glossing store (mutable state) over appdb.

The vocab table is the one sanctioned mutable incident store: each word carries a
`remaining` exposure budget that `scan_decrement` lowers until the word graduates
(status 'learned'). All vocab SQL lives here. `word_in_text`/`build_pattern` are
pure matching helpers (no DB), kept module-level like models/base.norm_key.
"""

import json
import re

import core
from appdb import connect, tx

START_REMAINING = 10
STEM_MIN_LEN = 4


def _norm(s):
    return re.sub(r"\s+", " ", s).strip().lower()


def build_pattern(word):
    word = word.strip().lower()
    esc = re.escape(word)
    left = r"(?<!\w)"
    right = r"(?!\w)"
    if len(word) >= STEM_MIN_LEN and word[-1:].isalnum():
        # The bare 'd' is for '-e' stems (care -> cared). Applying it to any word
        # over-matches (bear -> "beard", boar -> "board", bran -> "brand") and
        # decrements the wrong vocab entry, so gate it on an '-e' ending.
        tail = "s|es|ed|ing|d" if word.endswith("e") else "s|es|ed|ing"
        body = esc + f"(?:{tail})?"
    else:
        body = esc
    return re.compile(left + body + right, re.IGNORECASE)


def word_in_text(word, text):
    return build_pattern(word).search(text) is not None


def cloze_pattern(word, forms):
    """Compiled regex matching `word` or any surface `form` at a word boundary,
    case-insensitive, longest-variant-first so the longest form wins an overlap.
    Language-agnostic: word boundaries are universal, the inflection knowledge
    lives in `forms`. Shared by loot's `_valid` (a looted example must match) and
    anki's `_wrap_cloze` (push wraps every match as one c1), so validation and
    delivery can never drift apart. Unlike build_pattern (English-suffix guessing
    for scan_decrement), this carries no language assumptions."""
    variants = sorted({word, *forms}, key=len, reverse=True)
    alt = "|".join(re.escape(v) for v in variants)
    return re.compile(r"(?<!\w)(?:" + alt + r")(?!\w)", re.IGNORECASE)


class Vocab:
    @staticmethod
    def _add_on(
        con,
        word,
        translation,
        *,
        definition=None,
        ctx=None,
        examples=None,
        synonyms=None,
        alt_translations=None,
        forms=None,
        lemma=None,
    ):
        """add/refresh/relearn on an ALREADY-OPEN connection (opens no tx of its
        own). Writes ONLY the enrichment columns actually provided (not-None), so a
        bare add(word, translation) on an EXISTING row never wipes its enrichment,
        while the loot driver — which always passes the full bundle — overwrites it.
        Inserting a NEW row, however, requires a non-empty `examples` list: the DB
        floor (appdb m12, R-PAT-3) is translation + >=1 example, so a bare add of a
        brand-new word raises sqlite3.IntegrityError — there are no glossing-only
        rows. examples/synonyms/alt_translations/forms are Python lists, stored as
        json_valid TEXT; lemma is plain TEXT. Returns the same render-ready result
        dict as add()."""
        word = word.strip().lower()
        translation = (translation or "").strip()
        # Identity/empty translation = the LLM echoed the term back untranslated.
        # Never persist such a row; the untranslated result carries just the word.
        if not translation or _norm(translation) == _norm(word):
            return {"action": "untranslated", "word": word}
        now = core.now()
        # only the provided (not-None) enrichment columns are written
        enrich = {}
        if definition is not None:
            enrich["definition"] = definition
        if ctx is not None:
            enrich["ctx"] = ctx
        # ensure_ascii=False so first_language (often non-Latin) data is stored as
        # readable UTF-8, not \uXXXX escapes — json.loads round-trips either form.
        if examples is not None:
            enrich["examples"] = json.dumps(examples, ensure_ascii=False)
        if synonyms is not None:
            enrich["synonyms"] = json.dumps(synonyms, ensure_ascii=False)
        if alt_translations is not None:
            enrich["alt_translations"] = json.dumps(
                alt_translations, ensure_ascii=False
            )
        if forms is not None:
            enrich["forms"] = json.dumps(forms, ensure_ascii=False)
        if lemma is not None:
            enrich["lemma"] = lemma
        row = con.execute("SELECT * FROM vocab WHERE word = ?", (word,)).fetchone()
        if row is None:
            cols = [
                "word",
                "translation",
                "remaining",
                "status",
                "created_at",
                "updated_at",
            ]
            vals = [word, translation, START_REMAINING, "active", now, now]
            for c, v in enrich.items():
                cols.append(c)
                vals.append(v)
            placeholders = ", ".join("?" * len(cols))
            con.execute(
                f"INSERT INTO vocab({', '.join(cols)}) VALUES ({placeholders})", vals
            )
            action = "add"
        else:
            sets = ["translation = ?", "updated_at = ?"]
            params = [translation, now]
            if row["status"] in ("learned", "dropped"):
                sets += ["remaining = ?", "status = 'active'"]
                params.append(START_REMAINING)
                action = "relearn"
            else:
                action = "refresh"
            for c, v in enrich.items():
                sets.append(f"{c} = ?")
                params.append(v)
            params.append(word)
            con.execute(f"UPDATE vocab SET {', '.join(sets)} WHERE word = ?", params)
        new = con.execute("SELECT * FROM vocab WHERE word = ?", (word,)).fetchone()
        return {
            "action": action,
            "word": new["word"],
            "translation": new["translation"],
            "remaining": new["remaining"],
            "status": new["status"],
        }

    @staticmethod
    def add(
        word,
        translation=None,
        *,
        definition=None,
        ctx=None,
        examples=None,
        synonyms=None,
        alt_translations=None,
        forms=None,
        lemma=None,
        con=None,
    ):
        """Add or refresh a vocab pair, optionally with enrichment columns. Returns
        ONE render-ready result dict. With con=None opens its own immediate
        transaction; given a caller's open `con` the write commits atomically with
        the caller's. Only provided enrichment columns are written (see _add_on)."""
        kw = {
            "definition": definition,
            "ctx": ctx,
            "examples": examples,
            "synonyms": synonyms,
            "alt_translations": alt_translations,
            "forms": forms,
            "lemma": lemma,
        }
        if con is not None:
            return Vocab._add_on(con, word, translation, **kw)
        con = connect()
        try:
            with tx(con):  # BEGIN IMMEDIATE serializes the existence-read + write
                return Vocab._add_on(con, word, translation, **kw)
        finally:
            con.close()

    @staticmethod
    def get_many(words):
        """Return {word: dict(row)} for the given words that exist; absent words are
        omitted. Words are normalized (strip().lower()) to match the PK. Used by the
        loot driver's pre-read so the LLM can merge old context with new."""
        norm = sorted({w.strip().lower() for w in words if w and w.strip()})
        if not norm:
            return {}
        placeholders = ", ".join("?" * len(norm))
        con = connect()
        try:
            return {
                r["word"]: dict(r)
                for r in con.execute(
                    f"SELECT * FROM vocab WHERE word IN ({placeholders})", norm
                )
            }
        finally:
            con.close()

    @staticmethod
    def remove(word):
        """Soft-delete: mark the word 'dropped' (the row stays, so its anki_link
        mirror is never orphaned and a re-loot can un-drop it via _add_on). Still
        clears the word's mastery row — that's scheduling state, not vocabulary.
        Returns True if a vocab row matched."""
        word = word.strip().lower()
        now = core.now()
        con = connect()
        try:
            with tx(con):  # status flip + mastery cleanup, atomic
                cur = con.execute(
                    "UPDATE vocab SET status = 'dropped', updated_at = ?"
                    " WHERE word = ?",
                    (now, word),
                )
                con.execute(
                    "DELETE FROM mastery WHERE item_kind = 'vocab' AND item_key = ?",
                    (word,),
                )
            return cur.rowcount > 0
        finally:
            con.close()

    @staticmethod
    def list():
        """Every vocab row, ALL statuses (active/learned/dropped). The Anki push
        needs the full set: push the live ones, suspend the dropped ones.
        list_active() stays the glossing-specific reader."""
        con = connect()
        try:
            return [dict(r) for r in con.execute("SELECT * FROM vocab ORDER BY rowid")]
        finally:
            con.close()

    @staticmethod
    def list_active():
        con = connect()
        try:
            return [
                dict(r)
                for r in con.execute(
                    "SELECT * FROM vocab WHERE status = 'active' ORDER BY rowid"
                )
            ]
        finally:
            con.close()

    @staticmethod
    def relearn(word, con=None):
        """Reset a graduated word back into the active glossing loop
        (remaining -> START_REMAINING, status 'active'). Pass an open `con` to run
        the reset inside the caller's transaction (Tutor.record committing a vocab
        `fail`) so it commits atomically with their writes; with no `con` it opens
        and commits its own."""
        sql = "UPDATE vocab SET remaining = ?, status = 'active' WHERE word = ?"
        params = (START_REMAINING, word)
        if con is not None:
            con.execute(sql, params)  # the caller's `with con:` commits it
            return
        con = connect()
        try:
            with con:
                con.execute(sql, params)
        finally:
            con.close()

    @staticmethod
    def scan_decrement(text):
        """Decrement every active word that appears in `text`; graduate at 0.
        Returns the list of changed words. `text` is the assistant reply being
        scanned for exposures.

        One atomic statement, no read-then-write: the decrement is RELATIVE
        (`remaining - 1`), so concurrent scans from independent Stop hooks compose
        correctly instead of both writing an absolute value from a stale read.
        `word_matches` mirrors the registered-function pattern in
        `Messages.mark_drills`. Requires SQLite >= 3.35 for RETURNING (see DEV.md)."""
        now = core.now()
        con = connect()
        try:
            con.create_function("word_matches", 2, word_in_text)
            with con:
                # In SQLite an UPDATE's SET/WHERE expressions read the PRE-update
                # row value regardless of assignment order, so the CASE sees the
                # old `remaining` even though `remaining` is assigned above it.
                return [
                    r["word"]
                    for r in con.execute(
                        "UPDATE vocab SET remaining = MAX(remaining - 1, 0),"
                        " status = CASE WHEN remaining - 1 <= 0 THEN 'learned'"
                        " ELSE 'active' END, updated_at = ?"
                        " WHERE status = 'active' AND word_matches(word, ?)"
                        " RETURNING word",
                        (now, text),
                    )
                ]
        finally:
            con.close()
