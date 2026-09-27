# apc40sonar - General / Developer Reference

Architecture, configuration, behavior notes, and internals for the APC40 to Cakewalk
integration. The [README](../README.md) is the quickstart; this document is the detail
that does not belong there.

> **Documentation policy:** keep [`README.md`](../README.md) big-picture only (what the
> project is, quickstart, tests, troubleshooting, dev setup). Put all architecture,
> configuration, behavior, and internals **here**, and update this file when behavior
> changes. The remaining work and ideas live in [`TODO.md`](../TODO.md). Any change to
> what a control does also updates [`quick-reference.md`](quick-reference.md), the
> per-mode button map.

Protocol references live beside this file:

- [`quick-reference.md`](quick-reference.md) - what every APC40 control does in each mode
- [`apc40-communications-protocol.md`](apc40-communications-protocol.md) - Akai APC40 protocol
- [`apc40-output-reference.md`](apc40-output-reference.md) - APC40 LED/ring/color authority
- [`mcu-mapping.md`](mcu-mapping.md) - Mackie Control messages and the APC40 mapping
- [`mackie_control_protocol.md`](mackie_control_protocol.md) - deep MCU reference
- [`cakewalk-command-matrix.md`](cakewalk-command-matrix.md) - MCU vs keystroke bridging
- [`setup-loopmidi-and-cakewalk.md`](setup-loopmidi-and-cakewalk.md) - step-by-step install, loopMIDI, and Cakewalk setup

## Architecture

The app is a standalone Python process that owns all three MIDI ports directly. It
replaces the earlier MIDIMonster + Lua prototype; the protocol work is reused, but the
transport is owned so the app can send exactly the bytes it intends.

```text
APC40 hardware <--rtmidi--> engine <--rtmidi--> APC40-IN  --> Cakewalk (Mackie Control In)
                              ^                                  |
                              '-------- APC40-OUT <------------'  (Mackie Control Out)
```

- One process owns the physical `Akai APC40` (read + write).
- The same process owns `APC40-IN` (write) and `APC40-OUT` (read).
- Cakewalk never sees the APC40 directly; it sees a standard Mackie Control surface.
- No other application may open these ports while the app runs.

### Modules

| Module | Responsibility |
|---|---|
| `midi_io` | The only module that touches python-rtmidi. Port enumeration, name resolution, open helpers |
| `config` | Loads settings from `.env` / environment; no port names are hard-coded |
| `apc40` | APC40 constants, message builders, the Type 0 introduction SysEx, and the cached/forced LED+ring renderer |
| `mcu` | Mackie Control encoders (real Note On/Off, 14-bit faders, relative V-pot deltas, packed ring bytes) and decoders |
| `engine` | State machine and translation: faders, strip buttons, transport, clip grid, knob modes, feedback rendering, level meters, flashes |
| `lightshow` | The startup lightshow (lights every host-addressable control, then blacks out) |
| `mcu_display` | Decoders for Cakewalk's MCU LCD SysEx and 7-segment timecode/assignment CCs (HUD only) |
| `hud_state` | `HudSnapshot`, the immutable engine state the HUD shows |
| `hud_link` | The only HUD I/O: UDP JSON publisher/receiver on 127.0.0.1 and the HUD child-process supervisor |
| `hud_view` | Pure HUD view model: snapshot to strings/colors, toast timing, window placement |
| `hud` | The tkinter HUD window, run as its own process (`python -m apc40sonar.hud`) |
| `logging_setup` | Rotating file log plus console warnings |
| `__main__` | CLI, port opening, the event loop, and signal/error handling |

## Configuration reference

Port names and options live in `.env` at the repository root (copy
[`.env.example`](../.env.example)). The file is gitignored; the template is tracked.

