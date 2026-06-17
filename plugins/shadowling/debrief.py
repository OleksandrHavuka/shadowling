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

import concurrent.futures
import functools
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import typing

import core
import langcodes
from appdb import connect, tx
from config import config_block
from models.base import Model
from models.friction import Friction
from models.grammar import Grammar
from models.idioms import Idioms
from models.messages import Messages
from models.rephrasing import Rephrasing
from models.verbs import Verbs
from models.vocab import Vocab
from skillio import render

# The spec-verified model ids (claude 2.1.178, 2026-06-16/17): haiku for triage,
# sonnet for the analytical specialists.
HAIKU = "claude-haiku-4-5"
SONNET = "claude-sonnet-4-6"
CLAUDE_TIMEOUT = 180  # seconds per headless call

PROMPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts")


@functools.cache
def _prompt(name):
    """Read a specialist's static system prompt from prompts/<name>.txt (memoized
    — the files are static for the process lifetime)."""
    with open(os.path.join(PROMPTS_DIR, f"{name}.txt"), encoding="utf-8") as f:
        return f.read()


def _resolve_learning_code(cfg):
    """Map the configured learning-language NAME ('English') to its ISO 639 code
    ('en') via the langcodes table — a pure, instant, deterministic lookup (no
    LLM, so a transient model failure can't kill the whole run). Unknown name ->
    DebriefError pointing at /setup; the run then processes nothing and a later
    run retries once the config is fixed."""
    code = langcodes.NAME_TO_CODE.get(cfg["learning_language"].strip().lower())
    if code is None:
        raise DebriefError(
            f"no ISO code known for learning_language "
            f"{cfg['learning_language']!r}; add it to langcodes.py or run /setup"
        )
    return code


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
                    "langs": {
                        "type": "array",
                        "minItems": 1,
                        "items": {"type": "string", "enum": sorted(langcodes.CODES)},
                    },
                },
            },
        }
    },
}


def _config_block(cfg):
    """The <config> block, owned by config.config_block (single source)."""
    return config_block(cfg)


def _messages_block(rows, fields):
    """Wrap skillio.render(rows, fields=…) in the <messages> tag the specialists
    read — the one idiom every message slice uses."""
    return "<messages>" + render(rows, fields=fields) + "</messages>"


def _validate_triage(rows, valid_ids):
    """Reshape the triage model's tags for Messages.tag and enforce batch
    COVERAGE — the only invariant the schema can't express across a batch: every
    id we sent is tagged exactly once, and no id we did not send appears. Code
    format/non-emptiness is guaranteed by TRIAGE_SCHEMA (enum from langcodes.CODES
    + minItems:1). Returns [{"id": int, "langs": "en,uk"}]. Raises DebriefError
    (naming the offender) on a coverage violation, so the batch aborts and the
    session stays pending for a clean retry."""
    clean = []
    seen = set()
    for r in rows:
        rid = r.get("id")
        if rid not in valid_ids:
            raise DebriefError(f"triage returned an unknown message id: {rid!r}")
        codes = [c.strip() for c in (r.get("langs") or []) if isinstance(c, str)]
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
                _messages_block(batch, ["id", "text"]),
            ]
        )
        out = _run_claude(_prompt("triage"), data, TRIAGE_SCHEMA, HAIKU, runner=runner)
        valid_ids = {row["id"] for row in batch}
        clean = _validate_triage(out.get("tags", []), valid_ids)
        Messages.tag(clean)


def _findings_schema(*cols, enums=None, extra=None):
    """Build a {"findings": [ {col: string|enum, ...} ]} schema from a model's
    column list, so the schema is GENERATED from insert_cols and can't drift from
    it. `enums` ({col: iterable}) gives a column an `enum`; `extra` ({prop:
    subschema}) adds top-level properties (friction's `loot`). all-required,
    additionalProperties:false everywhere."""
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


# A {word, translation} pair array — friction's vocabulary loot.
_PAIRS_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "additionalProperties": False,
        "required": ["word", "translation"],
        "properties": {
            "word": {"type": "string"},
            "translation": {"type": "string"},
        },
    },
}


