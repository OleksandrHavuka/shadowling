# shadowling

**Learn vocabulary passively, while you work with Claude Code.** Most developers
work in a second language — shadowling turns your everyday Claude Code sessions
into quiet vocabulary practice in the language you're learning, instead of a
separate chore.

Collect words you don't know yet with `/loot`. From then on, whenever one of
those words appears in Claude's replies, Claude appends a translation in your
native language — inline and in a short summary at the bottom — until you've seen
it enough times to have learned it. No flashcards, no separate app: you absorb
terminology in the flow of your normal work.

Works for **any** language pair (set it once): the language you're learning →
your native language.

<!-- Demo GIF — drop a ~10s recording at docs/demo.gif and uncomment:
![shadowling demo](docs/demo.gif)
-->


---

## What it looks like

Examples here learn English glossed into Spanish, but you set your own languages
in one step.

You add a word once:

```
/loot throughput
→ stored: throughput = rendimiento (remaining 10, active)
```

Later, in any normal reply that happens to use the word:

```
...this batching improves throughput (rendimiento) under load, so the
queue drains faster.

---
📖 Vocabulary:
- throughput — rendimiento (10 to go)
```

After the word has appeared in 10 replies it "graduates" and is no longer glossed.
Re-adding a graduated word resets it.

---

## Install

```
/plugin marketplace add OleksandrHavuka/shadowling
/plugin install shadowling@shadowling-lab
```

Restart Claude Code. Requires **Python 3.9+** on your PATH (standard library only,
no pip dependencies).

The plugin ships two hooks (added automatically — your own hooks are untouched):

- `UserPromptSubmit` → injects the active word list + glossing instruction into
  context before each reply.