| Key | Default | Meaning |
|---|---|---|
| `APC40_PORT` | `Akai APC40` | Physical controller (read + write) |
| `MCU_OUT_PORT` | `APC40-IN` | App to Cakewalk (Mackie Control In Port) |
| `MCU_IN_PORT` | `APC40-OUT` | Cakewalk to app (Mackie Control Out Port) |
| `APC40_CLIENT_NAME` | `apc40sonar` | Name this app shows to WinMM |
| `APC40_MODE` | `generic` | APC40 operating mode: `generic`, `ableton`, `alt-ableton` |
| `KNOB_STEP_LIMIT` | `3` | Max V-pot steps emitted per knob event |
| `KNOB_NOISE_THRESHOLD` | `4` | Knob steps larger than this are ignored (0 disables) |
| `METERS` | `on` | Track level meters on the clip grid and clip latch on Clip Stop (`on`/`off`) |
| `METER_DECAY_MS` | `300` | Meter fall time per level, like a real MCU |
| `ZOOM_STEP_UNITS` | `6` | Crossfader travel (0-127 scale) per zoom step; lower = faster zoom |
| `ZOOM_IDLE_MS` | `300` | Leave Cakewalk's zoom mode this long after the crossfader stops |
| `CUE_STEP` | `1 beat` | Playhead move per Cue Level detent (`<count> <unit>`, see below) |
| `SHIFT_CUE_STEP` | `30 tick` | Playhead move per Cue Level detent with Shift held |
| `NUDGE_STEP` | `1 measure` | Playhead move per Nudge press (and per repeat while held) |
| `NUDGE_REPEAT_MS` | `150` | Repeat interval while Nudge is held (after a 0.4 s hold) |
| `SHIFT_ONESHOT_MS` | `3000` | A tapped (one-shot) Shift expires after this long |
| `HUD` | `on` | Launch the on-screen HUD (`--hud` / `--no-hud` override) |
| `HUD_PORT` | `47040` | UDP port on 127.0.0.1 between the app and the HUD |
| `HUD_POSITION` | `top-right` | `top-left` / `top-right` / `bottom-left` / `bottom-right`, or `x,y` on the monitor |
| `HUD_MONITOR` | `0` | Monitor index for placement (0 = primary) |
| `HUD_OPACITY` | `0.85` | Window alpha, 0.2-1.0 |
| `HUD_TOPMOST` | `on` | Keep the HUD above other windows |
| `HUD_CLICK_THROUGH` | `off` | Mouse passes through the HUD (it can then only be moved via `HUD_POSITION`) |
| `HUD_LAYOUT` | `compact` | `compact` (mode, transport, badges, toasts) or `expanded` (adds the 8 strips) |
| `HUD_TOAST_MS` | `1200` | How long an action toast stays visible |
| `HUD_LCD` | `on` | Receive Cakewalk's LCD SysEx on the MCU input (track names, values, messages) |

Lookup order for the file: the path in `APC40SONAR_ENV`, then `.env`, then `config/.env`.
Process-environment values override the file, so a one-off run can use
`set APC40_PORT=...` without editing anything.

## Runtime modes

| Command | Behavior |
|---|---|
| `uv run apc40sonar --list-ports` | Print ports and verify the configured names resolve; exit non-zero if any is missing |
| `uv run apc40sonar --lightshow` | Play the show, render the ready state, exit (APC40 only; no loopMIDI needed) |
| `uv run apc40sonar` | Full engine: lightshow, then the APC40 <-> Cakewalk event loop |
| `uv run apc40sonar --no-show` | Skip the lightshow |
| `uv run apc40sonar --monitor` | Also print incoming and outgoing MIDI (`apc:`/`mcu:` in, `apc>`/`mcu>` out) |
| `uv run apc40sonar --no-hud` | Run without the on-screen HUD (`--hud` overrides `HUD=off`) |
| `uv run python -m apc40sonar.hud` | Start a HUD by hand and attach it to a running app |
| `uv run apc40sonar --env PATH` | Use an explicit `.env` file |

`run-apc40-sonar.cmd` is a launcher that finds `uv` on `PATH` or falls back to
`%USERPROFILE%\.local\bin\uv.exe`.

## Behavior notes

### Mixer mapping (APC40 to MCU)

