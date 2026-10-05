# Akai APC40 Communications Protocol — Complete AI-Readable Reference

> Faithful structured transcription of Akai Professional, *Communications Protocol for Akai APC40 Controller*, Revision 1, May 1, 2009. Source: [`APC40_Communications_Protocol_rev_1.pdf`](../APC40_Communications_Protocol_rev_1.pdf).
>
> This reference concerns the **original APC40**, not the APC40 mkII or APC Mini. It preserves the source protocol's values, distinctions, limitations, and apparent inconsistencies. Editorial clarifications are explicitly labeled.

## 1. Document identity and scope

- **Document title:** Communications Protocol for Akai APC40 Controller
- **Running title:** Generic Communication Protocol for Akai APC40 Controller
- **Revision:** 1
- **Date:** May 1, 2009
- **Purpose:** Describe the message formats exchanged between an APC40 and a PC/Mac host.
- **Transport:** MIDI messages over USB.
- **Original application:** Control-surface interface for Ableton Live.
- **Other use:** The controller may alternatively control other software.

### 1.1 Direction terminology

All directions are from the host's viewpoint:

- **Outbound:** PC/Mac host → APC40.
- **Inbound:** APC40 → PC/Mac host.

### 1.2 Numeric and channel conventions used here

- Hexadecimal bytes use `0xNN`.
- Decimal values are shown where useful.
- Protocol MIDI channels are zero-based: channel `0` is conventional MIDI channel 1, through channel `15` as conventional MIDI channel 16.
- APC40 track channels are generally:

| Protocol channel | Conventional channel | Meaning |
|---:|---:|---|
| 0 | 1 | Track 1 |
| 1 | 2 | Track 2 |
| 2 | 3 | Track 3 |
| 3 | 4 | Track 4 |
| 4 | 5 | Track 5 |
| 5 | 6 | Track 6 |
| 6 | 7 | Track 7 |
| 7 | 8 | Track 8 |
| 8 | 9 | Master bank/context where explicitly documented for Generic Mode |

In status-byte templates such as `0x9<chan>`, `<chan>` is the low four-bit MIDI channel nibble.

---

## 2. APC40-specific System Exclusive envelope

Except for the universal Device Inquiry exchange, APC40 SysEx messages use this envelope:

| Byte position | Value | Meaning |
|---:|---|---|
| 1 | `0xF0` | MIDI System Exclusive start |
| 2 | `0x47` | Akai Professional one-byte manufacturer ID |
| 3 | `<DeviceID>` | System Exclusive device ID |
| 4 | `0x73` | APC40 product model ID |
| 5 | `<MessageID>` | Message-type identifier |
| 6 | `<DataLengthMS>` | Number of following data bytes, most-significant part |
| 7 | `<DataLengthLS>` | Number of following data bytes, least-significant part |
| 8 through `n+7` | `n` data bytes | Message-specific payload |
| `n+8` | `0xF7` | MIDI System Exclusive terminator |

### 2.1 Field semantics

- Manufacturer ID `0x47` is allocated to Akai Professional.
- The device ID normally selects among multiple devices connected to one host. The protocol expects only one APC40 at a time, so the host should use broadcast device ID `0x7F`. The source notes that the APC40 is unlikely to pay attention to this field.
- Product model ID `0x73` prevents messages intended for another Akai product from being handled as APC40 messages.
- The message ID determines the payload's size and interpretation.
- Payload lengths and formats differ by message type.

Canonical envelope:

```text
F0 47 <DeviceID> 73 <MessageID> <DataLengthMS> <DataLengthLS> <data...> F7
```

---

## 3. Universal MIDI Device Inquiry

The APC40 supports the standard MMC/MIDI Device Inquiry exchange. These are universal SysEx messages and **do not** use the APC40-specific envelope above.

### 3.1 Host → APC40 inquiry request

| Byte position | Value | Meaning |
|---:|---|---|
| 1 | `0xF0` | SysEx start |
| 2 | `0x7E` | Universal Non-Realtime message |
| 3 | `0x00` | Channel/device to inquire; set to `0` for this protocol |
| 4 | `0x06` | Inquiry sub-ID |
| 5 | `0x01` | Inquiry Request |
| 6 | `0xF7` | SysEx terminator |

Exact request:

```text
F0 7E 00 06 01 F7
```

### 3.2 APC40 → host inquiry response

The APC40 responds as follows:

| Byte position | Value | Meaning |
|---:|---|---|
| 1 | `0xF0` | SysEx start |
| 2 | `0x7E` | Universal Non-Realtime message |
| 3 | `<MIDIChannel>` | Common MIDI channel setting |
| 4 | `0x06` | Inquiry sub-ID |
| 5 | `0x02` | Inquiry Response |
| 6 | `0x47` | Akai manufacturer ID |
| 7 | `0x73` | APC40 product model ID |
| 8 | `0x00` | Data length, most significant |
| 9 | `0x19` | Data length, least significant; 25 data bytes follow |
| 10 | `<Version1>` | Software-version major, most significant |
| 11 | `<Version2>` | Software-version major, least significant |
| 12 | `<Version3>` | Software-version minor, most significant |
| 13 | `<Version4>` | Software-version minor, least significant |
| 14 | `<DeviceID>` | SysEx device ID |
| 15 | `<Serial1>` | Serial number first digit |
| 16 | `<Serial2>` | Serial number second digit |
| 17 | `<Serial3>` | Serial number third digit |
| 18 | `<Serial4>` | Serial number fourth digit |
| 19–34 | `<Manufacturing1>` through `<Manufacturing16>` | Sixteen manufacturing-data bytes, in order |
| 35 | `0xF7` | SysEx terminator |

