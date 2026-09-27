# Cakewalk by BandLab Command Matrix

Classifies each integration function by the **bridge** used to trigger it, and its
LED/feedback behavior. This is the **as-built** state; which APC40 button triggers each
function is in [`quick-reference.md`](quick-reference.md), and the mechanics are in
[`GENERAL.md`](GENERAL.md#behavior-notes).

## Bridge Selection Rules

1. **MCU** when Cakewalk's Mackie Control surface exposes the function, directly or via a
   modifier (M1-M4) or navigation mode. Preferred: no setup, and state comes back where
   Cakewalk reports it.
2. **MCU F-key** when the function is a Cakewalk command with no Mackie button: the
   Mackie Control preset assigns the command to F1-F8 and the app presses the F-key.
   Cakewalk reports no state for these.
3. **Keystroke** only when neither works (not built; see the end of this page).
4. **Local (engine only)** for LED conventions, mode switches, grid rendering and flashes.

Numbers are Cakewalk's own *Cakewalk/SONAR Mode* button table, which differs from the
standard MCU labels in places (89 = Loop, 90 = Home, 70-73 = M1-M4, 76 = Track,
80 = Aux, 82 = Undo, 83 = Redo, 84-87 = Marker / Loop / Select / Punch navigation).
Buttons Cakewalk acts on at release (modifiers, Loop, cursor keys, Rewind/Forward) are
released with Note On velocity 0, because Cakewalk drops real Note Offs.

## Mixer

| Function | Bridge | Message | Feedback |
|---|---|---|---|
| Track / bus volume 1-8 | MCU | Pitch Bend ch 0-7 | None (faders not motorized) |
| Master bus volume | MCU | Pitch Bend ch 8 (preset: Master Fader = Bus + Master bus) | None |
| Pan 1-8 | MCU | Assign Pan 42 (only when switching) + V-pot CC 16-23 | Track Control rings |
| Send 1-3 level | MCU | Assign Send 41 + Edit 51 + M1 + Bank/Channel moves to parameter 1 / 5 / 9 | Track Control rings |
| Reset knob parameter | MCU | V-pot push 32-39 | Ring |
| Mute / Solo / Rec arm 1-8 | MCU | Notes 16-23 / 8-15 / 0-7 | Strip LEDs |
| Select 1-8 | MCU | Select 24-31 (preset: *Select highlights track*) | Track Select LED |
| Bank + / - (8 strips) | MCU | Bank Right 47 / Left 46 | HUD |
| Channel + / - (1 strip) | MCU | Channel Right 49 / Left 48 | HUD |
| Strips = tracks / buses | MCU | Track 76 / Aux 80 | Track/Aux LEDs (tracked), HUD |
| Level meters | MCU | Channel pressure (preset: *Meters* on, or M2 + Name/Value 52) | Clip grid |

## Transport and playhead

| Function | Bridge | Message | Feedback |
|---|---|---|---|
| Play / Stop / Record | MCU | 94 / 93 / 95 | Transport LEDs |
| Go to start | MCU | Home 90 | - |
| Move playhead (measure / beat / tick) | MCU | Jog CC 60 with M1 / M2 / M3 held | - |
| Loop on/off | MCU | Loop 89 | Loop LED 89 |
| Auto-punch on/off | MCU F-key | F2 55 (preset) | None |
| Metronome during record | MCU F-key | F1 54 (preset) | None |
| Tap tempo | - | Not on Mackie Control; keystroke candidate | - |

## Markers, selection, loop and punch points

| Function | Bridge | Message |
|---|---|---|
| Insert marker | MCU | M1 + Marker 84 |
| Previous / next marker | MCU | Marker navigation 84 + Rewind 91 / Forward 92 |
| Selection start / end = playhead | MCU | Select navigation 86 + M1 + Rewind / Forward |
| Go to selection start / end | MCU | Select navigation 86 + Rewind / Forward |
| Loop points = selection | MCU | M2 + Loop navigation 85 |
| Punch points = selection | MCU | M2 + Punch navigation 87 |

Navigation modes toggle (pressing the active one returns to normal); the engine follows
their LEDs and always returns to normal navigation.

## Editing and views

| Function | Bridge | Message |
|---|---|---|
| Undo / Redo | MCU | 82 / 83 |
| Timeline zoom in / out | MCU | Zoom 100 + Cursor Right / Left |
| Fit project | MCU | Zoom 100 + M4 + Cursor Right |
| Cursor keys | MCU | 96-99 |

## Plug-ins (planned: Mixing mode)

The main Mackie surface has one row of 8 V-pots with one assignment, so plug-in control on
the Device Control knobs uses a **second surface**, Cakewalk's *Mackie Control C4*, which
keeps its own assignment and follows the selected track or bus. Parameter paging, next
plug-in and bypass come from the C4. See [`plans/c4-surface-plan.md`](../plans/c4-surface-plan.md).

## Instrument / drum (planned: Step Sequencer)

Grid pads as note triggers, and the Scene 2 step sequencer, send notes on a separate
loopMIDI cable into a Cakewalk MIDI track, never on the Mackie Control ports. See the step
sequencer section of [`TODO.md`](../TODO.md).

## Keystroke bridge (not built)

Most functions first planned as keystrokes turned out to be reachable over Mackie
Control (above). What would still need a keystroke:

| Command | Notes |
|---|---|
| Tap tempo | Tap Tempo button (99) only flashes its LED today |
| Quantize, split, delete | Free buttons if wanted later |
| MIDI overdub, record quantize | Their APC40 buttons are now Punch <- selection and Loop on/off |

If built: an input-injection dependency (`pydirectinput` or `pynput`), a dedicated,
conflict-free keymap assigned in `Preferences > Keyboard Shortcuts` (never rely on
Cakewalk's defaults), and a `keys` module emitting ordered press/release sequences.

## Feedback Principles

- Any LED that implies Cakewalk state must come from **MCU feedback**, never from a local
  toggle that can desync.
- Local-only actions use **momentary flashes** or HUD toasts rather than persistent LEDs.
- Persistent LEDs are reserved for MCU-backed states: mute, solo, arm, select, transport,
  loop, and the knob mode buttons.
- F-key commands (auto-punch, metronome) have no state feedback; the HUD can only echo
  the press.
