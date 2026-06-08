# shadowling

**Learn vocabulary passively, while you work with Claude Code.** Most developers
aren't native English speakers — shadowling turns your everyday Claude Code
sessions into quiet vocabulary practice instead of a separate chore.

Collect words you don't know yet with `/vocab`. From then on, whenever one of
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
/vocab throughput
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
  [English corrections](#english-corrections-en-review)).

---

## Usage

| Command | Effect |
|---|---|
| `/shadowling:setup` | Set your native language (run once). |
| `/vocab <word>[, ...]` | Translate the word(s) into your native language and start tracking them. |
| `/vocab-remove <word>[, ...]` | Stop tracking and delete word(s). |
| `/en-review` | Analyze your buffered English messages into personal correction docs. |

Run **`/shadowling:setup`** once to set your native language; the answer is saved
to `~/.shadowling/config.json`. (Commands also work fully-qualified, e.g.
`/shadowling:vocab`.)

---

## Configuration

Config lives at `~/.shadowling/config.json`:

```json
{
  "native_language": "Ukrainian",
  "learning_language": "English"
}
```

- `native_language` — the language words are translated **into** (the gloss). This
  is the one that matters; change it to learn with a different native language.
- `learning_language` — cosmetic framing in the instruction ("learning English
  vocabulary"). Matching is literal, so this doesn't affect behavior.

Missing or malformed values fall back to the defaults above. See
`config.example.json`.

---

## How it works

```
/vocab throughput
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

## English corrections (`/en-review`)

Beyond single words, shadowling can quietly build a **personal dataset of how you
(a non-native) phrase things vs. how natives say it** — so you can study it later.

It's a two-phase, **silent** model:

1. **Collect (passive).** When you write prompts in English, the `Stop` hook
   extracts your message and appends it to a raw buffer
   (`~/.shadowling/en_buffer.jsonl`). No analysis, nothing printed in the chat.
   Ukrainian/other-language and slash-command messages are skipped.
2. **Review (on demand).** Run `/en-review`. The analysis happens in a **subagent**
   with its own context window, so the buffer, the existing entries, and the
   reasoning never pollute your current conversation — only a short summary comes
   back. It reads the buffer, and appends findings to four growing markdown tables:

   | Doc | Captures |
   |---|---|
   | `grammar.md` | grammar fixes (also articles, prepositions, false friends) |
   | `rephrasings.md` | non-native phrasing → natural native phrasing / collocations |
   | `idioms.md` | idioms that would have fit the context |
   | `irregular_verbs.md` | irregular verbs you stumbled on, with the full triad |

   Then the buffer is cleared.

Each doc is a single markdown table with a stable key column, so duplicates are
skipped two ways: the subagent avoids near-duplicates it sees in the existing
entries, and the script refuses an exact key match as a safety net.

Everything stays local — the buffer and docs live in `~/.shadowling/`, no network
calls.

---

## Data & files

| Path | What |
|---|---|
| `~/.shadowling/words.csv` | your vocabulary (`word,translation,remaining,status`) |
| `~/.shadowling/config.json` | language settings |
| `~/.shadowling/en_buffer.jsonl` | buffered English messages awaiting `/en-review` |
| `~/.shadowling/{grammar,rephrasings,idioms,irregular_verbs}.md` | correction docs from `/en-review` |
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
python3 -m unittest test_vocab test_capture -v   # 63 tests, stdlib only
claude plugin validate . --strict                # validate the manifest
```

The tool is three dependency-free files (`core.py` shared infra, `vocab.py`
glossing, `capture.py` English-correction collection) plus tests.

---

## License

AGPL-3.0-only — see [LICENSE](../../LICENSE).
