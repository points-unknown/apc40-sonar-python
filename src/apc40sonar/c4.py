"""Mackie Control C4 protocol (Cakewalk's second surface): encode and decode.

The APC40's Device Control knobs drive the first V-pot row of a *Mackie
Control C4* surface in Cakewalk, which binds that row to 8 parameters of the
selected track's current plug-in and reports their rings and names.

Authority is Cakewalk's Mackie Control source (Cakewalk Control Surface SDK,
``Surfaces/MackieControl/MackieControlC4*.cpp``); ``plans/c4-surface-plan.md``
cites file and line for every claim. Pure protocol and state - no ports.

* Handshake: Cakewalk ignores every C4 input until it receives a serial
  number reply (the C4 has no "Disable handshake" option).
* Buttons: Note On velocity 0x7F = press, any other velocity = release.
  Cakewalk drops real Note Off, so releases are Note On velocity 0.
* V-pots: ``B0 (8*row + col) v``; bit 6 of *v* = counter-clockwise, low
  nibble = speed 1-15 (0 would reverse the direction).
* Rings: ``B0 (0x20 + 8*row + col) byte``, the MCU ring byte; 0 = no
  parameter bound.
* LCDs: ``F0 00 00 66 17 (0x30 + row) offset chars F7``, 2 lines of 56
  characters per V-pot row, sent as changed spans.
"""

from __future__ import annotations

import re
from typing import Sequence

DEVICE_TYPE = 0x17
SYSEX_HEADER = (0xF0, 0x00, 0x00, 0x66)
CMD_WAKE_UP = 0x01
CMD_SERIAL_QUERY = 0x1A
CMD_SERIAL_REPLY = 0x1B
SERIAL = (0x41, 0x50, 0x43, 0x34, 0x30, 0x43, 0x34)  # "APC40C4"; any 7 bytes work

ROWS = 4
COLS = 8

# Buttons (also the LED ids for 0x00-0x08).
# Split (0x00) cycles the split modes, but Cakewalk drops every note-0 message
# (as it does MCU Rec 1), so the C4 always stays unsplit. LEDs 0x00-0x02 = split.
LOCK = 0x03
SPOT_ERASE = 0x04  # LED on = lower split has the focus
TRACK = 0x06  # held: V-pot pushes pick the strip type / assignment
CHANNEL_STRIP = 0x07
FUNCTION = 0x08
BANK_LEFT, BANK_RIGHT = 0x09, 0x0A  # parameter page -/+ 8 (with M1: first / last)
PARAM_LEFT, PARAM_RIGHT = 0x0B, 0x0C  # parameter -/+ 1
SHIFT = 0x0D  # = M1, shared with the main surface; shifts no parameters
SLOT_UP, SLOT_DOWN = 0x11, 0x12  # plug-in +/- 1 (with M1: last / first)
VPOT_PUSH1 = 0x20  # 0x20 + 8*row + col

# Held Track, V-pot push row 2 / column 4 = upper split assignment "Plugin".
PUSH_ASSIGN_PLUGIN = VPOT_PUSH1 + COLS + 3

# The only notes the app ever sends: other C4 buttons change state the main
# surface shares (Lock, Track Left/Right, the M2-M4 modifiers) or move the focus.
SWITCH_WHITELIST = frozenset({
    TRACK, CHANNEL_STRIP, FUNCTION, BANK_LEFT, BANK_RIGHT,
    PARAM_LEFT, PARAM_RIGHT, SHIFT, SLOT_UP, SLOT_DOWN, PUSH_ASSIGN_PLUGIN,
    VPOT_PUSH1,  # the plug-in's on/off switch on row 1 / column 1 (Device On/Off)
})

CC_RING1 = 0x20  # 0x20-0x3F; row 1 = 0x20-0x27
VPOT_SPEED_MAX = 15

LCD_ID1 = 0x30  # 0x30-0x33, one per V-pot row
LCD_WIDTH = 56
LCD_SIZE = 2 * LCD_WIDTH
CELL_WIDTH = 7

VPOTS = ROWS * COLS  # without a split all 32 are bound: parameters offset+0 ... offset+31

# Cakewalk's temporary first-row text after a plug-in or track change:
# 'Track 3: "Vox", Plugin 2: "Sonitus Delay"' or '... Plugin 3: --None--'.
# Names can be cut off at the 56th character.
BANNER_RE = re.compile(
    r'^(Track|Bus|Aux|Master|VMain)\s+(\S+):\s+"([^"]*)"?,\s+Plugin\s+(\d+):\s+(--None--|"([^"]*)"?)'
)


# ---------------------------------------------------------------------------
# Encoders
# ---------------------------------------------------------------------------


def button_press(button: int) -> tuple[int, int, int]:
    return (0x90, button & 0x7F, 0x7F)


def button_release(button: int) -> tuple[int, int, int]:
    """Note On velocity 0: Cakewalk drops real Note Off."""

    return (0x90, button & 0x7F, 0x00)


def click(button: int) -> list[tuple[int, int, int]]:
    return [button_press(button), button_release(button)]


def vpot_delta(row: int, col: int, delta: int) -> tuple[int, int, int] | None:
    """V-pot turn of *delta* steps; ``None`` for 0. The value is never 0 or 0x40."""

    if delta == 0:
        return None
    speed = min(abs(delta), VPOT_SPEED_MAX)
    value = speed | (0x40 if delta < 0 else 0)
    return (0xB0, (row * COLS + col) & 0x1F, value)