Canonical response:

```text
F0 7E <MIDIChannel> 06 02 47 73 00 19
<Version1> <Version2> <Version3> <Version4> <DeviceID>
<Serial1> <Serial2> <Serial3> <Serial4>
<Manufacturing1> ... <Manufacturing16>
F7
```

The `0x0019` payload comprises 4 version bytes + 1 device-ID byte + 4 serial digits + 16 manufacturing bytes = 25 bytes.

---

## 4. Outbound messages: host → APC40

The source defines three host-to-device message types:

1. **Type 0:** Introduction/configuration SysEx.
2. **Type 1:** LED control using standard Note On/Off.
3. **Type 2:** Absolute controller/value and LED-ring updates using standard Control Change.

## 5. Outbound Type 0: introduction and operating mode

The host sends this before any APC40-specific message other than Device Inquiry. It tells the APC40 to initialize and supplies the host application's version so firmware can accommodate application changes.

The unit defaults to **Mode 0** at startup.

### 5.1 Accepted modes

| Mode | Identifier | Name |
|---:|---:|---|
| 0 | `0x40` | Generic Mode |
| 1 | `0x41` | Ableton Live Mode |
| 2 | `0x42` | Alternate Ableton Live Mode |

### 5.2 Type 0 message format

| Byte position | Value | Meaning |
|---:|---|---|
| 1 | `0xF0` | SysEx start |
| 2 | `0x47` | Akai manufacturer ID |
| 3 | `<DeviceID>` | SysEx device ID; normally broadcast `0x7F` |
| 4 | `0x73` | APC40 product model ID |
| 5 | `0x60` | Introduction message identifier |
| 6 | `0x00` | Payload length MS byte |
| 7 | `0x04` | Payload length LS byte; four data bytes follow |
| 8 | `0x40`, `0x41`, or `0x42` | Application/configuration mode identifier |
| 9 | `<VersionHigh>` | PC application software major version |
| 10 | `<VersionLow>` | PC application software minor version |
| 11 | `<BugfixLevel>` | PC application software bug-fix level |
| 12 | `0xF7` | SysEx terminator |

Canonical message:

```text
F0 47 <DeviceID> 73 60 00 04 <Mode> <Major> <Minor> <Bugfix> F7
```

Example skeleton for Generic Mode with broadcast device ID:

```text
F0 47 7F 73 60 00 04 40 <Major> <Minor> <Bugfix> F7
```

### 5.3 Generic Mode (Mode 0) behavior

| Control/group | Behavior in Mode 0 | Local LED behavior/state |
|---|---|---|
| Clip Launch buttons | Momentary | Green LED should light while on |
| Clip Stop buttons | Momentary | Corresponding LED should light while on |
| Activator, Solo, Record Arm | Toggle | Corresponding LED should light when on |
| Track Selection 1–8 + Master | Radio group; exactly one of nine selected | Selected button's LED lights; selection does **not** emit MIDI for its own state |
| Clip/Track (1), Device On/Off (2), left arrow (3), right arrow (4) | Toggle | Corresponding LED lights when on |
| Detail View (5), Rec Quantization (6), MIDI Overdub (7), Metronome (8) | Momentary | Corresponding LED lights while on |
| Scene Launch and Stop All Clips | Momentary | Corresponding LED should light while on |
| Track Control buttons | Toggle | Corresponding LED lights when on |
| Track Control knobs/buttons | Not banked | Fixed controls |
| Play, Stop, Record, Up, Down, Left, Right, Shift, Nudge+, Nudge−, Tap Tempo | Momentary | No additional local-LED rule stated here |
| All LED rings | Single style | Device sets rings to Single style |

#### Mode 0 Device Control banking

Track Selection chooses one of nine internal banks for all eight Device Control knobs and Device Control switches:

| Selected button | Device Control output channel |
|---|---:|
| Track 1 | 0 |
| Track 2 | 1 |
| Track 3 | 2 |
| Track 4 | 3 |
| Track 5 | 4 |
| Track 6 | 5 |
| Track 7 | 6 |
| Track 8 | 7 |
| Master | 8 |

Important consequences:

- Track Selection itself does not report its own state as MIDI in Mode 0.
- Device Control knobs and switches report on the channel selected by this radio group.
- Pressing a Track Selection button causes the APC40 to transmit the current positions of all eight Device Control knobs.
- Track Control knobs/buttons are independent of this bank mechanism.

### 5.4 Ableton Live Mode (Mode 1) behavior

- All buttons are momentary.
- Device Control knobs and buttons are not internally banked by the APC40.
- The APC40 controls knob LED rings locally, but the host can update them.
- The host controls all other LEDs.