| APC40 control | MCU message |
|---|---|
| Fader 1-8 (CC 7, ch0-7) | Pitch Bend ch0-7, 7-bit scaled to 14-bit |
| Master fader (CC 14, any channel) | Pitch Bend ch8 (Cakewalk master fader; see below) |
| Track Control knob 1-8 (CC 48-55) | V-pot rotation CC 16-23, relative |
| Record Arm (note 48) | Rec notes 0-7 |
| Solo (note 49) | Solo notes 8-15 |
| Activator/Mute (note 50) | Mute notes 16-23 |
| Track Select (note 51) | Select notes 24-31 |
| Clip Stop (note 52) | V-pot push notes 32-39 |
| Play / Stop / Record (91/92/93) | Play 94 / Stop 93 / Record 95 |
| Nudge - / + (101/100) | Jog CC 60 x `NUDGE_STEP`, repeated by the engine while held (see *Playhead steps*) |
| Bank Select Left / Right (97/96) | Bank Left 46 / Bank Right 47 (8-track window moves by 8) |
| Shift + Bank Select Left / Right | Channel Left 48 / Channel Right 49 (window moves by 1) |
| Bank Select Up / Down (94/95) | Cursor Up 96 / Down 97 (Cakewalk treats these as arrow keys) |
| Rec Quantize (63, bank channel 0-8) | Note 89: Cakewalk's **Loop on/off** (see below); LED 89 -> Rec Quantize LED |
| Metronome (65) | Mackie F2 (55): auto-punch (preset); Shift = F1 (54): metronome during record |
| Master (80, or its bank's knob dump) | Cakewalk Track 76 / Aux 80: strips show tracks / buses (toggle, from their LEDs) |
| Scene 1 / 2 / 3 (82-84) | Mode: Tracking / Step Sequencer (not built) / Mixing |
| Stop (92), pressed twice within 0.4 s | Stop 93, then Cakewalk **Home** 90 (go to start) on the second press |
| Crossfader (CC 15, absolute) | Horizontal zoom via MCU Zoom 100 + Cursor Left/Right (see below) |
| Cue Level (CC 47, relative) | Jog CC 60 x `CUE_STEP` per detent (`SHIFT_CUE_STEP` with Shift held), max 4 detents per event |
| Pan / Send A / Send B / Send C (87-90) | Assign Pan 42 / Assign Send 41 (only when switching), then send 1/2/3 selection (see below) + ring style |

**Cakewalk mode renames some MCU buttons.** With the *Cakewalk/SONAR Mode* protocol,
Cakewalk's Mackie Control uses its own button table, and a few notes differ from the
standard MCU labels: note 89 (standard *Click*) is **Loop on/off** (LED 89 shows loop
state). Loop toggles on **release**, and Cakewalk only passes status 0x90 to its buttons,
so the engine releases it with Note On velocity 0; a real Note Off (0x80) is dropped and
loop never toggles. The APC40's Rec Quantize button (Loop on/off) is momentary and switches its own LED
off on release; during playback Cakewalk's loop LED can arrive while the button is still
held, so the engine re-sends the last loop state on every Rec Quantize release. Note 90
(standard *Solo*) is **Home** (go to
start), and LED 86 (standard *Cycle*) is the Select-navigation mode. There is **no
metronome button**; the metronome is reached through an F-key (54-61) assigned to a
Cakewalk command on the surface page.

### Playhead steps

One Mackie jog message (CC 60, `0x01` forward / `0x41` back; Cakewalk reads only the
direction) moves the now time by one unit, chosen by the modifier held with it
(`NudgeTimeCursor`): **M1 = 1 measure**, **M2 = 1 beat** (both snap to the grid),
**M3 = 1 tick** (1/960 beat at Cakewalk's default), none = the preset's *Jog Wheel
Resolution*. A step setting `<count> <unit>` is therefore sent as the modifier press,
*count* jog messages, and the modifier release (Note On velocity 0). `CUE_STEP`,
`SHIFT_CUE_STEP` and `NUDGE_STEP` use this; a held Nudge repeats `NUDGE_STEP` every
`NUDGE_REPEAT_MS` after 0.4 s. Each unit is one MIDI message, so counts are capped at 48
and the engine sends at most `JOG_BUDGET_PER_FRAME` (48) jog messages per 20 ms frame,
dropping the excess. Without that, a fast spin with a fine tick step (it was 120 ticks)
flooded `APC40-IN` and loopMIDI's flood protection disabled the cable until loopMIDI
was restarted.

**Cursor keys need a visible release.** Cakewalk auto-repeats a cursor key (Up/Down/
Left/Right, 96-99) 0.4 s after the press and then every 50-500 ms until it sees the
release. It drops real Note Offs, so the engine releases cursor keys with Note On
velocity 0, like Loop; otherwise one Bank Select Up/Down press would keep repeating.

### Knob modes: Pan and Send A / B / C

Cakewalk's assignment buttons (Pan 42, Send 41, ...) have a trap: pressing the one that is
**already active** flips the knobs between *one parameter across 8 tracks* (what the APC40
wants) and *8 parameters of the selected track* (channel strip). That layout is shared by
every assignment, never reset, and never reported back. So the engine:

- tracks Cakewalk's assignment from its Pan/Send LEDs (notes 42/41) and presses an
  assignment button **only when switching**;
- when the assignment is unknown (startup), presses **Dynamics** (45, unused here) first,
  so the Pan press is always a switch, never a re-press.

Send A / B / C choose the send with Cakewalk's **Edit** mode (note 51, tracked from its
LED). Cakewalk lists 4 parameters per send and the knobs start on send 1's level
(parameter 1), so sends 1 / 2 / 3 are parameters 1 / 5 / 9. The engine turns Edit on,
presses M1 + Bank Left (go to the first parameter), steps with Bank Right (+8) and Channel
Right (+1), then turns Edit off. Pressing a lit Send button again re-runs the selection.
Cakewalk clamps at a track's last parameter, so a track with fewer sends stays on its last
one. Only sends 1-3 are reachable; reorder sends in Cakewalk to control others.

The layout is not saved with the project; Cakewalk starts every session in the 8-track
layout. If the knobs ever control one track's parameters instead of 8 tracks (for example
left over from an older build that re-pressed the assignment), restart Cakewalk.

