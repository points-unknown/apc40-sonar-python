# APC40 to Cakewalk by BandLab: Python Project Handoff

This document is the starting point for a **fresh session** building the Python
implementation. It captures the goal, the decisions, the validated protocol knowledge,
the lessons learned from the MIDIMonster prototype, and the first tasks.

Read this first, then the reference documents listed in section 3.

---

## 1. Goal

Build a robust, tightly coupled control-surface integration between an **original Akai
APC40** and **Cakewalk by BandLab**, where the APC40 acts as an eight-channel mixer plus
transport, knob modes, plug-in control, and grid macros, with **reliable bidirectional
feedback** (Cakewalk state drives the APC40 LEDs and rings).

The integration is implemented as a **standalone Python application** that owns the MIDI
ports directly.

---

## 2. Why Python (and not MIDIMonster)

A complete MIDIMonster v0.6 + Lua prototype was built and validated. It proved the
concept and produced the protocol references, but hit platform limitations that are
costly to work around:

| Problem | Impact | Python fix |
|---|---|---|
| `winmidi` cannot send a real Note Off (sends Note On velocity 0) | Cakewalk counted it as a second press, causing double-toggles | Send real Note Off (0x80) |
| Output values are de-duplicated | Repeated identical presses were dropped | Send exactly what we intend |
| A single `default-handler` does not reliably provide the input channel name | All inputs were silently dropped | Direct dispatch in code |
| Interval/show timing is opaque | The startup show sometimes never completed | Explicit timing |
| **Intermittent feedback loss** | MIDI-OX received Cakewalk feedback on `APC40-DEBUG` while MIDIMonster received nothing (loopMIDI reader starvation) | Own the port directly |
| Opaque console output | Slow debugging | Real logging and unit tests |

**Decision:** replace MIDIMonster/Lua with a Python app. Keep all protocol and design work.

---

## 3. Reference files to carry over

Copy these into the new project (see the copy command in section 11):

| File | Why |
|---|---|
| `docs/apc40-communications-protocol.md` | Complete Akai APC40 protocol (authoritative) |
| `APC40_Communications_Protocol_rev_1.pdf` | Original Akai PDF |
| `docs/apc40-output-reference.md` | APC40 LED/ring/color authority |
| `docs/mcu-mapping.md` | Mackie Control protocol and the APC40 mapping |
| `docs/mackie_control_protocol.md` | Deep MCU reference (TouchMCU) |
| `docs/cakewalk-command-matrix.md` | MCU vs keyboard bridging and the keymap |
| `docs/setup-loopmidi-and-cakewalk.md` | Port topology and Cakewalk setup |
| `plans/apc40-sonar-python-plan.md` | The Python implementation plan |
| `plans/apc40-sonar-python-handoff.md` | This document |
| `apc40-sonar.lua` | The working Lua engine (reference for logic and mappings) |
| `baseline/` | The validated startup lightshow (reference) |

---

## 4. Port topology

| Port | Direction | Used by |
|---|---|---|
| `Akai APC40` | read + write | the Python app only |
| `APC40-MCU` | app -> Cakewalk | app writes; Cakewalk surface **In Port** |
| `APC40-DEBUG` | Cakewalk -> app | Cakewalk surface **Out Port**; app reads |

- loopMIDI must be running; its ports exist only while it runs.
- Only the Python app may open the APC40 and the two loopMIDI ports.
- Do not run MIDI-OX on `APC40-DEBUG` while the app runs (it can starve the reader).

---

## 5. Cakewalk by BandLab setup

1. `Edit > Preferences > MIDI > Devices`: enable `APC40-MCU` and `APC40-DEBUG` in both
   Inputs and Outputs.
2. `Edit > Preferences > MIDI > Control Surfaces`: add a **Mackie Control** surface with
   **In Port = `APC40-MCU`** and **Out Port = `APC40-DEBUG`**.
3. Set *Control Strips Visible In* to **All Strips**.
4. Set *Refresh Frequency* to **50-75 ms**.
5. Cakewalk enumerates MIDI devices at startup; restart it after changing ports.

---

## 6. APC40 protocol essentials

Full detail in `docs/apc40-communications-protocol.md`. Key facts:

- MIDI channels are zero-based: `ch0` = Track 1 ... `ch7` = Track 8.
- **Strip LEDs** (per track channel): Record Arm 48, Solo 49, Activator 50, Track Select
  51, Clip Stop 52, Clip Launch rows 53-57.
- **Clip grid colors**: 0 off, 1 green, 2 green blink, 3 red, 4 red blink, 5 yellow,
  6 yellow blink, 7-127 green.
- **Global LEDs** (channel 0): utility row 58-65, Master 80, Stop All Clips 81 (input
  only, no host LED), Scenes 82-86, Pan 87, Send A 88, Send B 89, Send C 90, transport
  91-101.
- **Track Control ring position**: CC 48-55. **Track Control ring style**: CC 56-63.
- **Device Control ring position**: CC 16-23. **Device Control ring style**: CC 24-31.
- **Ring styles**: 0 off, 1 single, 2 volume, 3 pan.
- **Pan style center** is value 63/64.
- **Track Control knobs** are absolute (CC 48-55). **Faders** are CC 7 per track channel.
- **Pan/Send A/B/C buttons** are notes 87/88/89/90 (toggle buttons).

---

## 7. MCU essentials

Full detail in `docs/mcu-mapping.md`. Key facts:

- All messages on MIDI channel 0 unless noted.
- **Faders**: Pitch Bend, channels 0-7 (master = 8), 14-bit.
- **V-pot rotation**: CC 16-23, relative. `0x01`-`0x3F` = +1..+63, `0x41`-`0x7F` =
  -1..-63.