- `Stop` → scans the reply you just received (counts exposures, graduates learned
  words) **and** quietly stores your messages (any language) for later review (see
  [writing corrections](#writing-corrections-debrief)).

---

## Usage

| Command | Effect |
|---|---|
| `/shadowling:setup` | Set the three languages (run once; required before anything else works). |
| `/loot <word>[, ...]` | Translate the word(s) into your native language and start tracking them. |
| `/drop <word>[, ...]` | Stop tracking and delete word(s). |
| `/debrief` | Review your captured messages into per-category frequency datasets (grammar / rephrasings / idioms / verbs / friction). |
| `/tutor [size]` | Drill your recorded pains (friction phrasings, grammar, irregular verbs, learned vocab) with spaced repetition; ~8 cards by default. |
| `/aha <phrase> [+ your hunch]` | Explain an expression in the language you're learning that you can't read literally — verdict (memorize vs learnable rule) + how to read it, saved to the decode dataset. |
| `/vipe` | Dev: wipe the six category datasets for a clean test run (keeps config, vocab, message store). |

Run **`/shadowling:setup`** once to set the three languages; the answers are saved
to `~/.shadowling/config.json`. (Commands also work fully-qualified, e.g.
`/shadowling:loot`.)

---

## Configuration

Config lives at `~/.shadowling/config.json` and has exactly three keys — **all
required, no defaults**. Run `/shadowling:setup` once to set them; until then
the plugin politely refuses to work (hooks stay silent, skills point you to
setup).

```json
{
  "first_language": "Ukrainian",
  "learning_language": "English",
  "explanation_language": "English"
}
```

- `first_language` — your native language; the one words and corrections are translated **into**.
- `learning_language` — the language you're studying; the one your messages are
  analyzed and drilled in.
- `explanation_language` — the language `/debrief` and `/aha` write meanings,
  rules, and takeaways in.

See `config.example.json`.

---

## How it works

```
/loot throughput
   └─ Claude translates → loot.py add → vocab table in ~/.shadowling/shadowling.db
        throughput, rendimiento, remaining=10, active

(before every reply)  UserPromptSubmit hook → gloss.py inject
   └─ injects <vocab_glossing> block: rules + active words

(Claude replies)
   └─ first occurrence glossed inline + 📖 Vocabulary footer

(after the reply)  Stop hook → gloss.py scan
   └─ reads the reply, remaining−1 per used word; at 0 → "learned"
```

- **Deterministic** (in the script): storage, exposure counting, graduation,
  word matching.
- **Instruction-based** (Claude follows it): the actual glossing. There's no
  Claude Code hook that rewrites an assistant message after it's generated, so the
  gloss is the model following the injected rule (see **Good to know** below).

### Counting / graduation
A word starts at `remaining = 10`. Each reply it appears in decrements it by one
(once per reply, regardless of how many times it occurs). At `0` the word's status
becomes `learned` and it's no longer injected or glossed. Re-adding a learned word
resets it to `10`/`active`.

### Word matching
Case-insensitive, whole-word. Words ≥ 4 characters also match common suffixes
(`s`, `es`, `ed`, `ing`, `d`); shorter words match exactly. Terms with trailing
punctuation (e.g. `C++`) are matched too.

---

## Writing corrections (`/debrief`)

Beyond single words, shadowling can quietly build a **personal dataset of how you
(a non-native) phrase things vs. how natives say it** — so you can study it later.

It's a two-phase, **silent** model:

1. **Collect (passive).** When you write prompts, the `Stop` hook extracts your
   message and stores it in the local message store
   (`~/.shadowling/shadowling.db`) — any language, no analysis, nothing printed
   in the chat. Slash-command turns are skipped. Messages are kept forever:
   a debrief marks them processed instead of deleting them, so the store
   doubles as your language-tagged history.
2. **Review (on demand).** Run `/debrief`. A triage subagent first tags each
   message's language(s); then five per-category **specialist subagents** —
   grammar, rephrasing, idioms, irregular verbs, and friction — run in
   parallel, each with its own context window, so the batch, the existing
   entries, and the reasoning never pollute your current conversation; only a
   short summary comes back. Each specialist reads its slice of the batch and
   appends to one append-only dataset per category (explanations written in your
   `explanation_language`):

   | Category | Dataset |
   |---|---|
   | grammar | `grammar` (ranking: `grammar_ranked`) |
   | rephrasing | `rephrasing` (ranking: `rephrasing_ranked`) |
   | idioms | `idioms` (ranking: `idioms_ranked`) |
   | irregular verbs | `verbs` (ranking: `verbs_ranked`) |
   | friction (code-switching) | `friction` (ranking: `friction_ranked`) |

   If all of them succeed, the batch is marked processed (and kept as history).

Each category is an **append-only incident table** — one row per occurrence,
nothing overwritten. The matching `*_ranked` **view** computes the frequency
ranking on the fly (a `counter` per stable key, plus the latest example), so a
recurring mistake climbs the ranking while every verbatim instance stays
queryable. `python3 <plugin>/sql.py --md "SELECT * FROM <category>_ranked"` renders
any ranking as a markdown table.

Everything stays local — it all lives in `~/.shadowling/shadowling.db`, no
network calls.

The friction specialist deserves a note: it watches for **code-switching** —
the moments you bail from the language you're learning into your native language.
Native words dropped mid-sentence are treated as an implicit `/loot` (the
learning-language equivalent goes straight into your vocabulary), and recurring
bail-out zones
are ranked in the friction dataset with a type verdict: `lexical`, `phrasal`,
`structural`, `topical`, or `register`.

---

## Comprehension help (`/aha`)

The flip side of `/debrief`: instead of fixing the language you *wrote*, `/aha`
explains text you *read* but couldn't decode literally — idioms, set phrases, and
grammar patterns whose meaning isn't the sum of the words.

Run `/aha <phrase>`, optionally with your own hunch at what it means
(e.g. `/aha "it cost an arm and a leg" — I thought it's about an arm and a leg`).
Claude — seeing the conversation for context — gives a verdict and teaches it inline:

- **`fixed`** — a set expression you just have to memorize (the meaning isn't
  derivable). The key is the phrase itself.
- **`method`** — derivable from a grammar pattern you're missing; the key is the
  **rule** (e.g. `present-perfect-passive`), so one rule aggregates across the
  different phrases that trip you on it.

Comparing against your hunch, it points out exactly where your literal read went
wrong. Each call appends the verbatim submission — your hunch and where it
appeared — to the append-only `decode` dataset; the `decode_ranked` view is your
"what trips me most" ranking. Explanations follow your `explanation_language`.
Literal phrases and bare unknown words aren't recorded — for a single
unknown word it points you at `/loot` instead.

---

## Training (`/tutor`)

The datasets aren't just a mirror — `/tutor` closes the loop. Each session
deals a small deck of cards built from your own incidents: "how would you
say…?" for code-switching zones, "correct this sentence" for recurring
grammar errors, quick-fire irregular-verb forms, and reverse checks of
vocabulary you "learned" by exposure (fail one and it returns to glossing).
Scheduling is spaced repetition (Leitner: answer well → the item comes back
later; fail → tomorrow), and items your latest `/debrief` re-caught jump the
queue. Your answers during a session are NOT collected as writing material.

Requires Claude Code ≥ 2.1.163 for that last guarantee (older versions:
tutoring works, but drill answers may reach `/debrief` analysis).

---

## Data & files

| Path | What |
|---|---|
| `~/.shadowling/shadowling.db` | everything: message store (language tags, processed flags), the six category incident datasets with their computed rankings, your vocabulary, and the tutor's attempt log + spaced-repetition state |
| `~/.shadowling/config.json` | language settings |

Want a human-readable table? `python3 <plugin>/sql.py --md "SELECT * FROM <category>_ranked"`
renders any ranking as a markdown table (categories: grammar, rephrasing, idioms,
verbs, decode, friction).

Data is intentionally stored **outside** the plugin directory so it survives plugin
updates. Override the location with the `SHADOWLING_HOME` environment variable.

---

## Good to know

A few design notes so nothing surprises you:

- **Glossing is done by Claude, from an injected instruction.** There's no Claude
  Code hook that rewrites a finished message, so the gloss is the model following a
  rule rather than a guaranteed find-and-replace. In practice it's reliable — and
  everything that *can* be exact is: storage, exposure counting, and graduation all
  run in the script, independent of the glossing.
- **It stays out of your answers.** The word list lives in context, but the
  instruction explicitly tells Claude *not* to steer toward those words — only to
  annotate ones that would have appeared anyway. You get the glosses without the
  tool quietly changing what Claude says.
- **Everything stays on your machine.** The `Stop` hook reads your latest reply
  locally to count word exposures — there are no network calls and no telemetry,
  nothing leaves your computer.
- **Your data outlives updates.** Words and settings live in `~/.shadowling`,
  separate from the plugin's code, so updating or reinstalling never touches them.
- **The active list stays small.** Only un-learned words are injected, and each one
  retires after 10 exposures — so the per-prompt cost stays low as your vocabulary
  grows.

---

## Development

```
cd plugins/shadowling
python3 -m unittest discover -p 'test_*.py' -v    # full suite, stdlib only
claude plugin validate . --strict                 # validate the manifest
```

The tool is dependency-free stdlib Python: `core.py` (shared infra), `config.py`
(plugin-wide language config), `appdb.py` (the single sqlite home: connection,
`user_version` migrations, ranked views, read-only query), `gloss.py` (glossing),
`capture.py` (message capture), and the sqlite data layer (`models/` repositories +
per-skill entrypoints) plus tests.

See **[docs/ENGINEERING.md](docs/ENGINEERING.md)** for the design principles and the
guarantees behind them.

---

## License

AGPL-3.0-only — see [LICENSE](../../LICENSE).
