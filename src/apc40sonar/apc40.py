"""Akai APC40 (original) protocol: notes, colors, ring positions and styles.

Authority: ``docs/apc40-output-reference.md`` and
``docs/apc40-communications-protocol.md`` (Akai rev 1). This module is pure
protocol: it knows note/CC numbers and builds raw MIDI messages. Sending is
delegated to a caller-supplied callable, which keeps the encoding testable
without hardware.

Channel convention (zero-based, matching the Akai protocol and rtmidi):

* channels 0-7 select tracks 1-8 for the strip and clip-grid messages;
* global controls (utility row, Master, Scenes, transport) use channel 0.

The MIDI channel is part of the message, not a separate argument, for the
per-track messages: e.g. Track 1 Record Arm is ``note_on(0, 48, 127)``.
"""

from __future__ import annotations

from typing import Callable, Sequence

TRACKS = 8
ROWS = 5
# Device Control banks: Tracks 1-8 plus Master. The Device Control buttons
# (notes 58-65) and knobs (CC 16-23) report on the selected bank's channel
# (0-7, or 8 for Master), and their LEDs are stored per bank.
DEVICE_BANKS = 9

# ---------------------------------------------------------------------------
# Per-track note numbers (sent on channels 0-7)
# ---------------------------------------------------------------------------

NOTE_RECORD_ARM = 48
NOTE_SOLO = 49
NOTE_ACTIVATOR = 50  # mute
NOTE_TRACK_SELECT = 51
NOTE_CLIP_STOP = 52
NOTE_CLIP_ROW1 = 53  # rows 1-5 -> notes 53-57

# ---------------------------------------------------------------------------
# Global note numbers (channel 0)
# ---------------------------------------------------------------------------

NOTE_UTIL_CLIP_TRACK = 58
NOTE_UTIL_DEVICE_ONOFF = 59
NOTE_UTIL_LEFT_ARROW = 60
NOTE_UTIL_RIGHT_ARROW = 61
NOTE_UTIL_DETAIL_VIEW = 62
NOTE_UTIL_REC_QUANT = 63
NOTE_UTIL_OVERDUB = 64
NOTE_UTIL_METRONOME = 65
NOTE_MASTER = 80
NOTE_STOP_ALL_CLIPS = 81  # input only; no host-addressable LED
NOTE_SCENE1 = 82  # scenes 1-5 -> notes 82-86
NOTE_PAN = 87
NOTE_SEND_A = 88
NOTE_SEND_B = 89
NOTE_SEND_C = 90
NOTE_PLAY = 91
NOTE_STOP = 92
NOTE_RECORD = 93
NOTE_UP = 94
NOTE_DOWN = 95
NOTE_RIGHT = 96
NOTE_LEFT = 97
NOTE_SHIFT = 98
NOTE_TAP_TEMPO = 99
NOTE_NUDGE_PLUS = 100
NOTE_NUDGE_MINUS = 101

NOTE_UTIL_ROW = (
    NOTE_UTIL_CLIP_TRACK,
    NOTE_UTIL_DEVICE_ONOFF,
    NOTE_UTIL_LEFT_ARROW,
    NOTE_UTIL_RIGHT_ARROW,
    NOTE_UTIL_DETAIL_VIEW,
    NOTE_UTIL_REC_QUANT,
    NOTE_UTIL_OVERDUB,
    NOTE_UTIL_METRONOME,
)
SCENE_NOTES = tuple(NOTE_SCENE1 + i for i in range(5))
TRANSPORT_NOTES = (NOTE_PLAY, NOTE_STOP, NOTE_RECORD)
NAV_NOTES = (NOTE_UP, NOTE_DOWN, NOTE_LEFT, NOTE_RIGHT)

# ---------------------------------------------------------------------------
# Control Change numbers
# ---------------------------------------------------------------------------

CC_TRACK_LEVEL = 7  # channel faders, per-track channel 0-7
CC_MASTER_LEVEL = 14  # master fader (channel not significant)
CC_CROSSFADER = 15  # crossfader (channel not significant)
CC_CUE_LEVEL = 47  # Cue Level knob: relative, two's-complement delta

CC_DEVICE_KNOB1 = 16  # 16-23: Device Control positions
CC_DEVICE_RING_STYLE1 = 24  # 24-31: Device Control ring styles

CC_TRACK_KNOB1 = 48  # 48-55: Track Control positions
CC_TRACK_RING_STYLE1 = 56  # 56-63: Track Control ring styles

# ---------------------------------------------------------------------------
# Clip grid / Clip Stop color-state values
# ---------------------------------------------------------------------------

CLIP_OFF = 0
CLIP_GREEN = 1
CLIP_GREEN_BLINK = 2
CLIP_RED = 3
CLIP_RED_BLINK = 4
CLIP_YELLOW = 5
CLIP_YELLOW_BLINK = 6