### 5.5 Alternate Ableton Live Mode (Mode 2) behavior

- All buttons are momentary.
- Device Control knobs and buttons are not internally banked by the APC40.
- The host controls **all** LEDs, including knob rings.

### 5.6 Mode comparison

| Property | Mode 0 Generic | Mode 1 Ableton Live | Mode 2 Alternate Ableton Live |
|---|---|---|---|
| Startup default | Yes | No | No |
| Button semantics | Mixed momentary/toggle/radio | All momentary | All momentary |
| Device Control internal banking | 9 banks | None | None |
| Ring ownership | Locally initialized to Single; host updates available | APC40-controlled, host may update | Host-controlled |
| Other LED ownership | Mixed/local behaviors described | Host | Host |

---

## 6. Outbound Type 1: LED control with notes

A host changes LED state by sending standard MIDI Note On or Note Off:

- Note number identifies the LED/control.
- Velocity/data byte selects on/off, color, and/or blink state.
- MIDI channel selects a track for channelized strip/grid controls.
- Note On velocity `0` is equivalent to Note Off, but the source **prefers an actual Note Off**.

### 6.1 Note On format

| Byte | Value | Meaning |
|---:|---|---|
| 1 | `0x9<chan>` | MIDI Note On; channel nibble selects track where applicable |
| 2 | `<ControlID>` | LED object identifier/note number |
| 3 | `<State>` | LED state/color/blink value |

### 6.2 Note Off format

| Byte | Value | Meaning |
|---:|---|---|
| 1 | `0x8<chan>` | MIDI Note Off; channel nibble selects track where applicable |
| 2 | `<ControlID>` | LED object identifier/note number |
| 3 | Any | Ignored |

### 6.3 Track-strip and clip-grid LED assignments

Notes `0x30`–`0x39` use channels `0`–`7` to select Tracks 1–8.

| Note hex | Note dec | Musical label | Channel | LED | State/velocity meaning |
|---:|---:|---|---|---|---|
| `0x30` | 48 | C3 | 0–7 = Tracks 1–8 | Record Arm | `0` off; `1`–`127` on |
| `0x31` | 49 | C♯3 | 0–7 = Tracks 1–8 | Solo | `0` off; `1`–`127` on |
| `0x32` | 50 | D3 | 0–7 = Tracks 1–8 | Activator | `0` off; `1`–`127` on |
| `0x33` | 51 | D♯3 | 0–7 = Tracks 1–8 | Track Selection | `0` off; `1`–`127` on |
| `0x34` | 52 | E3 | 0–7 = Tracks 1–8 | Clip Stop | `0` off; `1` on; `2` blink; `3`–`127` on |
| `0x35` | 53 | F3 | 0–7 = Tracks 1–8 | Clip Launch row 1 | Clip color table below |
| `0x36` | 54 | F♯3 | 0–7 = Tracks 1–8 | Clip Launch row 2 | Clip color table below |
| `0x37` | 55 | G3 | 0–7 = Tracks 1–8 | Clip Launch row 3 | Clip color table below |
| `0x38` | 56 | G♯3 | 0–7 = Tracks 1–8 | Clip Launch row 4 | Clip color table below |
| `0x39` | 57 | A3 | 0–7 = Tracks 1–8 | Clip Launch row 5 | Clip color table below |

#### Clip Launch color/state values

| Velocity | Result |
|---:|---|
| `0` | Off |
| `1` | Green, steady |
| `2` | Green, blinking |
| `3` | Red, steady |
| `4` | Red, blinking |
| `5` | Yellow, steady |
| `6` | Yellow, blinking |
| `7`–`127` | Green, steady |

The grid therefore consists of 8 channel-selected columns × 5 note-selected rows = 40 independently addressed LEDs.

### 6.4 Mode 0 banked Device Control button LEDs

The source table assigns channels `0`–`8` to Tracks 1–8 and Master for these entries and marks them “mode 0 only.”

| Note hex | Dec | Label | Channel in Mode 0 | State |
|---:|---:|---|---|---|
| `0x3A` | 58 | Clip/Track (1) | 0–8 = Track 1–8/Master bank | `0` off; `1`–`127` on |
| `0x3B` | 59 | Device On/Off (2) | 0–8 = Track 1–8/Master bank | `0` off; `1`–`127` on |
| `0x3C` | 60 | Left arrow (3) | 0–8 = Track 1–8/Master bank | `0` off; `1`–`127` on |
| `0x3D` | 61 | Right arrow (4) | 0–8 = Track 1–8/Master bank | `0` off; `1`–`127` on |
| `0x3E` | 62 | Detail View (5) | 0–8 = Track 1–8/Master bank | `0` off; `1`–`127` on |
| `0x3F` | 63 | Rec Quantization (6) | 0–8 = Track 1–8/Master bank | `0` off; `1`–`127` on |
| `0x40` | 64 | MIDI Overdub (7) | 0–8 = Track 1–8/Master bank | `0` off; `1`–`127` on |
| `0x41` | 65 | Metronome (8) | 0–8 = Track 1–8/Master bank | `0` off; `1`–`127` on |

