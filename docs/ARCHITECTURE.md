# shadowling — architecture baseline

This is the **normative** rulebook for how shadowling is built. It describes the
**ideal**, not the current code. We build only the ways stated here; any other
variant must either be adapted to a rule, or flagged as not fitting the
architecture. Where today's code deviates, that deviation is **debt** — tracked in
[`Debt.md`](./Debt.md), not a reason to weaken a rule.

Each rule has a stable id (`R-<area>-<n>`) so reviews and `Debt.md` can cite it
exactly. A rule states the one allowed way; "NOT" lines sharpen the boundary.

---

## R-TOP — Topology: two LLM tiers + a deterministic core

- **R-TOP-1** Every plugin skill is two parts: a `SKILL.md` (instructions for the
  OUTER conversational LLM) and a deterministic Python **entrypoint**. The outer LLM
  only authors the call's input and relays its output; it carries **no control
  logic**.
- **R-TOP-2** A skill's control logic AND its skill-specific code live **in the
  skill's own folder** (`${CLAUDE_SKILL_DIR}`). The **plugin root holds ONLY shared,
  mandatory components reused across skills** — the data layer (`models/`, `appdb`),
  `core`, the I/O layer (`skillio`/`validator`), the headless engine
  (`headless`/`parallel`), shared `config`, `langcodes`. Control logic is never in
  `SKILL.md` prose or the outer LLM.
- **R-TOP-3** Heavy analysis runs in an INNER headless `claude -p` call — **always
  structured IO** (`--json-schema` → `structured_output`). Never hand-rolled logic in
  the entrypoint, never the outer LLM. The entrypoint orchestrates the inner call; it
  does not do the analysis itself.
- **R-TOP-4** Skill scripts are invoked from `SKILL.md` via env-rooted paths
  (`${CLAUDE_SKILL_DIR}` for skill-local code, `${CLAUDE_PLUGIN_ROOT}` for shared
  root code) — never a hardcoded absolute path.

## R-ARC — The four archetypes

Every entrypoint is exactly one of these. Do not invent a fifth shape.

- **R-ARC-1 Hook** (e.g. `capture`, `gloss`): harness → stdin-JSON → entrypoint →
  models → DB. No outer LLM, no XML, no inner LLM. Write-only and **must never raise**
  (a hook must not crash the session).
- **R-ARC-2 Analysis/enrichment** (e.g. `loot`, `debrief`, `tutor`, `aha`): full cycle
  with an INNER schema-constrained `claude -p` call (R-TOP-3).
- **R-ARC-3 Pure read/mutation** (e.g. `drop`): outer LLM → **XML-stdin** (R-IO-1) →
  entrypoint → models → DB (→ render out). **No** inner LLM.
- **R-ARC-4 Dev-tool** (e.g. `reinstall`, `sql.py`, the `/drift` gate):
  for the **developer — MUST NOT ship to plugin users**, so it lives in
  `.claude/skills/`, **never in `plugins/`**. Exempt from R-IO-1 (argv / raw SQL
  allowed); **never invoked by a plugin skill** (R-IO-7). It reaches shared plugin
  modules by inserting the working-tree `plugins/shadowling/` onto `sys.path` (a dev
  tool runs against the repo source, not the installed cache).

## R-IO — Skill ↔ script I/O contract

There are exactly two ways to drive an entrypoint's functionality, split by consumer:

- **R-IO-1** An **LLM (plugin skill)** drives a script **strictly via a tagged-XML
  payload on stdin** (quoted heredoc `<<'SL_IN'`), parsed by `skillio.parse(schema)`
  (`_parse_xml` → `_element_to_py` → `validator.validate`). The **operation AND all
  data** live in that payload. **No argv on the LLM path** — no verb, no flag, no
  positional argument.
- **R-IO-2** **Code** consumes functionality by importing the module and calling its
  functions directly. NEVER by shelling out to the script.
- **R-IO-3** Output back to the LLM is serialized by the one serializer
  `skillio.render` (emits `<row>…</row>`; the entrypoint frames it with the named
  tag). `<row>` = list, symmetric with `parse`.
- **R-IO-4** `validator` stays **pure and XML-agnostic** — shape-checking is decoupled
  from the wire format.
- **R-IO-5** Every error surfaced to the LLM is **self-correcting**: it states the
  exact problem AND shows the expected format, so the model can retry.
- **R-IO-6** New code uses `skillio.parse`/`render`. The legacy tolerant TSV path
  (`read_fields`/`rows`) is deprecated — no new use.