class _Spec(typing.NamedTuple):
    """One specialist category's single owner: the repository it persists into and
    the StructuredOutput schema it returns. The schema is GENERATED from the model's
    insert_cols (and friction's enum), so the two can't drift. Iterating SPECS is
    the only place the category set is enumerated — persistence, dedup reads, the
    fan-out schemas, and CATEGORIES all derive from it, so adding a category is a
    one-line edit that can't leave a category half-wired."""

    model: type[Model]
    schema: dict


# friction's schema adds its `type` enum (= Friction.enums) + a top-level `loot`
# array; the other four are a plain findings array over their insert_cols.
SPECS = {
    "grammar": _Spec(Grammar, _findings_schema(*Grammar.insert_cols)),
    "rephrasing": _Spec(Rephrasing, _findings_schema(*Rephrasing.insert_cols)),
    "idioms": _Spec(Idioms, _findings_schema(*Idioms.insert_cols)),
    "verbs": _Spec(Verbs, _findings_schema(*Verbs.insert_cols)),
    "friction": _Spec(
        Friction,
        _findings_schema(
            *Friction.insert_cols, enums=Friction.enums, extra={"loot": _PAIRS_SCHEMA}
        ),
    ),
}

CATEGORIES = tuple(SPECS)


def _build_jobs(cfg, lang, lang_slice, full_slice, dedup):
    """Build the per-specialist (system_prompt, stdin_data, schema, model) jobs on
    the MAIN thread (all DB reads already done; the workers do only the
    subprocess). Reuses skillio.render for every data block so the driver invents
    no new format. The four lang-sliced specialists get the learning-language
    slice + their own dedup; friction gets the full timeline (with langs) + the
    learning code + its own dedup + grammar dedup (cross-correlation)."""
    cfg_block = _config_block(cfg)
    lang_msgs = _messages_block(lang_slice, ["id", "text"])

    def lang_job(name):
        data = "\n".join(
            [
                cfg_block,
                lang_msgs,
                f"<{name}>" + render(dedup[name]) + f"</{name}>",
            ]
        )
        return (_prompt(name), data, SPECS[name].schema, SONNET)

    jobs = {
        name: lang_job(name) for name in ("grammar", "rephrasing", "idioms", "verbs")
    }
    friction_msgs = _messages_block(full_slice, ["id", "text", "langs"])
    jobs["friction"] = (
        _prompt("friction"),
        "\n".join(
            [
                cfg_block,
                "<learning_code>" + lang + "</learning_code>",
                friction_msgs,
                "<friction>" + render(dedup["friction"]) + "</friction>",
                "<grammar>" + render(dedup["grammar"]) + "</grammar>",
            ]
        ),
        SPECS["friction"].schema,
        SONNET,
    )
    return jobs