> **Source ambiguity:** The heading says all note values outside `0x30`–`0x39` ignore MIDI channel, but these eight rows explicitly assign channels `0`–`8` in Mode 0. This reference preserves both statements. Implementations should treat the explicit Mode 0 rows as the more specific rule and validate hardware behavior if relying on per-bank LED state.

### 6.5 Other LEDs explicitly listed for outbound control

The source does not supply a channel in these rows; under its general statement, MIDI channel is ignored.

| Note hex | Dec | Musical label as normalized | LED | State/velocity meaning |
|---:|---:|---|---|---|
| `0x50` | 80 | G♯5 | Master | `0` off; `1`–`127` on |
| `0x52` | 82 | A♯5 | Scene Launch 1 | `0` off; `1` on; `2` blink; `3`–`127` on |
| `0x53` | 83 | B5 | Scene Launch 2 | `0` off; `1` on; `2` blink; `3`–`127` on |
| `0x54` | 84 | C6 | Scene Launch 3 | `0` off; `1` on; `2` blink; `3`–`127` on |
| `0x55` | 85 | C♯6 | Scene Launch 4 | `0` off; `1` on; `2` blink; `3`–`127` on |
| `0x56` | 86 | D6 | Scene Launch 5 | `0` off; `1` on; `2` blink; `3`–`127` on |
| `0x57` | 87 | D♯6 | Pan | `0` off; `1`–`127` on |
| `0x58` | 88 | E6 | Send A | `0` off; `1`–`127` on |
| `0x59` | 89 | F6 | Send B | `0` off; `1`–`127` on |
| `0x5A` | 90 | F♯6 | Send C | `0` off; `1`–`127` on |

> **Outbound-table limits:** The source's outbound LED assignment table does not list Stop All Clips (`0x51`) or transport/navigation notes (`0x5B`–`0x65`), even though those controls appear in the inbound button table and some are discussed as having local behavior. Do not infer host-addressable LED behavior from the inbound table alone.

---

## 7. Outbound Type 2: controller-value and LED-ring updates

Controls that report absolute values inbound can have their displayed/current controller value updated by a host Control Change message.

- CC number identifies the control.
- CC value is the new control/display value.
- Channel selects a track/bank where applicable.

### 7.1 Message format

| Byte | Value | Meaning |
|---:|---|---|
| 1 | `0xB<chan>` | MIDI Control Change; channel selects track where applicable |
| 2 | `<ControlID>` | Control-surface object identifier/CC number |
| 3 | `<Value>` | Controller value or LED-ring style |

### 7.2 Absolute controller value assignments

| Control | Channel | CC hex | CC dec | Notes |
|---|---|---:|---:|---|
| Track Level | 0–7 = Tracks 1–8 | `0x07` | 7 | Channel fader value |
| Master Level | Not specified/ignored | `0x0E` | 14 | Master fader value |
| Crossfader | Not specified/ignored | `0x0F` | 15 | Crossfader value |
| Device Knob 1 | 0–8 in Mode 0 | `0x10` | 16 | Tracks 1–8/Master banks in Mode 0 |
| Device Knob 2 | 0–8 in Mode 0 | `0x11` | 17 | Same |
| Device Knob 3 | 0–8 in Mode 0 | `0x12` | 18 | Same |
| Device Knob 4 | 0–8 in Mode 0 | `0x13` | 19 | Same |
| Device Knob 5 | 0–8 in Mode 0 | `0x14` | 20 | Same |
| Device Knob 6 | 0–8 in Mode 0 | `0x15` | 21 | Same |
| Device Knob 7 | 0–8 in Mode 0 | `0x16` | 22 | Same |
| Device Knob 8 | 0–8 in Mode 0 | `0x17` | 23 | Same |
| Track Knob 1 | Not banked | `0x30` | 48 | Track Control knob 1 ring/value |
| Track Knob 2 | Not banked | `0x31` | 49 | Track Control knob 2 ring/value |
| Track Knob 3 | Not banked | `0x32` | 50 | Track Control knob 3 ring/value |
| Track Knob 4 | Not banked | `0x33` | 51 | Track Control knob 4 ring/value |
| Track Knob 5 | Not banked | `0x34` | 52 | Track Control knob 5 ring/value |
| Track Knob 6 | Not banked | `0x35` | 53 | Track Control knob 6 ring/value |
| Track Knob 7 | Not banked | `0x36` | 54 | Track Control knob 7 ring/value |
| Track Knob 8 | Not banked | `0x37` | 55 | Track Control knob 8 ring/value |

### 7.3 LED-ring style assignments

The host sets each ring's display style using a separate CC.

