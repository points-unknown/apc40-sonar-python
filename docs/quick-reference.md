# APC40 Quick Reference

What every APC40 control does, in every mode. This is the user-facing map. For
the MIDI detail behind each action, see [`GENERAL.md`](GENERAL.md) and
[`mcu-mapping.md`](mcu-mapping.md).

> **Keep this current.** Any change to what a control does, and any new mode or Shift
> combo, updates this file in the same change. `src/apc40sonar/engine.py` is the source
> of truth. If the two disagree, this file is wrong.

**Status:** **Live** = works now. *Provisional* = placeholder behavior, will change.
`-` = does nothing yet. The **Planned** column comes from [`TODO.md`](../TODO.md) and is
not built.

Assumes `APC40_MODE=generic` (the default and the only mode tested).

## Modes at a glance

The APC40 has several independent mode layers. Each one changes a different part of the
panel.

| Mode layer | Options | Switch with | Shown by | Default | Affects |
|---|---|---|---|---|---|
| **Knob mode** | Pan, Send A, Send B, Send C | Pan / Send A / Send B / Send C buttons | Lit mode button; ring style (pan vs. fill) | Pan | Track Control knobs + rings |
| **Grid mode** | Meters, Pads | `METERS=on/off` in `.env` (restart) | Grid shows meters or stays dark | Meters | Clip grid, Clip Stop LEDs |
| **Shift layer** | Held / released | Hold **Shift** | Shift LED lit while held | Released | Buttons that have a Shift combo |
| **Cakewalk meters** | Off / On | **Shift + Detail View** | Detail View flashes; grid meters appear or stop | Whatever Cakewalk had | Whether Cakewalk sends meter data |
| *Knob target* (planned) | Mix, Device | Not built | - | Mix | Which knob bank drives the MCU V-pots |
| *Grid modes* (planned) | Meters, step sequencer, drum pads, clip launch | Scene 1-5 (Scene 1 = meters, Scene 2 = sequencer) | Lit Scene LED | Meters | Clip grid, Clip Stop row, Bank Select arrows (sequencer) |

## Track strips (x8, one per Cakewalk track in the current bank)

| Control | Action | LED / display | Status | Planned |
|---|---|---|---|---|
| **Fader** | Track volume | None (faders are not motorized) | **Live** | - |
| **Track Selection** | Select the track in Cakewalk (detected from the knob dump the APC40 sends on each press; needs *Select highlights track* in the Mackie Control preset) | Lit on the selected track, from Cakewalk | **Live** | - |
| **Activator** | Mute on/off (lit = **muted**, from Cakewalk) | From Cakewalk | **Live** | - |
| **Solo** | Solo on/off | From Cakewalk | **Live** | - |
| **Record Arm** | Arm on/off | From Cakewalk | **Live** (track 1 cannot arm: Cakewalk ignores it) | - |
| **Clip Stop** | MCU V-pot push for this strip | Meters mode: red = clip latched. Pads mode: off | **Live** | - |

The Activator LED follows Cakewalk's mute state, so lit means muted. This is the
opposite of Ableton, where lit means active.

## Clip grid (8 x 5) and Scene column

| Control | Meters mode (default) | Pads mode (`METERS=off`) | Planned |
|---|---|---|---|
| **Grid pads** | Press does nothing. Each column is a level meter for its track: rows 5-3 green, 2 yellow, 1 red | Pad lights green while held. No action | Step sequencer (5 lanes x 8 steps, tap cycles velocity color), drum pads, clip launch |
| **Scene 1-5** | *Provisional:* lights its LED, no action (Scene 5 lit at startup) | Same | Grid-mode select (Scene 1 meters, Scene 2 step sequencer, 3-5 reserved) |
| **Stop All Clips** | Transport Stop + clears all clip latches + flashes Stop and Clip Stop LEDs | Stop + flash | - |

Meter scale (row: lit at): 1: 0 dB, 2: -6 dB, 3: -10 dB, 4: -20 dB, 5: -40 dB.

## Knobs

### Track Control knobs (top right, x8)

| Knob mode | Knobs control | Rings show | Status |
|---|---|---|---|
| **Pan** | Track pan | Pan style, centered at startup; then Cakewalk's value | **Live** |
| **Send A** | Level of each track's **send 1** | Fill style, Cakewalk's value | **Live** |
| **Send B** | Level of each track's **send 2** | Fill style, Cakewalk's value | **Live** |
| **Send C** | Level of each track's **send 3** | Fill style, Cakewalk's value | **Live** |

Only the first three sends on a track are reachable. To control a later send, move it into
one of the top three slots in Cakewalk. On a track with fewer sends, the knob stays on its
last send.

### Device Control knobs (bottom right, x8)

