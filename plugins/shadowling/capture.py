#!/usr/bin/env python3
"""capture.py - shadowling English-correction collector (stdlib only, Python 3.9+).

The Stop hook silently buffers the user's English messages (extracted from the
chat transcript) into ~/.shadowling/en_buffer.jsonl. On demand, `/en-review` has a
subagent read the buffer (`dump`) and append findings to four growing markdown
tables (`add-row`), then `clear` the buffer. Nothing is printed into the chat.
"""
import json
import os
import sys
from datetime import datetime

from core import data_dir, last_user_text, register_script_path
from mddb import norm_key, _split_row, _is_separator, _escape_cell

# Each doc: filename, column headers (order == add-row arg order), key column index
# used for dedup. Docs are single growing markdown tables; date is a column.
DOCS = {
    "grammar": {
        "file": "grammar.md",
        "cols": ["date", "❌ original", "✅ fixed", "rule"],
        "key": 1,
    },
    "rephrasings": {
        "file": "rephrasings.md",
        "cols": ["date", "\U0001f7e1 yours", "\U0001f7e2 natural", "why"],
        "key": 1,
    },
    "idioms": {
        "file": "idioms.md",
        "cols": ["date", "context", "idiom", "meaning", "you wrote"],
        "key": 2,
    },
    "irregular_verbs": {
        "file": "irregular_verbs.md",
        "cols": ["base", "past", "past participle", "example fix", "date"],
        "key": 0,
    },
}

MIN_LETTERS = 8  # below this we can't judge language reliably / not worth logging

# Claude Code wraps slash-command / local-command turns in these tags. Such turns
# are not the user's own writing, so they must never be buffered for analysis.
COMMAND_WRAPPERS = ("<command-", "<local-command-")


def buffer_path():
    return os.environ.get("SHADOWLING_EN_BUFFER") or os.path.join(
        data_dir(), "en_buffer.jsonl")


def doc_path(doc):
    return os.path.join(data_dir(), DOCS[doc]["file"])


def docs_paths():
    return {d: doc_path(d) for d in DOCS}


def is_english(text):
    """Heuristic: enough letters AND latin script dominates over cyrillic."""
    letters = [c for c in text if c.isalpha()]
    if len(letters) < MIN_LETTERS:
        return False
    latin = sum(1 for c in letters if "a" <= c.lower() <= "z")
    cyrillic = sum(1 for c in letters if "Ѐ" <= c <= "ӿ")
    return latin > cyrillic and latin >= len(letters) * 0.6


# --- buffer ----------------------------------------------------------------

def _read_buffer():
    path = buffer_path()
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def _append_buffer(record):
    path = buffer_path()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def capture(stdin_text):
    """Stop-hook entry: buffer the last user message if it's English. Never raises."""
    try:
        data = json.loads(stdin_text) if stdin_text.strip() else {}
    except (json.JSONDecodeError, AttributeError, TypeError):
        return False
    text = (last_user_text(data.get("transcript_path", "")) or "").strip()
    if not text or text.startswith("/"):
        return False
    if text.startswith(COMMAND_WRAPPERS):  # slash/local command echoes, not prose
        return False
    if not is_english(text):
        return False
    existing = _read_buffer()
    if existing and existing[-1].get("text") == text:
        return False  # guard against repeated Stop on the same turn
    _append_buffer({"ts": datetime.now().isoformat(timespec="seconds"), "text": text})
    return True


# --- markdown tables -------------------------------------------------------

def read_keys(doc):
    """Set of normalized keys already present in a doc's table (empty if no file)."""
    path = doc_path(doc)
    if not os.path.exists(path):
        return set()
    headers = DOCS[doc]["cols"]
    key_idx = DOCS[doc]["key"]
    keys = set()
    with open(path, encoding="utf-8") as f:
        for line in f.read().splitlines():
            if not line.strip().startswith("|"):
                continue
            cells = _split_row(line)
            if cells == headers or _is_separator(cells):
                continue
            if key_idx < len(cells):
                k = norm_key(cells[key_idx].replace("\\|", "|"))
                if k:
                    keys.add(k)
    return keys


def add_row(doc, *cols):
    """Append a row to a doc table, skipping exact-key duplicates.

    Callers pass the content columns only; the `date` column (recording date) is
    filled in here with today's date — it's a write-time fact, not the caller's.
    Returns 'added' | 'dup' | 'error'. Printing is the caller's (main's) job.
    """
    if doc not in DOCS:
        return "error"
    spec = DOCS[doc]
    headers = spec["cols"]
    cols = list(cols)
    if "date" in headers:
        di = headers.index("date")
        cols = cols[:di] + [datetime.now().strftime("%Y-%m-%d")] + cols[di:]
    cols = cols + [""] * len(headers)
    cols = cols[:len(headers)]
    key = norm_key(cols[spec["key"]])
    if key and key in read_keys(doc):
        return "dup"
    path = doc_path(doc)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    new_file = not os.path.exists(path)
    with open(path, "a", encoding="utf-8") as f:
        if new_file:
            f.write("| " + " | ".join(headers) + " |\n")
            f.write("| " + " | ".join("---" for _ in headers) + " |\n")
        f.write("| " + " | ".join(_escape_cell(c) for c in cols) + " |\n")
    return "added"


# --- commands --------------------------------------------------------------

def _xml(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def pending_count():
    return len(_read_buffer())


def dump():
    """Build the <en_review> block: pending buffer entries + existing keys per doc."""
    pending = _read_buffer()
    out = ["<en_review>", "  <pending>"]
    for i, rec in enumerate(pending, 1):
        out.append('    <entry n="{0}" ts="{1}">{2}</entry>'.format(
            i, _xml(rec.get("ts", "")), _xml(rec.get("text", ""))))
    out.append("  </pending>")
    out.append("  <existing>")
    for doc in DOCS:
        out.append("    <{0}>".format(doc))
        for k in sorted(read_keys(doc)):
            out.append("      <key>{0}</key>".format(_xml(k)))
        out.append("    </{0}>".format(doc))
    out.append("  </existing>")
    out.append("</en_review>")
    if not pending:
        out.append("# buffer empty: nothing to analyze")
    return "\n".join(out)


def clear():
    path = buffer_path()
    if os.path.exists(path):
        os.remove(path)
    return "cleared"


def paths():
    lines = ["buffer: " + buffer_path()]
    for d, p in docs_paths().items():
        lines.append("{0}: {1}".format(d, p))
    return "\n".join(lines)


def main(argv):
    register_script_path()
    if not argv:
        print("usage: capture.py {capture|pending-count|dump|add-row|clear|paths} ...",
              file=sys.stderr)
        return 1
    cmd = argv[0]
    if cmd == "capture":
        try:
            capture(sys.stdin.read())
        except Exception:  # the Stop hook must never crash the session
            pass
        return 0
    if cmd == "pending-count":
        print(pending_count())
        return 0
    if cmd == "dump":
        print(dump())
        return 0
    if cmd == "add-row":
        if len(argv) < 2:
            print("usage: capture.py add-row <doc> <col>...", file=sys.stderr)
            return 1
        result = add_row(argv[1], *argv[2:])
        print(result)
        return 1 if result == "error" else 0
    if cmd == "clear":
        print(clear())
        return 0
    if cmd == "paths":
        print(paths())
        return 0
    print("unknown command: " + cmd, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
