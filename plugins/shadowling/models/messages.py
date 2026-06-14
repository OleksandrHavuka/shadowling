"""models/messages.py - the captured-message store (mixed mutable state) over appdb.

Rows are never deleted: a successful /debrief stamps the analyzed batch
`processed_at`, so the table doubles as the permanent, language-tagged message
log. The Stop hook (capture.py) writes via `capture`; triage tags via `tag`;
the analytic specialists read slices via `list`; the debrief orchestrator drives
`sessions`/`mark_processed`/`mark_drills`. All message SQL lives here.
"""

import json
import re
from contextlib import closing
from datetime import datetime
from difflib import SequenceMatcher

from appdb import connect

MIN_LETTERS = 8  # below this it's not analyzable prose / not worth logging

# Claude Code wraps slash-command / local-command turns in these tags. Such turns
# are not the user's own writing, so they must never be captured for analysis.
COMMAND_WRAPPERS = ("<command-", "<local-command-")

LANG_CODE = re.compile(r"^[a-z]{2,3}$")  # ISO-style; "und" fits too

DRILL_SIMILARITY = 0.90  # gate threshold; width characterized in MarkDrillsTest


def _now():
    return datetime.now().isoformat(timespec="seconds")


def _enough_letters(text):
    return sum(1 for c in text if c.isalpha()) >= MIN_LETTERS


def _xml(s):
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


class Messages:
    @staticmethod
    def capture(text, session_id=None):
        """Store the last user message (any language) if it qualifies; dedups
        against the most recent row. Returns True iff stored. Admission rules
        live here so the Stop hook stays thin (it only reads transcript + gate)."""
        text = (text or "").strip()
        if not text or text.startswith("/"):
            return False
        if text.startswith(COMMAND_WRAPPERS):  # command echoes, not prose
            return False
        if not _enough_letters(text):
            return False
        with closing(connect()) as con, con:
            last = con.execute(
                "SELECT text FROM messages ORDER BY id DESC LIMIT 1"
            ).fetchone()
            if last is not None and last["text"] == text:
                return False  # guard against repeated Stop on the same turn
            con.execute(
                "INSERT INTO messages(created_at, text, session_id) VALUES (?, ?, ?)",
                (_now(), text, session_id),
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
        """Unprocessed rows as a <messages> XML block; optionally sliced. The
        representation lives here so the 6 specialists share one format."""
        sql = (
            "SELECT id, created_at, text, langs FROM messages "
            "WHERE processed_at IS NULL AND kind IS NULL"
        )
        params = []
        if session:
            sql += " AND session_id = ?"
            params.append(session)
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
            rows = con.execute(sql, params).fetchall()
        if not rows:
            return "<messages></messages>"
        out = ["<messages>"]
        for r in rows:
            out.append(
                '  <m id="{}" created_at="{}" langs="{}">{}</m>'.format(
                    r["id"],
                    _xml(r["created_at"]),
                    _xml(r["langs"] or ""),
                    _xml(r["text"]),
                )
            )
        out.append("</messages>")
        return "\n".join(out)

    @staticmethod
    def tag(pairs):
        """pairs: 'id=code[,code]' strings. Returns (ok_count, errors)."""
        updates, errors = [], []
        for p in pairs:
            id_part, eq, langs_part = p.partition("=")
            codes = [c.strip() for c in langs_part.split(",") if c.strip()]
            if (
                not eq
                or not id_part.isdigit()
                or not codes
                or not all(LANG_CODE.match(c) for c in codes)
            ):
                errors.append("malformed pair: " + p)
                continue
            updates.append((json.dumps(codes), int(id_part)))
        ok = 0
        with closing(connect()) as con, con:
            for langs_json, mid in updates:
                cur = con.execute(
                    "UPDATE messages SET langs=? WHERE id=?", (langs_json, mid)
                )
                if cur.rowcount == 0:
                    errors.append(f"unknown id: {mid}")
                else:
                    ok += 1
        return ok, errors

    @staticmethod
    def mark_processed(session=None):
        """Stamp tagged+unprocessed rows (and drill rows — excluded from analysis
        but must not stay pending forever); untagged natural rows stay."""
        sql = (
            "UPDATE messages SET processed_at=? WHERE processed_at IS NULL "
            "AND (langs IS NOT NULL OR kind = 'drill')"
        )
        params = [_now()]
        if session:
            sql += " AND session_id = ?"
            params.append(session)
        with closing(connect()) as con, con:
            cur = con.execute(sql, params)
            kept = con.execute(
                "SELECT COUNT(*) FROM messages"
                " WHERE processed_at IS NULL AND kind IS NULL"
            ).fetchone()[0]
        return f"processed {cur.rowcount}, kept {kept} untagged"

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
        + a fixed similarity threshold; no LLM judgment."""
        with closing(connect()) as con:
            con.create_function("similarity", 2, Messages._similarity)
            with con:
                cur = con.execute(
                    "UPDATE messages SET kind = 'drill' "
                    "WHERE processed_at IS NULL AND kind IS NULL "
                    "AND session_id IS NOT NULL "
                    "AND EXISTS (SELECT 1 FROM attempts a "
                    "            WHERE a.session_id = messages.session_id "
                    "              AND similarity(a.answer, messages.text) >= ?)",
                    (DRILL_SIMILARITY,),
                )
                marked = cur.rowcount
            unmatched = con.execute(
                "SELECT COUNT(*) FROM attempts a "
                "WHERE a.session_id IS NOT NULL "
                "AND NOT EXISTS (SELECT 1 FROM messages m "
                "                WHERE m.session_id = a.session_id "
                "                  AND similarity(a.answer, m.text) >= ?)",
                (DRILL_SIMILARITY,),
            ).fetchone()[0]
        return f"marked {marked} drill answer(s); {unmatched} attempt(s) unmatched"