### Modes and the Tracking utility row

The Scene buttons select the operating mode (`Engine.mode`, always `tracking` at start);
the mode's Scene LED is lit and re-sent on every Scene release (the APC40 may blank it
locally). Only utility-row buttons 58-61 depend on the mode: in **Tracking** they are
editing and navigation, in **Mixing** they are reserved for C4 plug-in control and do
nothing yet. 62-65, Nudge and everything else work the same in both.

Tracking uses Cakewalk's own Mackie buttons (Cakewalk mode numbers):

| APC40 | Cakewalk Mackie |
|---|---|
| Clip/Track / Shift | Undo 82 / Redo 83 |
| Device On/Off | M1 + Marker 84 (insert marker) |
| Left / Right arrow | Marker navigation 84 + Rewind 91 / Forward 92 (previous / next marker) |
| Shift + Left / Right | Select navigation 86 + Rewind / Forward (go to selection from / thru) |
| Shift + Nudge - / + | Select navigation 86 + M1 + Rewind / Forward (selection from / thru = now) |
| Detail View | M2 + Loop 85 (loop from selection) |
| MIDI Overdub | M2 + Punch 87 (punch from selection) |

Navigation buttons (Marker 84, Loop 85, Select 86, Punch 87) enter their mode, or return
to normal navigation when that mode is already active (`OnSelectNavigationMode`). The
engine follows Cakewalk's navigation LEDs 84-87, enters the mode only if needed, runs the
Rewind/Forward press, and presses the button again to return to normal, so Nudge and the
other buttons never inherit a navigation mode. Rewind/Forward are released with Note On
velocity 0: in marker navigation Cakewalk repeats them until it sees the release.

**Master** toggles the strips between tracks and buses with Cakewalk's Track 76 / Aux 80
buttons, following their LEDs. In Generic Mode Master is part of the Track Selection radio
group, so it may arrive as note 80 or only as the Master bank's knob dump (channel 8); a
dump within `MASTER_DEDUP_FRAMES` of a Master note is the same press. The APC40 lights
Master itself, so the HUD shows Tracks/Buses instead of the LED.