def serial_reply(serial: Sequence[int] = SERIAL) -> tuple[int, ...]:
    """The answer to Cakewalk's serial-number query; it enables the surface."""

    return (*SYSEX_HEADER, DEVICE_TYPE, CMD_SERIAL_REPLY, *(b & 0x7F for b in serial[:7]), 0xF7)


def wake_up() -> tuple[int, ...]:
    """Make Cakewalk forget the serial, query again and then refresh everything."""

    return (*SYSEX_HEADER, DEVICE_TYPE, CMD_WAKE_UP, 0xF7)


def assign_plugin_macro() -> list[tuple[int, int, int]]:
    """Upper split assignment = Plugin: hold Track, push V-pot 2/4, release Track."""

    return [
        button_press(TRACK),
        button_press(PUSH_ASSIGN_PLUGIN),
        button_release(PUSH_ASSIGN_PLUGIN),
        button_release(TRACK),
    ]


def with_shift(buttons: Sequence[int]) -> list[tuple[int, int, int]]:
    """Click *buttons* while M1 is held (Slot Down = first plug-in, Bank Left = first page)."""

    messages = [button_press(SHIFT)]
    for button in buttons:
        messages += click(button)
    messages.append(button_release(SHIFT))
    return messages


# ---------------------------------------------------------------------------
# Decoders
# ---------------------------------------------------------------------------


def is_serial_query(raw: Sequence[int]) -> bool:
    return len(raw) >= 7 and tuple(raw[:4]) == SYSEX_HEADER and raw[5] == CMD_SERIAL_QUERY


def parse_lcd(raw: Sequence[int]) -> tuple[int, int, str] | None:
    """``(row, offset, text)`` for a C4 LCD write, else ``None``."""

    if len(raw) < 8 or tuple(raw[:4]) != SYSEX_HEADER or raw[-1] != 0xF7:
        return None
    lcd = raw[5]
    if not LCD_ID1 <= lcd < LCD_ID1 + ROWS:
        return None
    offset = raw[6]
    if offset >= LCD_SIZE:
        return None
    text = "".join(chr(b) if 0x20 <= b <= 0x7E else " " for b in raw[7:-1])
    return lcd - LCD_ID1, offset, text[: LCD_SIZE - offset]


def parse_banner(text: str) -> tuple[str, int, str | None] | None:
    """``('Track 3: "Vox"', slot, plug-in or None)`` from a banner line, else ``None``."""

    match = BANNER_RE.match(text.strip())
    if match is None:
        return None
    kind, number, name, slot, rest, plugin = match.groups()
    strip = f'{kind} {number}: "{name.strip()}"'
    return strip, int(slot), None if rest == "--None--" else (plugin or "").strip()


class C4Display:
    """The four V-pot rows' LCDs: parameter names and values, and the banner.

    Without a split, Cakewalk binds all 32 V-pots to parameters 1-32 of the
    plug-in (row 1 = 1-8, row 2 = 9-16, ...); each row's LCD has the 8 names on
    line 0 and the values on line 1. For about a second after a plug-in or
    track change Cakewalk writes a banner over row 1's names, naming the track
    and plug-in. Writes are diffs, so each row's 112 characters are kept.
    """

    def __init__(self) -> None:
        self._rows = [[" "] * LCD_SIZE for _ in range(ROWS)]
        self.seen = False
        self.version = 0
        self.strip = ""  # 'Track 3: "Vox"' from the last banner
        self.slot: int | None = None  # 1-based plug-in slot from the last banner
        self.plugin: str | None = None  # its name; None = no plug-in in that slot
        self._banner_text = ""

    def apply(self, offset: int, text: str, row: int = 0) -> str | None:
        """Patch a row. Returns the banner text when a new banner appeared."""

        self._rows[row][offset : offset + len(text)] = list(text)
        self.seen = True
        self.version += 1
        if row != 0:
            return None
        line = self.line(0).strip()
        if line == self._banner_text:
            return None
        banner = parse_banner(line)
        self._banner_text = line if banner else ""
        if banner is None:
            return None
        self.strip, self.slot, self.plugin = banner
        return line

    def line(self, n: int, row: int = 0) -> str:
        return "".join(self._rows[row][n * LCD_WIDTH : (n + 1) * LCD_WIDTH])

    def showing_banner(self) -> bool:
        return bool(self._banner_text)

    def cells(self, line: int, row: int = 0) -> tuple[str, ...]:
        text = self.line(line, row)
        return tuple(text[i * CELL_WIDTH : (i + 1) * CELL_WIDTH].strip() for i in range(COLS))

    def labels(self, row: int = 0) -> tuple[str, ...]:
        """Parameter names, or blanks while the banner covers them."""

        if row == 0 and self.showing_banner():
            return ("",) * COLS
        return self.cells(0, row)

    def values(self, row: int = 0) -> tuple[str, ...]:
        return self.cells(1, row)

    def label(self, vpot: int) -> str:
        """Name of the parameter on V-pot *vpot* (0-31)."""

        return self.labels(vpot // COLS)[vpot % COLS]

    def value(self, vpot: int) -> str:
        return self.values(vpot // COLS)[vpot % COLS]
