# lexigloss

A Claude Code plugin marketplace. It currently hosts a single plugin:

### `lexigloss`

Passive vocabulary learning for non-native developers — collect words with
`/vocab` and Claude appends a translation in your native language inline in its
replies, until you've seen each word enough times to have learned it. Works for
any native language.

→ Full documentation: [`plugins/lexigloss/README.md`](plugins/lexigloss/README.md)

## Install

```
/plugin marketplace add OleksandrHavuka/lexigloss
/plugin install lexigloss
```

Then restart Claude Code. Requires **Python 3.9+** (standard library only).

Trying it locally before publishing? Point the marketplace at the repo folder:

```
/plugin marketplace add ~/projects/lexigloss
/plugin install lexigloss
```

## License

MIT — see [LICENSE](LICENSE).