### Crossfader zoom

The crossfader zooms Cakewalk's timeline horizontally, entirely over Mackie Control:

- With Cakewalk's **zoom mode** on (MCU Zoom, note 100), Cursor Left/Right become
  Ctrl+Left / Ctrl+Right (zoom out / in) and Zoom + M4 + Right is *fit project to window*.
  These are keystrokes Cakewalk sends to itself, so they act on the view that has
  keyboard focus (the Track view).
- The slider's movement is accumulated; every `ZOOM_STEP_UNITS` (default 6 of 0-127) is
  one zoom step, right = in, left = out, at most 4 steps per message. The first reading
  after startup only sets the baseline.
- The engine turns zoom mode on at the first step and off again after `ZOOM_IDLE_MS`
  (default 300 ms) without movement, so the arrow buttons return to normal. It follows
  Cakewalk's Zoom LED: if zoom mode was already on (turned on some other way) the
  crossfader uses it and leaves it on.
- At the far left (value 0-1) it sends one *fit project* (Zoom + M4 + Right; M4 is
  released with Note On velocity 0). It re-arms once the slider is
  back above 10, so end-of-travel jitter does not repeat it. After a fit, moving right
  zooms in step by step, so the slider position roughly tracks the zoom level.
- No preset setting is needed (the earlier plan used an F2 assignment; Cakewalk's
  built-in Zoom + M4 + Right replaces it).

Cakewalk's master fader defaults to strip type *Master*, which is the hardware-output
strip, not the project's Master **bus**. Set the surface's **Master Fader** group to
**Bus** + your Master bus (Utilities > Mackie Control); it is saved per project. Cakewalk
echoes master fader moves back as Pitch Bend ch8, which the engine ignores like all fader
feedback.

Feedback renders MCU notes 0-31 to the strip LEDs, transport/Click/Cycle to the
corresponding APC40 LEDs, MCU CC 48-55 to the ring banks, and MCU channel meters to the
clip grid (see below). Fader feedback is ignored (the APC40 faders are not motorized).

### Level meters

Cakewalk sends each strip's level as MCU Channel Pressure `D0 <sv>` (`s` strip 0-7, `v`
level 0-13; `E`/`F` set/clear overload). With `METERS=on` (default) each clip-grid column
is a bottom-up meter for its track, and the Clip Stop LED is that track's clip indicator:

| Grid row | Lit at MCU level | Approx. | Color |
|---|---|---|---|
| 1 (top) | 12+ | 0 dB | red |
| 2 | 9+ | -6 dB | yellow |
| 3 | 7+ | -10 dB | green |
| 4 | 5+ | -20 dB | green |
| 5 (bottom) | 3+ | -40 dB | green |

- A real MCU decays its meters locally and the host relies on that, so the engine drops
  one level every `METER_DECAY_MS` (serviced by `tick()`); a new value restarts the timer.
- The Clip Stop LED turns red on the host overload flag **or** on level 13 (not every host
  sends the flag) and stays latched until the host clears it or **Stop All Clips** is
  pressed. Clip Stop still sends V-pot push when pressed.
- While meters are on the grid pads do not light when pressed (the grid is a display).
  With `METERS=off` the pads go back to momentary green and nothing meter-related is drawn.
- LED writes are de-duplicated, so a steady signal costs no traffic; only segment changes
  are sent.
- **Cakewalk sends no meters by default.** Its Mackie Control surface starts with
  *Meters: Off* and skips meter output entirely in that state. Set **Meters** to *Signal
  LEDs* (or *Signal LEDs + Meters*) on the surface property page (**Utilities > Mackie
  Control**); the choice is stored in the project. Cakewalk scales its meter as
  `level = peak * 13`, and `MackieControl.ini` `[Meters] UpdatePeriod` sets how many
  refreshes pass between updates.
