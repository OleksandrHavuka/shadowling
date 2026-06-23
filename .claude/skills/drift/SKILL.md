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
- Also run the rulebook's **rule-gap loop** ("How this doc is used" → "Self-improvement"):
  surface rare rule-gap candidates; on approval append the rule to `docs/ARCHITECTURE.md`,
  else drop. Never park a candidate.
- Never touch production code. Writes are limited to a confirmed `docs/Debt.md` append
  (deviation from an existing rule) and, on approval, a new rule in `docs/ARCHITECTURE.md`.
  If the target matches the baseline and no gap surfaces, say so and skip triage.
