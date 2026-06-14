#!/usr/bin/env python3
"""traceability.py - enforce the end-to-end data-structure contract (stdlib only).

shadowling's invariant: a column has ONE name from schema -> repository ->
SQL consumer -> skill. This module proves that mechanically, so a rename that
drifts any layer fails loudly instead of silently. Three surfaces share one
`check()`:

  * test_traceability.py asserts `check() == []`            (CI / suite)
  * `python3 traceability.py`  is the dev CLI               (exit 1 on drift)
  * `python3 traceability.py hook`  is the PostToolUse hook (exit 2 feeds back)

Everything is DISCOVERED from the repo files, never hardcoded: the data layer
from `models/<cat>.py` (a Model subclass + a `record` fn + any PROMPT_SQL, by
convention), the record heredocs from `skills/**/SKILL.md`, and the live schema
from `appdb` (the one foundation it reaches down into — only `appdb` can
materialize the migrations). So adding or renaming a category needs no edit here.

What it proves:
  1. every model `insert_col` (and the `key`) is a real table column;
  2. every skill's entrypoint `record <<'SL_IN'` heredoc — discovered by
     entrypoint basename — has a tag sequence equal to the column sequence its
     values land in (recorder params, kind->type); plus the reverse: a record
     heredoc with no matching `models/<cat>.py` recorder, or a recorder with no
     documenting skill line, is a violation;
  3. every discovered `PROMPT_SQL` statement selects only real columns.

Scope (honest): this guards the incident-category record path + the prompt SQL,
and — because check() runs against a freshly-migrated DB — surfaces a broken
migration or view via connect(). It does NOT analyze the message-store / vocab /
attempts / mastery write paths; those are guarded by their own unit tests. View
display aliases (`learner_wrote AS "you wrote"`) are intentionally not asserted.
"""

import importlib
import inspect
import json
import os
import re
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))

# A PostToolUse edit whose path contains one of these can break the contract.
_RELEVANT = ("appdb.py", "/models/", "/skills/")

# `<entrypoint>.py" record <<'DELIM'` ... `DELIM` — the heredoc each incident
# skill feeds record fields through. The category is the entrypoint's BASENAME
# (the skill's own .py file), since the entrypoint name IS the category. The
# `record\s+<<'` shape (no args between) excludes tutor.py's `record <kind> ...`.
_RECORD_HEREDOC = re.compile(
    r"(\w+)\.py\"\s+record\s+<<'(\w+)'\n(.*?)\n\2(?=\n|$)", re.DOTALL
)

# A recorder's local param name -> the column/tag its value lands in. The lone
# entry is the decode/friction divergence: the recorders take `kind` (the column
# `type` is a Python builtin), so the documented tag is `type`. This used to live
# in models; it belongs here, with the only check that consumes it.
PARAM_TO_COLUMN = {"kind": "type"}


def _discover_record_lines():
    """Every entrypoint `record <<'SL_IN'` heredoc across skills/**/SKILL.md, as
    (cat, [tag_names_in_order], relpath); cat is the entrypoint .py basename.
    Format-coupled to the documented
    heredoc-of-tags syntax: a reformat that breaks the match drops the line from
    discovery, which the reverse "recorder has no skill line" check then flags —
    so it surfaces, never silently passes."""
    found = []
    for root, _dirs, files in os.walk(os.path.join(HERE, "skills")):
        if "SKILL.md" not in files:
            continue
        path = os.path.join(root, "SKILL.md")
        with open(path, encoding="utf-8") as f:
            text = f.read()
        for m in _RECORD_HEREDOC.finditer(text):
            found.append(
                (
                    m.group(1),
                    re.findall(r"(?m)^<(\w+)>", m.group(3)),
                    os.path.relpath(path, HERE),
                )
            )
    return found


def _discover_models():
    """Discover the data layer straight from the files in models/ — no
    hand-maintained registry, no named modules. Imports each models/<cat>.py and
    returns three maps, by convention:
      recorders[cat]     -> the module-level `record` fn (cat = the file basename)
      models_by_cat[cat] -> the Model subclass DEFINED there (duck-typed: truthy
                            `table` + `insert_cols` + `key`)
      prompt_sqls[cat]   -> any module-level PROMPT_SQL mapping
    The only things it 'knows' are those structural conventions; a category added
    as a new models/<cat>.py is picked up here with zero edits."""
    recorders, models_by_cat, prompt_sqls = {}, {}, {}
    for fname in sorted(os.listdir(os.path.join(HERE, "models"))):
        if not fname.endswith(".py") or fname in ("__init__.py", "base.py"):
            continue
        cat = fname[:-3]
        mod = importlib.import_module("models." + cat)
        rec = getattr(mod, "record", None)
        if callable(rec) and getattr(rec, "__module__", "") == mod.__name__:
            recorders[cat] = rec
        for _name, obj in inspect.getmembers(mod, inspect.isclass):
            if (
                obj.__module__ == mod.__name__
                and getattr(obj, "table", None)
                and getattr(obj, "insert_cols", None)
                and getattr(obj, "key", None)
            ):
                models_by_cat[cat] = obj
        psql = getattr(mod, "PROMPT_SQL", None)
        if isinstance(psql, dict):
            prompt_sqls[cat] = psql
    return recorders, models_by_cat, prompt_sqls


