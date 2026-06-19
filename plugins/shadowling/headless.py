#!/usr/bin/env python3
"""headless.py - the headless `claude -p` engine (stdlib only).

Owns everything about driving a single non-interactive claude call: locating the
binary, building the locked-down argv, running it behind an injectable subprocess
seam, and parsing the StructuredOutput result. Knows nothing about debrief or
loot domains — both import it. Extracted from debrief.py (behaviour-preserving).
"""

import json
import os
import shutil
import subprocess

# Spec-verified model ids; single owner (debrief + loot import these).
HAIKU = "claude-haiku-4-5"
SONNET = "claude-sonnet-4-6"

DEFAULT_TIMEOUT = 300  # seconds per headless call

# Tool lockdown for every headless call, alongside `--tools ""`. A bare name in
# --disallowed-tools removes the tool from the model's context: "*" = every
# built-in tool, "mcp__*" = every MCP tool. `--tools ""` drops built-ins but not
# MCP; this closes that gap as a second barrier over --safe-mode.
DISALLOWED_TOOLS = "* mcp__*"


class HeadlessError(Exception):
    """Any failure in a headless call, its validation, or its result parsing."""


def resolve_claude():
    """Locate the claude executable. Prefer PATH (npm/native installs); then the
    local-installer path (`claude migrate-installer` exposes claude only as a
    shell alias pointing at ~/.claude/local/claude, invisible to a subprocess's
    PATH). Returns an absolute path, or None if nothing usable is found."""
    found = shutil.which("claude")
    if found:
        return found
    local = os.path.join(os.path.expanduser("~"), ".claude", "local", "claude")
    if os.path.isfile(local) and os.access(local, os.X_OK):
        return local
    return None


def subprocess_runner(argv, data, timeout=DEFAULT_TIMEOUT):
    """Production seam: spawn claude, feed `data` on STDIN (ARG_MAX-safe), return
    stdout text. Raises subprocess.TimeoutExpired on timeout (mapped to
    HeadlessError by run_claude)."""
    proc = subprocess.run(
        argv, input=data, capture_output=True, text=True, timeout=timeout
    )
    return proc.stdout


def parse_result(stdout):
    """Parse claude's `--output-format json` stdout (a JSON array of event
    objects). Take the LAST type=='result' event; require subtype=='success' and a
    falsy is_error; return its structured_output dict. Relies on subtype/is_error,
    NOT the exit code. Any other shape -> HeadlessError."""
    try:
        events = json.loads(stdout)
    except (ValueError, TypeError) as e:
        raise HeadlessError("claude did not return JSON") from e
    if not isinstance(events, list):
        raise HeadlessError("claude JSON was not an event array")
    results = [e for e in events if isinstance(e, dict) and e.get("type") == "result"]
    if not results:
        raise HeadlessError("no result event in claude output")
    result = results[-1]
    if result.get("subtype") != "success" or result.get("is_error"):
        raise HeadlessError(
            f"claude result not success: subtype={result.get('subtype')!r}"
            f" is_error={result.get('is_error')!r}"
        )
    out = result.get("structured_output")
    if not isinstance(out, dict):
        raise HeadlessError("claude result is missing structured_output")
    return out


def run_claude(
    system_prompt,
    data,
    schema,
    model,
    *,
    runner=None,
    effort=None,
    timeout=DEFAULT_TIMEOUT,
):
    """Run one headless `claude -p` call and return its validated structured_output.
    `data` goes on STDIN; only the small static role goes in --system-prompt.
    `effort` (when set) appends `--effort <level>`. `runner` is the injectable
    2-arg subprocess seam: None in production (real subprocess after a
    resolve_claude() pre-flight), a fake `runner(argv, data)` in tests. Raises
    HeadlessError on a missing claude, a timeout, or any unexpected output shape."""
    claude = "claude"
    if runner is None:
        claude = resolve_claude()
        if claude is None:
            raise HeadlessError("`claude` was not found on PATH or ~/.claude/local")

        def runner(argv, data):
            return subprocess_runner(argv, data, timeout)

    argv = [
        claude,
        "-p",
        "--safe-mode",
        "--system-prompt",
        system_prompt,
        "--model",
        model,
        "--tools",
        "",
        "--disallowed-tools",
        DISALLOWED_TOOLS,
        "--output-format",
        "json",
        "--json-schema",
        json.dumps(schema),
        "--max-turns",
        "4",
    ]
    if effort is not None:
        argv += ["--effort", effort]
    try:
        stdout = runner(argv, data)
    except subprocess.TimeoutExpired as e:
        raise HeadlessError(f"claude timed out after {timeout}s") from e
    return parse_result(stdout)


def findings_schema(*cols, enums=None, extra=None):
    """Build a {"findings": [ {col: string|enum, ...} ]} schema from a column list,
    so the schema is GENERATED from a model's insert_cols and can't drift. `enums`
    ({col: iterable}) gives a column an enum; `extra` ({prop: subschema}) adds
    top-level properties. all-required, additionalProperties:false everywhere."""
    enums = enums or {}
    extra = extra or {}
    props = {
        c: (
            {"type": "string", "enum": sorted(enums[c])}
            if c in enums
            else {"type": "string"}
        )
        for c in cols
    }
    item = {
        "type": "object",
        "additionalProperties": False,
        "required": list(cols),
        "properties": props,
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["findings", *extra],
        "properties": {"findings": {"type": "array", "items": item}, **extra},
    }
