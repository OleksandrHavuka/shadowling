# Anki sync (`/anki-sync`) — setup from scratch

`/anki-sync` mirrors your enriched shadowling vocabulary into **Anki** as
randomized-cloze flashcards, and pulls review progress back: a word whose lapse
count grew in Anki re-enters glossing in shadowling. Your vocabulary stays the
source of truth; Anki is the spaced-repetition engine; the link between them is
stored locally.

It talks to Anki through the **AnkiConnect** add-on over `http://127.0.0.1:8765`
— a local, no-network bridge. So Anki Desktop must be **running with AnkiConnect
installed** whenever you sync.

This guide is the one-time setup, in order. Steps 1, 3, 4, 5 are required. Step 2
(an AnkiWeb account) and step 6 (phone) are only needed if you also want the cards
on your phone.

---

## 1. Install Anki Desktop

Download the official desktop app from **<https://apps.ankiweb.net>** (macOS,
Windows, Linux) and launch it once. On first run it creates a local profile and an
empty collection — that's all you need here.

> There is no separate "Anki app account". The only account is **AnkiWeb** (next
> step), and you sign into it *from inside* the desktop app. (Note: **AnkiHub** is
> an unrelated third-party paid service — you do **not** need it.)

## 2. (Optional — for phone sync) Create an AnkiWeb account

Cross-device sync goes through AnkiWeb, Anki's free official cloud middleman.

1. Create an account at **<https://ankiweb.net>** (email + password) and verify it.
2. In Anki Desktop, click **Sync** (top toolbar) and sign in with those AnkiWeb
   credentials.

Skip this entirely if you only study on the desktop — `/anki-sync` works without
any AnkiWeb account.

## 3. Install the AnkiConnect add-on

This is the bridge `/anki-sync` calls.

1. In Anki Desktop: **Tools → Add-ons → Get Add-ons…**
2. Paste the add-on code **`2055492159`** → **OK**.
3. Let it download.

No configuration is required: AnkiConnect listens on `127.0.0.1:8765` by default,
which is exactly what shadowling uses, and CORS does not apply (the sync is a local
script, not a browser).

## 4. Restart Anki

Add-ons load on startup, so **quit Anki completely and reopen it**. AnkiConnect is
now active.

Keep Anki **running** whenever you run `/anki-sync` — the add-on only answers while
the app is open.

## 5. Run the sync

In Claude Code:

```
/anki-sync
```

On the first run it:

- creates the note type **`Shadowling Cloze`**,
- creates the deck **`shadowling::<learning_language>`** (e.g. `shadowling::English`),
- pushes every enriched vocab word as one cloze card (tagged `shadowling`),
- pulls Anki's review progress back into shadowling.

It prints one summary line, e.g.:

```
anki-sync: +253 added, 0 updated, 0 suspended, 0 skipped (not enriched), 253 pulled, 0 relearned, 0 errors
```

Re-running is **idempotent**: existing cards become `updated`, no duplicates.
Dropped words (`/drop`) get their card **suspended**; words you haven't enriched
yet are **skipped** (run `/loot` on them first).

## 6. (Optional) Get the cards on your phone

Install **AnkiDroid** (Android) or **AnkiMobile** (iOS), then:

1. **Desktop → Sync → Upload to AnkiWeb** (first time, the desktop holds the data).
2. **Phone:** sign in with the same AnkiWeb account → **Sync → Download from AnkiWeb**.
3. After that, just hit **Sync** on either device; AnkiWeb keeps them in step.

The card template's JavaScript is written to run in AnkiDroid's webview too, so the
randomized example shows correctly on the phone.

> **Progress flow matters.** `/anki-sync` reads the **desktop's local** collection.
> If you review on the phone, sync **phone → AnkiWeb → desktop** *before* running
> `/anki-sync`, otherwise the desktop (and shadowling) won't see those reviews yet.

---

## What a card looks like

The card is a single-direction **cloze recall**, redesigned for breathing room and
self-paced difficulty:

- **Front:** one of the word's example sentences with the word (or an inflected
  form) blanked out — `She [...] great satisfaction from solving complex problems.`
  — vertically centered and large. Below it a tap-to-reveal **hint chip** shows the
  translation only if you ask for it (tap when stuck, grade honestly; stop tapping
  as the word solidifies).
- **Back:** a dimmed, revealed context line; a **hero** block with the word, a
  **🔊 tap-to-replay pronunciation** (on-device TTS — no audio files), and the
  translation in accent; then labeled sections, each shown only when it has content:
  **meaning → also → synonyms → forms → base form → seen in**.

You recall the word, flip, and self-grade with **Again / Hard / Good / Easy** —
that grade is what feeds Anki's scheduler (enable **FSRS** in Anki's settings for
the modern algorithm).

If a word has several examples, the front shows **one at random** each review.

### Typed answer (optional)

By default there is no typing — recall is mental. If you want **active recall by
typing** (which can help fix spelling), enable it once: open
`~/.shadowling/config.json` and add a fourth key:

```json
{
  "first_language": "Ukrainian",
  "learning_language": "English",
  "explanation_language": "English",
  "anki_typed": true
}
```

Re-run `/anki-sync`. Each card then shows a native input on the front; the keyboard
pops automatically and **Enter** flips the card. The back shows a clean green
`✓ correct` / red `✕ try again` banner (case- and trailing-space-insensitive), and
only when you actually typed something — "Show answer" alone shows no banner. To
turn it off again, set `"anki_typed": false` (or remove the key) and re-sync.

> **shadowling owns the card templates and styling.** Every `/anki-sync` rewrites
> the `Shadowling Cloze` note type's templates and CSS to the current shadowling
> design, so any manual edits you make in Anki's card editor are overwritten on the
> next sync. Your **scheduling** (due dates, intervals, lapses, ease) lives on the
> cards and is never touched — updates are additive-only (fields are only added,
> never removed or reordered; no card template is ever deleted), so no review
> progress is lost.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `cannot reach AnkiConnect at http://127.0.0.1:8765` | Anki isn't running, or the AnkiConnect add-on / restart (steps 3–4) was missed. Open Anki and retry. |
| `<shadowling_misconfig>` notice | shadowling's languages aren't set — run `/shadowling:setup` first. |
| `… N errors` in the summary | A per-word push failed (e.g. a hand-inserted row with no clozable example). The rest still synced; the failed word is named — re-`/loot` it. |
| Cards don't appear on the phone | You skipped the AnkiWeb upload (step 6.1) or signed into a different account on the phone. |
| Phone reviews don't reach shadowling | Sync phone → AnkiWeb → desktop before `/anki-sync` (see the progress-flow note above). |
| No pronunciation sound on the back | TTS uses your device's installed voices. Install a voice for your `learning_language` (OS settings on desktop; Android/iOS TTS settings on phone). No voice → silent, which is harmless. |