def _fan_out(jobs, *, runner=None):
    """Run the five specialists in parallel (one claude subprocess each; NO DB I/O
    in the workers). Returns (findings_by_category, failed) where `failed` maps a
    failed category -> the DebriefError reason; the rest land in `findings`. A
    specialist returning {"findings": []} is a SUCCESS — the gate is valid JSON
    returned, not non-empty findings."""
    findings, failed = {}, {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        futures = {
            pool.submit(_run_claude, sp, data, schema, model, runner=runner): cat
            for cat, (sp, data, schema, model) in jobs.items()
        }
        for fut in concurrent.futures.as_completed(futures):
            cat = futures[fut]
            try:
                findings[cat] = fut.result()
            except DebriefError as e:
                failed[cat] = str(e)
    return findings, failed


def _result(session, *, ok, failed=(), empty=False, errors=None):
    """One per-session result row for the run summary. `failed` is the list of
    failed stage/category names; `errors` maps each to its reason (printed by
    _print_summary)."""
    return {
        "session": session,
        "ok": ok,
        "failed": list(failed),
        "empty": empty,
        "errors": dict(errors or {}),
    }


def _persist(session, findings, loot):
    """Write a whole session in ONE per-session transaction: all five categories'
    findings + friction's loot + the processed-mark. Opened only AFTER all the
    slow LLM work, so it does not block other writers across the analysis; tx()
    (BEGIN IMMEDIATE) makes a concurrent capture-hook writer wait rather than
    interleave. Any failure (a ValueError from a finding's key/enum check, or a
    SQLite error) rolls the WHOLE session back — no partial write — and the next
    /debrief re-lists and re-runs it cleanly."""
    con = connect()  # fresh connection (cheap re-check; not the read-phase one)
    try:
        with tx(con):
            for cat, spec in SPECS.items():
                for item in findings[cat]:
                    spec.model.insert(item, con=con, session=session)
            for pair in loot:
                Vocab.add(
                    pair["word"], pair["translation"], con=con
                )  # vocab: no session
            Messages.mark_processed(session, con=con)
    finally:
        con.close()


def _run_session(session, cfg, lang, *, runner=None):
    """Process ONE session: triage -> per-language slice gate -> 5-way parallel
    specialist analysis -> atomic persist. Returns a _result dict. Nothing is
    persisted unless ALL five specialists succeed; a failure anywhere (triage,
    a specialist, or persist) leaves the session pending for the next run."""
    try:
        _run_triage(session, cfg, runner=runner)
    except DebriefError as e:
        return _result(session, ok=False, failed=["triage"], errors={"triage": str(e)})

    lang_slice = Messages.list(session=session, lang=lang)
    if not lang_slice:
        # Empty-language gate: triage tagged every row but none carries the
        # learning-language code, so neither the lang specialists nor friction's
        # code-switching analysis have anything. Persist just the processed-mark
        # (the tagged rows must not stay pending) and return OK.
        try:
            _persist(session, {c: [] for c in CATEGORIES}, [])
        except (ValueError, KeyError, TypeError, sqlite3.Error) as e:
            return _result(
                session, ok=False, failed=["persist"], errors={"persist": str(e)}
            )
        return _result(session, ok=True, empty=True)

    # All DB reads here, on the MAIN thread, before the fan-out.
    full_slice = Messages.list(session=session)
    dedup = {cat: spec.model.select() for cat, spec in SPECS.items()}
    jobs = _build_jobs(cfg, lang, lang_slice, full_slice, dedup)
    findings, failed = _fan_out(jobs, runner=runner)
    if failed:
        return _result(session, ok=False, failed=sorted(failed), errors=failed)

    try:
        persist_findings = {c: findings[c]["findings"] for c in CATEGORIES}
        loot = findings["friction"].get("loot", [])
        _persist(session, persist_findings, loot)
    except (ValueError, KeyError, TypeError, sqlite3.Error) as e:
        return _result(
            session, ok=False, failed=["persist"], errors={"persist": str(e)}
        )
    return _result(session, ok=True)


def _print_summary(marked, results):
    """The compact /debrief Bash output: drills marked, one line per session
    (OK / OK (empty) / ERROR <name — reason; …>), then totals."""
    print(f"marked {marked} drill(s)")
    for r in results:
        if r["ok"]:
            print(f"{r['session']}: OK" + (" (empty)" if r["empty"] else ""))
        else:
            parts = [
                f"{n} — {r['errors'][n]}" if r["errors"].get(n) else n
                for n in r["failed"]
            ]
            print(f"{r['session']}: ERROR {'; '.join(parts)}")
    ok = sum(1 for r in results if r["ok"])
    failed = len(results) - ok
    line = f"{ok}/{len(results)} session(s) OK"
    if failed:
        line += f"; re-run /debrief to retry the {failed} failed"
    print(line)


def main(runner=None):
    """The per-run driver. Returns a process exit code: 1 if any session failed
    (or config/lang resolution failed), else 0. Takes no interactive input and
    respects SHADOWLING_HOME — cron-safe. `runner` is the injectable subprocess
    seam (None in production; a fake in tests)."""
    marked = Messages.mark_drills()  # own commit, idempotent; fences tutor answers
    cfg = core.load_config()
    if not core.config_ready(cfg):
        print(cfg["notice"], file=sys.stderr)
        return 1
    try:
        lang = _resolve_learning_code(cfg)
    except DebriefError as e:
        print(f"could not resolve the learning-language code: {e}", file=sys.stderr)
        return 1
    sessions = Messages.sessions()
    if not sessions:
        print(f"marked {marked} drill(s); nothing to review")
        return 0
    results = [_run_session(s["session"], cfg, lang, runner=runner) for s in sessions]
    _print_summary(marked, results)
    return 1 if any(not r["ok"] for r in results) else 0


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


if __name__ == "__main__":
    sys.exit(main())