# ---------------------------------------------------------------------------
# LED-ring styles (CC 24-31 and 56-63)
# ---------------------------------------------------------------------------

RING_OFF = 0
RING_SINGLE = 1
RING_VOLUME = 2
RING_PAN = 3

# Ordinary LED on/off velocities.
LED_OFF = 0
LED_ON = 127

# ---------------------------------------------------------------------------
# System Exclusive: Type 0 introduction / operating mode
# ---------------------------------------------------------------------------

SYSEX_START = 0xF0
SYSEX_END = 0xF7
AKAI_MANUFACTURER_ID = 0x47
APC40_PRODUCT_ID = 0x73
APC40_INTRODUCTION = 0x60  # Type 0 message identifier
DEVICE_ID_BROADCAST = 0x7F

MODE_GENERIC = 0x40
MODE_ABLETON = 0x41
MODE_ALT_ABLETON = 0x42

MODE_BY_NAME = {
    "generic": MODE_GENERIC,
    "ableton": MODE_ABLETON,
    "alt-ableton": MODE_ALT_ABLETON,
    "alternate-ableton": MODE_ALT_ABLETON,
    "altableton": MODE_ALT_ABLETON,
}


def resolve_mode(value: str | int) -> int:
    """Resolve a mode name or numeric/hex string to its identifier byte."""

    if isinstance(value, int):
        mode = value
    else:
        text = value.strip().lower()
        if text in MODE_BY_NAME:
            return MODE_BY_NAME[text]
        mode = int(text, 0)  # accepts "0x41" and "65"

    if mode not in (MODE_GENERIC, MODE_ABLETON, MODE_ALT_ABLETON):
        raise ValueError(f"unknown APC40 mode: {value!r}")
    return mode


def build_introduction(
    mode: int = MODE_GENERIC,
    *,
    major: int = 0,
    minor: int = 1,
    bugfix: int = 0,
    device_id: int = DEVICE_ID_BROADCAST,
) -> tuple[int, ...]:
    """Build the Type 0 introduction/configuration SysEx message.

    Canonical form::

        F0 47 <DeviceID> 73 60 00 04 <Mode> <Major> <Minor> <Bugfix> F7

    The host should send this before any other APC40-specific message. The
    default Generic Mode (0x40) matches the validated prototype behavior; it is
    configurable so the device can instead be driven in Ableton Live Mode.
    """

    return (
        SYSEX_START,
        AKAI_MANUFACTURER_ID,
        device_id & 0x7F,
        APC40_PRODUCT_ID,
        APC40_INTRODUCTION,
        0x00,
        0x04,
        mode & 0x7F,
        major & 0x7F,
        minor & 0x7F,
        bugfix & 0x7F,
        SYSEX_END,
    )


# ---------------------------------------------------------------------------
# Raw message builders
# ---------------------------------------------------------------------------


def note_on(channel: int, note: int, velocity: int) -> tuple[int, int, int]:
    """Build a Note On message. ``velocity`` 0 is Note On velocity 0."""

    return (0x90 | (channel & 0x0F), note & 0x7F, velocity & 0x7F)


def note_off(channel: int, note: int, velocity: int = 0) -> tuple[int, int, int]:
    """Build a real Note Off message (0x80)."""

    return (0x80 | (channel & 0x0F), note & 0x7F, velocity & 0x7F)


def control_change(channel: int, cc: int, value: int) -> tuple[int, int, int]:
    """Build a Control Change message."""

    return (0xB0 | (channel & 0x0F), cc & 0x7F, value & 0x7F)


# ---------------------------------------------------------------------------
# Ring address helpers (1-based knob index -> CC)
# ---------------------------------------------------------------------------


def track_ring_cc(knob: int) -> int:
    """Track Control ring *position* CC for knob 1-8 (48-55)."""

    return CC_TRACK_KNOB1 + (knob - 1)


def track_ring_style_cc(knob: int) -> int:
    """Track Control ring *style* CC for knob 1-8 (56-63)."""

    return CC_TRACK_RING_STYLE1 + (knob - 1)


def device_ring_cc(knob: int) -> int:
    """Device Control ring *position* CC for knob 1-8 (16-23)."""

    return CC_DEVICE_KNOB1 + (knob - 1)


def device_ring_style_cc(knob: int) -> int:
    """Device Control ring *style* CC for knob 1-8 (24-31)."""

    return CC_DEVICE_RING_STYLE1 + (knob - 1)


# ---------------------------------------------------------------------------
# Output renderer
# ---------------------------------------------------------------------------


