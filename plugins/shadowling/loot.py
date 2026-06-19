#!/usr/bin/env python3
"""loot.py - the deterministic headless driver for fat /loot enrichment.

A peer of debrief.py at the plugin root. Reads a JSON {word: micro_context} map on
stdin (harvested by the main-context /loot skill), pre-reads each word's existing
vocab row, fans out chunked headless `claude -p` enrichment calls (with_retry per
chunk), validates each item, and dumb-UPSERTs the result. The LLM does the
old+new context merge; this driver carries no merge/ratchet logic. Stdlib only;
cron-safe (no interactive input)."""

import functools
import json
import os
import sqlite3
import sys

import core
from appdb import connect, tx
from config import config_block
from headless import SONNET, HeadlessError, run_claude
from models.vocab import Vocab
from parallel import fan_out, log, with_retry
from skillio import render

CHUNK_SIZE = 8
MAX_WORKERS = 6
ATTEMPTS = 3
BACKOFF = 2.0
MAX_RETRY_MISSING_PASSES = 1  # one extra pass for schema-invalid/missing words
LOOT_EFFORT = "medium"

PROMPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts")

LOOT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["words"],
    "properties": {
        "words": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "word",
                    "translation",
                    "examples",
                    "synonyms",
                    "definition",
                    "source_context",
                ],
                "properties": {
                    "word": {"type": "string"},
                    "translation": {"type": "string"},
                    "examples": {"type": "array", "items": {"type": "string"}},
                    "synonyms": {"type": "array", "items": {"type": "string"}},
                    "definition": {"type": "string"},
                    "source_context": {"type": "string"},
                },
            },
        }
    },
}


@functools.cache
def _loot_prompt():
    with open(os.path.join(PROMPTS_DIR, "loot.txt"), encoding="utf-8") as f:
        return f.read()


def _chunk(items, size):
    return [items[i : i + size] for i in range(0, len(items), size)]


def _build_data(cfg, chunk, contexts, existing):
    """The stdin block for one chunk: <config> + a <words> table where each row
    carries the new context and the existing record (the merge inputs)."""
    rows = []
    for w in chunk:
        rec = existing.get(w, {})
        rows.append(
            {
                "word": w,
                "context": contexts.get(w, ""),
                "known_translation": rec.get("translation") or "",
                "known_examples": rec.get("examples") or "",
                "known_source_context": rec.get("source_context") or "",
            }
        )
    return "\n".join([config_block(cfg), "<words>" + render(rows) + "</words>"])


def _valid(item, word):
    """An item is valid if it has a non-empty translation and >=1 example, each
    example containing the target word case-insensitively (plain, no cloze)."""
    if not (item.get("translation") or "").strip():
        return False
    examples = item.get("examples")
    if not isinstance(examples, list) or not examples:
        return False
    return all(isinstance(s, str) and word.lower() in s.lower() for s in examples)


def _enrich_chunk(cfg, chunk, contexts, existing, *, runner):
    """Enrich one chunk via a single with_retry'd headless call. Returns {word:
    item} for the VALID items only. Raises HeadlessError if the call exhausts its
    retries (the whole chunk's words then stay pending — not retry-missing'd)."""
    data = _build_data(cfg, chunk, contexts, existing)
    out = with_retry(
        lambda: run_claude(
            _loot_prompt(), data, LOOT_SCHEMA, SONNET, runner=runner, effort=LOOT_EFFORT
        ),
        attempts=ATTEMPTS,
        backoff=BACKOFF,
        retry_on=HeadlessError,
    )
    cset = set(chunk)
    valid = {}
    for item in out.get("words", []):
        w = (item.get("word") or "").strip().lower()
        if w in cset and _valid(item, w):
            valid[w] = item
    return valid


def _chunk_thunk(cfg, chunk, contexts, existing, runner):
    """Zero-arg thunk enriching one chunk. Binds `chunk` as an argument so the
    fan-out closure can't capture the comprehension's loop variable."""
    return lambda: _enrich_chunk(cfg, chunk, contexts, existing, runner=runner)


def _persist(enriched):
    """Dumb UPSERT each enriched word in its OWN transaction (partial-success: one
    bad row rolls back only itself). Returns the count persisted."""
    con = connect()
    n = 0
    try:
        for word, item in enriched.items():
            try:
                with tx(con):
                    Vocab.add(
                        word,
                        item["translation"],
                        definition=item.get("definition"),
                        source_context=item.get("source_context"),
                        examples=item.get("examples"),
                        synonyms=item.get("synonyms"),
                        con=con,
                    )
                n += 1
            except (ValueError, KeyError, TypeError, sqlite3.Error) as e:
                log(f"    ✗ persist {word} — {e}")
    finally:
        con.close()
    return n


def run(payload, cfg, *, runner=None):
    """Enrich + persist a {word: micro_context} map. Returns a summary dict
    {total, enriched, pending}. A chunk whose call fails leaves its words pending
    (not retried); words merely missing/invalid from a successful chunk get one
    retry-missing pass."""
    words = {
        w.strip().lower(): (c or "") for w, c in payload.items() if w and w.strip()
    }
    total = len(words)
    existing = Vocab.get_many(list(words))
    enriched = {}
    failed = set()
    pending = set(words)
    for p in range(MAX_RETRY_MISSING_PASSES + 1):
        if not pending:
            break
        chunks = _chunk(sorted(pending), CHUNK_SIZE)
        chunk_words = {f"p{p}-c{i}": set(ch) for i, ch in enumerate(chunks)}
        jobs = {
            name: _chunk_thunk(cfg, sorted(cw), words, existing, runner)
            for name, cw in chunk_words.items()
        }
        ok, chunk_failed = fan_out(jobs, max_workers=MAX_WORKERS)
        for name in chunk_failed:
            failed |= chunk_words[name]  # call failed -> pending, not retried
        for got in ok.values():
            enriched.update(got)
        pending = set(words) - set(enriched) - failed  # missing/invalid -> retry
    pending |= failed
    persisted = _persist(enriched)
    return {"total": total, "enriched": persisted, "pending": sorted(pending)}


def main(runner=None):
    """Read {word: context} JSON from stdin, gate on config, enrich, print a
    summary. Exit 1 on a config/parse error or if any word stayed pending."""
    cfg = core.load_config()
    if not core.config_ready(cfg):
        print(cfg["notice"], file=sys.stderr)
        return 1
    try:
        payload = json.loads(sys.stdin.read())
    except ValueError:
        print("loot.py: stdin must be a JSON object {word: context}", file=sys.stderr)
        return 1
    if not isinstance(payload, dict) or not payload:
        print("loot.py: empty or non-object payload", file=sys.stderr)
        return 1
    summary = run(payload, cfg, runner=runner)
    line = f"{summary['enriched']}/{summary['total']} enriched"
    if summary["pending"]:
        line += f"; re-run /loot to retry {len(summary['pending'])}: " + ", ".join(
            summary["pending"]
        )
    print(line, flush=True)
    return 1 if summary["pending"] else 0


if __name__ == "__main__":
    sys.exit(main())
