#!/usr/bin/env python3
"""debrief.py - the deterministic headless driver for the per-session debrief.

A peer of capture.py / gloss.py at the plugin root. It owns the control logic
that used to live in the /debrief orchestrator LLM: the per-session loop, the
all-OK gate, the conditional processed-mark, plus language-code and JSON-schema
validation. The only thing left to a model is the linguistic analysis, done via
headless `claude -p` calls behind an injectable subprocess seam (so tests never
spawn claude). Specialists RETURN validated findings; this driver persists a
whole session's findings + its processed-mark in ONE short per-session
transaction, so a failure rolls back clean and a retry starts fresh. Stdlib only,
Python 3.9+; cron-safe by construction (no interactive input)."""

import json
import os
import re
import shutil
import subprocess

import core
from models.messages import Messages
from skillio import render

# The spec-verified model ids (claude 2.1.178, 2026-06-16/17): haiku for triage +
# the once-per-run language-code resolution, sonnet for the analytical specialists.
HAIKU = "claude-haiku-4-5"
SONNET = "claude-sonnet-4-6"
CLAUDE_TIMEOUT = 180  # seconds per headless call

# ISO-style language code (moved here from skills/debrief-triage/triage.py); "und"
# fits too. Used both for triage validation and the language-code resolution.
LANG_CODE = re.compile(r"^[a-z]{2,3}$")

PROMPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts")

# The language-code resolver's role is a one-liner (not rewritten from a SKILL.md
# body), so it stays an inline constant rather than a prompts/*.txt file.
LANG_CODE_PROMPT = (
    "You map a natural-language NAME to its ISO 639 language code. The input is a "
    "single <learning_language> tag holding a language name (e.g. English, "
    "Ukrainian, German). Return the lowercase ISO 639-1 two-letter code when one "
    "exists (English->en, German->de, Spanish->es, Ukrainian->uk), else the ISO "
    "639-3 three-letter code. Answer ONLY by calling the StructuredOutput tool "
    'once with {"code": "<code>"}.'
)
LANG_CODE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["code"],
    "properties": {"code": {"type": "string"}},
}


def _prompt(name):
    """Read a specialist's static system prompt from prompts/<name>.txt."""
    with open(os.path.join(PROMPTS_DIR, f"{name}.txt"), encoding="utf-8") as f:
        return f.read()


def _resolve_learning_code(cfg, *, runner=None, attempts=2):
    """Map the configured learning-language NAME ('English') to its ISO 639 code
    ('en') via a tiny haiku call. Deriving the code from the name stays model
    judgment (per the ENGINEERING.md deterministic-boundary table), so the plugin
    keeps no language->code table and stays language-agnostic. A couple of
    internal retries; raises DebriefError if it still fails (the run then
    processes nothing and a later run retries)."""
    data = "<learning_language>" + cfg["learning_language"] + "</learning_language>"
    last = DebriefError("language-code resolution never ran")
    for _ in range(attempts):
        try:
            out = _run_claude(
                LANG_CODE_PROMPT, data, LANG_CODE_SCHEMA, HAIKU, runner=runner
            )
            code = str(out.get("code", "")).strip().lower()
            if LANG_CODE.match(code):
                return code
            last = DebriefError(f"resolved code {code!r} is not a valid ISO 639 code")
        except DebriefError as e:
            last = e
    raise last


TRIAGE_BATCH = 200
TRIAGE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["tags"],
    "properties": {
        "tags": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "langs"],
                "properties": {
                    "id": {"type": "integer"},
                    "langs": {"type": "array", "items": {"type": "string"}},
                },
            },
        }
    },
}


def _config_block(cfg):
    """The <config> block exactly as config.py `show` emits it, so a prompt's
    'read the config languages' instruction maps to the same shape the old skills
    saw. Reuses skillio.render — the driver invents no new format."""
    return "<config>" + render([{k: cfg[k] for k in core.CONFIG_KEYS}]) + "</config>"


