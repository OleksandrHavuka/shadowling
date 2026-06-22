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

import functools
import os
import sqlite3
import sys
import time
import typing

import core
import langcodes
from appdb import connect, tx
from config import config_block
from headless import HAIKU, SONNET, HeadlessError, findings_schema, run_claude
from models.base import Model
from models.friction import Friction
from models.grammar import Grammar
from models.idioms import Idioms
from models.messages import Messages
from models.rephrasing import Rephrasing
from models.verbs import Verbs
from parallel import fan_out, log
from skillio import render

# debrief's historical exception name is now the shared engine error.
DebriefError = HeadlessError

# Sonnet 4.6's `--effort` knob controls thinking depth AND total token spend; the CLI
# default is `high`, which makes each analytical call burn ~100-140s. The five
# specialists are subagent-style structured-extraction tasks, so `medium` roughly
# halves wall-time with negligible quality loss (measured: ~56s vs ~120s, 11 vs 10-12
# findings). NOT passed to the haiku triage call — effort errors on Haiku 4.5.
SPECIALIST_EFFORT = "medium"

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
        log(f"    → triage {len(batch)} msg(s)")
        t0 = time.monotonic()
        data = "\n".join(
            [
                _config_block(cfg),
                _messages_block(batch, ["id", "text"]),
            ]
        )
        try:
            out = run_claude(
                _prompt("triage"), data, TRIAGE_SCHEMA, HAIKU, runner=runner
            )
            valid_ids = {row["id"] for row in batch}
            clean = _validate_triage(out.get("tags", []), valid_ids)
        except DebriefError as e:
            log(f"    ✗ triage ERROR {time.monotonic() - t0:.0f}s — {e}")
            raise
        Messages.tag(clean)
        log(f"    ✓ triage OK {time.monotonic() - t0:.0f}s ({len(clean)} tagged)")


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
    "grammar": _Spec(Grammar, findings_schema(*Grammar.insert_cols)),
    "rephrasing": _Spec(Rephrasing, findings_schema(*Rephrasing.insert_cols)),
    "idioms": _Spec(Idioms, findings_schema(*Idioms.insert_cols)),
    "verbs": _Spec(Verbs, findings_schema(*Verbs.insert_cols)),
    "friction": _Spec(
        Friction,
        findings_schema(
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


def _specialist_thunk(sp, data, schema, model, runner):
    """A zero-arg thunk for one specialist call at SPECIALIST_EFFORT (all sonnet)."""
    return lambda: run_claude(
        sp, data, schema, model, runner=runner, effort=SPECIALIST_EFFORT
    )


def _fan_out(jobs, *, runner=None):
    """Run the five specialists in parallel via parallel.fan_out. Returns
    (findings_by_category, failed) where findings maps category -> structured_output
    and failed maps a failed category -> the error reason string. A specialist
    returning {"findings": []} is a SUCCESS — the gate is valid JSON returned, not
    non-empty findings. parallel.fan_out streams each specialist's start/duration/
    OK-ERROR to stderr so a slow fan-out is visible live. Specialists run at
    SPECIALIST_EFFORT (they are sonnet; effort is NOT passed to the haiku triage
    call, which rejects it)."""
    thunks = {
        cat: _specialist_thunk(sp, data, schema, model, runner)
        for cat, (sp, data, schema, model) in jobs.items()
    }
    findings, failed = fan_out(thunks, max_workers=5)
    return findings, {cat: str(e) for cat, e in failed.items()}


def _result(session, *, ok, failed=(), empty=False, errors=None, loot=()):
    """One per-session result row for the run summary. `failed` is the list of
    failed stage/category names; `errors` maps each to its reason (rendered by
    _session_status); `loot` is the session's friction-loot words for main to
    enrich (empty on every non-OK and empty-language result)."""
    return {
        "session": session,
        "ok": ok,
        "failed": list(failed),
        "empty": empty,
        "errors": dict(errors or {}),
        "loot": list(loot),
    }


def _persist(session, findings):
    """Write a whole session in ONE per-session transaction: all five categories'
    findings + the processed-mark. Opened only AFTER all the slow LLM work, so it
    does not block other writers across the analysis; tx() (BEGIN IMMEDIATE) makes a
    concurrent capture-hook writer wait rather than interleave. Any failure (a
    ValueError from a finding's key/enum check, or a SQLite error) rolls the WHOLE
    session back — no partial write — and the next /debrief re-lists and re-runs it
    cleanly. Vocab is NOT written here: friction-loot words are enriched separately,
    best-effort, by main via loot.run."""
    con = connect()  # fresh connection (cheap re-check; not the read-phase one)
    try:
        with tx(con):
            for cat, spec in SPECS.items():
                for item in findings[cat]:
                    spec.model.insert(item, con=con, session=session)
            Messages.mark_processed(session, con=con)
    finally:
        con.close()


def _run_session(session, cfg, lang, dedup, *, runner=None):
    """Process ONE session: triage -> per-language slice gate -> 5-way parallel
    specialist analysis -> atomic persist. `dedup` is the {category: existing rows}
    snapshot read once by the caller (see main). Returns a _result dict. Nothing is
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
            _persist(session, {c: [] for c in CATEGORIES})
        except (ValueError, KeyError, TypeError, sqlite3.Error) as e:
            return _result(
                session, ok=False, failed=["persist"], errors={"persist": str(e)}
            )
        return _result(session, ok=True, empty=True)

    # All DB reads here, on the MAIN thread, before the fan-out (`dedup` is the
    # caller's once-per-batch snapshot — see main).
    full_slice = Messages.list(session=session)
    jobs = _build_jobs(cfg, lang, lang_slice, full_slice, dedup)
    findings, failed = _fan_out(jobs, runner=runner)
    if failed:
        return _result(session, ok=False, failed=sorted(failed), errors=failed)

    try:
        persist_findings = {c: findings[c]["findings"] for c in CATEGORIES}
        _persist(session, persist_findings)
    except (ValueError, KeyError, TypeError, sqlite3.Error) as e:
        return _result(
            session, ok=False, failed=["persist"], errors={"persist": str(e)}
        )
    loot_words = sorted(
        {
            (p.get("word") or "").strip().lower()
            for p in findings["friction"].get("loot", [])
            if (p.get("word") or "").strip()
        }
    )
    return _result(session, ok=True, loot=loot_words)


def _run_session_safe(session, cfg, lang, dedup, *, runner=None):
    """_run_session with a last-resort net: a non-DebriefError that escapes a phase
    opening its own transaction (e.g. a triage-time 'database is locked' from
    Messages.tag past busy_timeout) becomes ONE failed session, never a dead run.
    Expected/precise handling stays inside _run_session; this is the top-level
    per-session isolation boundary, so the broad except is deliberate."""
    try:
        return _run_session(session, cfg, lang, dedup, runner=runner)
    except Exception as e:  # deliberate per-session isolation boundary
        return _result(
            session,
            ok=False,
            failed=["unexpected"],
            errors={"unexpected": f"{type(e).__name__}: {e}"},
        )


def _session_status(r):
    """The per-session status streamed live as each session completes:
    OK / OK (empty) / ERROR <name — reason; …>."""
    if r["ok"]:
        return "OK (empty)" if r["empty"] else "OK"
    parts = [
        f"{n} — {r['errors'][n]}" if r["errors"].get(n) else n for n in r["failed"]
    ]
    return f"ERROR {'; '.join(parts)}"


def _totals_line(results):
    """The closing tally: how many sessions succeeded, plus the retry hint when any
    failed (a re-run reprocesses only the still-pending sessions)."""
    ok = sum(1 for r in results if r["ok"])
    failed = len(results) - ok
    line = f"{ok}/{len(results)} session(s) OK"
    if failed:
        line += f"; re-run /debrief to retry the {failed} failed"
    return line


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
        print(f"marked {marked} drill(s); nothing to review", flush=True)
        return 0
    total = len(sessions)
    # Stream progress live (flush=True) so a long run shows which session it is on
    # and surfaces each failure as it happens, instead of going dark until the end:
    # stdout is block-buffered when piped (not a TTY), so nothing reaches the caller
    # until the buffer flushes. The "[i/N] <session> … " prefix is printed BEFORE the
    # session runs (no trailing newline) so the in-flight session is visible even
    # mid-call; _session_status completes that line when it returns.
    print(f"marked {marked} drill(s); reviewing {total} session(s)", flush=True)
    # Read the dedup snapshot ONCE and reuse it across sessions; only a session that
    # actually persisted findings invalidates it, so the common empty/failed sessions
    # don't trigger the five full-view reads. _run_session_safe isolates each session
    # so one unexpected error can't abort the rest of the run.
    dedup = None
    results = []
    for i, s in enumerate(sessions, 1):
        if dedup is None:
            dedup = {cat: spec.model.select() for cat, spec in SPECS.items()}
        session = s["session"]
        print(f"[{i}/{total}] {session} … ", end="", flush=True)
        r = _run_session_safe(session, cfg, lang, dedup, runner=runner)
        print(_session_status(r), flush=True)
        results.append(r)
        if r["ok"] and not r["empty"]:  # this session added findings -> snapshot stale
            dedup = None
    print(_totals_line(results), flush=True)
    return 1 if any(not r["ok"] for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
