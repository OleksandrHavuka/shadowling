"""models/messages.py - the captured-message store (mixed mutable state) over appdb.

Rows are never deleted: a successful analysis pass stamps the batch
`processed_at`, so the table doubles as the permanent, language-tagged message
log. `langs` (a JSON array of codes) carries the language triage; `kind`
('drill') fences tutor answers out of the analysis slices. Every method is a
verb over this one table — all message SQL lives here.
"""

import json
from contextlib import closing
from difflib import SequenceMatcher

import core
from appdb import connect

MIN_LETTERS = 8  # below this it's not analyzable prose / not worth logging

# Claude Code wraps slash-command / local-command turns in these tags. Such turns
# are not the user's own writing, so they must never be captured for analysis.
COMMAND_WRAPPERS = ("<command-", "<local-command-")

DRILL_SIMILARITY = 0.90  # gate threshold; width characterized in MarkDrillsTest


def _enough_letters(text):
    return sum(1 for c in text if c.isalpha()) >= MIN_LETTERS


class Messages:
    @staticmethod
    def capture(text, session_id=None):
        """Store the last user message (any language) if it qualifies; dedups
        against the most recent row. Returns True iff stored. The admission rules
        (empty / slash / command-wrapper / min-letters / no-session / dedup) live
        here, in one place, rather than in the caller. A turn with no session_id is
        unattributable, so it is NOT logged — per-session provenance is mandatory
        (the analysis findings it would produce carry a NOT NULL session_id)."""
        text = (text or "").strip()
        if not text or text.startswith("/"):
            return False
        if text.startswith(COMMAND_WRAPPERS):  # command echoes, not prose
            return False
        if not _enough_letters(text):
            return False
        if not session_id:  # provenance is mandatory — can't attribute the turn
            return False
        with closing(connect()) as con, con:
            last = con.execute(
                "SELECT text FROM messages ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if last is not None and last["text"] == text:
                return False  # guard against repeated Stop on the same turn
            con.execute(
                "INSERT INTO messages(created_at, text, session_id) VALUES (?, ?, ?)",
                (core.now(), text, session_id),
            )
        return True

    @staticmethod
    def pending_count():
        with closing(connect()) as con:
            return con.execute(
                "SELECT COUNT(*) FROM messages"
                " WHERE processed_at IS NULL AND kind IS NULL"
            ).fetchone()[0]

    @staticmethod
    def sessions():
        """Sessions that still need analysis (pending = unprocessed non-drill)."""
        with closing(connect()) as con:
            rows = con.execute(
                "SELECT session_id AS session, COUNT(*) AS pending FROM messages "
                "WHERE processed_at IS NULL AND kind IS NULL "
                "GROUP BY session_id ORDER BY MIN(id)"
            ).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def list(lang=None, untagged=False, limit=None, session=None):
        """Unprocessed rows (plain dicts: id, created_at, text, langs), optionally
        sliced. Presentation (the <messages> tag block) is composed at the
        boundary via skillio.render — the repository returns data only. A falsy
        `session` scopes to the bounded `session_id IS NULL` group (never global),
        matching mark_processed — so the driver's per-session pipeline reads,
        analyses, and marks exactly the same NULL-group rows."""
        sql = (
            "SELECT id, created_at, text, langs FROM messages "
            "WHERE processed_at IS NULL AND kind IS NULL"
        )
        params = []
        if session:
            sql += " AND session_id = ?"
            params.append(session)
        else:
            sql += " AND session_id IS NULL"
        if untagged:
            sql += " AND langs IS NULL"
        elif lang:
            sql += (
                " AND EXISTS (SELECT 1 FROM json_each(messages.langs) "
                "WHERE json_each.value = ?)"
            )
            params.append(lang)
        sql += " ORDER BY id"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        with closing(connect()) as con:
            return [dict(r) for r in con.execute(sql, params).fetchall()]

    @staticmethod
    def tag(rows):
        """Persist language codes for the given message rows. `rows` is the
        heredoc payload parsed by skillio: a list of {"id": str, "langs":
        "code[,code]"}. The codes are trusted (the triage LLM authored them) —
        this is persistence only: it stamps each id's `langs` and returns the
        count of rows actually updated. A nonexistent or non-numeric id matches
        nothing (sqlite applies INTEGER affinity to the bound id), so a bad id
        simply doesn't count — it never crashes the batch."""
        ok = 0
        with closing(connect()) as con, con:
            for r in rows:
                codes = [c.strip() for c in r["langs"].split(",") if c.strip()]
                cur = con.execute(
                    "UPDATE messages SET langs=? WHERE id=?",
                    (json.dumps(codes), r["id"]),
                )
                ok += cur.rowcount
        return ok

    @staticmethod
    def _mark_processed_on(con, session=None):
        """The full mark_processed body on an ALREADY-OPEN connection — opens no
        transaction of its own. Stamps tagged+unprocessed rows (and drill rows —
        excluded from analysis but must not stay pending forever); untagged
        natural rows stay. A non-empty `session` scopes to that session; a falsy
        `session` scopes to the bounded NULL-session group (`session_id IS NULL`)
        — never global. Returns {"processed", "kept"}."""
        sql = (
            "UPDATE messages SET processed_at=? WHERE processed_at IS NULL "
            "AND (langs IS NOT NULL OR kind = 'drill')"
        )
        params = [core.now()]
        if session:
            sql += " AND session_id = ?"
            params.append(session)
        else:
            sql += " AND session_id IS NULL"
        cur = con.execute(sql, params)
        kept = con.execute(
            "SELECT COUNT(*) FROM messages WHERE processed_at IS NULL AND kind IS NULL"
        ).fetchone()[0]
        return {"processed": cur.rowcount, "kept": kept}

    @staticmethod
    def mark_processed(session=None, con=None):
        """Stamp tagged+unprocessed (and drill) rows processed. With con=None
        opens its own connection + transaction; given a caller's open `con` (the
        debrief driver's per-session tx) the processed-mark commits atomically
        with the session's findings. Body is _mark_processed_on. A falsy `session`
        scopes to the bounded NULL-session group (never global) — see
        Messages.list, which now uses the same rule. Mirrors Vocab.relearn's con=."""
        if con is not None:
            return Messages._mark_processed_on(con, session)
        with closing(connect()) as con, con:
            return Messages._mark_processed_on(con, session)

    @staticmethod
    def _similarity(a, b):
        # casefold: ratio() is case-sensitive. " ".join(split()) collapses every
        # whitespace run to a single space and strips the ends. autojunk=False:
        # the default heuristic degrades on long strings.
        a = " ".join(a.casefold().split())
        b = " ".join(b.casefold().split())
        return SequenceMatcher(None, a, b, autojunk=False).ratio()

    @staticmethod
    def mark_drills():
        """Stamp unprocessed messages that match a recorded tutor answer for the
        SAME session (kind='drill'). Deterministic: machine-recorded session ids
        + a fixed similarity threshold; no LLM judgment. similarity() runs ONCE,
        in this UPDATE; the result persists in `kind`, so no later query
        recomputes it. The non-empty guards stop ratio('','')==1.0 mislabeling."""
        with closing(connect()) as con:
            con.create_function("similarity", 2, Messages._similarity)
            with con:
                cur = con.execute(
                    "UPDATE messages SET kind = 'drill' "
                    "WHERE processed_at IS NULL AND kind IS NULL "
                    "AND session_id IS NOT NULL "
                    "AND EXISTS (SELECT 1 FROM attempts a "
                    "            WHERE a.session_id = messages.session_id "
                    "              AND length(trim(a.answer)) > 0 "
                    "              AND length(trim(messages.text)) > 0 "
                    "              AND similarity(a.answer, messages.text) >= ?)",
                    (DRILL_SIMILARITY,),
                )
                marked = cur.rowcount
        return marked
