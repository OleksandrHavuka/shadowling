#!/usr/bin/env bash
# check.sh — one command that runs every dev gate (the definition-of-done).
#
# Dev-only: each tool resolves to its on-PATH binary, else `uvx <tool>`. If a tool
# is reachable by NEITHER, the gate is reported as FAILED with an install hint —
# never silently skipped, so a missing dependency can't masquerade as "all pass".
# Exits non-zero if any gate fails or is unavailable, so an agent or CI sees a
# machine-readable result. Runnable from anywhere.
set -uo pipefail
cd "$(dirname "$0")" # plugins/shadowling — where tach.toml + the modules live

UV_HINT="install uv (provides uvx): curl -LsSf https://astral.sh/uv/install.sh | sh"
fails=0

# need <tool>: prints how to invoke it ("ruff" or "uvx ruff"), or "" if neither
# the binary nor uvx is available.
need() {
    if command -v "$1" >/dev/null 2>&1; then
        printf '%s' "$1"
    elif command -v uvx >/dev/null 2>&1; then
        printf 'uvx %s' "$1"
    fi
}

run() { # run <label> <cmd...>
    local label="$1"
    shift
    echo "── $label ──"
    if "$@"; then
        echo "✓ $label"
    else
        echo "✗ $label"
        fails=$((fails + 1))
    fi
}

missing() { # missing <tool> — a required dev tool is unavailable: fail, don't skip
    echo "── $1 ──"
    echo "✗ $1 unavailable — $UV_HINT" >&2
    echo "  (or install just this tool: uv tool install $1)" >&2
    fails=$((fails + 1))
}

# 1. ruff — format + lint
RUFF=$(need ruff)
if [ -n "$RUFF" ]; then
    run "ruff format" $RUFF format --check .
    run "ruff lint" $RUFF check .
else
    missing ruff
fi

# 2. tach — import architecture (the clean dependency tree)
TACH=$(need tach)
if [ -n "$TACH" ]; then
    run "tach (imports)" $TACH check
else
    missing tach
fi

# 3. mypy — type contract on the library modules (not tests/skills scripts)
MYPY=$(need mypy)
if [ -n "$MYPY" ]; then
    run "mypy (types)" $MYPY --check-untyped-defs ./*.py models/
else
    missing mypy
fi

# 4. test suite — property tests need hypothesis; provide it via uvx (or an
#    already-installed copy). If neither is available, FAIL rather than run a
#    reduced suite that silently skips them.
if command -v uvx >/dev/null 2>&1; then
    run "tests (+hypothesis)" \
        uvx --with hypothesis python3 -m unittest discover -p 'test_*.py'
elif python3 -c 'import hypothesis' >/dev/null 2>&1; then
    run "tests (+hypothesis)" python3 -m unittest discover -p 'test_*.py'
else
    echo "── tests ──"
    echo "✗ tests need hypothesis for the property suite — $UV_HINT" >&2
    fails=$((fails + 1))
fi

echo "──────────"
if [ "$fails" -gt 0 ]; then
    echo "FAIL: $fails gate(s) failed or unavailable"
    exit 1
fi
echo "OK: all gates pass"