- **V-pot LED ring**: CC 48-55. Byte = bit6 LED, bits5-4 mode, bits3-0 value (0-11).
  Modes: 0 single dot, 1 pan, 2 volume, 3 centered bar.
- **Buttons**: Note On velocity 127 on press, **real Note Off on release**.
  - Rec 1-8 = notes 0-7, Solo 1-8 = 8-15, Mute 1-8 = 16-23, Select 1-8 = 24-31.
  - V-pot push 1-8 = 32-39.
  - Assign Track/Send/Pan/Plug-in/EQ/Instrument = 40-45.
  - Bank Left/Right = 46/47, Channel Left/Right = 48/49.
  - Transport: Rewind 91, Forward 92, Stop 93, Play 94, Record 95.
  - Up/Down/Left/Right = 96-99, Zoom 100, Scrub 101.
- **Fader feedback** (Pitch Bend) is ignored: the APC40 faders are not motorized.

---

## 8. Validated mixer mapping (from the prototype)

| APC40 control | MCU message |
|---|---|
| Fader 1-8 (CC 7, ch0-7) | Pitch Bend ch0-7 |
| Track Control knob 1-8 (CC 48-55) | V-pot relative CC 16-23 |
| Record Arm 1-8 (note 48, ch0-7) | Rec notes 0-7 |
| Solo 1-8 (note 49) | Solo notes 8-15 |
| Activator 1-8 (note 50) | Mute notes 16-23 |
| Track Select 1-8 (note 51) | Select notes 24-31 |
| Play / Stop / Record (91/92/93) | Play 94 / Stop 93 / Record 95 |
| Pan / Send A / Send B / Send C (87-90) | Assign Pan 42 / Assign Send 41 |

Feedback: MCU notes 0-31 -> strip LEDs; MCU CC 48-55 -> Track Control rings; MCU
transport notes -> transport LEDs.

---

## 9. Knob modes (validated behavior)

- Pressing **Pan** (87): light only Pan, clear Send A/B/C, set Track ring style to 3
  (pan), center all rings at 63, send MCU Assign Pan (42).
- Pressing **Send A/B/C** (88/89/90): light only that button, clear the others, set ring
  style to 2 (volume), send MCU Assign Send (41).
- Mode-button LEDs must be written unconditionally (the device lights them locally, so a
  change-cache can go stale).

---

## 10. Lessons learned (avoid these in Python)

1. **Send real Note Off** for MCU buttons; never rely on Note On velocity 0.
2. **Do not de-duplicate** output; send every intended message.
3. **Do not gate input handling behind the startup show**; a control surface must always
   respond.
4. **Force mode-button LED writes**; the device toggles them locally.
5. **Pan style center is 63/64**; set it explicitly when entering Pan mode.
6. **Send V-pot deltas as a single relative message**, not one step at a time.
7. **Only one reader per loopMIDI port**; do not run MIDI-OX on the feedback port.
8. **Cakewalk enumerates devices at startup**; restart it after port changes.

---

## 11. Copy command

Run this from the current project root to create the new project folder and copy the
knowledge base. Adjust the destination path if you prefer.

```bat
set SRC=C:\Users\point\OneDrive\Desktop\midimonster
set DST=C:\Users\point\OneDrive\Desktop\apc40-sonar-python

mkdir "%DST%"
mkdir "%DST%\docs"
mkdir "%DST%\plans"
mkdir "%DST%\reference"

copy "%SRC%\docs\apc40-communications-protocol.md" "%DST%\docs\"
copy "%SRC%\docs\apc40-output-reference.md" "%DST%\docs\"
copy "%SRC%\docs\mcu-mapping.md" "%DST%\docs\"
copy "%SRC%\docs\mackie_control_protocol.md" "%DST%\docs\"
copy "%SRC%\docs\cakewalk-command-matrix.md" "%DST%\docs\"
copy "%SRC%\docs\setup-loopmidi-and-cakewalk.md" "%DST%\docs\"
copy "%SRC%\plans\apc40-sonar-python-plan.md" "%DST%\plans\"
copy "%SRC%\plans\apc40-sonar-python-handoff.md" "%DST%\plans\"
copy "%SRC%\APC40_Communications_Protocol_rev_1.pdf" "%DST%\reference\"
copy "%SRC%\apc40-sonar.lua" "%DST%\reference\"
xcopy "%SRC%\baseline" "%DST%\reference\baseline\" /E /I

dir "%DST%" /s /b
```

---

## 12. Toolchain: uv + virtual environment

This project uses **uv** for environment and dependency management.

```bat
cd C:\Users\point\OneDrive\Desktop\apc40-sonar-python
uv init --name apc40sonar
uv venv
uv add python-rtmidi PyYAML
uv add --dev pytest
```

- `uv run apc40sonar` runs the app inside the managed environment.
- `uv run pytest` runs the tests.
- Dependencies live in `pyproject.toml`; `uv.lock` is committed.
- Do not use the system Python directly.

---

## 13. First tasks in the new session

1. Initialize the project with `uv` and add `python-rtmidi`, `PyYAML`, and `pytest`.
2. Scaffold the `apc40sonar` package, `config/apc40-sonar.yaml`, and
   `run-apc40-sonar.cmd`.
3. Implement `midi_io.py` with a `--list-ports` mode and confirm the ports open.
4. Implement `apc40.py` and `mcu.py` with unit tests.
5. Implement the `engine.py` mixer core and feedback rendering.
6. Port the startup lightshow.
7. Validate end-to-end with Cakewalk.
8. Add grid modes, device/plug-in control, and global commands.
9. Polish: recovery, logging, docs, and the launcher.

See `plans/apc40-sonar-python-plan.md` for the full module layout and behavior spec.
