#!/usr/bin/env python3
"""vocab.py - global vocabulary glossing store (stdlib only, Python 3.9+)."""
import csv
import json
import os
import re
import sys

FIELDS = ["word", "translation", "remaining", "status"]
START_REMAINING = 10
STEM_MIN_LEN = 4


def data_dir():
    """Persistent data directory (NOT the plugin code dir, which is ephemeral)."""
    return os.environ.get("VOCAB_HOME") or os.path.expanduser("~/.lexigloss")


def csv_path():
    return os.environ.get("VOCAB_CSV") or os.path.join(data_dir(), "words.csv")


def load_rows(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return [dict(r) for r in csv.DictReader(f)]


def save_rows(path, rows):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r[k] for k in FIELDS})


def add(word, translation):
    word = word.strip().lower()
    translation = translation.strip()
    path = csv_path()
    rows = load_rows(path)
    for r in rows:
        if r["word"] == word:
            if r["status"] == "learned":
                r["remaining"] = str(START_REMAINING)
                r["status"] = "active"
                r["translation"] = translation
                action = "relearn"
            else:
                r["translation"] = translation
                action = "refresh"
            save_rows(path, rows)
            return action, r
    row = {
        "word": word,
        "translation": translation,
        "remaining": str(START_REMAINING),
        "status": "active",
    }
    rows.append(row)
    save_rows(path, rows)
    return "add", row


def remove(word):
    word = word.strip().lower()
    path = csv_path()
    rows = load_rows(path)
    kept = [r for r in rows if r["word"] != word]
    if len(kept) == len(rows):
        return False
    save_rows(path, kept)
    return True


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
    return [r for r in load_rows(csv_path()) if r["status"] == "active"]


def last_assistant_text(transcript_path):
    if not transcript_path or not os.path.exists(transcript_path):
        return ""
    last = ""
    with open(transcript_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if obj.get("type") != "assistant":
                continue
            content = obj.get("message", {}).get("content", [])
            if isinstance(content, str):
                text = content
            else:
                parts = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        parts.append(block.get("text", ""))
                text = "".join(parts)
            if text.strip():
                last = text
    return last


def scan(stdin_text):
    try:
        data = json.loads(stdin_text) if stdin_text.strip() else {}
    except (json.JSONDecodeError, AttributeError):
        return []
    text = last_assistant_text(data.get("transcript_path", ""))
    if not text:
        return []
    path = csv_path()
    rows = load_rows(path)
    changed = []
    for r in rows:
        if r["status"] != "active":
            continue
        if word_in_text(r["word"], text):
            try:
                remaining = int(r["remaining"]) - 1
            except (ValueError, TypeError):
                continue
            if remaining <= 0:
                remaining = 0
                r["status"] = "learned"
            r["remaining"] = str(remaining)
            changed.append(r["word"])
    if changed:
        save_rows(path, rows)
    return changed


DEFAULT_CONFIG = {"native_language": "Ukrainian", "learning_language": "English"}


def config_path():
    return os.environ.get("VOCAB_CONFIG") or os.path.join(data_dir(), "config.json")


def load_config():
    """Read config.json, falling back to DEFAULT_CONFIG for missing/bad values."""
    cfg = dict(DEFAULT_CONFIG)
    try:
        with open(config_path(), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return cfg
    if isinstance(data, dict):
        for key in DEFAULT_CONFIG:
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                cfg[key] = value.strip()
    return cfg


def gloss_rules(native_language, learning_language):
    """Build the glossing instruction for the configured language pair."""
    return (
        "VOCAB GLOSSING: The user is learning {learning} vocabulary. For each "
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
    ).format(native=native_language, learning=learning_language)


def inject(event="SessionStart"):
    rows = list_active()
    if not rows:
        return ""
    cfg = load_config()
    rules = gloss_rules(cfg["native_language"], cfg["learning_language"])
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


def register_script_path():
    """Record this script's absolute path so the slash command can find it.

    Hooks run with ${CLAUDE_PLUGIN_ROOT} set and know __file__; the /vocab command
    body does not get that variable, so it reads the path from here instead.
    """
    try:
        path = os.path.join(data_dir(), ".script_path")
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(os.path.abspath(__file__))
    except OSError:
        pass


def main(argv):
    register_script_path()
    if not argv:
        print("usage: vocab.py {add|remove|list-active|inject|scan} ...",
              file=sys.stderr)
        return 1
    cmd = argv[0]
    if cmd == "add":
        if len(argv) < 3:
            print('usage: vocab.py add "<word>" "<translation>"', file=sys.stderr)
            return 1
        action, row = add(argv[1], argv[2])
        print("{0}: {1} = {2} (remaining {3}, {4})".format(
            action, row["word"], row["translation"], row["remaining"], row["status"]))
        return 0
    if cmd == "remove":
        if len(argv) < 2:
            print('usage: vocab.py remove "<word>"', file=sys.stderr)
            return 1
        print("removed" if remove(argv[1]) else "not found")
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
