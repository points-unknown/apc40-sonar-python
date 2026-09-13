# Cakewalk by BandLab Command Matrix

Classifies each desired integration function by the **bridge** used to trigger it, and
defines the LED/feedback behavior. This shapes the Lua encoder/decoder.

## Bridge Selection Rules

1. **MCU** when Cakewalk exposes a normal control-surface parameter *and* returns state.
2. **Keystroke (`wininput`)** when the function is a global command with no MCU message.
3. **Local (Lua only)** when the action is handled entirely inside MIDIMonster (LED
   conventions, mode switches, grid rendering, flashes).

Important: **we do not rely on Cakewalk's default keyboard shortcuts.** In
`Preferences > Keyboard Shortcuts` we will assign a **dedicated, conflict-free keymap**
for every keyboard-only function we need. This makes the integration self-contained,
documented, and independent of Cakewalk version defaults.

`wininput` key combos are emitted as an ordered press/release sequence, for example
`Ctrl+Alt+T` = press `control` -> press `t` -> release `t` -> release `control`.

## Mixer

| Function | Bridge | Message / key | Feedback |
|---|---|---|---|
| Track volume 1-8 | MCU | Pitch Bend ch 0-7 | None (faders not motorized) |
| Track pan 1-8 | MCU | Assign Pan (note 42) + V-pot CC 16-23 | Track Control ring (CC 48-55) |
| Track mute 1-8 | MCU | Mute notes 16-23 | Activator LED (note 50/track) |
| Track solo 1-8 | MCU | Solo notes 8-15 | Solo LED (note 49/track) |
| Track record arm 1-8 | MCU | Rec notes 0-7 | Record Arm LED (note 48/track) |
| Track select 1-8 | MCU | Select notes 24-31 | Track Select LED (note 51/track) |
| Track bank + / - | MCU | Bank Right 47 / Bank Left 46 | Local bank indicator on grid |
| Channel + / - | MCU | Channel Right 49 / Channel Left 48 | Local |
| Master fader | MCU | Assign Track + Master via pitch ch 8 (if mapped) else keystroke | Local Master LED |

## Transport

| Function | Bridge | Message / key | Feedback |
|---|---|---|---|
| Play | MCU | Play note 94 | APC40 Play LED |
| Stop | MCU | Stop note 93 | APC40 Stop LED |
| Record | MCU | Record note 95 | APC40 Record LED |
| Rewind / Forward | MCU | Notes 91 / 92 | Local flash |
| Loop / Cycle toggle | MCU | Cycle note 86 | Grid/utility LED |
| Metronome toggle | MCU | Click note 89 | Metronome LED (note 65) |
| Punch (Drop) toggle | MCU | Drop note 87 | Local flash |
| Nudge | MCU | Nudge note 85 | Local |
| Tap tempo | Keystroke | `Ctrl+Alt+T` | Local flash |
| Auto punch toggle | Keystroke | `Ctrl+Alt+P` | Local flash |

## Navigation

| Function | Bridge | Message / key | Feedback |
|---|---|---|---|
| Marker previous / next | Keystroke | `Ctrl+Alt+Left` / `Ctrl+Alt+Right` | Local |
| Go to start / end | Keystroke | `Ctrl+Alt+Home` / `Ctrl+Alt+End` | Local |
| Up / Down / Left / Right | MCU | Notes 96-99 | Local |
| Zoom out / in | MCU | Zoom note 100 (or keystroke) | Local |
| Scrub | MCU | Scrub note 101 | Local |

## Editing

| Function | Bridge | Message / key | Feedback |
|---|---|---|---|
| Undo | MCU | Undo note 81 | Local flash |
| Redo | Keystroke | `Ctrl+Alt+Z` | Local flash |
| Save | MCU | Save note 80 | Local flash |
| Cancel / Enter | MCU | Notes 82 / 83 | Local flash |
| Quantize selection | Keystroke | `Ctrl+Alt+Q` | Local flash |
| Set loop from selection | Keystroke | `Ctrl+Alt+L` | Grid LED on loop row |
| Selection start / end | Keystroke | `Ctrl+Alt+[` / `Ctrl+Alt+]` | Local |
| Split / delete selected | Keystroke | `Ctrl+Alt+S` / `Ctrl+Alt+Delete` | Local |
| Toggle MIDI overdub | Keystroke | `Ctrl+Alt+O` | Overdub LED (note 64) |
| Toggle record quantize | Keystroke | `Ctrl+Alt+R` | Local flash |

