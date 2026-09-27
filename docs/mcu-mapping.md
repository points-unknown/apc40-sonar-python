# MCU Protocol Reference and APC40 Integration Map

Authoritative reference for the Mackie Control Universal (MCU) messages the engine
emits and decodes, plus the concrete APC40-to-MCU and MCU-to-APC40 mapping.

Primary source: the reverse-engineered *Mackie Control Protocol* document from the
TouchMCU project (<https://github.com/NicoG60/TouchMCU>), validated against Mackie Control
Universal Pro hardware by Raphaël Doursenaud. A local copy is kept in `scratch/mcu_protocol.md`
(gitignored).

Cakewalk by BandLab's **Mackie Control** surface in **Universal Mode** implements this
standard message set.

## MCU Basics

### Channel

All messages use **MIDI channel 0** (the first channel) unless noted. Faders use channels
0-8 (eight strips plus master).

### Note "bang" semantics

Buttons and LEDs use a **Note On immediately followed by Note Off** on the same note.
The Note On **velocity** encodes state:

| LED state | Velocity | Notes |
|---|---:|---|
| Off | 0 | any even value |
| Blink | 1 | any odd value except 0x7F |
| Solid | 127 (0x7F) | |

When emulating the surface, the engine should send the same bang (On then Off) for
button presses and for LED state changes.

### Message types used

| Purpose | Message |
|---|---|
| V-pot rotation | Control Change |
| V-pot LED ring | Control Change |
| Fader position | Pitch Bend (14-bit) |
| Button press / LED | Note bang |
| Metering | Channel Pressure |
| LCD text | SysEx |

## MCU Input (surface to host)

| Control | Message |
|---|---|
| Fader 1-8 / Master position | Pitch Bend, channels 0-7 / 8 |
| Fader 1-8 / Master touch | Notes 104-112 |
| V-pot 1-8 rotation | CC 16-23, value 0x01 = clockwise, 0x41 = counter-clockwise |
| V-pot 1-8 push (switch) | Notes 32-39 |
| Rec 1-8 | Notes 0-7 |
| Solo 1-8 | Notes 8-15 |
| Mute 1-8 | Notes 16-23 |
| Select 1-8 | Notes 24-31 |
| Assign buttons (Track/Send/Pan/Plug-in/EQ/Instrument) | Notes 40-45 |
| Bank Left / Right | Notes 46 / 47 |
| Channel Left / Right | Notes 48 / 49 |
| Flip / Global | Notes 50 / 51 |
| Name-Value / SMPTE-Beats | Notes 52 / 53 |
| F1-F8 | Notes 54-61 |
| Track/Input/Audio/Instrument/Aux/Bus/Output/User view | Notes 62-69 |
| Shift/Option/Control/Alt | Notes 70-73 |
| Automation Read/Off, Write, Trim, Touch, Latch, Group | Notes 74-79 |
| Save / Undo / Cancel / Enter | Notes 80-83 |
| Markers / Nudge / Cycle / Drop / Replace / Click / Solo | Notes 84-90 |
| Rewind / Forward / Stop / Play / Record | Notes 91-95 |
| Up / Down / Left / Right / Zoom / Scrub | Notes 96-101 |
| User switches 1-2 | Notes 102-103 |
| Jog wheel | CC 60, value 0x01 / 0x41 |

## MCU Output (host to surface)

| Control | Message |
|---|---|
| Fader position | Pitch Bend, channels 0-8 |
| V-pot LED ring | CC 48-55 |
| Button / LED | Note bang with velocity (0 off, 1 blink, 127 solid) |
| LCD text | SysEx `F0 00 00 66 14 12 <offset> <chars...> F7` |
| Timecode / assignment digits | CC 64-75 (channel 0 or 15) |
| Channel meters | Channel Pressure `0xD0 <sv>` |

### V-pot LED ring encoding (CC 48-55)

The byte is a packed pair:

| Bits | Meaning |
|---|---|
| b7 | always 0 |
| b6 | LED under the encoder on/off |
| b5-b4 | ring **mode** |
| b3-b0 | ring **value** (0-11) |

Ring rendering by mode:

| Mode | Style | Rendering |
|---|---|---|
| `0b00` | Single dot | One LED at the value position |
| `0b01` | Pan | Fans left/right from center (classic pan indicator) |
| `0b10` | Volume | Bar fills from left to the value |
| `0b11` | Centered bar | Bar grows outward from center |

## MIDI Note Map (channel 0)

| Note | Dec | Hex | Control |
|---|---:|---:|---|
| C-1..G-1 | 0-7 | 00-07 | Rec 1-8 |
| G#-1..D#0 | 8-15 | 08-0F | Solo 1-8 |
| E0..B0 | 16-23 | 10-17 | Mute 1-8 |
| C1..G1 | 24-31 | 18-1F | Select 1-8 |
| G#1..D#2 | 32-39 | 20-27 | V-pot push 1-8 |
| E2..A2 | 40-45 | 28-2D | Assign Track / Send / Pan / Plug-in / EQ / Instrument |
| A#2, B2 | 46, 47 | 2E, 2F | Bank Left / Right |
| C3, C#3 | 48, 49 | 30, 31 | Channel Left / Right |
| D3, D#3 | 50, 51 | 32, 33 | Flip / Global |
| E3, F3 | 52, 53 | 34, 35 | Name-Value / SMPTE-Beats |
| F#3..C#4 | 54-61 | 36-3D | F1-F8 |
| D4..A4 | 62-69 | 3E-45 | MIDI/Inputs/Audio/Instrument/Aux/Busses/Outputs/User |
| A#4..C#5 | 70-73 | 46-49 | Shift / Option / Control / Alt |
| D5..G5 | 74-79 | 4A-4F | Read-Off / Write / Trim / Touch / Latch / Group |
| G#5..B5 | 80-83 | 50-53 | Save / Undo / Cancel / Enter |
| C6..F#6 | 84-90 | 54-5A | Markers / Nudge / Cycle / Drop / Replace / Click / Solo |
| G6..B6 | 91-95 | 5B-5F | Rewind / Forward / Stop / Play / Record |
| C7..F7 | 96-101 | 60-65 | Up / Down / Left / Right / Zoom / Scrub |
| F#7, G7 | 102, 103 | 66, 67 | User switch 1-2 |
| G#7..D#8 | 104-111 | 68-6F | Fader 1-8 touch |
| E8 | 112 | 70 | Master fader touch |
| F8/G8 | 113-115 | 71-73 | SMPTE / BEATS / Rude Solo LEDs |

## MIDI CC Map (channel 0)

| CC | Control |
|---:|---|
| 16-23 | V-pot 1-8 rotation |
| 46 | External control |
| 48-55 | V-pot 1-8 LED ring |
| 60 | Jog wheel |
| 64-73 | Timecode digits 1-10 |
| 74-75 | Assignment digits 1-2 |

## Pitch Bend Map

| Channel | Fader |
|---|---|
| 0-7 | Fader 1-8 position |
| 8 | Master fader position |

14-bit value: 0 = bottom, 16383 = top.

## APC40 to MCU Mapping (Control Path)

| APC40 control | APC40 input | MCU message to emit |
|---|---|---|
| Fader 1-8 | CC 7 on `ch0`-`ch7` | Pitch Bend on channels 0-7, 7-bit scaled to 14-bit |
| Track Control knob 1-8 | CC 48-55 on `ch0` | V-pot rotation CC 16-23, relative (`0x01`/`0x41`) |
| Activator (Mute) 1-8 | Note 50 on `ch0`-`ch7` | Mute Note 16-23 on channel 0 |
| Solo 1-8 | Note 49 on `ch0`-`ch7` | Solo Note 8-15 |
| Record Arm 1-8 | Note 48 on `ch0`-`ch7` | Rec Note 0-7 |
| Track Select 1-8 | Note 51 on `ch0`-`ch7` | Select Note 24-31 |
| Clip Stop 1-8 | Note 52 on `ch0`-`ch7` | V-pot push Note 32-39 (or local macro) |
| Play / Stop / Record | Notes 91 / 92 / 93 | Play 94 / Stop 93 / Record 95 |
| Left / Right (transport) | Notes 97 / 96 | Bank Left 46 / Bank Right 47 or Channel 48/49 |
| Up / Down | Notes 94 / 95 | Channel Left 48 / Right 49 or Up/Down 96/97 |
| Shift | Note 98 | Shift Note 70 (modifier) |
| Nudge - / + | Notes 101 / 100 | Nudge Note 85 / Left-Right 98-99 |
| Tap Tempo | Note 99 | No MCU tap; use keystroke |
| Utility row (58-65) | Notes 58-65 | Assign / function notes or keystrokes (see command matrix) |
| Scene 1-5 | Notes 82-86 | F1-F5 (54-58) or local grid-mode switches |
| Master | Note 80 | Select Master / Global Note 51 |
| Stop All Clips | Note 81 | Transport Stop 93 + local acknowledgment |
| Clip grid 1-8 x 1-5 | Notes 53-57 on `ch0`-`ch7` | Function notes / assign / local grid modes |

> Note on transport numbering: MCU **Record is note 95 (0x5F)** and **Play is 94 (0x5E)**,
> whereas the APC40 sends Play as 91, Stop as 92, Record as 93. The encoder must translate,
> not pass through.

## MCU to APC40 Mapping (Feedback Path)

| MCU feedback | APC40 rendering |
|---|---|
| Rec LED (notes 0-7) | Record Arm LED (note 48 per track), on/off |
| Solo LED (notes 8-15) | Solo LED (note 49) |
| Mute LED (notes 16-23) | Activator LED (note 50) |
| Select LED (notes 24-31) | Track Select LED (note 51) |
| V-pot LED ring (CC 48-55) | Track Control ring (CC 48-55) or Device Control ring depending on mode |
| V-pot LED under encoder (bit 6) | Not available; ignore |
| Transport LED (stop/play/record) | APC40 Play/Stop/Record LEDs |
| Fader position (pitch bend) | **Not displayable** (APC40 faders are not motorized); read and ignore |
| LCD text (SysEx) | Unused (APC40 has no display); optionally log |
| Meters (channel pressure) | Unused; optionally map to grid as a level meter |

## Encoder Delta Encoding (Absolute APC40 knob to Relative MCU V-pot)

MCU V-pots are **relative**; the APC40 Track/Device knobs are **absolute** (0-127).

Algorithm per knob:

```text
last = stored absolute value (init to first observed value)
delta = new - last
normalize delta into a reasonable range, e.g. clamp to [-3, 3]
if delta > 0 then emit CC <vpot_cc> with 0x01, delta times
if delta < 0 then emit CC <vpot_cc> with 0x41, (-delta) times
last = new
```

Notes:

- The APC40 knob's absolute position and Cakewalk's parameter value are independent; the
  **ring feedback from MCU is the source of truth** for the displayed value.
- Cap the number of steps per event to avoid message storms during fast turns.

## Ring Translation (MCU mode to APC40 ring style)

| MCU ring mode | Style | APC40 ring style value |
|---|---|---|
| `0b00` | Single dot | 1 (single LED) |
| `0b01` | Pan | 3 (pan) |
| `0b10` | Volume | 2 (volume) |
| `0b11` | Centered bar | 2 (volume, approximate) |

Ring **value** 0-11 maps to APC40 ring **position** 0-127 by scaling:
`apc_position = round(mcu_value / 11 * 127)`.

Both ring banks accept host style messages on the original APC40:

- Device Control rings: style CCs 24-31.
- Track Control rings: style CCs 56-63.

The engine writes Track Control style `3` (Pan) when Pan mode is selected, and style `2`
(Volume) for Send/level modes.

## Cakewalk by BandLab Specifics

- Universal Mode implements the standard message set above.
- In Track view the 8 V-pots default to **pan**; the Assign buttons (notes 40-45) switch
  the V-pot assignment to Track / Send / Pan / Plug-in / EQ / Instrument.
- Channel Left/Right (48/49) and Bank Left/Right (46/47) navigate the controlled strips.
- Cakewalk sends fader positions and V-pot rings back on the same cable; fader feedback is
  intentionally ignored (no motorized faders).

## Open Items to Verify on Hardware

- [ ] V-pot LED ring values and modes actually update APC40 rings as expected
- [ ] Cakewalk's exact V-pot default assignment in the current project view
- [ ] Whether Cakewalk echoes Select/Mute/Solo/Rec LED states reliably
