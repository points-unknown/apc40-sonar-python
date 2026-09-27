# APC40 (Original) Output / LED Reference

Consolidated reference for **host-to-APC40** output (LEDs, colors, rings). This is the
authority the renderer in `src/apc40sonar/apc40.py` follows. Items marked **VERIFY** must be confirmed on hardware.

Source: Akai *Communications Protocol for Akai APC40 Controller* rev 1, plus behavior
validated by the startup lightshow fixture in [`reference/baseline/`](../reference/baseline/README.md).

> Do not confuse the original APC40 with the **APC40 mkII** or **APC Mini**. Their
> channels, colors, and capabilities differ.

## MIDI Channel Convention

The Akai protocol uses **zero-based** channels, as do python-rtmidi and `--monitor`
(`ch0`). Some MIDI tools display them one-based.

| Protocol / apc40sonar | One-based display | APC40 meaning |
|---:|---:|---|
| `ch0` | 1 | Track 1 |
| `ch1` | 2 | Track 2 |
| `ch2` | 3 | Track 3 |
| `ch3` | 4 | Track 4 |
| `ch4` | 5 | Track 5 |
| `ch5` | 6 | Track 6 |
| `ch6` | 7 | Track 7 |
| `ch7` | 8 | Track 8 |

Global controls (Scene, Master, transport, utility row) are emitted on `ch0`.

## Generic LED Behavior

- **Ordinary buttons** (single-color): Note On with nonzero velocity = **on**;
  Note Off (or Note On velocity 0) = **off**. The exact nonzero value usually does not
  matter.
- **Clip grid and Clip Stop**: special small velocity values select color/blink state
  (table below).

Example (raw bytes, as `--monitor` prints them; channel 0 = Track 1):

```text
[144, 48, 1]   Note On  note 48 value 1  -> Track 1 Record Arm LED on
[128, 48, 0]   Note Off note 48          -> Track 1 Record Arm LED off
[144, 53, 3]   Note On  note 53 value 3  -> Track 1 row 1 pad red
```

## Clip Grid and Clip Stop Color / State Values

| Value | Visual state |
|---:|---|
| 0 | Off |
| 1 | Green / solid on |
| 2 | Green blinking |
| 3 | Red (clip grid) |
| 4 | Red blinking (clip grid) |
| 5 | Amber / yellow (clip grid) |
| 6 | Amber blinking (clip grid) |

Apply this table only to the **clip grid** (notes 53-57 per track channel) and the
**Clip Stop** LEDs (note 52). Standard buttons are generally on/off.

## Per-Track Note Output (channels `ch0`-`ch7`)

| Note (dec) | Note (hex) | Control LED | State encoding |
|---:|---:|---|---|
| 48 | 0x30 | Record Arm | On/off |
| 49 | 0x31 | Solo | On/off |
| 50 | 0x32 | Activator (Mute) | On/off |
| 51 | 0x33 | Track Select | On/off |
| 52 | 0x34 | Clip Stop | Color/state table |
| 53 | 0x35 | Clip Launch row 1 | Color/state table |
| 54 | 0x36 | Clip Launch row 2 | Color/state table |
| 55 | 0x37 | Clip Launch row 3 | Color/state table |
| 56 | 0x38 | Clip Launch row 4 | Color/state table |
| 57 | 0x39 | Clip Launch row 5 | Color/state table |

The track is selected by MIDI channel, so Track 3 Clip Launch row 1 is
`apc40.ch2.note53`.

## Global Note Output (channel `ch0`)

| Note (dec) | Note (hex) | Control LED |
|---:|---:|---|
| 58 | 0x3A | Clip/Track |
| 59 | 0x3B | Device On/Off |
| 60 | 0x3C | Left Arrow |
| 61 | 0x3D | Right Arrow |
| 62 | 0x3E | Detail View |
| 63 | 0x3F | Rec Quantization |
| 64 | 0x40 | MIDI Overdub |
| 65 | 0x41 | Metronome |
| 80 | 0x50 | Master |
| 81 | 0x51 | Stop All Clips | **Not host-addressable (see below)** |
| 82 | 0x52 | Scene Launch 1 |
| 83 | 0x53 | Scene Launch 2 |
| 84 | 0x54 | Scene Launch 3 |
| 85 | 0x55 | Scene Launch 4 |
| 86 | 0x56 | Scene Launch 5 |
| 91 | 0x5B | Play |
| 92 | 0x5C | Stop |
| 93 | 0x5D | Record |
| 94-101 | 0x5E-0x65 | Up, Down, Right, Left, Shift, Tap Tempo, Nudge +, Nudge - (**VERIFY** host LED support) |

