# lexigloss

**Passive vocabulary glossing for Claude Code.** Collect words you're learning
with a slash command; from then on, whenever one of those words shows up in
Claude's replies, Claude appends a translation in your native language — inline
and in a small summary at the bottom — until you've seen it enough times to have
learned it. No flashcards, no separate app: you absorb terminology in the flow of
your normal work.

By default it glosses English words with Ukrainian translations, but the
languages are configurable.

---

## What it looks like

You add a word once:

```
/vocab throughput
→ stored: throughput = пропускна здатність (remaining 10, active)
```

Later, in any normal reply that happens to use the word:

```
...this batching improves throughput (пропускна здатність) under load, so the
queue drains faster.

---
📖 Vocabulary:
- throughput — пропускна здатність (10 to go)
```

After the word has appeared in 10 replies it "graduates" and is no longer glossed.
Re-adding a graduated word resets it.

---

## Install

```
/plugin marketplace add <your-github-user>/lexigloss
/plugin install lexigloss
```

Restart Claude Code. Requires **Python 3.9+** on your PATH (standard library only,
no pip dependencies).

The plugin ships two hooks (added automatically — your own hooks are untouched):

- `UserPromptSubmit` → injects the active word list + glossing instruction into
  context before each reply.
- `Stop` → scans the reply you just received, counts exposures, and graduates
  learned words.

---

## Usage

| Command | Effect |
|---|---|
| `/vocab <word>` | Translate `<word>` into your native language and start tracking it. |
| `/vocab remove <word>` | Stop tracking and delete a word. |

On the **first** `/vocab` you'll be asked your native language once; the answer is
saved to `~/.lexigloss/config.json`.

---

## Configuration

Config lives at `~/.lexigloss/config.json`:

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
/vocab despite
   └─ Claude translates → vocab.py add → ~/.lexigloss/words.csv
        despite, попри, remaining=10, active

(before every reply)  UserPromptSubmit hook → vocab.py inject
   └─ injects <vocab_glossing> block: rules + active words

(Claude replies)
   └─ first occurrence glossed inline + 📖 Vocabulary footer

(after the reply)  Stop hook → vocab.py scan
   └─ reads the reply, remaining−1 per used word; at 0 → "learned"
```

- **Deterministic** (in the script): storage, exposure counting, graduation,
  word matching.
- **Instruction-based** (Claude follows it): the actual glossing. There is no
  Claude Code hook that rewrites an assistant message after it's generated, so the
  gloss is produced by the model from the injected instruction — which also means
  it can't bias your answers: the instruction explicitly says not to steer word
  choice toward the list, only to annotate words that would have appeared anyway.

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

## Data & files

| Path | What |
|---|---|
| `~/.lexigloss/words.csv` | your vocabulary (`word,translation,remaining,status`) |
| `~/.lexigloss/config.json` | language settings |
| `~/.lexigloss/.script_path` | script location recorded by the hooks (internal) |

Data is intentionally stored **outside** the plugin directory so it survives plugin
updates. Override the location with the `VOCAB_HOME` environment variable.

---

## Limitations

- Glossing is instruction-following, not a guaranteed text transform — Claude has
  to comply with the injected rule. Counting and graduation are deterministic
  regardless.
- The active word list is injected into context on every prompt. Graduation keeps
  it small; there's no frequency-based cap yet, so adding hundreds of rarely-used
  words would grow per-prompt token cost.

---

## Development

```
cd plugins/lexigloss
python3 -m unittest test_vocab -v        # 36 tests, stdlib only
claude plugin validate . --strict         # validate the manifest
```

The whole tool is one dependency-free file (`vocab.py`) plus tests.

---

## License

MIT — see [LICENSE](../../LICENSE).