## Views and Screensets

| Function | Bridge | Message / key | Feedback |
|---|---|---|---|
| Toggle Console view | Keystroke | `Ctrl+Alt+C` | Local |
| Toggle Track view | Keystroke | `Ctrl+Alt+K` | Local |
| Show/hide Inspector | Keystroke | `Ctrl+Alt+I` | Local |
| Screenset 1-5 | Keystroke | `Ctrl+Alt+1` .. `Ctrl+Alt+5` | Scene LED on current set |

## Device / Plug-in

| Function | Bridge | Message / key | Feedback |
|---|---|---|---|
| Plug-in parameter 1-8 | MCU | Assign Plug-in (note 43) + V-pot CC 16-23 | Device Control rings (CC 16-23 + style 24-31) |
| Send A/B/C + utility | MCU | Assign Send (note 41) + V-pot | Device Control rings |
| Instrument parameters | MCU | Assign Instrument (note 45) + V-pot | Device Control rings |
| EQ parameters | MCU | Assign EQ (note 44) + V-pot | Device Control rings |
| Focused plug-in bypass | Keystroke | `Ctrl+Alt+B` | Device On/Off LED (note 59) |

> V-pot multiplexing: the same 8 MCU V-pots serve **Mix mode** (Track Control knobs) and
> **Device mode** (Device Control knobs). Mode is a local Lua state switched by the user.

## Instrument / Drum

| Function | Bridge | Message / key | Feedback |
|---|---|---|---|
| Grid pads as note triggers | MCU? No | Route as MIDI notes to a Cakewalk instrument track on a MIDI channel | Local pad LED |
| Keyboard-style playing | Local | Grid pads emit notes | Local |

This is a specialization to be designed in the grid-mode phase; it may require a separate
virtual port if Cakewalk needs the notes on a normal instrument input rather than the MCU
surface port.

## Keymap To Assign in Cakewalk

Before Phase 6, create this keymap in `Preferences > Keyboard Shortcuts`. Adjust any key
that conflicts with an existing binding. Record the final assignments here.

| Command | Proposed key | Notes |
|---|---|---|
| Tap tempo | `Ctrl+Alt+T` | |
| Auto punch | `Ctrl+Alt+P` | |
| Redo | `Ctrl+Alt+Z` | Undo is handled by MCU |
| Quantize | `Ctrl+Alt+Q` | |
| Set loop from selection | `Ctrl+Alt+L` | |
| Selection start | `Ctrl+Alt+[` | |
| Selection end | `Ctrl+Alt+]` | |
| Split | `Ctrl+Alt+S` | |
| MIDI overdub | `Ctrl+Alt+O` | |
| Record quantize | `Ctrl+Alt+R` | |
| Console view | `Ctrl+Alt+C` | |
| Track view | `Ctrl+Alt+K` | |
| Inspector | `Ctrl+Alt+I` | |
| Screensets 1-5 | `Ctrl+Alt+1`..`Ctrl+Alt+5` | |
| Marker previous / next | `Ctrl+Alt+Left` / `Ctrl+Alt+Right` | |
| Go to start / end | `Ctrl+Alt+Home` / `Ctrl+Alt+End` | |
| Plug-in bypass | `Ctrl+Alt+B` | |

## Feedback Principles

- Any LED that implies SONAR/DAW state must come from **MCU feedback**, never from a local
  toggle that can desync.
- Local-only actions use **momentary flashes** (brief blink) rather than persistent LEDs.
- Persistent LEDs are reserved for MCU-backed states: mute, solo, arm, select, transport,
  cycle, click, overdub.
