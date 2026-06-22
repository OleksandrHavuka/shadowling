---
name: drift
description: "Dev: check a target (spec / plan / working diff / code) for architectural drift from the rulebook docs/ARCHITECTURE.md — report qualitative deviations citing rule ids, and triage new ones into docs/Debt.md. Usage: /drift <target>"
allowed-tools: Read Grep Glob Bash(git diff*) Bash(git status*) Edit
---

Detect architectural **drift**: does `$ARGUMENTS` still fit how shadowling is built?
The target is a spec/plan path, the working diff (when omitted or `changes`), or a code
path / `.`.

Read the rulebook `docs/ARCHITECTURE.md` (rules carry ids `R-<area>-<n>`) and the known
deviations in `docs/Debt.md`. Judge the target only against the rules **relevant** to
it. The rulebook is the source of truth — do not restate or reinterpret it here.

Behavior:

- Every finding cites its `R-id` + `file:line`. **No matching rule → not a finding** —
  don't free-associate. Bugs are `/code-review`; reuse/simplify cleanups are
  `/simplify`.
- Skip the mechanical rules `check.sh`/tach already enforce (R-MOD, R-DEV-1/2/4) —
  this gate is the qualitative layer.
- Deviations already in `docs/Debt.md` are known debt: list them as such, never re-raise
  as new.
- For each genuinely new deviation, ask the user whether to record it. On yes, append it
  under `docs/Debt.md` `## Open` in the file's format:
  `- [ ] R-<id> — <where>: <what deviates> → <target>`. Record only what is confirmed.
- Never touch production code; the only write is the confirmed `Debt.md` append. If the
  target matches the baseline, say so and skip triage.