- **R-IO-7 Carve-outs** (NOT bound by R-IO-1):
  - **Hooks** (e.g. `capture`) receive **harness-owned JSON** on stdin — that wire is
    the harness's contract, not ours.
  - **`sql.py`** is the **dev/admin DB console**: used only by dev tools/skills
    (`.claude/skills/`, `shadowling-db`), **NEVER by a plugin skill**. Its argv SQL
    and flags are legitimate there.

## R-LLM — Headless (inner) LLM calls

The deterministic core drives the INNER LLM tier: it shells out to `claude -p` for the
heavy analysis, schema-constrained.

- **R-LLM-1** Every inner call goes through the one engine
  `headless.run_claude(system, data, schema, model, *, runner=None, effort=None,
  timeout=…)`. NOT a direct `subprocess` call from an entrypoint — `run_claude` is the
  single owner of argv construction (`--json-schema`, the tool lockdown `--tools ""` +
  MCP block + `--safe-mode`), error mapping (timeout → `HeadlessError`), and parsing.
- **R-LLM-2** Every inner call is **`--json-schema`-constrained**; the driver
  (`parse_result`) reads `structured_output` and discards the unavoidable trailing text
  turn. `parse_result` does NOT re-check shape — the `--json-schema` is the model-side
  shape contract (see R-LLM-7).
- **R-LLM-3** Model ids come only from `headless` constants (`HAIKU`, `SONNET`).
  Timeouts come only from `headless.DEFAULT_TIMEOUT`. No literal model strings or
  timeouts anywhere else — one edit changes all calls.
- **R-LLM-4** The `runner` seam is mandatory and injectable: `run_claude` takes the
  function that actually executes the call — `None` in production (real subprocess that
  spawns `claude`), a fake returning canned `structured_output` in tests. **Tests never
  spawn `claude`**; this seam is the whole testability story (debrief/loot run
  end-to-end through fakes — instant, offline, deterministic).
- **R-LLM-5** Analytical (sonnet) calls pass an explicit `--effort` (`SPECIALIST_EFFORT`,
  currently `medium`) — the real latency lever (caps thinking depth + token spend). The
  haiku triage call **never** passes `--effort` (Haiku 4.5 rejects it).
- **R-LLM-6** Multi-call phases fan out concurrently via `parallel.fan_out`, never
  serially (e.g. the five debrief specialists run in parallel).
- **R-LLM-7 Validation ownership.** Shape validation has ONE owner — `validator.py`
  for inbound model XML (via `skillio.parse`) and the inner `--json-schema` for
  inner-LLM output. Never hand-roll a shape check. An entrypoint adds ONLY
  **semantic / cross-state** validation the schema cannot express — e.g. `loot._valid`
  (a usable, clozable example) and `debrief._validate_triage` (every sent id tagged
  exactly once). A different layer, not duplicated shape checks.
- **R-LLM-8 Auth.** Inner calls authenticate via the user's Claude Code subscription
  (shell out to `claude`), never an API key — see R-DEV-2.

## R-DB — Data layer

- **R-DB-1** ONE sqlite home for all data (`shadowling.db`). Markdown/exports are
  on-demand artifacts (`sql.py --md`), never a second source of truth.
- **R-DB-2** Each table is owned by **exactly one** `models/*` module (single owner).
  The uniform incident/findings models (`grammar`, `friction`, `idioms`, `rephrasing`,
  `verbs`, `decode`) subclass the shared base `models/base.py` (`Model` — common
  insert/select + schema metadata), never copy-pasted CRUD; genuinely different-shape
  tables (`vocab` upsert-by-word, `messages` log, `anki_link`, `tutor`) are bespoke.
  Duplication is resolved by giving the data one owner — NOT a shared-helper crutch.
- **R-DB-3** All DB access goes through a `models/*` method or a skill entrypoint;
  `sql.py` is the dev/admin console (dev use only, per R-IO-7). NEVER raw `sqlite3`
  outside the data layer.
- **R-DB-4** Writes happen inside `appdb.tx` (BEGIN IMMEDIATE) and are **atomic** per
  operation/session — a failure rolls the whole unit back, no partial write.
- **R-DB-5** Schema/data-layer changes are made ONLY by appending a new migration in
  `appdb.py`. Migrations are **append-only**: never edit or reorder a shipped one.
  They auto-run on connect (with a `.bak` backup).