- **Shift + Detail View toggles Cakewalk's meters** from the APC40. It sends Cakewalk's
  own M2 (Option, note 71) + Name/Value (note 52) combo, which steps *Off -> Signal LEDs
  -> Signal LEDs + Meters -> Off*. While meters are on Cakewalk streams every strip on
  each refresh (silence included), so the app treats "meter traffic in the last 0.5 s"
  as on. Turning off sends one step, waits 0.5 s, and sends a second step if meters are
  still streaming (it was at *Signal LEDs*), so one press is always a clean on/off. The
  Detail View LED flashes to acknowledge; a second press while it settles is ignored.
- M2 is released with **Note On velocity 0**: Cakewalk only dispatches status 0x90 to its
  buttons, so a real Note Off would leave Option stuck on. The combo needs the surface's
  default **Mackie Control** protocol; with *Universal* Cakewalk drops notes 70-73. If a
  toggle-on produces no meters the app logs a warning saying so.

### Shift layer

Shift (note 98) is tracked locally and sends nothing to Cakewalk; the APC40's Shift has
no LED, so the HUD shows it. `Engine.shift_state` is `off`, `held`, `once` or `locked`:

- **Held**: a button pressed while Shift is down is shifted, and releasing Shift then
  does nothing (it was a combo, not a tap).
- **Tap** (press and release with no button in between) arms a **one-shot**: the next
  button press is shifted and clears it, whatever the button. It expires after
  `SHIFT_ONESHOT_MS` (default 3000).
- A second tap within 0.4 s **locks** Shift until the next tap; a slower second tap
  cancels the one-shot.
- Knobs (`Engine.knob_shift`, used by Shift + Cue Level) see only held or locked Shift,
  so a stray knob turn never uses up a one-shot.

Mapped Shift combos replace the button's normal action; unmapped ones behave as if
Shift were not active.

| Combo | Action |
|---|---|
| Shift + Detail View (62) | Toggle Cakewalk's Mackie Control meters (see above) |
| Shift + Bank Select Left / Right | Move the strip window by one track (MCU Channel Left/Right) |
| Shift + Metronome (65) | MCU F1 (54): the preset assigns it to Cakewalk's *Metronome During Record* |

### Latching buttons

In Generic Mode the Record Arm / Solo / Activator buttons **latch**: the device sends
Note On when the button turns on and Note Off when it turns off (it does not send an
immediate off on release). Each edge must emit exactly one MCU button press, or Cakewalk
ignores the "off" edge and the button appears to need two presses to clear. Track Select
is a radio group, so only its "on" edge acts; Clip Stop, transport, navigation and
Metronome are momentary and act on the press edge.

The first four utility buttons (Clip/Track, Device On/Off, Left/Right arrow, 58-61)
latch the same way: the APC40 lights its own LED and sends Note On on one press, then
turns it off and sends Note Off on the next. The engine treats **both edges as a press**
of their one-shot action (undo, marker, ...) and forces the LED back off, so they stay
dark and act on every press. The other four (62-65) are momentary.

### Device Control banks

The APC40 keeps nine Device Control banks (Tracks 1-8 and Master), chosen by the Track
Selection / Master buttons. The Device Control button row (notes 58-65: Clip/Track,
Device On/Off, arrows, Detail View, Rec Quantize, Overdub, Metronome) and the Device
Control knobs (CC 16-23) report on the **selected bank's channel**: 0-7, or 8 for
Master. The engine accepts them on any of channels 0-8 and treats the row as one set of
global buttons. Their LEDs are stored per bank, so the renderer writes utility-row LEDs to
all nine channels and they stay visible whichever bank is selected.

The Device rings and knob positions are per bank too. The engine tracks the **current
bank** from the channel of the latest Device knob or utility-row message, writes Device
ring feedback to that bank's channel, and keeps a separate knob baseline per bank, so the
position dump the APC40 sends on a bank switch matches that bank's last values instead of
reading as knob movement. The startup baseline centers the Device rings on all nine
banks.

### Track Selection in Generic Mode

