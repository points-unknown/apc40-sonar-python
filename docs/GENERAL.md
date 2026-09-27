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
| `uv run apc40sonar --env PATH` | Use an explicit `.env` file |

`run-apc40-sonar.cmd` is a launcher that finds `uv` on `PATH` or falls back to
`%USERPROFILE%\.local\bin\uv.exe`.

## Behavior notes

### Mixer mapping (APC40 to MCU)

| APC40 control | MCU message |
|---|---|
| Fader 1-8 (CC 7, ch0-7) | Pitch Bend ch0-7, 7-bit scaled to 14-bit |
| Track Control knob 1-8 (CC 48-55) | V-pot rotation CC 16-23, relative |
| Record Arm (note 48) | Rec notes 0-7 |
| Solo (note 49) | Solo notes 8-15 |
| Activator/Mute (note 50) | Mute notes 16-23 |
| Track Select (note 51) | Select notes 24-31 |
| Clip Stop (note 52) | V-pot push notes 32-39 |
| Play / Stop / Record (91/92/93) | Play 94 / Stop 93 / Record 95 |
| Metronome (65) | Click note 89 |
| Pan / Send A / Send B / Send C (87-90) | Assign Pan 42 / Assign Send 41 + ring style |

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

Shift (note 98) is tracked locally and lights while held; it sends nothing to Cakewalk.
Mapped Shift combos replace the button's normal action; unmapped ones behave as if
Shift were not held.

| Combo | Action |
|---|---|
| Shift + Detail View (62) | Toggle Cakewalk's Mackie Control meters (see above) |

### Latching buttons

In Generic Mode the Record Arm / Solo / Activator buttons **latch**: the device sends
Note On when the button turns on and Note Off when it turns off (it does not send an
immediate off on release). Each edge must emit exactly one MCU button press, or Cakewalk
ignores the "off" edge and the button appears to need two presses to clear. Track Select
is a radio group, so only its "on" edge acts; Clip Stop, transport, navigation and
Metronome are momentary and act on the press edge.

### Device Control banks

The APC40 keeps nine Device Control banks (Tracks 1-8 and Master), chosen by the Track
Selection / Master buttons. The Device Control button row (notes 58-65: Clip/Track,
Device On/Off, arrows, Detail View, Rec Quantize, Overdub, Metronome) and the Device
Control knobs (CC 16-23) report on the **selected bank's channel**: 0-7, or 8 for
Master. The engine accepts them on any of channels 0-8 and treats the row as one set of
global buttons. Their LEDs are stored per bank, so the renderer writes utility-row LEDs to
all nine channels and they stay visible whichever bank is selected.

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
