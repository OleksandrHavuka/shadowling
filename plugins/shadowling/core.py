#!/usr/bin/env python3
"""core.py - shared infrastructure for shadowling scripts (stdlib only, Python 3.9+).

The dependency-free foundation the rest of the plugin builds on: it imports
nothing from the project, so the dependency arrow only ever points *into* here.
Provides data-dir resolution, config load/save + the whole-plugin gate,
chat-transcript reading, and the write-time date/slug helpers. core stays
unaware of its callers by design — describe what it offers, never who uses it.
"""

import json
import os
import re
from datetime import datetime

# first_language = the learner's native/mother tongue (translations go INTO it);
# learning_language = the language the learner is studying (the prose that gets
#   analyzed/drilled; never assume a specific one — English is no longer baked in);
# explanation_language = the language corrections/explanations are written in.
# Order matches /shadowling:setup's questions and the documented config.json.
CONFIG_KEYS = ("first_language", "learning_language", "explanation_language")


def data_dir():
    """Persistent data directory (NOT the plugin code dir, which is ephemeral)."""
    return os.environ.get("SHADOWLING_HOME") or os.path.expanduser("~/.shadowling")


def config_path():
    return os.path.join(data_dir(), "config.json")


def raw_config():
    """Parsed config.json as written (no defaults). Returns {} if missing/bad."""
    try:
        with open(config_path(), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def load_config():
    """Each CONFIG_KEYS value ("" when missing/malformed; no defaults) plus the
    gate state derived in this one place: "missing" (required keys with no value)
    and "notice" (the user-facing misconfig text, "" when ready). The gate
    otherwise closes glossing silently (capture keeps logging — it needs no
    config), so the UserPromptSubmit hook just emits cfg["notice"]. Both are
    in-memory only — save_config persists raw_config, not this."""
    data = raw_config()
    cfg: dict[str, object] = {}
    for key in CONFIG_KEYS:
        value = data.get(key)
        cfg[key] = value.strip() if isinstance(value, str) else ""
    missing = [key for key in CONFIG_KEYS if not cfg[key]]
    cfg["missing"] = missing
    cfg["notice"] = ""
    if missing:
        cfg["notice"] = (
            "<shadowling_misconfig>\n"
            "shadowling is not fully configured — vocab glossing and analysis "
            "(/debrief, /tutor) are OFF (your messages are still captured).\n"
            "Missing required setting(s): " + ", ".join(missing) + ".\n"
            "Run /shadowling:setup (or `config.py set <key> <value>`) to enable.\n"
            "</shadowling_misconfig>"
        )
    return cfg


def config_ready(cfg=None):
    """The whole-plugin gate: True iff every CONFIG_KEYS value is non-empty."""
    cfg = load_config() if cfg is None else cfg
    return all(cfg.get(key) for key in CONFIG_KEYS)


def save_config(values):
    """Merge `values` into config.json, preserving any existing keys.

    Reads the current file (ignoring corruption), updates it with the given
    string values, and writes the result back. Returns the written dict.
    """
    path = config_path()
    data = raw_config()
    for key, value in values.items():
        if isinstance(value, str) and value.strip():
            data[key] = value.strip()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return data


def _last_message_text(transcript_path, role):
    """Text of the last transcript message with the given role ('assistant'/'user')."""
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
            if obj.get("type") != role:
                continue
            if obj.get("isMeta"):  # slash-command bodies, skill injections, etc.
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


def last_assistant_text(transcript_path):
    return _last_message_text(transcript_path, "assistant")


def last_user_text(transcript_path):
    return _last_message_text(transcript_path, "user")


def today():
    """Today's date as YYYY-MM-DD — the single write-time date source."""
    return datetime.now().strftime("%Y-%m-%d")


def now():
    """Current local time as an ISO timestamp to the second
    (YYYY-MM-DDTHH:MM:SS) — the single write-time timestamp source for audit
    stamps and the attempts event log. `today()` stays for date-only math."""
    return datetime.now().isoformat(timespec="seconds")


def slugify(s):
    """Canonical kebab-case slug key, robust to whatever the LLM emits.

    Lowercases (casefold, so e.g. ß -> ss), turns any run of whitespace/underscores
    into a single hyphen, KEEPS Unicode letters/digits of ANY script (Cyrillic,
    CJK, …) and drops only punctuation/symbols, then collapses repeated hyphens
    and trims leading/trailing ones. The slug is an internal GROUP BY key, never
    shown to the user, so native script is preserved (no transliteration). So
    "Word Choice_Plural", "word-choice-plural", and "  word  choice plural " all
    canonicalize to the same key, keeping the frequency counter honest. The only
    degenerate output is all-punctuation input -> "" (rejected at the chokepoint).
    """
    s = re.sub(r"[\s_]+", "-", s.strip()).casefold()
    # Keep Unicode word chars (\w = letters/digits/underscore) and hyphens; the
    # step above already turned every "_" into "-", so \w won't re-admit "_".
    s = re.sub(r"[^\w-]+", "", s, flags=re.UNICODE)
    s = re.sub(r"-+", "-", s)
    return s.strip("-")
