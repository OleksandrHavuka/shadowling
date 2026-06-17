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
import shutil
import subprocess

# The spec-verified model ids (claude 2.1.178, 2026-06-16/17): haiku for triage +
# the once-per-run language-code resolution, sonnet for the analytical specialists.
HAIKU = "claude-haiku-4-5"
SONNET = "claude-sonnet-4-6"
CLAUDE_TIMEOUT = 180  # seconds per headless call


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
