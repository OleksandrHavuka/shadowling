#!/usr/bin/env python3
"""vocab.py - SHIM (uniform-DB refactor). Data lives in models/vocab.py; this
keeps the glossing hooks (inject/scan) and the add/remove/list-active CLI
working until loot.py/drop.py/gloss.py take over. Deleted/renamed in phase 3."""

import json
import sys

from core import config_ready, last_assistant_text, load_config
from models.vocab import Vocab
from tagio import read_fields, rows


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
    return Vocab.scan_decrement(text)


def gloss_rules(first_language):
    """Build the glossing instruction for the learner's first (native) language."""
    return (
        "VOCAB GLOSSING: The user is learning new vocabulary. For each "
        "active word listed below, the FIRST time that word appears in any reply "
        f"you write to the user, append its {first_language} translation inline in "
        "parentheses immediately after the word (write the word, then its "
        f"{first_language} translation in parentheses). Gloss only the "
        "first occurrence "
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
    )


def inject(event="SessionStart"):
    cfg = load_config()
    if cfg["missing"]:
        context = cfg["notice"]
    else:
        rows_ = Vocab.list_active()
        if not rows_:
            return ""
        rules = gloss_rules(cfg["first_language"])
        word_lines = "\n".join(
            "- {} = {} (remaining {})".format(
                r["word"], r["translation"], r["remaining"]
            )
            for r in rows_
        )
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
        print(
            "usage: vocab.py {add|remove|list-active|inject|scan} ...",
            file=sys.stderr,
        )
        return 1
    cmd = argv[0]
    if cmd == "add":
        cfg = load_config()
        if cfg["missing"]:
            print(cfg["notice"], file=sys.stderr)
            return 1
        try:
            items = read_fields({"items": rows("word", "translation")})["items"]
        except ValueError as e:
            print("error: " + str(e), file=sys.stderr)
            return 1
        if not items:
            print(
                "usage: vocab.py add (word<TAB>translation lines in an "
                "<items>...</items> tag on stdin)",
                file=sys.stderr,
            )
            return 1
        for item in items:
            action, row = Vocab.add(item["word"], item["translation"])
            print(
                "{}: {} = {} (remaining {}, {})".format(
                    action,
                    row["word"],
                    row["translation"],
                    row["remaining"],
                    row["status"],
                )
            )
        return 0
    if cmd == "remove":
        words = argv[1:]
        if not words:
            print('usage: vocab.py remove "<word>" ["<word>" ...]', file=sys.stderr)
            return 1
        for word in words:
            print(
                "{}: {}".format(word, "removed" if Vocab.remove(word) else "not found")
            )
        return 0
    if cmd == "list-active":
        for r in Vocab.list_active():
            print(
                "{} = {} (remaining {})".format(
                    r["word"], r["translation"], r["remaining"]
                )
            )
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
    print(f"unknown command: {cmd}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
