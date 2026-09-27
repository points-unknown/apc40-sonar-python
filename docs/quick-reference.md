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
| **Shift layer** | Off / held / one-shot / locked | Hold, tap, or double-tap **Shift** (see Shift combos) | HUD badge `SHIFT` / `SHIFT 1x` / `SHIFT LOCK` (the APC40's Shift has no LED) | Off | Buttons that have a Shift combo; Shift + Cue Level |
| **Cakewalk meters** | Off / On | **Shift + Detail View** | Detail View flashes; grid meters appear or stop | Whatever Cakewalk had | Whether Cakewalk sends meter data |
| **Mode** | **Tracking**, *Step Sequencer* (not built), **Mixing** | **Scene 1 / 2 / 3** | Lit Scene LED; HUD `Tracking` / `Mixing` | Tracking (always at startup) | Utility-row buttons 58-61 (see Utility row) |
| **Strips** | Tracks, Buses | **Master** button | HUD `Trk 9-16` / `Buses` | Tracks | What the 8 strips (faders, buttons, knobs, meters) control |

## Track strips (x8, one per Cakewalk track in the current bank)

| Control | Action | LED / display | Status | Planned |
|---|---|---|---|---|
| **Fader** | Track volume | None (faders are not motorized) | **Live** | - |
| **Track Selection** | Select the track in Cakewalk (detected from the knob dump the APC40 sends on each press; needs *Select highlights track* in the Mackie Control preset) | Lit on the selected track, from Cakewalk | **Live** | - |
| **Activator** | Mute on/off (lit = **muted**, from Cakewalk) | From Cakewalk | **Live** | - |
| **Solo** | Solo on/off | From Cakewalk | **Live** | - |
| **Record Arm** | Arm on/off | From Cakewalk | **Live** (track 1 cannot arm: Cakewalk ignores it) | - |
| **Clip Stop** | **Reset this track's Track Control knob to its default**: in Pan mode re-centers the pan; in Send A / B / C mode resets that send's level to its default | Meters mode: red = this track clipped (stays lit until **Stop All Clips**). Pads mode: off | **Live** | - |

The Activator LED follows Cakewalk's mute state, so lit means muted. This is the
opposite of Ableton, where lit means active.

## Clip grid (8 x 5) and Scene column

| Control | Meters mode (default) | Pads mode (`METERS=off`) | Planned |
|---|---|---|---|
| **Grid pads** | Press does nothing. Each column is a level meter for its track: rows 5-3 green, 2 yellow, 1 red | Pad lights green while held. No action | Step sequencer (5 lanes x 8 steps, tap cycles velocity color), drum pads, clip launch |
| **Scene 1 / 2 / 3** | **Mode:** 1 = Tracking, 2 = Step Sequencer (*not built yet*), 3 = Mixing. The active mode's Scene LED is lit | Same | Scenes 4-5: free |
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
| **Cue Level** | Move the playhead, clockwise = forward: **1 beat** per detent (`CUE_STEP`). **Shift + Cue Level** = fine: **30 ticks** (1/32 of a beat) per detent (`SHIFT_CUE_STEP`) | **Live** | - |
| **Footswitch 1 / 2** | - | `-` | e.g. Play/Stop and Record |

## Knob mode buttons

| Button | Action | LED | Status |
|---|---|---|---|
| **Pan** | Knob mode = Pan: the Track Control knobs set each track's pan | Only the active mode button is lit | **Live** |
| **Send A / B / C** | Knob mode = send 1 / 2 / 3 level. Pressing the lit one again re-selects its send | Only the active mode button is lit | **Live** |

## Utility row (under the Device Control knobs)

These buttons work, and their LEDs show, whichever track (or Master) is selected. The
row groups **Loop** (62-63) and **Punch** (64-65): the "from selection" setter next to its
on/off toggle.

| Button | Tracking (Scene 1) | Mixing (Scene 3) | Shift + button (both modes) | LED |
|---|---|---|---|---|
| **Clip/Track** (58) | **Undo** | *Reserved for plug-in control (C4)* | Tracking: **Redo** | - |
| **Device On/Off** (59) | **Insert marker** at the playhead | *Reserved (C4)* | - | - |
| **Left / Right arrow** (60/61) | **Previous / next marker** | *Reserved (C4)* | Tracking: **go to selection start / end** | - |
| **Detail View** (62) | **Loop <- selection**: loop points = the current selection | Same | **Cakewalk meters on/off** | Flashes on the meters toggle |
| **Rec Quantize** (63) | **Loop on/off** (playback repeats between the loop points) | Same | - | **Lit while loop is on**, from Cakewalk |
| **MIDI Overdub** (64) | **Punch <- selection**: punch points = the current selection | Same | - | - |
| **Metronome** (65) | **Auto-punch on/off** (Mackie F2 in the preset) | Same | **Metronome during record on/off** (Mackie F1) | None: Cakewalk reports neither state |

Set the selection with **Shift + Nudge - / +** (selection start / end = playhead), then
use Loop <- selection or Punch <- selection.

## Transport and navigation

| Button | Action | LED | Status | Planned |
|---|---|---|---|---|
| **Play** | Play | From Cakewalk | **Live** | - |
| **Stop** | Stop. **Press twice quickly** (within 0.4 s) to also return to the start of the project | From Cakewalk | **Live** | - |
| **Record** | Record | From Cakewalk | **Live** | - |
| **Bank Select Left / Right** | Move the 8-track window by **8 tracks** (tracks 1-8 -> 9-16 ...) | Flashes on press | **Live** | Page steps in the step sequencer |
| **Shift + Bank Select Left / Right** | Move the 8-track window by **1 track** | Flashes on press | **Live** | - |
| **Bank Select Up / Down** | Cakewalk arrow key Up / Down | - | **Live** | Page lanes in the step sequencer |
| **Shift** | Modifier: hold, tap (one-shot) or double-tap (lock); see Shift combos | No LED on the APC40; shown in the HUD | **Live** | - |
| **Tap Tempo** | - (LED flash only) | Flash | *Provisional* | Tap tempo keystroke (needs keystroke bridge) |
| **Nudge - / +** | Move the playhead back / forward **1 measure** per press (`NUDGE_STEP`); **hold** to keep moving (repeats every `NUDGE_REPEAT_MS` after 0.4 s) | - | **Live** | - |
| **Shift + Nudge - / +** | **Selection start / end = playhead** | - | **Live** | - |
| **Master** (Track Selection) | **Toggle the 8 strips between Tracks and Buses** (faders, strip buttons, knobs, meters and Track Selection then act on buses) | The APC40 lights it itself (Track Selection radio group); the HUD shows `Buses` | **Live** | - |

## Shift combos

Three ways to use **Shift**:

| You do | Effect | HUD |
|---|---|---|
| **Hold** Shift and press a button | That press is shifted | `SHIFT` |
| **Tap** Shift | The **next button press** is shifted, then Shift turns off. Any button uses it up, even one without a Shift combo. Expires after 3 s (`SHIFT_ONESHOT_MS`) | `SHIFT 1x` |
| **Double-tap** Shift (within 0.4 s) | **Locked**: every button press is shifted until you tap Shift again | `SHIFT LOCK` |

Knobs (Shift + Cue Level) follow a **held or locked** Shift only; a tapped one-shot waits
for a button. Buttons without a combo do their normal action while shifted.

| Combo | Action | Status |
|---|---|---|
| **Shift + Detail View** | Toggle Cakewalk Mackie Control meters on/off (sends M2 + Name/Value; steps twice if needed) | **Live** |
| **Shift + Bank Select Left / Right** | Move the 8-track window by 1 track | **Live** |
| **Shift + Metronome** | Metronome **during record** on/off (sends Mackie F1; the preset assigns F1 to *Metronome During Record*) | **Live** |
| **Shift + Clip/Track** | Redo (Tracking) | **Live** |
| **Shift + Left / Right arrow** | Go to selection start / end (Tracking) | **Live** |
| **Shift + Nudge - / +** | Selection start / end = playhead | **Live** |

Planned combos from [`TODO.md`](../TODO.md): Shift + Mute = clear all mutes,
Shift + Scene = record-enable scene, other alternate strip actions.

## On-screen HUD

Window that shows what the panel is doing. Opens automatically with the app; turn it
off with `--no-hud` or `HUD=off` in `.env`. Settings (`HUD_POSITION`,
`HUD_LAYOUT`, `HUD_OPACITY`, ...) are listed in [`GENERAL.md`](GENERAL.md#configuration-reference).

| Area | Shows |
|---|---|
| Mode (large, colored) | `PAN` (amber), `SEND A (1)` (cyan), `SEND B (2)` (violet), `SEND C (3)` (green) |
| `Tracking \| Trk 9-16` | Mode, then the tracks on the 8 strips (`Buses` when Master switched them to buses). `Trk ?` until the first Track Selection press; `Trk ~17-24` = estimated after Bank/Channel moves, confirmed by the next select |
| `Sel 12 Vocals` | Selected track number and name |
| Transport | `STOP` / `PLAY` / `REC`, from Cakewalk |
| Time | Bars.beats.ticks (or SMPTE), from Cakewalk |
| `Assign SE` | Cakewalk's assignment display (`PN` = pan, `SE` = sends) |
| Badges | **LOOP**, **ZOOM** (crossfader zoom mode), **METERS** (Cakewalk meters on), **SHIFT** / **SHIFT 1x** / **SHIFT LOCK** (held / one-shot / locked); dim = off |
| Toast (right) | ~1 s message for each action: `Send B`, `Bank >`, `Channel <`, `Go to start`, `Stop all`, `Zoom: fit project`, `Cakewalk meters on`, `Metronome (rec) toggled`, and Cakewalk's `Track 12: "Vocals"` |
| Status line | `no link to apc40sonar` (app not running), `Cakewalk idle` (no feedback lately), red `Strip layout!` (Cakewalk flipped the knobs to one track) |
| Strips (expanded layout) | Per strip: name (a knob's value briefly replaces it, in white), param label or value, R/S/M dots, level meter with clip mark; selected strip highlighted |

Mouse: drag to move; right-click for Compact / Expanded, Opacity, Quit HUD. Clicking it
never takes keyboard focus from Cakewalk.

## Playhead step sizes

Set in `.env` as `<count> <unit>`, unit = `measure`, `beat`, `tick` (1/960 beat) or
`jog` (the Mackie preset's *Jog Wheel Resolution*). Measure and beat steps land on the
grid. The count is 1-48: each unit is one MIDI message, and bigger values
(or spinning very fast) could flood the loopMIDI cable.

| Key | Control | Default |
|---|---|---|
| `CUE_STEP` | Cue Level, per detent | `1 beat` |
| `SHIFT_CUE_STEP` | Shift + Cue Level, per detent | `30 tick` (1/32 beat) |
| `NUDGE_STEP` | Nudge - / +, per press and per repeat while held | `1 measure` |
| `NUDGE_REPEAT_MS` | Repeat interval while Nudge is held | `150` |

## Exit

On Ctrl+C the grid fills red and drains away top to bottom, then the whole panel
goes dark: a dark APC40 means the app is not running.

## Startup state

After the lightshow the panel rests in:

- Knob mode **Pan**, Pan button lit, Track Control rings centered
- Device Control rings centered (pan style)
- **Tracking** mode, **Scene 1** lit; strips on Tracks
- Grid dark until Cakewalk sends meters or LED state