| Ring | Channel | Style CC hex | CC dec | Accepted value meaning |
|---|---|---:|---:|---|
| Device Knob 1 | 0–8 in Mode 0 | `0x18` | 24 | `0` off, `1` Single, `2` Volume, `3` Pan, `4`–`127` Single |
| Device Knob 2 | 0–8 in Mode 0 | `0x19` | 25 | Same |
| Device Knob 3 | 0–8 in Mode 0 | `0x1A` | 26 | Same |
| Device Knob 4 | 0–8 in Mode 0 | `0x1B` | 27 | Same |
| Device Knob 5 | 0–8 in Mode 0 | `0x1C` | 28 | Same |
| Device Knob 6 | 0–8 in Mode 0 | `0x1D` | 29 | Same |
| Device Knob 7 | 0–8 in Mode 0 | `0x1E` | 30 | Same |
| Device Knob 8 | 0–8 in Mode 0 | `0x1F` | 31 | Same |
| Track Knob 1 | Not banked | `0x38` | 56 | `0` off, `1` Single, `2` Volume, `3` Pan, `4`–`127` Single |
| Track Knob 2 | Not banked | `0x39` | 57 | Same |
| Track Knob 3 | Not banked | `0x3A` | 58 | Same |
| Track Knob 4 | Not banked | `0x3B` | 59 | Same |
| Track Knob 5 | Not banked | `0x3C` | 60 | Same |
| Track Knob 6 | Not banked | `0x3D` | 61 | Same |
| Track Knob 7 | Not banked | `0x3E` | 62 | Same |
| Track Knob 8 | Not banked | `0x3F` | 63 | Same |

> The source explicitly documents Track Control ring-style CCs `0x38`–`0x3F`. These are distinct from Track Control ring-value CCs `0x30`–`0x37`.

---

## 8. Exact LED-ring rendering

Each knob ring has 15 LEDs. The bit strings below list those LEDs **left to right**:

- `0` = LED off.
- `1` = LED on.
- Min/Max give the inclusive incoming controller-value range producing that pattern.

### 8.1 Single style

Single style actually alternates between one and two neighboring LEDs to provide 29 visual positions across 15 LEDs.

| Min | Max | 15 LED states, left → right |
|---:|---:|---|
| 0 | 3 | `100000000000000` |
| 4 | 8 | `110000000000000` |
| 9 | 12 | `010000000000000` |
| 13 | 17 | `011000000000000` |
| 18 | 21 | `001000000000000` |
| 22 | 25 | `001100000000000` |
| 26 | 30 | `000100000000000` |
| 31 | 34 | `000110000000000` |
| 35 | 38 | `000010000000000` |
| 39 | 43 | `000011000000000` |
| 44 | 47 | `000001000000000` |
| 48 | 52 | `000001100000000` |
| 53 | 56 | `000000100000000` |
| 57 | 60 | `000000110000000` |
| 61 | 65 | `000000010000000` |
| 66 | 69 | `000000011000000` |
| 70 | 73 | `000000001000000` |
| 74 | 78 | `000000001100000` |
| 79 | 82 | `000000000100000` |
| 83 | 87 | `000000000110000` |
| 88 | 91 | `000000000010000` |
| 92 | 95 | `000000000011000` |
| 96 | 100 | `000000000001000` |
| 101 | 104 | `000000000001100` |
| 105 | 108 | `000000000000100` |
| 109 | 113 | `000000000000110` |
| 114 | 117 | `000000000000010` |
| 118 | 122 | `000000000000011` |
| 123 | 127 | `000000000000001` |

### 8.2 Volume style

Volume style is a left-to-right cumulative bar. Value `0` turns all LEDs off; `127` lights all 15.

| Min | Max | 15 LED states, left → right |
|---:|---:|---|
| 0 | 0 | `000000000000000` |
| 1 | 9 | `100000000000000` |
| 10 | 18 | `110000000000000` |
| 19 | 27 | `111000000000000` |
| 28 | 36 | `111100000000000` |
| 37 | 45 | `111110000000000` |
| 46 | 54 | `111111000000000` |
| 55 | 63 | `111111100000000` |
| 64 | 71 | `111111110000000` |
| 72 | 80 | `111111111000000` |
| 81 | 89 | `111111111100000` |
| 90 | 98 | `111111111110000` |
| 99 | 107 | `111111111111000` |
| 108 | 116 | `111111111111100` |
| 117 | 126 | `111111111111110` |
| 127 | 127 | `111111111111111` |

### 8.3 Pan style

Pan style uses LED 8 (the center bit in the 15-bit string) as the center/reference. Values below center illuminate progressively farther left through center; values above center illuminate progressively right from center.

| Min | Max | 15 LED states, left → right |
|---:|---:|---|
| 0 | 8 | `111111110000000` |
| 9 | 17 | `011111110000000` |
| 18 | 26 | `001111110000000` |
| 27 | 35 | `000111110000000` |
| 36 | 44 | `000011110000000` |
| 45 | 53 | `000001110000000` |
| 54 | 62 | `000000110000000` |
| 63 | 64 | `000000010000000` |
| 65 | 73 | `000000011000000` |
| 74 | 82 | `000000011100000` |
| 83 | 91 | `000000011110000` |
| 92 | 100 | `000000011111000` |
| 101 | 109 | `000000011111100` |
| 110 | 118 | `000000011111110` |
| 119 | 127 | `000000011111111` |

---

## 9. Inbound messages: APC40 → host

Inbound messages report control-surface events and responses to host requests. Standard MIDI event messages contain:

- A Control ID identifying the physical control.
- A data field containing either an absolute value or a relative change.

Three inbound standard-MIDI types are defined:

1. **NOTE1:** Button Note On/Off.
2. **CC1:** Absolute Control Change.
3. **CC2:** Relative Control Change.

