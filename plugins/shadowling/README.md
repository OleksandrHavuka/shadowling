# shadowling

**Learn vocabulary passively, while you work with Claude Code.** Most developers
aren't native English speakers — shadowling turns your everyday Claude Code
sessions into quiet vocabulary practice instead of a separate chore.

Collect words you don't know yet with `/loot`. From then on, whenever one of
those words appears in Claude's replies, Claude appends a translation in your
native language — inline and in a short summary at the bottom — until you've seen
it enough times to have learned it. No flashcards, no separate app: you absorb
terminology in the flow of your normal work.

Works for **any** native language (set it once). English vocabulary → your
language is the default.

<!-- Demo GIF — drop a ~10s recording at docs/demo.gif and uncomment:
![shadowling demo](docs/demo.gif)
-->


---

## What it looks like

Examples here translate into Spanish, but you set your own native language in one
step.

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
  words) **and** quietly buffers your English messages for later review (see
  [English corrections](#english-corrections-debrief)).

---

## Usage

| Command | Effect |
|---|---|
| `/shadowling:setup` | Set your native language (run once). |
| `/loot <word>[, ...]` | Translate the word(s) into your native language and start tracking them. |
| `/drop <word>[, ...]` | Stop tracking and delete word(s). |
| `/debrief` | Review your buffered English messages into per-category frequency docs (grammar / rephrasings / idioms / verbs). |
| `/aha <phrase> [+ your hunch]` | Explain an English expression you can't read literally — verdict (memorize vs learnable rule) + how to read it, saved to `decode.md`. |
| `/vipe` | Dev: wipe the `/debrief` product/log docs for a clean test run (keeps config, words, buffer, raw corpus). |

Run **`/shadowling:setup`** once to set your native language; the answer is saved
to `~/.shadowling/config.json`. (Commands also work fully-qualified, e.g.
`/shadowling:loot`.)

---

## Configuration

Config lives at `~/.shadowling/config.json`:

```json
{
  "native_language": "Ukrainian",
  "learning_language": "English",
  "explanation_language": "English"
}
```

- `native_language` — the language words are translated **into** (the gloss). This
  is the one that matters; change it to learn with a different native language. Set
  it with `/shadowling:setup`.
- `explanation_language` — the language `/debrief` and `/aha` write their
  **explanations** in (meanings, takeaways, corrections). Defaults to English; set
  it with `config.py set-explanation-lang "<language>"`.
- `learning_language` — cosmetic framing in the instruction ("learning English
  vocabulary"). Matching is literal, so this doesn't affect behavior.

Missing or malformed values fall back to the defaults above. See
`config.example.json`.

---

## How it works

```
/loot throughput
   └─ Claude translates → vocab.py add → ~/.shadowling/words.csv
        throughput, rendimiento, remaining=10, active

(before every reply)  UserPromptSubmit hook → vocab.py inject
   └─ injects <vocab_glossing> block: rules + active words

(Claude replies)
   └─ first occurrence glossed inline + 📖 Vocabulary footer

(after the reply)  Stop hook → vocab.py scan
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

## English corrections (`/debrief`)

Beyond single words, shadowling can quietly build a **personal dataset of how you
(a non-native) phrase things vs. how natives say it** — so you can study it later.

It's a two-phase, **silent** model:

1. **Collect (passive).** When you write prompts in English, the `Stop` hook
   extracts your message and dual-writes it: to the transient buffer
   (`~/.shadowling/buffer.jsonl`, the current unprocessed batch) **and** to the
   permanent raw corpus (`~/.shadowling/messages.log.jsonl`). No analysis, nothing
   printed in the chat. Ukrainian/other-language and slash-command messages are
   skipped.
2. **Review (on demand).** Run `/debrief`. It orchestrates four per-category
   **specialist subagents** — grammar, rephrasing, idioms, irregular verbs — in
   parallel, each with its own context window, so the buffer, the existing entries,
   and the reasoning never pollute your current conversation; only a short summary
   comes back. Each specialist reads the buffer and writes two things per category
   (its explanations written in your `explanation_language`, English by default):

   | Category | Frequency product (markdown) | Findings log (append-only JSONL) |
   |---|---|---|
   | grammar | `grammar.md` | `grammar.log.jsonl` |
   | rephrasing | `rephrasings.md` | `rephrasings.log.jsonl` |
   | idioms | `idioms.md` | `idioms.log.jsonl` |
   | irregular verbs | `irregular_verbs.md` | `irregular_verbs.log.jsonl` |

   If all four succeed, the buffer is cleared (the raw corpus is kept).

Each product is a markdown table keyed on a stable column with a `counter`: a
recurring mistake bumps its counter instead of adding a row, so the table doubles
as a frequency ranking of your weak spots. The matching `*.log.jsonl` keeps every
verbatim instance, append-only, for deeper study.

Everything stays local — the buffer, corpus, and docs live in `~/.shadowling/`, no
network calls.

---

## Comprehension help (`/aha`)

The flip side of `/debrief`: instead of fixing English you *wrote*, `/aha` explains
English you *read* but couldn't decode literally — idioms, set phrases, and grammar
patterns whose meaning isn't the sum of the words.

Run `/aha <phrase>`, optionally with your own hunch at what it means
(e.g. `/aha "it cost an arm and a leg" — I thought it's about an arm and a leg`).
Claude — seeing the conversation for context — gives a verdict and teaches it inline:

- **`fixed`** — a set expression you just have to memorize (the meaning isn't
  derivable). The key is the phrase itself.
- **`method`** — derivable from a grammar pattern you're missing; the key is the
  **rule** (e.g. `present-perfect-passive`), so one rule aggregates across the
  different phrases that trip you on it.

Comparing against your hunch, it points out exactly where your literal read went
wrong. Each call writes the deduped product `decode.md` (your "what trips me most"
ranking) and appends the verbatim submission — your hunch and where it appeared — to
`decode.log.jsonl`; explanations follow your `explanation_language` (English by
default). Literal phrases and bare unknown words aren't recorded — for a single
unknown word it points you at `/loot` instead.

---

## Data & files

| Path | What |
|---|---|
| `~/.shadowling/words.csv` | your vocabulary (`word,translation,remaining,status`) |
| `~/.shadowling/config.json` | language settings |
| `~/.shadowling/buffer.jsonl` | current batch of buffered English messages awaiting `/debrief` |
| `~/.shadowling/messages.log.jsonl` | permanent raw corpus of every captured English message |
| `~/.shadowling/{grammar,rephrasings,idioms,irregular_verbs}.md` | per-category frequency products from `/debrief` |
| `~/.shadowling/{grammar,rephrasings,idioms,irregular_verbs}.log.jsonl` | append-only findings datasets from `/debrief` |
| `~/.shadowling/decode.md` | comprehension product from `/aha` — deduped ranking of expressions you couldn't read literally |
| `~/.shadowling/decode.log.jsonl` | append-only log of every `/aha` submission (your hunch + context) |
| `~/.shadowling/.script_path` | script location recorded by the hooks (internal) |

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
(plugin-wide language config), `vocab.py` (glossing), `capture.py` (English-message
capture), `jsonl.py` (append-only log helper), and the markdown data layer
(`mddb.py`, `db.py` CLI, `models/`) plus tests.

---

## License

MIT — see [LICENSE](../../LICENSE).
