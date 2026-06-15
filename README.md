# shadowling

A Claude Code plugin marketplace hosting a single plugin:

### `shadowling`

Passive language learning for non-native developers. Collect words with `/loot`
and Claude appends a translation in your native language inline in its replies,
until you've seen each word enough times to have learned it. `/debrief` quietly
turns what you write in the language you're learning into personal correction docs —
grammar, natural phrasing, idioms, and irregular verbs — while `/aha` explains
expressions you can't read literally. Works for any language pair.

→ Full documentation: [`plugins/shadowling/README.md`](plugins/shadowling/README.md)

## Install

```
/plugin marketplace add OleksandrHavuka/shadowling
/plugin install shadowling@shadowling-lab
```

Then restart Claude Code. Requires **Python 3.9+** (standard library only).

Trying it locally before publishing? Point the marketplace at the repo folder:

```
/plugin marketplace add ~/projects/shadowling
/plugin install shadowling@shadowling-lab
```

## License

AGPL-3.0-only — see [LICENSE](LICENSE).
