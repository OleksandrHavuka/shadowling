#!/usr/bin/env python3
"""core.py - shared infrastructure for shadowling scripts (stdlib only, Python 3.9+).

Home-directory resolution, config loading, and transcript reading, shared by
`vocab.py` (glossing) and `capture.py` (message collection).
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
    """Exactly CONFIG_KEYS, each "" when missing/malformed. No defaults."""
    data = raw_config()
    cfg = {}
    for key in CONFIG_KEYS:
        value = data.get(key)
        cfg[key] = value.strip() if isinstance(value, str) else ""
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


def slugify(s):
    """Canonical kebab-case slug key, robust to whatever the LLM emits.

    Lowercases, turns any run of whitespace/underscores into a single hyphen, drops
    every remaining char outside [a-z0-9-], collapses repeated hyphens, and trims
    leading/trailing hyphens. Guarantees the result matches `^[a-z0-9]+(-[a-z0-9]+)*$`
    (or is empty). So "Word Choice_Plural", "word-choice-plural", and "  word  choice
    plural " all canonicalize to the same key, keeping the frequency counter honest.
    """
    s = re.sub(r"[\s_]+", "-", s.strip().lower())
    s = re.sub(r"[^a-z0-9-]+", "", s)
    s = re.sub(r"-+", "-", s)
    return s.strip("-")