## 10. Inbound NOTE1: button press/release

Two-state transitions use:

- Note On when a button is depressed.
- Note Off when a button is released.
- Note number as Control ID.

In Modes 1 and 2, **all buttons act as momentary buttons**.

### 10.1 Press message

| Byte | Value | Meaning |
|---:|---|---|
| 1 | `0x9<chan>` | Note On; channel selects track/context where applicable |
| 2 | `<ControlID>` | Button note number |
| 3 | `0x7F` | Nonzero press value |

### 10.2 Release message

| Byte | Value | Meaning |
|---:|---|---|
| 1 | `0x8<chan>` | Note Off; channel selects track/context where applicable |
| 2 | `<ControlID>` | Button note number |
| 3 | `0x7F` | Ignored release data value |

### 10.3 Button assignments and Mode 0 semantics

The source says notes `0x30`–`0x49` use channels `0`–`7` for Tracks 1–8, while all other notes ignore channel. Within that range, its table explicitly gives channels `0`–`8` only for `0x3A`–`0x41` in Mode 0 and no assignments for `0x42`–`0x49`.

| Control | Channel/context | Note hex | Dec | Mode 0 button type |
|---|---|---:|---:|---|
| Record Arm | 0–7 = Tracks 1–8 | `0x30` | 48 | Toggle |
| Solo | 0–7 = Tracks 1–8 | `0x31` | 49 | Toggle |
| Activator | 0–7 = Tracks 1–8 | `0x32` | 50 | Toggle |
| Track Selection | 0–7 = Tracks 1–8 | `0x33` | 51 | N/A; internal radio selection does not report its state in Mode 0 |
| Clip Stop | 0–7 = Tracks 1–8 | `0x34` | 52 | Momentary |
| Clip Launch row 1 | 0–7 = Tracks 1–8 | `0x35` | 53 | Momentary |
| Clip Launch row 2 | 0–7 = Tracks 1–8 | `0x36` | 54 | Momentary |
| Clip Launch row 3 | 0–7 = Tracks 1–8 | `0x37` | 55 | Momentary |
| Clip Launch row 4 | 0–7 = Tracks 1–8 | `0x38` | 56 | Momentary |
| Clip Launch row 5 | 0–7 = Tracks 1–8 | `0x39` | 57 | Momentary |
| Clip/Track (1) | 0–8 = Track 1–8/Master; Mode 0 only | `0x3A` | 58 | Toggle |
| Device On/Off (2) | 0–8 = Track 1–8/Master; Mode 0 only | `0x3B` | 59 | Toggle |
| Left arrow (3) | 0–8 = Track 1–8/Master; Mode 0 only | `0x3C` | 60 | Toggle |
| Right arrow (4) | 0–8 = Track 1–8/Master; Mode 0 only | `0x3D` | 61 | Toggle |
| Detail View (5) | 0–8 = Track 1–8/Master; Mode 0 only | `0x3E` | 62 | Momentary |
| Rec Quantization (6) | 0–8 = Track 1–8/Master; Mode 0 only | `0x3F` | 63 | Momentary |
| MIDI Overdub (7) | 0–8 = Track 1–8/Master; Mode 0 only | `0x40` | 64 | Momentary |
| Metronome (8) | 0–8 = Track 1–8/Master; Mode 0 only | `0x41` | 65 | Momentary |
| Master Track Selection | Channel ignored/not stated | `0x50` | 80 | N/A |
| Stop All Clips | Channel ignored | `0x51` | 81 | Momentary |
| Scene Launch 1 | Channel ignored | `0x52` | 82 | Momentary |
| Scene Launch 2 | Channel ignored | `0x53` | 83 | Momentary |
| Scene Launch 3 | Channel ignored | `0x54` | 84 | Momentary |
| Scene Launch 4 | Channel ignored | `0x55` | 85 | Momentary |
| Scene Launch 5 | Channel ignored | `0x56` | 86 | Momentary |
| Pan | Channel ignored | `0x57` | 87 | Toggle |
| Send A | Channel ignored | `0x58` | 88 | Toggle |
| Send B | Channel ignored | `0x59` | 89 | Toggle |
| Send C | Channel ignored | `0x5A` | 90 | Toggle |
| Play | Channel ignored | `0x5B` | 91 | Momentary |
| Stop | Channel ignored | `0x5C` | 92 | Momentary |
| Record | Channel ignored | `0x5D` | 93 | Momentary |
| Up | Channel ignored | `0x5E` | 94 | Momentary |
| Down | Channel ignored | `0x5F` | 95 | Momentary |
| Right | Channel ignored | `0x60` | 96 | Momentary |
| Left | Channel ignored | `0x61` | 97 | Momentary |
| Shift | Channel ignored | `0x62` | 98 | Momentary |
| Tap Tempo | Channel ignored | `0x63` | 99 | Momentary |
| Nudge + | Channel ignored | `0x64` | 100 | Momentary |
| Nudge − | Channel ignored | `0x65` | 101 | Momentary |

> **Track Selection nuance:** The table lists Track Selection note `0x33`, but the Mode 0 behavior section says Track Selection buttons do not send MIDI for their state. Therefore `0x33` is relevant as a host-controlled LED and in host-owned modes, but a host must not expect Mode 0 selection-state events from those buttons.

