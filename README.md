# Blackjack Helper

`bj-helper` is a voice-driven blackjack helper for Linux desktops.

It is built for a very specific use case: you are playing blackjack, you want instant basic-strategy advice, and you do not want to look up charts or type card values by hand. You left click the tray icon, say the cards, and the app speaks the move.

## What It Does

- listens from a tray-icon click
- transcribes short spoken phrases locally with Vosk
- speaks the recommended move with local TTS
- runs as a tray app and keeps its current status in the tray menu
- automatically follows its own advice internally until it needs another card from you

That last point matters:

- you do **not** say `hit`, `stand`, `double`, or `split` during normal play
- the app tells you what to do
- if the advised move draws a card, you only say the new card
- if the app says `Stand.`, `Surrender.`, or finishes a double, the hand is done
- if you want to abandon the current hand and move on, say `next`

## How To Use It

Normal hand flow:

1. Left click the tray icon.
2. Say the opening cards in this exact order: dealer card, your first card, your second card.
3. The app speaks the move.
4. If that move needs another card, left click the tray icon again and say the new card.
5. Repeat until the hand is done.
6. Say `next` any time you want to reset and move on.

Example:

1. Left click the tray icon
2. Say `five ace seven`
3. Wait for the advice
4. App says `Double.`
5. Left click the tray icon again
6. Say `three`
7. Wait for the next advice

Split flow:

1. Left click the tray icon
2. Say `six eight eight`
3. Wait for the advice
4. App says `Split.`
5. Left click the tray icon again
6. Say the replacement card for hand 1
7. Left click the tray icon again
8. Say the replacement card for hand 2
9. After that, keep feeding cards only when the app’s recommended move requires one

Split notes:

- after a split, each click expects exactly one replacement or drawn card
- after both split replacement cards are entered, the app automatically continues with hand 1, then hand 2, then later split hands if they exist
- split aces are treated as one-card-only hands under the current ruleset, so after each ace gets one replacement card that branch is finished
- `rules.max_split_hands` caps the total number of hands, including the original hand

Round reset flow:

1. When a round is finished, you do **not** need to say `next`
2. The next left click starts a fresh opening hand automatically
3. `next` still works as a manual reset if you want to abandon the current hand early

The app does not open a main window. Left click the tray icon to start listening. Right click it for current state, hand context, and quick actions like `Start Listening`, `Repeat Last Advice`, `Next Hand`, and `Quit`.

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

Control word behavior:

- `next` resets the current hand immediately, even in the middle of a split or while waiting on a card
- `cancel` does the same thing with different wording
- `repeat` repeats the last actual blackjack recommendation
- `undo` restores the previous step
- these control words work during any listening capture; you do not need a separate command mode
- action words like `hit`, `stand`, `double`, `split`, `surrender`, and `insurance` are not part of the supported user flow

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
./run-bj-helper
```

`run-bj-helper` is the recommended launcher. It uses the project virtualenv automatically and sets `PYTHONPATH` for the local source tree.

Runtime entry points:

- `./run-bj-helper` starts the tray app if it is not already running
- if the tray app is already running, `./run-bj-helper` exits cleanly instead of opening a second copy
- `./run-bj-helper start-listening` tells the running tray app to begin a listening capture, which is useful for a KDE shortcut

If you prefer the console script directly:

```bash
. .venv/bin/activate
bj-helper
```

## Config

The checked-in base config lives at [config.json](/home/jako/stuff/bj-helper/config.json).

When you launch through `./run-bj-helper`, that repo-root config is loaded first, then `${XDG_CONFIG_HOME:-~/.config}/bj-helper/config.json` is applied on top as a machine-specific override if it exists.

If you already have `${XDG_CONFIG_HOME:-~/.config}/bjcalc/config.json`, the app migrates it automatically on first launch.

Useful keys:

- `recording_cue_path`
- `recording_cue_volume`
- `stt.model_path`
- `stt.listen_seconds`
- `tts.backend`
- `tts.voice`
- `tts.language`
- `tts.rate`
- `tts.pitch`
- `tts.volume`
- `tts.model_path`
- `tts.speaker_id`
- `rules.deck_mode`
- `rules.dealer_soft_17`
- `rules.double_after_split`
- `rules.max_split_hands`
- `rules.surrender`
- `rules.insurance_enabled`

Notes:

- `stt.model_path` and `recording_cue_path` may be relative in the repo config; they resolve relative to the config file that declared them.
- the checked-in rules default to a common online-style setup: `deck_mode = "shoe"`, `dealer_soft_17 = "hit"`, `double_after_split = true`, `max_split_hands = 4`, `surrender = "none"`, and `insurance_enabled = false`

## Runtime Notes

- `ffmpeg` is required for microphone capture.
- a local Vosk model is required for speech recognition.
- the default TTS backend is `speechd`; if that is unavailable, the app can fall back to `espeak-ng`.
- for higher-quality local TTS, install `piper` or `piper-tts`, set `tts.backend` to `piper`, and point `tts.model_path` at a Piper `.onnx` voice model.
- Piper playback also needs one of `ffplay`, `paplay`, or `aplay`.
- the app installs a local desktop entry and tray icon under `~/.local/share`

## Current Behavior

- left click on the tray icon starts listening
- right click on the tray icon opens the menu
- the app is tray-only; there is no main window
- only one tray instance is allowed at a time
- after a round finishes, the next listen starts a fresh opening hand automatically
- `Repeat Last Advice` repeats the last actual blackjack recommendation, not prompts or status chatter
- spoken advice is action-only: `Hit.`, `Stand.`, `Double.`, `Split.`, or `Surrender.`
- there is a short delay after you click before speech starts
- the tray tooltip is simply `Blackjack Helper`
- current state and hand context stay in the tray menu
- desktop notifications are only used for real runtime failures such as broken TTS or missing STT/audio dependencies
