# shadowling — architecture debt

Known places where the code deviates from [`ARCHITECTURE.md`](./ARCHITECTURE.md).
Each entry is a TODO: a deliberate, accepted gap to close over time. When this file
is empty, the codebase fully matches the baseline and the fitness skill is in pure
maintenance mode (guarding against any *new* deviation).

Entries are added **interactively** by the architecture-fitness skill: it shows a
deviation, and you decide whether to record it here (accept as tracked debt) or fix
it now. Each entry cites the rule it violates.

Format:

```
- [ ] R-<area>-<n> — <file/area>: <what deviates> → <target>
```

---

## Open

Unify the skill→script wire to XML (R-IO-1): every place a plugin skill drives a
script via argv migrates to a tagged-XML stdin payload. Code paths already call
modules directly (R-IO-2) and stay.

- [ ] R-IO-1 — `setup`/`aha`/`tutor` skills drive `config.py` via argv
  (`set <key> <value>`, `show`) → XML stdin. (config reads by code are already direct.)
- [ ] R-IO-1 — `drop` skill drives `drop.py` via argv (`remove "<t>" …`) → XML stdin.
- [ ] R-IO-1 — `aha` skill drives `decode.py` with an argv verb (`record`) → fold the
  op into the XML payload.
- [ ] R-IO-1 / R-IO-6 — `tutor` full refactor: argv (`deck`/`record`/`stats`,
  `--size`, positional `<kind> <key> <exercise> <verdict>`) + legacy `read_fields`
  TSV → one XML payload via `parse`.
- [ ] R-IO-6 — `skillio.py`: legacy TSV path (`read_fields`/`rows`) → delete once
  `decode`/`tutor` are migrated.
- [ ] R-IO-1 — `skillio.py` dead argv helpers `parse_message_slice_args`,
  `parse_session_arg` → delete now (only tests reference them); `parse_size_arg` →
  delete with the tutor refactor.
- [ ] R-IO-7 / R-ARC-4 — `vipe` is a plugin skill but uses `sql.py` (forbidden) →
  reclassify `vipe` as an R-ARC-4 dev-tool (move to `.claude/skills/`), or migrate it
  off `sql.py` to model methods.
- [ ] R-ARC-4 — `sql.py` lives at the plugin root and so ships to users → move to
  `.claude/skills/` (dev-only), wiring its `appdb`/`core` imports via a `sys.path`
  insert to the working-tree `plugins/shadowling/`.
- [ ] R-MOD-2 — bring `skills/` into tach (`exclude` drops `"skills"`) and declare
  every skill entrypoint as a module (`skills.<name>.<entry>`) with its `depends_on`.
  (Verified feasible: tach resolves the flat imports from the nested non-package dirs.)
- [ ] R-MOD-2 — declare `headless` and `parallel` (root infra, currently undeclared in
  `tach.toml`) with their `depends_on` and the edges to them. (`loot` becomes a
  `skills.loot.loot` module when it moves per R-TOP-2.)
- [ ] R-PAT-3 — add DB constraints (NOT NULL / CHECK) on required enrichment fields
  (e.g. `vocab.translation`, non-empty `examples`) so an incomplete row cannot be
  written — backing enrich-only at the schema, not just `loot._valid`. Decide the
  `untranslated` flow: whether a translation-less vocab row is still permitted.
- [ ] R-TOP-2 — `debrief.py`, `loot.py`, `anki.py` live at the plugin root but are
  skill-specific → move into their skill folders (`skills/debrief/`, `skills/loot/`,
  `skills/anki_sync/`). Root keeps only shared infra (`models`, `appdb`, `core`,
  `skillio`/`validator`, `headless`/`parallel`, `config`, `langcodes`).
- [ ] R-TOP-2 — `capture.py` / `gloss.py` (hooks) sit at the bare plugin root → move
  into a dedicated `hooks/` dir next to `hooks.json` (Claude Code convention),
  referenced via `${CLAUDE_PLUGIN_ROOT}/hooks/…`.

## Done

<!-- move entries here (checked) when closed, or delete; kept short -->