The Track Selection buttons send **no note** in Generic Mode. They are a local radio group:
the APC40 lights the pressed button itself, switches its Device Control bank, and
transmits all eight Device knob positions (CC 16-23) on that track's channel. The engine
collects Device knob messages into a burst; once no more arrive for
`KNOB_DUMP_QUIET_FRAMES` (2 frames, ~40 ms), a burst holding all eight knobs on exactly
**one** channel 0-7 becomes an MCU Select for that strip. A single knob turn never sends
all eight, the Master button (channel 8) selects no track, and a burst spanning several
channels (a whole-surface dump) is ignored. Cakewalk only selects the track itself with
*Select highlights track* checked in the Mackie Control preset.

### Knob smoothing

The Track Control and Device Control knobs are endless encoders whose absolute value is
re-referenced whenever the host writes their LED ring (Cakewalk feedback does this on
every refresh). That produces an occasional large step that is not physical movement.
The engine computes a modular difference (so 0/127 wraparound is a small step), ignores
steps larger than `KNOB_NOISE_THRESHOLD`, and clamps what remains to `KNOB_STEP_LIMIT`.
The knobs are detented and normally report one step per detent, so the defaults remove the
re-reference jumps without affecting intentional turns.

### Ring translation

MCU ring mode maps to an APC40 ring style: single to 1, pan to 3, volume/centered to 2.
The MCU ring value (0-11) scales to an APC40 position: `round(value / 11 * 127)`. Pan
style centers at 63/64; the engine centers the rings when Pan mode is selected so the
display matches a centered pan until real feedback arrives.

### Startup

Before any other APC40-specific message the app sends the Type 0 introduction
(`F0 47 7F 73 60 00 04 <mode> <major> <minor> <bugfix> F7`) to select the configured
operating mode. The lightshow then lights every host-addressable control and blacks out,
and `render_baseline()` leaves the surface ready: Pan mode, both ring banks centered,
Master and Scene 5 lit. Stop All Clips (note 81) has no host-addressable LED and is not
used; it is acknowledged by flashing the Stop LED and the eight Clip Stop LEDs.

### On-screen HUD

The APC40 has no display, so an always-on-top window shows what the controller is
doing and what Cakewalk reports. It is on by default; turn it off with `HUD=off` or
`--no-hud`.
Design notes: [`plans/hud-concept.md`](../plans/hud-concept.md).

- **Compact:** knob mode (`PAN` / `SEND A (1)` ...), strip window (`Trk 9-16`),
  selected track, transport, BBT/SMPTE time, the Cakewalk assignment display, badges
  (Loop, Zoom mode, Cakewalk meters, Shift), a toast for actions with no LED feedback
  (`Bank >`, `Send B`, `Go to start`, `Metronome (rec) toggled`, Cakewalk's
  `Track 12: "Vocals"` messages ...), and a status line (`no link`, `Cakewalk idle`,
  `Strip layout!` when the assignment dot shows Cakewalk flipped the knobs).
- **Expanded** adds the 8 strips: LCD name (a V-pot value peek briefly replaces it,
  in white), lower LCD line (param label or value, per Cakewalk's Name/Value state),
  R/S/M dots, a level meter with clip marker, and the selected strip highlighted.
- Drag with the left mouse button; right-click for layout, opacity and Quit. The window
  never takes keyboard focus from Cakewalk.

How it works: the engine keeps a pure `HudSnapshot` (`Engine.hud_snapshot()`); the run
loop sends it as one UDP JSON datagram to 127.0.0.1 when it changed, at most every
50 ms, plus a 1 s heartbeat. The HUD is a separate process (launched with
`CREATE_NO_WINDOW`, respawned up to 3 times, closed with the app), so a HUD crash,
hang or window drag can never stall MIDI. `HUD_LCD=on` stops ignoring SysEx on the
MCU input only.

Cakewalk never reports the strip-window offset. The HUD derives it from a track select:
Cakewalk lights the strip's Select LED and shows `Track N: "name"`, so offset =
N - 1 - strip. Bank/Channel presses shift it provisionally (shown as `Trk ~9-16`) until
the next select confirms it; before the first select it shows `Trk ?`. The Metronome
(F1) toggle has no Cakewalk feedback, so the HUD can only echo that it was pressed.


### Exit

On Ctrl+C the app plays a short exit animation (`lightshow.goodbye`: the grid fills
red, then drains top to bottom) and leaves every LED and ring off, so a dark panel means
the app is not running. A failure while drawing it is logged and does not block exit.

## Logging

Run modes write a rotating log to `logs/apc40-sonar.log` (gitignored, 1 MB x 3): port
opens, the selected mode, the lightshow, and any per-message handler errors. Warnings and
errors are also mirrored to the console. A handler that raises is logged and skipped so a
single bad event cannot stall the loop.

## Known limitations

- **Track 1 Record Arm.** Cakewalk's Mackie Control ignores MCU Rec note 0 (the first
  strip), so APC Track 1 Record Arm cannot arm Cakewalk track 1 over the surface; arm that
  track with the mouse. Tracks 2-8 are normal. A Cakewalk Remote Control binding was tried
  as a workaround but it conflicts with the Mackie Control surface and disabled the other
  track buttons, so it was reverted.