---

## 11. Inbound CC1: absolute controls

Most continuous controls report absolute position with a standard Control Change message.

### 11.1 Message format

| Byte | Value | Meaning |
|---:|---|---|
| 1 | `0xB<chan>` | MIDI Control Change; channel selects track/context where applicable |
| 2 | `<ControlID>` | CC number/control identifier |
| 3 | `<Value>` | Absolute control value, `0`–`127` |

### 11.2 Absolute control assignments

| Control | Channel/context | CC hex | CC dec | Value notes |
|---|---|---:|---:|---|
| Track Level | 0–7 = Tracks 1–8 | `0x07` | 7 | Absolute fader position |
| Master Level | Not specified | `0x0E` | 14 | Absolute fader position |
| Crossfader | Not specified | `0x0F` | 15 | Absolute position |
| Device Knob 1 | 0–8 = Track 1–8/Master in Mode 0 | `0x10` | 16 | Absolute knob position |
| Device Knob 2 | 0–8 = Track 1–8/Master in Mode 0 | `0x11` | 17 | Absolute knob position |
| Device Knob 3 | 0–8 = Track 1–8/Master in Mode 0 | `0x12` | 18 | Absolute knob position |
| Device Knob 4 | 0–8 = Track 1–8/Master in Mode 0 | `0x13` | 19 | Absolute knob position |
| Device Knob 5 | 0–8 = Track 1–8/Master in Mode 0 | `0x14` | 20 | Absolute knob position |
| Device Knob 6 | 0–8 = Track 1–8/Master in Mode 0 | `0x15` | 21 | Absolute knob position |
| Device Knob 7 | 0–8 = Track 1–8/Master in Mode 0 | `0x16` | 22 | Absolute knob position |
| Device Knob 8 | 0–8 = Track 1–8/Master in Mode 0 | `0x17` | 23 | Absolute knob position |
| Track Knob 1 | Not banked/channel not specified | `0x30` | 48 | Absolute knob position |
| Track Knob 2 | Not banked/channel not specified | `0x31` | 49 | Absolute knob position |
| Track Knob 3 | Not banked/channel not specified | `0x32` | 50 | Absolute knob position |
| Track Knob 4 | Not banked/channel not specified | `0x33` | 51 | Absolute knob position |
| Track Knob 5 | Not banked/channel not specified | `0x34` | 52 | Absolute knob position |
| Track Knob 6 | Not banked/channel not specified | `0x35` | 53 | Absolute knob position |
| Track Knob 7 | Not banked/channel not specified | `0x36` | 54 | Absolute knob position |
| Track Knob 8 | Not banked/channel not specified | `0x37` | 55 | Absolute knob position |
| Footswitch 1 | Channel not specified | `0x40` | 64 | `0x7F` depressed; `0x00` released |
| Footswitch 2 | Channel not specified | `0x43` | 67 | `0x7F` depressed; `0x00` released |

Mode 0 bank-switch behavior is especially important: after selecting Track 1–8 or Master, the APC40 sends all eight Device Knob positions on the corresponding channel.

---

## 12. Inbound CC2: relative controls

Some controls report movement since the previous report rather than absolute position. The APC40 uses a standard Control Change message whose value encodes a signed delta.

### 12.1 Message format

| Byte | Value | Meaning |
|---:|---|---|
| 1 | `0xB<chan>` | MIDI Control Change |
| 2 | `<ControlID>` | Relative control's CC number |
| 3 | `<Change>` | Encoded relative delta |

### 12.2 Delta encoding

| Data value | Interpretation |
|---:|---|
| `0x00` | No change; control is stationary |
| `0x01` | Increment by 1 since last report |
| `0x02` | Increment by 2 |
| … | … |
| `0x3F` | Increment by 63 |
| `0x40` | Decrement by 64 |
| `0x41` | Decrement by 63 |
| … | … |
| `0x7E` | Decrement by 2 |
| `0x7F` | Decrement by 1 |

Equivalent decoding rule for 7-bit value `v`:

```text
if v == 0:       delta = 0
if 1 <= v <= 63: delta = v
if 64 <= v <= 127: delta = v - 128
```

Thus positive values are `0x01`–`0x3F`; negative values are `0x40`–`0x7F` and represent `-64` through `-1`.

### 12.3 Relative controller assignment

| Control | CC hex | CC dec | Notes |
|---|---:|---:|---|
| Cue Level | `0x2F` | 47 | Relative delta encoding above |

---

## 13. Consolidated machine-oriented map

### 13.1 Note controls

| Decimal range/value | Hex | Direction | Channel semantics | Function |
|---:|---:|---|---|---|
| 48–52 | `0x30`–`0x34` | In + Out | 0–7 tracks | Arm, Solo, Activator, Select, Clip Stop |
| 53–57 | `0x35`–`0x39` | In + Out | 0–7 tracks | Clip Launch rows 1–5 |
| 58–65 | `0x3A`–`0x41` | In + Out | 0–8 Mode 0 bank context per explicit rows | Device Control buttons 1–8 |
| 80 | `0x50` | In + Out | Global/ignored | Master selection/LED |
| 81 | `0x51` | In; outbound not listed | Global/ignored | Stop All Clips |
| 82–86 | `0x52`–`0x56` | In + Out | Global/ignored | Scene Launch 1–5 |
| 87–90 | `0x57`–`0x5A` | In + Out | Global/ignored | Pan, Send A, Send B, Send C |
| 91–101 | `0x5B`–`0x65` | In; outbound not listed | Global/ignored | Transport/navigation/Shift/Tap/Nudge |