| Knob target | Knobs control | Rings show | Status |
|---|---|---|---|
| **Mix** (current; no button switches it yet) | Nothing | Centered, pan style (startup) | `-` |
| *Device* (planned) | Focused plug-in / EQ / instrument parameters | Cakewalk's value and ring style | Planned |
| *C4 surface* (planned) | Plug-in parameters on a second surface, with the Track Control knobs still on pan/sends | C4 ring feedback | Planned |

### Other continuous controls

| Control | Action | Status | Planned |
|---|---|---|---|
| **Master fader** | Master bus volume (set Cakewalk's Mackie *Master Fader* to Bus + Master bus; see setup guide) | **Live** | - |
| **Crossfader** | **Horizontal zoom**: slide right = zoom in, left = zoom out (one step per ~6/127 of travel); **fully left = fit project**. Cakewalk's Track view needs keyboard focus | **Live** | - |
| **Cue Level** | Move the playhead: one step per detent, clockwise = forward. Step size = the *Jog Wheel Resolution* in the Mackie Control preset (Measures by default) | **Live** | Shift + Cue Level for finer steps |
| **Footswitch 1 / 2** | - | `-` | e.g. Play/Stop and Record |

## Knob mode buttons

| Button | Action | LED | Status |
|---|---|---|---|
| **Pan** | Knob mode = Pan (MCU Assign Pan) | Only the active mode button is lit | **Live** |
| **Send A / B / C** | Knob mode = send 1 / 2 / 3 level. Pressing the lit one again re-selects its send | Only the active mode button is lit | **Live** |

## Utility row (under the Device Control knobs)

These buttons work, and their LEDs show, whichever track (or Master) is selected.

| Button | Action | Shift + button | LED | Status | Planned |
|---|---|---|---|---|---|
| **Clip/Track** | - | - | - | `-` | Track/clip context for the Track Control knobs |
| **Device On/Off** | - | - | - | `-` | Focused plug-in bypass, LED shows state |
| **Left arrow** | - | - | - | `-` | Device knob page / parameter bank |
| **Right arrow** | - | - | - | `-` | Device knob page / parameter bank |
| **Detail View** | - | **Toggle Cakewalk meters** on/off | Flashes on toggle | **Live** (Shift only) | Local view toggle or keystroke |
| **Rec Quantize** | - | - | - | `-` | Keystroke `Ctrl+Alt+R` with flash |
| **MIDI Overdub** | - | - | - | `-` | Keystroke `Ctrl+Alt+O`, LED from feedback |
| **Metronome** | **Loop on/off** (Cakewalk's transport loop: playback repeats between the loop markers) | **Metronome during record on/off** (needs F1 in the Mackie Control preset) | Lit while **loop** is on, from Cakewalk. The metronome has no LED | **Live** | - |

## Transport and navigation

| Button | Action | LED | Status | Planned |
|---|---|---|---|---|
| **Play** | Play | From Cakewalk | **Live** | - |
| **Stop** | Stop. **Press twice quickly** (within 0.4 s) to also return to the start of the project | From Cakewalk | **Live** | - |
| **Record** | Record | From Cakewalk | **Live** | - |
| **Bank Select Left / Right** | Move the 8-track window by **8 tracks** (tracks 1-8 -> 9-16 ...) | Flashes on press | **Live** | Page steps in the step sequencer |
| **Shift + Bank Select Left / Right** | Move the 8-track window by **1 track** | Flashes on press | **Live** | - |
| **Bank Select Up / Down** | Cakewalk arrow key Up / Down | - | **Live** | Page lanes in the step sequencer |
| **Shift** | Modifier (hold) | Lit while held | **Live** | More Shift combos (see below) |
| **Tap Tempo** | - (LED flash only) | Flash | *Provisional* | Tap tempo keystroke (needs keystroke bridge) |
| **Nudge + / -** | - | - | `-` | MCU Rewind/Forward or Nudge |
| **Master** (Track Selection) | - (LED stays lit) | Lit | *Provisional* | Select master bus or MCU Flip |

## Shift combos

Hold **Shift** and press the second button. Buttons without a combo do their normal
action while Shift is held.

| Combo | Action | Status |
|---|---|---|
| **Shift + Detail View** | Toggle Cakewalk Mackie Control meters on/off (sends M2 + Name/Value; steps twice if needed) | **Live** |
| **Shift + Bank Select Left / Right** | Move the 8-track window by 1 track | **Live** |
| **Shift + Metronome** | Metronome **during record** on/off (sends Mackie F1; the preset assigns F1 to *Metronome During Record*) | **Live** |

Planned combos from [`TODO.md`](../TODO.md): Shift + Mute = clear all mutes,
Shift + Scene = record-enable scene, other alternate strip actions.

## Startup state

After the lightshow the panel rests in:

- Knob mode **Pan**, Pan button lit, Track Control rings centered
- Device Control rings centered (pan style)
- **Master** and **Scene 5** lit
- Grid dark until Cakewalk sends meters or LED state