- **Stop All Clips** has no host-addressable LED on the original APC40 (see above).
- **Faders** are not motorized, so Cakewalk fader feedback cannot be displayed.
- **Select/Mute/Solo/Rec echo** and Cakewalk's exact V-pot default assignment still need
  confirmation across project views; see the open items in [`mcu-mapping.md`](mcu-mapping.md).

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `cannot open APC40 port` | Another app holds the port | Close MIDI-OX, Cakewalk, Ableton, etc., or uncheck `Akai APC40` in Cakewalk's MIDI Devices |
| `APC40-IN` / `APC40-OUT` missing | loopMIDI not running, or ports not registered | Start loopMIDI; re-add the ports; reboot after a fresh loopMIDI install; see [`setup-loopmidi-and-cakewalk.md`](setup-loopmidi-and-cakewalk.md) |
| A button toggles twice per press | APC40 also configured directly in Cakewalk | Remove any direct APC40 device/surface in Cakewalk |
| LEDs flicker continuously | Feedback loop | Ensure only this app routes back to the APC40; never pass MCU feedback straight through |
| Controls do nothing but LEDs work | Surface not added, or wrong In/Out port | Re-add Mackie Control with In `APC40-IN`, Out `APC40-OUT` |
| Knob feels too coarse or too slow | Step limit / noise gate | Tune `KNOB_STEP_LIMIT` (1-2 for finer) and `KNOB_NOISE_THRESHOLD` |

Use `--monitor` to see both directions and identify whether a failure is in the
APC40-to-MCU path or the Cakewalk-to-APC40 path.

## Development

- Python 3.14, managed by `uv` (see `.python-version`). Do not use the system Python.
- Dependencies: `python-rtmidi`, `PyYAML`; dev: `pytest`.
- Source lives under `src/apc40sonar/`; tests under `tests/`.
- Run tests: `uv run pytest`. They are hardware-free; the renderer takes an injected send
  callable and the engine takes an injected MCU send, so everything is unit-testable.

### Design decisions carried over from the Lua prototype

- Send **real Note Off** (0x80) for MCU buttons; never rely on Note On velocity 0.
- **Do not de-duplicate** output at the transport; send every intended message. (The
  renderer only de-duplicates identical LED/ring values, with a `force` escape hatch.)
- **Do not gate input handling** behind the startup show; a control surface must always
  respond.
- Force LEDs the device also drives locally (mode buttons, MCU-authoritative strip LEDs).
- Send V-pot deltas as a single relative message rather than one step at a time.
- Only one reader per loopMIDI port; do not run MIDI-OX on the feedback port while the
  app runs (it can starve the reader).

### Roadmap

1. Utility row (notes 58-65), Scene buttons, and device/plug-in mode.
2. Keystroke bridge for the keyboard-only commands in [`cakewalk-command-matrix.md`](cakewalk-command-matrix.md)
   (needs an input-injection dependency such as `pydirectinput` or `pynput`, and the
   dedicated conflict-free Cakewalk keymap).
3. Grid modes and instrument/drum note routing.