## Stop All Clips Limitation

The original APC40 accepts **Stop All Clips** as an input (note 81) but does **not**
expose a host-addressable LED for it. Sending note 81 does not illuminate the button.
Do not attempt LED feedback for it.

Recommended substitute acknowledgment: light the Stop transport LED briefly and blink all
eight Clip Stop LEDs.

## Encoder Ring Output (channel `ch0`)

### Track Control rings (position and style)

| Ring | Position CC (dec/hex) | Style CC (dec/hex) |
|---:|---:|---:|
| Track Control 1 | 48 / `0x30` | 56 / `0x38` |
| Track Control 2 | 49 / `0x31` | 57 / `0x39` |
| Track Control 3 | 50 / `0x32` | 58 / `0x3A` |
| Track Control 4 | 51 / `0x33` | 59 / `0x3B` |
| Track Control 5 | 52 / `0x34` | 60 / `0x3C` |
| Track Control 6 | 53 / `0x35` | 61 / `0x3D` |
| Track Control 7 | 54 / `0x36` | 62 / `0x3E` |
| Track Control 8 | 55 / `0x37` | 63 / `0x3F` |

### Device Control rings (position and style)

| Device knob | Position CC | Style CC |
|---:|---:|---:|
| Device Control 1 | 16 | 24 |
| Device Control 2 | 17 | 25 |
| Device Control 3 | 18 | 26 |
| Device Control 4 | 19 | 27 |
| Device Control 5 | 20 | 28 |
| Device Control 6 | 21 | 29 |
| Device Control 7 | 22 | 30 |
| Device Control 8 | 23 | 31 |

### Ring style values

| Style value | Display |
|---:|---|
| 0 | Off |
| 1 | Single LED / dot |
| 2 | Volume (bar) style |
| 3 | Pan (center) style |

### Track Control ring style — confirmed by the Akai protocol

The original Akai protocol explicitly assigns Track Control ring-style CCs `56`–`63`
(`0x38`–`0x3F`). They are distinct from position CCs `48`–`55`.

For Pan mode, send style value `3` to all eight style CCs. A position value of `63` or
`64` then displays the centered 12-o'clock Pan state. For Send/level modes, send style
value `2` for a cumulative volume bar.

## Input Summary (for reference)

The integration is bidirectional; these are the APC40-to-host messages the encoder consumes.

| APC40 control | Type | Identifier | Channel |
|---|---|---|---|
| Channel faders 1-8 | CC 7 | `cc7` | `ch0`-`ch7` |
| Track Control knobs 1-8 | CC 48-55 | `cc48`-`cc55` | `ch0` |
| Device Control knobs 1-8 | CC 16-23 | `cc16`-`cc23` | `ch0` |
| Record Arm / Solo / Activator / Select / Clip Stop | Notes 48-52 | `note48`-`note52` | per-track `ch0`-`ch7` |
| Clip grid rows 1-5 | Notes 53-57 | `note53`-`note57` | per-track `ch0`-`ch7` |
| Utility row (Clip/Track to Metronome) | Notes 58-65 | `note58`-`note65` | `ch0` |
| Master / Stop All Clips | Notes 80-81 | `note80`-`note81` | `ch0` |
| Scene 1-5 | Notes 82-86 | `note82`-`note86` | `ch0` |
| Transport | Notes 91-101 | `note91`-`note101` | `ch0` |

## Hardware Validation Checklist

Run `uv run apc40sonar --monitor` to watch the traffic.

- [ ] Record Arm LED lights and clears (note 48, any nonzero / off)
- [ ] Solo, Activator, Select LEDs light and clear (notes 49-51)
- [ ] Clip Stop LED shows solid and blink (value 1 and 2)
- [ ] Clip grid shows all six color/state values (0-6)
- [ ] Scene LEDs light (notes 82-86)
- [ ] Master LED lights (note 80)
- [ ] Play / Stop / Record LEDs light (notes 91-93)
- [ ] Track Control rings render position from CC 48-55
- [ ] Track Control rings change style from CC 56-63 (`3` Pan, `2` Volume)
- [ ] Device Control rings render position from CC 16-23
- [ ] Device Control ring styles change rendering from CC 24-31 (0-3)
- [ ] Determine whether Track Control rings accept a style CC (**VERIFY**)
- [ ] Confirm Stop All Clips (note 81) does not light
