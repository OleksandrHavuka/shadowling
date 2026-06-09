#!/usr/bin/env python3
"""core.py - shared infrastructure for shadowling scripts (stdlib only, Python 3.9+).

Home-directory resolution, config loading, transcript reading, and the
`.script_path` registration used by both `vocab.py` (glossing) and `capture.py`
(English-correction collection).
"""
import json
import os
from datetime import datetime

DEFAULT_CONFIG = {"native_language": "Ukrainian", "learning_language": "English"}


def data_dir():
    """Persistent data directory (NOT the plugin code dir, which is ephemeral)."""
    return os.environ.get("SHADOWLING_HOME") or os.path.expanduser("~/.shadowling")


def config_path():
    return os.environ.get("SHADOWLING_CONFIG") or os.path.join(data_dir(), "config.json")


def raw_config():
    """Parsed config.json as written (no defaults). Returns {} if missing/bad."""
    try:
        with open(config_path(), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def load_config():
    """Read config.json, falling back to DEFAULT_CONFIG for missing/bad values."""
    cfg = dict(DEFAULT_CONFIG)
    data = raw_config()
    for key in DEFAULT_CONFIG:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            cfg[key] = value.strip()
    return cfg


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


def register_script_path():
    """Record this script's absolute path (in `.script_path`) so slash commands can
    locate the plugin's scripts. Hooks get `${CLAUDE_PLUGIN_ROOT}`; command bodies
    don't, so they read this file and resolve their target as
    `dirname(.script_path)/<script>.py`.
    """
    try:
        path = os.path.join(data_dir(), ".script_path")
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(os.path.abspath(__file__))
    except OSError:
        pass


def today():
    """Today's date as YYYY-MM-DD — the single write-time date source."""
    return datetime.now().strftime("%Y-%m-%d")