- **R-DB-6** `session_id` is the **backbone of traceability and data integrity**:
  every table whose rows are session-originated (captures, incidents, findings —
  anything traceable to a session) carries a **NOT NULL `session_id`**. It is
  mandatory provenance and the basis for cross-table synthesis (the future tutor).
  Exempt only: aggregate/upsert tables keyed by their own identity (e.g. `vocab` — one
  row per word, touched by many sessions), where a single `session_id` is meaningless.

## R-CFG — Configuration gate

- **R-CFG-1** Config has exactly **three mandatory keys** — `first_language` (native /
  translations), `learning_language` (what is studied), `explanation_language`
  (corrections). Analysis/enrichment skills gate on `core.config_ready` (all three
  set); when unset they emit a `<shadowling_misconfig>` notice and exit non-zero,
  steering the user to `/setup`. **Invariant: the target language is never hardcoded** —
  all language-specific behavior derives from these keys; skills stay
  language-agnostic.
- **R-CFG-2** Capture/logging is **never** config-gated — messages are logged even
  before `/setup` so nothing is lost.
- **R-CFG-3** No new config key unless a behavior genuinely needs per-user choice;
  prefer a hardcoded sensible default (YAGNI).
- **R-CFG-4** Config's sole current purpose is **feeding properties into LLM prompts**
  (`config.config_block`) — it is not a general app-settings store. Any non-LLM use of
  config requires a deliberate discussion + redesign first; do not quietly repurpose
  it.

## R-MOD — Module boundaries

- **R-MOD-1** Flat module layout. Inter-module dependencies are declared in
  `tach.toml` and enforced by `tach check`. A new edge needs a declaration.
- **R-MOD-2** **Maximal coverage: EVERY module is declared and its edges enforced —
  root infra AND skills.** Each skill entrypoint is a tach module
  (`skills.<name>.<entry>` with its own `depends_on`); `skills/` is in tach scope (no
  `__init__.py` needed — tach resolves the flat imports statically). No
  undeclared-module exemption.
- **R-MOD-3** Structure is enforced by the **flat layout + tach**, not by Python
  packaging. import-linter and repackaging into nested packages were considered and
  **rejected** — do not introduce package nesting or a second structure-enforcement
  tool.

## R-DEV — Development & runtime constraints

- **R-DEV-1** Production code is **stdlib-only**, Python 3.9+ — **zero runtime
  dependencies**. New dependencies are allowed ONLY for **dev tooling** (ruff, tach,
  mypy, hypothesis) and only via the package manager, never added by hand.
- **R-DEV-2** Auth is the user's Claude Code **subscription** (shell out to `claude`).
  NEVER `ANTHROPIC_API_KEY` / per-token billing.
- **R-DEV-3** Entrypoints are **cron-safe**: no interactive input; respect
  `SHADOWLING_HOME`.
- **R-DEV-4** Every commit passes `bash check.sh` (ruff format/lint, tach, mypy,
  unittest + hypothesis). Lint findings are fixed at the **root** — never `noqa`/
  suppress, never bend data/logic to satisfy a rule.
- **R-DEV-5** File edits go through the editor tools, never CLI `sed`/`awk`.

## R-PAT — Named patterns (reuse these shapes)

- **R-PAT-1 Best-effort side-work.** A secondary step (e.g. debrief enriching
  friction-loot via `loot.run`) runs AFTER the main unit is committed and OUTSIDE its
  transaction. It is isolated: its failure is reported (printed) but **cannot change
  the main operation's success or the process exit code**.
- **R-PAT-2 Additive-only external-model mutation.** When mutating an external store
  we don't own (e.g. the Anki note model) only add fields/templates; never remove,
  rename, or reorder — that destroys downstream state.
- **R-PAT-3 Enrich-only writes, DB-enforced.** A record reaches the store only after
  successful enrichment; an un-enrichable input is reported, not written as a bare row.
  The required-field floor is enforced by **DB constraints** (NOT NULL / CHECK) so an
  incomplete row physically cannot be inserted — not by app code alone (R-DB).
  Semantic checks SQL can't express (e.g. a clozable example) stay at the app layer
  (`loot._valid`).
- **R-PAT-4 Idempotency.** Re-running an operation is safe and never duplicates:
  triage re-lists only untagged rows, `/anki-sync` updates rather than re-creates,
  migrations are safe on every connect. Required for cron / retry safety.

---

## How this doc is used

- New work (spec, plan, code) must conform to these rules or be flagged.
- The `/drift` skill reads this file, finds deviations, and asks which to record in
  [`Debt.md`](./Debt.md).
- A rule is changed **deliberately**, by editing this file — not by silently letting
  code drift from it.
