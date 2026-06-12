#!/usr/bin/env python3
"""vocab.py - vocabulary glossing store for shadowling (stdlib only, Python 3.9+)."""
import json
import re
import sys
from datetime import datetime

from appdb import connect
from core import config_ready, last_assistant_text, load_config

START_REMAINING = 10
STEM_MIN_LEN = 4


def _now():
    # full ISO timestamp for the vocab audit stamps, matching capture._now().
    return datetime.now().isoformat(timespec="seconds")


def _norm(s):
    return re.sub(r"\s+", " ", s).strip().lower()


def add(word, translation):
    word = word.strip().lower()
    translation = translation.strip()
    # Guard against a failed/identity translation (e.g. the LLM echoing the term
    # back untranslated). Never persist such a row — signal the caller instead.
    if not translation or _norm(translation) == _norm(word):
        return "untranslated", {
            "word": word, "translation": translation,
            "remaining": "-", "status": "-",
        }
    now = _now()
    con = connect()
    try:
        row = con.execute("SELECT * FROM vocab WHERE word = ?",
                          (word,)).fetchone()
        with con:
            if row is None:
                con.execute(
                    "INSERT INTO vocab(word, translation, remaining, status,"
                    " created_at, updated_at) VALUES (?, ?, ?, 'active', ?, ?)",
                    (word, translation, START_REMAINING, now, now))
                action = "add"
            elif row["status"] == "learned":
                con.execute(
                    "UPDATE vocab SET translation = ?, remaining = ?,"
                    " status = 'active', updated_at = ? WHERE word = ?",
                    (translation, START_REMAINING, now, word))
                action = "relearn"
            else:
                con.execute(
                    "UPDATE vocab SET translation = ?, updated_at = ?"
                    " WHERE word = ?", (translation, now, word))
                action = "refresh"
        new = con.execute("SELECT * FROM vocab WHERE word = ?",
                          (word,)).fetchone()
        return action, dict(new)
    finally:
        con.close()


def remove(word):
    word = word.strip().lower()
    con = connect()
    try:
        with con:
            cur = con.execute("DELETE FROM vocab WHERE word = ?", (word,))
        return cur.rowcount > 0
    finally:
        con.close()


def build_pattern(word):
    word = word.strip().lower()
    esc = re.escape(word)
    left = r"(?<!\w)"
    right = r"(?!\w)"
    if len(word) >= STEM_MIN_LEN and word[-1:].isalnum():
        body = esc + r"(?:s|es|ed|ing|d)?"
    else:
        body = esc
    return re.compile(left + body + right, re.IGNORECASE)


def word_in_text(word, text):
    return build_pattern(word).search(text) is not None


def list_active():
    con = connect()
    try:
        return [dict(r) for r in con.execute(
            "SELECT * FROM vocab WHERE status = 'active' ORDER BY rowid")]
    finally:
        con.close()


def scan(stdin_text):
    if not config_ready():
        return []
    try:
        data = json.loads(stdin_text) if stdin_text.strip() else {}
    except (json.JSONDecodeError, AttributeError):
        return []
    text = last_assistant_text(data.get("transcript_path", ""))
    if not text:
        return []
    changed = []
    now = _now()
    con = connect()
    try:
        rows = con.execute(
            "SELECT * FROM vocab WHERE status = 'active'").fetchall()
        with con:
            for r in rows:
                if not word_in_text(r["word"], text):
                    continue
                remaining = max(r["remaining"] - 1, 0)
                status = "learned" if remaining == 0 else "active"
                con.execute(
                    "UPDATE vocab SET remaining = ?, status = ?,"
                    " updated_at = ? WHERE word = ?",
                    (remaining, status, now, r["word"]))
                changed.append(r["word"])
        return changed
    finally:
        con.close()


def gloss_rules(native_language):
    """Build the glossing instruction for the configured native language."""
    return (
        "VOCAB GLOSSING: The user is learning new vocabulary. For each "
        "active word listed below, the FIRST time that word appears in any reply "
        "you write to the user, append its {native} translation inline in "
        "parentheses immediately after the word (write the word, then its "
        "{native} translation in parentheses). Gloss only the first occurrence "
        "per reply. Do not gloss any word not in this list. CRITICAL: this list "
        "must NOT influence what you say. Write exactly as you naturally would; "
        "only annotate a word if it would have appeared anyway. Never insert, "
        "swap in, or steer toward these words to make them match. Additionally, "
        "at the very END of any reply in which you used one or more of these "
        "words, append a summary block: a separator line '---', then a line "
        "'\U0001f4d6 Vocabulary:', then one bullet per USED word formatted as "
        "'- word — translation (N to go)', where N is that word's remaining "
        "value shown in the list below. List each used word once. If you used "
        "none of these words, omit the block entirely. The active words "
        "(word = translation, remaining shown) are in the <active_words> tag "
        "below."
    ).format(native=native_language)


def inject(event="SessionStart"):
    cfg = load_config()
    if not config_ready(cfg):
        return ""
    rows = list_active()
    if not rows:
        return ""
    rules = gloss_rules(cfg["native_language"])
    word_lines = "\n".join(
        "- {0} = {1} (remaining {2})".format(
            r["word"], r["translation"], r["remaining"])
        for r in rows)
    context = (
        "<vocab_glossing>\n"
        "<rules>\n" + rules + "\n</rules>\n"
        "<active_words>\n" + word_lines + "\n</active_words>\n"
        "</vocab_glossing>"
    )
    out = {
        "hookSpecificOutput": {
            "hookEventName": event,
            "additionalContext": context,
        }
    }
    return json.dumps(out, ensure_ascii=False)


def main(argv):
    if not argv:
        print("usage: vocab.py {add|remove|list-active|inject|scan} ...",
              file=sys.stderr)
        return 1
    cmd = argv[0]
    if cmd == "add":
        if not config_ready():
            print("shadowling is not configured — run /shadowling:setup",
                  file=sys.stderr)
            return 1
        pairs = argv[1:]
        if not pairs or len(pairs) % 2 != 0:
            print('usage: vocab.py add "<word>" "<translation>" ['
                  '"<word>" "<translation>" ...]', file=sys.stderr)
            return 1
        for i in range(0, len(pairs), 2):
            action, row = add(pairs[i], pairs[i + 1])
            print("{0}: {1} = {2} (remaining {3}, {4})".format(
                action, row["word"], row["translation"],
                row["remaining"], row["status"]))
        return 0
    if cmd == "remove":
        words = argv[1:]
        if not words:
            print('usage: vocab.py remove "<word>" ["<word>" ...]', file=sys.stderr)
            return 1
        for word in words:
            print("{0}: {1}".format(
                word, "removed" if remove(word) else "not found"))
        return 0
    if cmd == "list-active":
        for r in list_active():
            print("{0} = {1} (remaining {2})".format(
                r["word"], r["translation"], r["remaining"]))
        return 0
    if cmd == "inject":
        event = argv[1] if len(argv) > 1 else "SessionStart"
        out = inject(event)
        if out:
            print(out)
        return 0
    if cmd == "scan":
        try:
            scan(sys.stdin.read())
        except Exception:
            pass
        return 0  # Stop hook must never fail
    print("unknown command: {0}".format(cmd), file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