def check():
    """Return human-readable violation strings; `[]` means the contract holds.

    Runs against a throwaway DB so it tests the CODE's schema, not the dev's
    real ~/.shadowling."""
    violations = []
    home = tempfile.mkdtemp(prefix="shadowling-trace-")
    prev = os.environ.get("SHADOWLING_HOME")
    os.environ["SHADOWLING_HOME"] = home
    try:
        import appdb  # the foundation: the only reach DOWN, to materialize schema

        recorders, models_by_cat, prompt_sqls = _discover_models()
        con = appdb.connect()
        try:

            def cols(table):
                return {r["name"] for r in con.execute(f"PRAGMA table_info({table})")}

            # 1. models: every insert_col and the key is a real column
            for cat, model in models_by_cat.items():
                tcols = cols(model.table)
                for c in model.insert_cols:
                    if c not in tcols:
                        violations.append(
                            f"{cat}: insert_col {c!r} is not a column of {model.table}"
                        )
                if model.key not in tcols:
                    violations.append(
                        f"{cat}: key {model.key!r} is not a column of {model.table}"
                    )

            # 2. skills: discovered record lines <-> the recorder column sequence
            documented = set()
            for cat, tags, rel in _discover_record_lines():
                documented.add(cat)
                rec = recorders.get(cat)
                if rec is None:
                    violations.append(
                        f"{cat}: {rel} documents a `record` line with no matching "
                        f"models/{cat}.py recorder"
                    )
                    continue
                expected = [
                    PARAM_TO_COLUMN.get(p, p) for p in inspect.signature(rec).parameters
                ]
                if tags != expected:
                    violations.append(
                        f"{cat}: {rel} tags {tags} != column sequence {expected}"
                    )
            for cat in recorders:
                if cat not in documented:
                    violations.append(
                        f"{cat}: models/{cat}.py has a recorder but no documenting "
                        "skill `record` line"
                    )

            # 3. every discovered PROMPT_SQL reads only real columns
            for modname, psql in prompt_sqls.items():
                for kind, sql in psql.items():
                    m = re.search(r"SELECT (.+?) FROM (\w+)", sql)
                    if m is None:  # report, never crash, on an unparseable shape
                        violations.append(
                            f"{modname}.PROMPT_SQL[{kind!r}]: cannot parse a "
                            f"`SELECT <cols> FROM <table>` shape from {sql!r}"
                        )
                        continue
                    table = m.group(2)
                    tcols = cols(table)
                    for field in (f.strip() for f in m.group(1).split(",")):
                        if field not in tcols:
                            violations.append(
                                f"{modname}.PROMPT_SQL[{kind!r}]: {field!r} is not "
                                f"a column of {table}"
                            )
        finally:
            con.close()
    finally:
        if prev is None:
            os.environ.pop("SHADOWLING_HOME", None)
        else:
            os.environ["SHADOWLING_HOME"] = prev
        shutil.rmtree(home, ignore_errors=True)
    return violations


def _edited_path(stdin_text):
    try:
        data = json.loads(stdin_text) if stdin_text.strip() else {}
    except (json.JSONDecodeError, ValueError, TypeError):
        return ""
    return (data.get("tool_input") or {}).get("file_path", "") or ""


def main(argv):
    if argv and argv[0] == "hook":
        # PostToolUse: only re-check after edits to contract-relevant files, and
        # emit feedback (exit 2) on a violation so a break is seen in-session.
        # Never raise — a hook must not derail the edit it observed.
        try:
            path = _edited_path(sys.stdin.read())
            if not any(seg in path for seg in _RELEVANT):
                return 0
            violations = check()
        except Exception:
            return 0
        if violations:
            print(
                "data-structure traceability broken by this edit:\n  "
                + "\n  ".join(violations),
                file=sys.stderr,
            )
            return 2
        return 0

    violations = check()
    if violations:
        print(f"TRACEABILITY VIOLATIONS ({len(violations)}):")
        for v in violations:
            print("  - " + v)
        return 1
    print("OK: data-structure traceability holds")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