class Apc40Output:
    """Render APC40 LED/ring state, de-duplicating unless forced.

    * ``send`` receives a raw MIDI message (a 3-int sequence).
    * Identical consecutive writes to the same LED or ring are suppressed,
      which keeps feedback traffic low. Pass ``force=True`` for controls the
      device also drives locally (mode buttons, MCU-authoritative strip LEDs):
      their cached value can otherwise go stale and suppress a needed write.
    """

    def __init__(self, send: Callable[[Sequence[int]], None]) -> None:
        self._send = send
        self._last: dict[tuple[str, int, int], int] = {}

    def _emit(self, key: tuple[str, int, int], message: tuple[int, int, int], value: int, force: bool) -> None:
        if not force and self._last.get(key) == value:
            return
        self._send(message)
        self._last[key] = value

    def note(self, channel: int, note: int, velocity: int, *, force: bool = False) -> None:
        """Set a note LED. Velocity 0/off sends a real Note Off."""

        value = velocity & 0x7F
        key = ("note", channel & 0x0F, note & 0x7F)
        message = note_off(channel, note) if value == 0 else note_on(channel, note, value)
        self._emit(key, message, value, force)

    def cc(self, cc: int, value: int, *, channel: int = 0, force: bool = False) -> None:
        """Set a controller (LED ring position or style)."""

        v = value & 0x7F
        key = ("cc", channel & 0x0F, cc & 0x7F)
        self._emit(key, control_change(channel, cc, v), v, force)

    # -- semantic helpers -------------------------------------------------

    def strip_led(self, track: int, note: int, velocity: int, *, force: bool = False) -> None:
        """Record Arm / Solo / Activator / Select LED for *track* (0-7)."""

        self.note(track, note, velocity, force=force)

    def clip_pad(self, track: int, row: int, state: int, *, force: bool = False) -> None:
        """Clip Launch pad for *track* (0-7), *row* (1-5), color *state* 0-6."""

        self.note(track, NOTE_CLIP_ROW1 + (row - 1), state, force=force)

    def clip_stop(self, track: int, state: int, *, force: bool = False) -> None:
        """Clip Stop LED for *track* (0-7), color *state* 0-6."""

        self.note(track, NOTE_CLIP_STOP, state, force=force)

    def global_note(self, note: int, velocity: int, *, force: bool = False) -> None:
        """A global LED (utility row, Master, Scenes, transport).

        Utility-row LEDs are per Device Control bank, so they are written to
        all nine bank channels and stay visible whichever bank is selected.
        Every other global LED is on channel 0.
        """

        if note in NOTE_UTIL_ROW:
            for bank in range(DEVICE_BANKS):
                self.note(bank, note, velocity, force=force)
        else:
            self.note(0, note, velocity, force=force)

    def ring_position(self, cc: int, value: int, *, channel: int = 0, force: bool = False) -> None:
        """Set an LED-ring position (0-127) on *cc*.

        Device Control rings are stored per bank, so *channel* selects the
        bank (0-8); Track Control rings are not banked and use channel 0.
        """

        self.cc(cc, value, channel=channel, force=force)

    def ring_style(self, cc: int, style: int, *, channel: int = 0, force: bool = False) -> None:
        """Set an LED-ring style (0 off, 1 single, 2 volume, 3 pan) on *cc*."""

        self.cc(cc, style, channel=channel, force=force)

    def clear_all(self) -> None:
        """Turn off every host-addressable LED and ring.

        Stop All Clips (note 81) is intentionally omitted: the original APC40
        has no host-addressable LED for it.
        """

        for track in range(TRACKS):
            for row in range(1, ROWS + 1):
                self.clip_pad(track, row, CLIP_OFF, force=True)
            self.clip_stop(track, CLIP_OFF, force=True)
            for note in (NOTE_RECORD_ARM, NOTE_SOLO, NOTE_ACTIVATOR, NOTE_TRACK_SELECT):
                self.strip_led(track, note, LED_OFF, force=True)

        for note in NOTE_UTIL_ROW:
            self.global_note(note, LED_OFF, force=True)
        self.global_note(NOTE_MASTER, LED_OFF, force=True)
        for note in SCENE_NOTES:
            self.global_note(note, LED_OFF, force=True)
        for note in (NOTE_PLAY, NOTE_STOP, NOTE_RECORD, *NAV_NOTES, NOTE_SHIFT, NOTE_TAP_TEMPO,
                     NOTE_NUDGE_PLUS, NOTE_NUDGE_MINUS):
            self.global_note(note, LED_OFF, force=True)
        for note in (NOTE_PAN, NOTE_SEND_A, NOTE_SEND_B, NOTE_SEND_C):
            self.global_note(note, LED_OFF, force=True)

        for knob in range(1, TRACKS + 1):
            self.ring_position(track_ring_cc(knob), 0, force=True)
            self.ring_style(track_ring_style_cc(knob), RING_OFF, force=True)
            self.ring_position(device_ring_cc(knob), 0, force=True)
            self.ring_style(device_ring_style_cc(knob), RING_OFF, force=True)