### 13.2 CC controls

| CC decimal | Hex | Direction | Function |
|---:|---:|---|---|
| 7 | `0x07` | In + Out | Track Level, channel-selected |
| 14 | `0x0E` | In + Out | Master Level |
| 15 | `0x0F` | In + Out | Crossfader |
| 16–23 | `0x10`–`0x17` | In + Out | Device Knobs 1–8 values |
| 24–31 | `0x18`–`0x1F` | Out | Device Knobs 1–8 ring styles |
| 47 | `0x2F` | In | Cue Level relative delta |
| 48–55 | `0x30`–`0x37` | In + Out | Track Knobs 1–8 values |
| 56–63 | `0x38`–`0x3F` | Out | Track Knobs 1–8 ring styles |
| 64 | `0x40` | In | Footswitch 1 |
| 67 | `0x43` | In | Footswitch 2 |

### 13.3 Core byte patterns

```text
APC40 introduction:
F0 47 <device> 73 60 00 04 <mode> <major> <minor> <bugfix> F7

LED on/state:
9<channel> <note> <state>

LED off (preferred):
8<channel> <note> <ignored>

Button pressed inbound:
9<channel> <note> 7F

Button released inbound:
8<channel> <note> 7F

Absolute control or ring update in either documented direction:
B<channel> <cc> <value>

Relative Cue Level inbound:
B<channel> 2F <encoded-delta>
```

---

## 14. Protocol caveats and faithful-source notes

1. **Mode matters.** Generic Mode has local toggle/radio/banking behavior; Modes 1 and 2 make every button momentary and differ in LED ownership.
2. **Initialize first.** Send Type 0 before other APC40-specific messages; Device Inquiry is the exception.
3. **Use broadcast device ID `0x7F`.** This is the source's recommended value for the expected one-device setup.
4. **Prefer Note Off for LED off.** Note On velocity zero is accepted as equivalent, but is not the source's preferred representation.
5. **Do not generalize clip colors.** Values `3`–`6` have red/yellow meanings only for Clip Launch LEDs. Clip Stop and Scene Launch have their own simpler blink encodings.
6. **Do not infer output capability from input capability.** The inbound table includes Stop All Clips and transport/navigation controls that the outbound LED table does not list.
7. **Preserve channel specificity.** Track strips/grid use channels 0–7. Mode 0 Device Controls explicitly use 0–8 for nine banks.
8. **The source has a channel-rule tension.** It says notes outside `0x30`–`0x39` ignore channel, while explicitly assigning channels 0–8 to Mode 0 notes `0x3A`–`0x41`.
9. **Musical note labels in the PDF contain typographic/OCR inconsistencies.** Numeric note IDs are authoritative in this reference; musical labels were normalized from the numeric MIDI notes.
10. **Arrow glyphs were damaged in extraction.** Physical labels and ordering establish `0x3C` as left-arrow button (3) and `0x3D` as right-arrow button (4), matching the descriptive Mode 0 sequence.
11. **Track ring-style CCs are documented.** The source explicitly maps Track Knob ring styles to CC `0x38`–`0x3F`.
12. **No timing or acknowledgment requirements are specified.** Apart from Device Inquiry response and the instruction to send Introduction first, the document defines no retry, timeout, rate-limit, checksum, or acknowledgment mechanism.

---

## 15. Implementation checklist

- [ ] Optionally send universal Device Inquiry and parse all 25 response data bytes.
- [ ] Send Introduction SysEx with selected mode and application version before normal APC40-specific communication.
- [ ] Treat protocol channels as zero-based.
- [ ] Decode Note On `0x7F` as press and Note Off as release.
- [ ] Respect Mode 0 local toggle/radio behavior and absent Track Selection state messages.
- [ ] Handle Device Control's nine Mode 0 channel banks and eight-position dump after bank selection.
- [ ] Preserve independent, non-banked Track Control knobs/buttons.
- [ ] Encode clip-grid LED values exactly as `0`–`6`/`7`–`127` specified.
- [ ] Encode Clip Stop and Scene Launch blink states separately from clip colors.
- [ ] Support Device ring value CCs `16`–`23` and style CCs `24`–`31`.
- [ ] Support Track ring value CCs `48`–`55` and style CCs `56`–`63`.
- [ ] Decode Cue Level CC `47` as signed 7-bit relative movement (`v <= 63 ? v : v - 128`).
- [ ] Decode both footswitches as absolute `0x7F` pressed / `0x00` released.
- [ ] Avoid claiming host LED support where the outbound table is silent.

---

## 16. Document history

| Date | Change | Author |
|---|---|---|
| May 1, 2009 | First draft based on APC40 document | Alex Souppa |
