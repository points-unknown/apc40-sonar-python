"""Mackie Control Universal protocol: encode and decode.

Authority: ``docs/mcu-mapping.md`` (standard MCU message set as implemented by
Cakewalk's Mackie Control surface in Universal mode).

All messages use MIDI channel 0 unless noted; faders use channels 0-8 (eight
strips plus master). This module is pure protocol - it builds and parses raw
MIDI messages and never touches a port.

Key correction over the Lua prototype: button presses are a **real Note On
(velocity 127)** and releases are a **real Note Off (0x80)**. The MIDIMonster
``winmidi`` backend could only emit Note On velocity 0, which Cakewalk counted
as a second press and double-toggled.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

CHANNEL = 0

# ---------------------------------------------------------------------------
# Note numbers
# ---------------------------------------------------------------------------

NOTE_REC1 = 0  # 0-7
NOTE_SOLO1 = 8  # 8-15
NOTE_MUTE1 = 16  # 16-23
NOTE_SELECT1 = 24  # 24-31
NOTE_VPOT_PUSH1 = 32  # 32-39

NOTE_ASSIGN_TRACK = 40
NOTE_ASSIGN_SEND = 41
NOTE_ASSIGN_PAN = 42
NOTE_ASSIGN_PLUGIN = 43
NOTE_ASSIGN_EQ = 44
NOTE_ASSIGN_INSTRUMENT = 45

NOTE_BANK_LEFT = 46
NOTE_BANK_RIGHT = 47
NOTE_CHANNEL_LEFT = 48
NOTE_CHANNEL_RIGHT = 49
NOTE_FLIP = 50
NOTE_GLOBAL = 51
NOTE_NAME_VALUE = 52
NOTE_F1 = 54  # F1-F8 = 54-61; Cakewalk runs the command assigned on its surface page

# Modifiers M1-M4 (Cakewalk: M1 Ctrl, M2 Option, M3 Snapshot, M4 Shift). Held
# while another button is pressed. Cakewalk only honors them with its default
# "Mackie Control" protocol; Universal protocol drops notes 70-73.
NOTE_M1 = 70
NOTE_M2 = 71
NOTE_M3 = 72
NOTE_M4 = 73

NOTE_SAVE = 80
NOTE_UNDO = 81
NOTE_CANCEL = 82
NOTE_ENTER = 83
NOTE_MARKERS = 84
NOTE_NUDGE = 85
NOTE_CYCLE = 86
NOTE_DROP = 87
NOTE_REPLACE = 88
NOTE_CLICK = 89
NOTE_SOLO_GLOBAL = 90
NOTE_REWIND = 91
NOTE_FORWARD = 92
NOTE_STOP = 93
NOTE_PLAY = 94
NOTE_RECORD = 95
NOTE_UP = 96
NOTE_DOWN = 97
NOTE_LEFT = 98
NOTE_RIGHT = 99
NOTE_ZOOM = 100
NOTE_SCRUB = 101

# Cakewalk's own meaning ("Cakewalk/SONAR Mode" protocol) where it differs from
# the standard MCU labels above. Cakewalk has no Click (metronome) button.
NOTE_CW_LOOP = 89  # standard "Click": transport loop on/off; LED = loop state
NOTE_CW_HOME = 90  # standard "Solo": go to start
NOTE_CW_DYNAMICS = 45  # standard "Instrument": Dynamics assignment
NOTE_CW_EDIT = 51  # standard "Global": Edit mode (Bank/Channel move the parameter)

NOTE_FADER_TOUCH1 = 104  # 104-111, master = 112
NOTE_MASTER_FADER_TOUCH = 112

FADER_MASTER_CHANNEL = 8  # Pitch Bend channel of the master fader

# ---------------------------------------------------------------------------
# Control Change numbers
# ---------------------------------------------------------------------------

CC_VPOT1 = 16  # 16-23: V-pot rotation
CC_RING1 = 48  # 48-55: V-pot LED ring
CC_JOG = 60
CC_TIMECODE1 = 64  # 64-75
CC_ASSIGN1 = 74  # 74-75

# ---------------------------------------------------------------------------
# LED / button velocities and ring encoding
# ---------------------------------------------------------------------------

BUTTON_PRESS_VELOCITY = 127
LED_OFF = 0
LED_BLINK = 1
LED_SOLID = 127

RELATIVE_POSITIVE_LIMIT = 0x3F  # +63
RELATIVE_NEGATIVE_LIMIT = 0x3F  # -63 (0x40 would be -64)
RELATIVE_NEGATIVE_BASE = 0x40

RING_MODE_SINGLE = 0b00
RING_MODE_PAN = 0b01
RING_MODE_VOLUME = 0b10
RING_MODE_CENTERED = 0b11

RING_VALUE_MAX = 11

# Channel meters: Channel Pressure ``0xD0 <sv>``, s = strip 0-7, v = level.
METER_LEVEL_MAX = 0x0D  # 100 % (> 0 dB); 0x0C is 0 dB
METER_OVERLOAD_SET = 0x0E
METER_OVERLOAD_CLEAR = 0x0F


# ---------------------------------------------------------------------------
# Raw message builders
# ---------------------------------------------------------------------------


def note_on(note: int, velocity: int = BUTTON_PRESS_VELOCITY, channel: int = CHANNEL) -> tuple[int, int, int]:
    return (0x90 | (channel & 0x0F), note & 0x7F, velocity & 0x7F)


def note_off(note: int, velocity: int = 0, channel: int = CHANNEL) -> tuple[int, int, int]:
    """Build a *real* Note Off (0x80) - the fix for the double-toggle bug."""

    return (0x80 | (channel & 0x0F), note & 0x7F, velocity & 0x7F)


def control_change(cc: int, value: int, channel: int = CHANNEL) -> tuple[int, int, int]:
    return (0xB0 | (channel & 0x0F), cc & 0x7F, value & 0x7F)


def pitch_bend(channel: int, value: int) -> tuple[int, int, int]:
    """Build a 14-bit Pitch Bend message (0 = bottom, 16383 = top)."""

    v = max(0, min(16383, int(value)))
    return (0xE0 | (channel & 0x0F), v & 0x7F, (v >> 7) & 0x7F)


# ---------------------------------------------------------------------------
# Semantic encoders
# ---------------------------------------------------------------------------


def button_press(note: int, channel: int = CHANNEL) -> tuple[int, int, int]:
    return note_on(note, BUTTON_PRESS_VELOCITY, channel)


def button_release(note: int, channel: int = CHANNEL) -> tuple[int, int, int]:
    return note_off(note, 0, channel)


def cakewalk_release(note: int, channel: int = CHANNEL) -> tuple[int, int, int]:
    """A button release Cakewalk actually sees: Note On velocity 0.

    Cakewalk's Mackie Control only dispatches status 0x90 to its button
    handler, so a real Note Off is silently dropped. That is harmless for
    ordinary buttons (only the press acts) but breaks anything Cakewalk acts
    on at release: a held modifier stays stuck on, and Loop (which toggles on
    release) never toggles.
    """

    return note_on(note, 0, channel)


def jog(forward: bool) -> tuple[int, int, int]:
    """One jog-wheel step. Cakewalk reads only the direction bit (0x40 = back)
    and moves the now time by its Jog Wheel Resolution per message."""

    return control_change(CC_JOG, 0x01 if forward else 0x41)


def fader_from_7bit(channel: int, value7: int) -> tuple[int, int, int]:
    """Scale an APC40 7-bit fader value (0-127) to a 14-bit MCU Pitch Bend."""

    v7 = max(0, min(127, int(value7)))
    value14 = round(v7 / 127 * 16383)
    return pitch_bend(channel, value14)


def vpot_relative_value(delta: int) -> int | None:
    """Encode a signed V-pot delta as a single relative CC value.

    ``0x01``-``0x3F`` are +1..+63 and ``0x41``-``0x7F`` are -1..-63. Deltas are
    clamped to +/-63 so one event never exceeds a single message. Returns
    ``None`` for a zero delta.
    """

    if delta == 0:
        return None
    if delta > 0:
        return min(delta, RELATIVE_POSITIVE_LIMIT)
    return RELATIVE_NEGATIVE_BASE + min(-delta, RELATIVE_NEGATIVE_LIMIT)


def vpot_delta(vpot: int, delta: int) -> tuple[int, int, int] | None:
    """Build the relative CC for V-pot rotation.

    *vpot* is 1-8 and maps to CC 16-23. Returns ``None`` when *delta* is 0.
    """

    value = vpot_relative_value(delta)
    if value is None:
        return None
    return control_change(CC_VPOT1 + (vpot - 1), value)


def ring_byte(mode: int, value: int, led: bool = False) -> int:
    """Pack a V-pot ring byte: bit6 LED, bits5-4 mode, bits3-0 value."""

    return ((1 if led else 0) << 6) | ((mode & 0x03) << 4) | (value & 0x0F)


def ring_message(cc: int, mode: int, value: int, led: bool = False) -> tuple[int, int, int]:
    return control_change(cc, ring_byte(mode, value, led))


# ---------------------------------------------------------------------------
# Decoding
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RingValue:
    """Decoded V-pot ring byte."""

    mode: int
    value: int
    led: bool


@dataclass(frozen=True)
class DecodedMessage:
    """A parsed incoming MIDI message.

    ``kind`` is one of ``note_on``, ``note_off``, ``cc``, ``pitch_bend``,
    ``pressure`` (channel pressure) or ``sysex``. ``number`` is the note or CC
    number (0 for pitch bend, pressure and SysEx). ``value`` is the velocity,
    CC value, 14-bit pitch value, or pressure value (0 for SysEx, whose bytes
    are in ``raw``).
    """

    kind: str
    channel: int
    number: int
    value: int
    raw: tuple[int, ...]


def decode(message: Sequence[int]) -> DecodedMessage | None:
    """Parse a raw MIDI message. Returns ``None`` for unsupported types.

    Note On velocity 0 is normalized to ``note_off``, matching MIDI semantics.
    A complete SysEx message (``F0 ... F7``, the MCU LCD text) decodes as
    ``sysex``; other system messages are ignored.
    """

    raw = tuple(message)
    if len(raw) < 2:
        return None

    status = raw[0]
    if status == 0xF0 and raw[-1] == 0xF7:
        return DecodedMessage("sysex", 0, 0, 0, raw)
    if status >= 0xF0:
        return None

    kind = status & 0xF0
    channel = status & 0x0F

    if kind == 0x90:
        velocity = raw[2] if len(raw) > 2 else 0
        actual = "note_on" if velocity > 0 else "note_off"
        return DecodedMessage(actual, channel, raw[1] & 0x7F, velocity & 0x7F, raw)

    if kind == 0x80:
        velocity = raw[2] if len(raw) > 2 else 0
        return DecodedMessage("note_off", channel, raw[1] & 0x7F, velocity & 0x7F, raw)

    if kind == 0xB0:
        value = raw[2] if len(raw) > 2 else 0
        return DecodedMessage("cc", channel, raw[1] & 0x7F, value & 0x7F, raw)

    if kind == 0xE0:
        lsb = raw[1] & 0x7F
        msb = (raw[2] & 0x7F) if len(raw) > 2 else 0
        return DecodedMessage("pitch_bend", channel, 0, lsb | (msb << 7), raw)

    if kind == 0xD0:
        return DecodedMessage("pressure", channel, 0, raw[1] & 0x7F, raw)

    return None


def decode_ring(value: int) -> RingValue:
    """Decode a V-pot ring CC value byte."""

    v = value & 0x7F
    return RingValue(mode=(v >> 4) & 0x03, value=v & 0x0F, led=bool((v >> 6) & 0x01))


@dataclass(frozen=True)
class MeterValue:
    """Decoded channel-meter pressure byte."""

    strip: int  # 0-7
    level: int  # 0-13, or METER_OVERLOAD_SET / METER_OVERLOAD_CLEAR


def decode_meter(value: int) -> MeterValue:
    """Split a meter Channel Pressure value into strip (high nibble) and level."""

    v = value & 0x7F
    return MeterValue(strip=(v >> 4) & 0x07, level=v & 0x0F)


def meter_message(strip: int, level: int) -> tuple[int, int]:
    """Build a meter Channel Pressure message (as Cakewalk sends it)."""

    return (0xD0 | CHANNEL, ((strip & 0x07) << 4) | (level & 0x0F))


def led_state(velocity: int) -> str:
    """Map an MCU LED velocity to ``"off"``, ``"blink"`` or ``"solid"``.

    MCU convention: 0 / any even value is off, any odd value except 0x7F is
    blink, and 0x7F is solid.
    """

    v = velocity & 0x7F
    if v == LED_SOLID:
        return "solid"
    if v == 0:
        return "off"
    return "blink" if v % 2 == 1 else "off"


def ring_value_to_position(value: int) -> int:
    """Scale an MCU ring value (0-11) to an APC40 ring position (0-127)."""

    v = max(0, min(RING_VALUE_MAX, value))
    return round(v / RING_VALUE_MAX * 127)
