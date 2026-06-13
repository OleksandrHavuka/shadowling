#!/usr/bin/env python3
"""traceability.py - enforce the end-to-end data-structure contract (stdlib only).

shadowling's invariant: a column has ONE name from schema -> repository ->
SQL consumer -> skill. This module proves that mechanically, so a rename that
drifts any layer fails loudly instead of silently. Three surfaces share one
`check()`:

  * test_traceability.py asserts `check() == []`            (CI / suite)
  * `python3 traceability.py`  is the dev CLI               (exit 1 on drift)
  * `python3 traceability.py hook`  is the PostToolUse hook (exit 2 feeds back)

What it proves:
  1. every model `insert_col` (and the `key`) is a real table column;
  2. every skill `db.py <cat> record "<...>"` line — DISCOVERED across
     skills/**/SKILL.md, not hardcoded — has a placeholder sequence equal to the
     column sequence its positional args land in (recorder params, kind->type);
     plus the reverse: a record line for an unregistered category, or a
     registered recorder with no documenting skill line, is a violation;
  3. every `tutor.PROMPT_SQL` statement selects only real columns.

Scope (honest): this guards the incident-category record path + tutor prompts,
and — because check() runs against a freshly-migrated DB — surfaces a broken
migration or view via connect(). It does NOT analyze capture.py / vocab.py /
attempts / mastery write paths; those are guarded by their own unit tests. View
display aliases (`learner_wrote AS "you wrote"`) are intentionally not asserted.
"""
import inspect
import json
import os
import re
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))

# A recorder's local param name -> the column its positional arg actually lands
# in. The lone entry is the intentional divergence: decode/friction recorders
# take `kind` (the column `type` is a Python builtin), so the skill says <type>.
_PARAM_TO_COLUMN = {"kind": "type"}

# A PostToolUse edit whose path contains one of these can break the contract.
_RELEVANT = ("appdb.py", "tutor.py", "/models/", "/skills/")


def _discover_record_lines():
    """Every `<cat> record "<a>" "<b>" ...` command across skills/**/SKILL.md, as
    (cat, [placeholders], relpath). Format-coupled to the documented quoted-
    angle-bracket placeholder syntax: a reformat that breaks the match drops the
    line from discovery, which the reverse "recorder has no skill line" check
    then flags — so it surfaces, never silently passes."""
    found = []
    for root, _dirs, files in os.walk(os.path.join(HERE, "skills")):
        if "SKILL.md" not in files:
            continue
        path = os.path.join(root, "SKILL.md")
        with open(path, encoding="utf-8") as f:
            text = f.read()
        for m in re.finditer(r'(\w+) record ((?:"<[^>]+>" ?)+)', text):
            found.append((m.group(1),
                          re.findall(r'<([^>]+)>', m.group(2)),
                          os.path.relpath(path, HERE)))
    return found


def check():
    """Return human-readable violation strings; `[]` means the contract holds.

    Runs against a throwaway DB so it tests the CODE's schema, not the dev's
    real ~/.shadowling."""
    violations = []
    home = tempfile.mkdtemp(prefix="shadowling-trace-")
    prev = os.environ.get("SHADOWLING_HOME")
    os.environ["SHADOWLING_HOME"] = home
    try:
        import appdb
        import models
        import tutor
        con = appdb.connect()
        try:
            def cols(table):
                return {r["name"] for r in
                        con.execute(f"PRAGMA table_info({table})")}

            # 1. models: every insert_col and the key is a real column
            for cat, model in models.REGISTRY.items():
                tcols = cols(model.table)
                for c in model.insert_cols:
                    if c not in tcols:
                        violations.append(
                            f"{cat}: insert_col {c!r} is not a column of {model.table}")
                if model.key not in tcols:
                    violations.append(
                        f"{cat}: key {model.key!r} is not a column of {model.table}")

            # 2. skills: discovered record lines <-> the recorder column sequence
            documented = set()
            for cat, placeholders, rel in _discover_record_lines():
                documented.add(cat)
                rec = models.RECORDERS.get(cat)
                if rec is None:
                    violations.append(
                        f"{cat}: {rel} documents a `record` line for an unregistered "
                        "category")
                    continue
                expected = [_PARAM_TO_COLUMN.get(p, p)
                            for p in inspect.signature(rec).parameters]
                if placeholders != expected:
                    violations.append(
                        f"{cat}: {rel} placeholders {placeholders} != "
                        f"column sequence {expected}")
            for cat in models.RECORDERS:
                if cat not in documented:
                    violations.append(
                        f"{cat}: registered recorder has no documenting skill "
                        "`record` line")

            # 3. tutor: PROMPT_SQL reads only real columns
            for kind, sql in tutor.PROMPT_SQL.items():
                m = re.search(r'SELECT (.+?) FROM (\w+)', sql)
                table = m.group(2)
                tcols = cols(table)
                for field in (f.strip() for f in m.group(1).split(",")):
                    if field not in tcols:
                        violations.append(
                            f"tutor PROMPT_SQL[{kind!r}]: {field!r} is not "
                            f"a column of {table}")
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
            print("data-structure traceability broken by this edit:\n  "
                  + "\n  ".join(violations), file=sys.stderr)
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