def _validate_triage(rows, valid_ids):
    """Validate the triage model's tags and reshape them for Messages.tag.

    `rows` is structured_output["tags"]: [{"id": int, "langs": [str]}]. `valid_ids`
    is the set of message ids in this batch. Enforces (1) every returned id is one
    we sent (no hallucinated id), (2) every batch id is tagged (full coverage, so
    the triage loop always makes progress and terminates), and (3) each code
    matches LANG_CODE. Returns Messages.tag-shaped rows
    [{"id": int, "langs": "en,uk"}]. Raises DebriefError (naming the offender) on
    any violation — the caller aborts the batch, nothing is tagged, and the
    session stays pending for a clean retry (exactly as the old triage skill did
    for a bad code)."""
    clean = []
    seen = set()
    for r in rows:
        rid = r.get("id")
        raw = r.get("langs") or []
        codes = [c.strip() for c in raw if isinstance(c, str) and c.strip()]
        if rid not in valid_ids:
            raise DebriefError(f"triage returned an unknown message id: {rid!r}")
        if not codes or not all(LANG_CODE.match(c) for c in codes):
            raise DebriefError(
                f"triage: bad language code(s) for id {rid!r}: {raw!r}"
                " (expected 2-3 lowercase letters, e.g. en or en,uk)"
            )
        seen.add(rid)
        clean.append({"id": rid, "langs": ",".join(codes)})
    missing = valid_ids - seen
    if missing:
        raise DebriefError(f"triage did not tag message id(s): {sorted(missing)}")
    return clean


def _run_triage(session, cfg, *, runner=None):
    """Loop until no untagged message remains in the session. Each pass: read an
    untagged batch (DB), run the haiku triage call, validate, and Messages.tag
    (its OWN committed transaction). Tags written mid-loop are fine — a re-run
    re-tags identically. Full-coverage validation guarantees each pass tags every
    row it read, so the loop always terminates. Raises DebriefError on any
    failure (the session stays pending; partial tags are harmless)."""
    while True:
        batch = Messages.list(session=session, untagged=True, limit=TRIAGE_BATCH)
        if not batch:
            return
        data = "\n".join(
            [
                _config_block(cfg),
                "<messages>" + render(batch, fields=["id", "text"]) + "</messages>",
            ]
        )
        out = _run_claude(_prompt("triage"), data, TRIAGE_SCHEMA, HAIKU, runner=runner)
        valid_ids = {row["id"] for row in batch}
        clean = _validate_triage(out.get("tags", []), valid_ids)
        Messages.tag(clean)


class DebriefError(Exception):
    """Any failure in a headless call, its validation, or persistence. Caught per
    session/run; the affected session stays pending and the summary reports it."""


def _subprocess_runner(argv, data):
    """Production seam: spawn claude, feed `data` (the bulk slice + dedup context)
    on STDIN (ARG_MAX-safe), return stdout text. Raises subprocess.TimeoutExpired
    on timeout (mapped to DebriefError by _run_claude)."""
    proc = subprocess.run(
        argv, input=data, capture_output=True, text=True, timeout=CLAUDE_TIMEOUT
    )
    return proc.stdout


def _parse_result(stdout):
    """Parse claude's `--output-format json` stdout (a JSON array of event
    objects). Take the LAST type=='result' event; require subtype=='success' and a
    falsy is_error; return its structured_output dict. Relies on subtype/is_error,
    NOT the exit code (the StructuredOutput tool turn can make the CLI exit
    non-zero even on success). Any other shape -> DebriefError."""
    try:
        events = json.loads(stdout)
    except (ValueError, TypeError) as e:
        raise DebriefError("claude did not return JSON") from e
    if not isinstance(events, list):
        raise DebriefError("claude JSON was not an event array")
    results = [e for e in events if isinstance(e, dict) and e.get("type") == "result"]
    if not results:
        raise DebriefError("no result event in claude output")
    result = results[-1]
    if result.get("subtype") != "success" or result.get("is_error"):
        raise DebriefError(
            f"claude result not success: subtype={result.get('subtype')!r}"
            f" is_error={result.get('is_error')!r}"
        )
    out = result.get("structured_output")
    if not isinstance(out, dict):
        raise DebriefError("claude result is missing structured_output")
    return out


def _run_claude(system_prompt, data, schema, model, *, runner=None):
    """Run one headless `claude -p` analysis call and return its validated
    structured_output. `data` (the bulk slice + dedup context) goes on STDIN; only
    the small static role goes in --system-prompt. `runner` is the injectable
    subprocess seam: None in production (real subprocess.run after a shutil.which
    pre-flight), a fake in tests. Raises DebriefError on a missing claude, a
    timeout, or any unexpected output shape."""
    if runner is None:
        if shutil.which("claude") is None:
            raise DebriefError("`claude` was not found on PATH")
        runner = _subprocess_runner
    argv = [
        "claude",
        "-p",
        "--safe-mode",
        "--system-prompt",
        system_prompt,
        "--model",
        model,
        "--tools",
        "",
        "--output-format",
        "json",
        "--json-schema",
        json.dumps(schema),
        "--max-turns",
        "4",
    ]
    try:
        stdout = runner(argv, data)
    except subprocess.TimeoutExpired as e:
        raise DebriefError(f"claude timed out after {CLAUDE_TIMEOUT}s") from e
    return _parse_result(stdout)
