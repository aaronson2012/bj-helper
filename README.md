# bjcalc

`bjcalc` is a voice-driven blackjack helper for Linux desktops.

It is built for a very specific use case: you are playing blackjack, you want instant basic-strategy advice, and you do not want to look up charts or type card values by hand. You hold a push-to-talk shortcut, say the cards, and the app speaks the move.

## What It Does

- listens on a global push-to-talk hotkey
- transcribes short spoken phrases locally with Vosk
- speaks the recommended move with local TTS
- shows the current hand and transcript in a small HUD window
- automatically follows its own advice internally until it needs another card from you

That last point matters:

- you do **not** say `hit`, `stand`, `double`, or `split` during normal play
- the app tells you what to do
- if the advised move draws a card, you only say the new card
- if you want to abandon the current hand and move on, say `next`

## How To Use It

The default hotkey is `Alt+Z`.

General loop:

1. Hold `Alt+Z`.
2. Say the opening cards in this exact order: dealer card, your first card, your second card.
3. Release `Alt+Z`.
4. The app speaks the move.
5. If that move needs another card, hold `Alt+Z` again and say the new card.
6. Repeat until the hand is done.
7. Say `next` any time you want to reset and move on.

Example:

1. Hold `Alt+Z`
2. Say `five ace seven`
3. Release
4. App says `Double.`
5. Hold `Alt+Z`
6. Say `three`
7. Release

Split example:

1. Hold `Alt+Z`
2. Say `six eight eight`
3. Release
4. App says `Split.`
5. Hold `Alt+Z`
6. Say the replacement card for hand 1
7. Hold `Alt+Z`
8. Say the replacement card for hand 2
9. After that, keep feeding cards only when the app’s recommended move requires one

## What You Can Say

Card words:

- `ace`
- `two` through `ten`
- `jack`
- `queen`
- `king`
- numeric forms like `2` and `10`

Control words:

- `next`
- `repeat`
- `undo`
- `cancel`

`next` is the main escape hatch. It resets the current hand immediately, even if you are in the middle of a split or waiting on a card.

## Mental Model

The app is not trying to be a full blackjack simulator.

It is an advisor that tracks only enough state to continue your decision tree:

- your current hand
- split hands
- cards you report after draw actions
- current strategy recommendation

It does **not** resolve the dealer hand, bankroll, or table outcome.

## Install

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m ensurepip --upgrade
python3 -m pip install -e .
```

## Run

```bash
. .venv/bin/activate
bjcalc
```

## Config

The config file lives at `${XDG_CONFIG_HOME:-~/.config}/bjcalc/config.json`.

Useful keys:

- `hotkey`
- `stt.model_path`
- `stt.listen_seconds`
- `tts.backend`
- `tts.voice`
- `tts.language`
- `tts.rate`
- `tts.pitch`
- `ui.show_hud`
- `rules.deck_mode`
- `rules.dealer_soft_17`
- `rules.double_after_split`
- `rules.surrender`
- `rules.insurance_enabled`
- `rules.peek_for_blackjack`

## Runtime Notes

- `ffmpeg` is required for microphone capture.
- a local Vosk model is required for speech recognition
- the default Linux TTS path here uses `speech-dispatcher`
- the global hotkey helper reads `/dev/input`, so it is launched with `sudo`

## Current Behavior

- shortcut: `Alt+Z`
- spoken advice is intentionally short, usually just `Hit.`, `Stand.`, `Double.`, `Split.`, or `Surrender.`
- there is a small delay after you release the hotkey before speech starts
- KDE notifications are mostly suppressed; normal updates stay in the HUD window
