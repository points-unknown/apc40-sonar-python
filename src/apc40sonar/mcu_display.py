"""Decoders for the MCU displays Cakewalk writes: the LCD and the 7-segments.

The APC40 has no display, so this text is only used by the on-screen HUD.
Pure protocol state - no ports, no I/O.

Authority is Cakewalk's Mackie Control surface source (see
``plans/hud-concept.md`` section 1.2):

* **LCD**: 2 lines x 56 characters, written by SysEx
  ``F0 00 00 66 <dev> 12 <offset> <chars...> F7`` where offset = line * 56 + x.
  Cakewalk sends only the changed span of a line, so :class:`LcdBuffer` keeps
  the whole screen and patches it. Each line is 8 cells of 7 characters (6 of
  text plus a separator), one per strip.
* **7-segment**: CC 64-73 on channel 0 are the ten timecode digits, CC 73 the
  leftmost; CC 75 / 74 are the left / right assignment characters. Value bit 6
  is the decimal point, bits 0-5 the character (0x40-0x5F folded down by 0x40).
"""

from __future__ import annotations

import re
from typing import Sequence

LCD_LINES = 2
LCD_WIDTH = 56
LCD_SIZE = LCD_LINES * LCD_WIDTH
LCD_CELLS = 8
LCD_CELL_WIDTH = 7

# SysEx header: F0, Mackie manufacturer ID 00 00 66, then the device byte.
SYSEX_HEADER = (0xF0, 0x00, 0x00, 0x66)
# Cakewalk fills the device byte from the handshake or its expected type
# (0x14 main surface, 0x15 extender, 0x17 C4); accept the whole family.
DEVICE_IDS = range(0x10, 0x18)
CMD_LCD = 0x12

CC_TIMECODE_FIRST = 64  # rightmost digit
CC_TIMECODE_LAST = 73  # leftmost digit
CC_ASSIGN_RIGHT = 74
CC_ASSIGN_LEFT = 75
TIMECODE_DIGITS = 10
# Digit groups Cakewalk uses: BBT "%3d%02d  %03d" (measure, beat, blank, tick)
# and SMPTE hours(3) minutes(2) seconds(2) frames(3).
TIMECODE_GROUPS = ((0, 3), (3, 5), (5, 7), (7, 10))

# Cakewalk's temporary whole-line messages: 'Track 5: "Vocals"', 'Bus 2: "Drums"'.
TRACK_MESSAGE_RE = re.compile(r'\b(Track|Bus)\s+(\d+)\s*:\s*"([^"]*)"')


def _printable(byte: int) -> str:
    return chr(byte) if 0x20 <= byte <= 0x7E else " "


def parse_lcd_sysex(raw: Sequence[int]) -> tuple[int, str] | None:
    """Return ``(offset, text)`` for an MCU LCD SysEx message, else ``None``."""

    if len(raw) < 8 or tuple(raw[:4]) != SYSEX_HEADER or raw[-1] != 0xF7:
        return None
    if raw[4] not in DEVICE_IDS or raw[5] != CMD_LCD:
        return None
    offset = raw[6]
    if offset >= LCD_SIZE:
        return None
    return offset, "".join(_printable(b) for b in raw[7:-1])


class LcdBuffer:
    """The 2 x 56 character MCU LCD, patched span by span."""

    def __init__(self) -> None:
        self._chars = [" "] * LCD_SIZE
        self.seen = False  # any LCD write received

    def apply(self, raw: Sequence[int]) -> bool:
        """Patch the buffer from one SysEx message. Returns True if it was LCD text."""

        parsed = parse_lcd_sysex(raw)
        if parsed is None:
            return False
        offset, text = parsed
        text = text[: LCD_SIZE - offset]
        self._chars[offset : offset + len(text)] = list(text)
        self.seen = True
        return True

    def line(self, n: int) -> str:
        start = n * LCD_WIDTH
        return "".join(self._chars[start : start + LCD_WIDTH])

    def cell(self, line: int, strip: int) -> str:
        """The 7-character cell of *strip* (0-7) on *line*, whitespace stripped."""

        start = line * LCD_WIDTH + strip * LCD_CELL_WIDTH
        return "".join(self._chars[start : start + LCD_CELL_WIDTH]).strip()

    def temp_message(self) -> str | None:
        """The upper line when it holds a centered message instead of 8 cells.

        Cell layout leaves the last column of every cell blank; Cakewalk's
        temporary messages (``Track 5: "Vocals"``) are centered over the whole
        line and run through those separator columns.
        """

        upper = self.line(0)
        text = upper.strip()
        if not text:
            return None
        separators = (s * LCD_CELL_WIDTH + LCD_CELL_WIDTH - 1 for s in range(LCD_CELLS))
        if TRACK_MESSAGE_RE.search(upper) or any(upper[i] != " " for i in separators):
            return " ".join(text.split())
        return None


def parse_track_message(text: str) -> tuple[str, int, str] | None:
    """Split ``Track 5: "Vocals"`` into ``("Track", 5, "Vocals")``."""

    match = TRACK_MESSAGE_RE.search(text)
    if match is None:
        return None
    return match.group(1), int(match.group(2)), match.group(3).strip()


def decode_segment(value: int) -> tuple[str, bool]:
    """Decode one 7-segment byte into ``(character, dot)``."""

    v = value & 0x7F
    code = v & 0x3F
    char = chr(code + 0x40) if code < 0x20 else chr(code)
    return char, bool(v & 0x40)


class SevenSeg:
    """Timecode (10 digits) and assignment (2 characters) displays."""

    def __init__(self) -> None:
        self._digits = [" "] * TIMECODE_DIGITS
        self._digit_dots = [False] * TIMECODE_DIGITS
        self._assign = [" ", " "]
        self._assign_dots = [False, False]
        self.seen = False

    def apply(self, cc: int, value: int) -> bool:
        """Apply one CC. Returns True if *cc* belongs to a 7-segment display."""

        if CC_TIMECODE_FIRST <= cc <= CC_TIMECODE_LAST:
            index = CC_TIMECODE_LAST - cc  # CC 73 is the leftmost digit
            self._digits[index], self._digit_dots[index] = decode_segment(value)
        elif cc in (CC_ASSIGN_LEFT, CC_ASSIGN_RIGHT):
            index = 0 if cc == CC_ASSIGN_LEFT else 1
            self._assign[index], self._assign_dots[index] = decode_segment(value)
        else:
            return False
        self.seen = True
        return True

    def timecode(self) -> str:
        """The time as ``37.02.000`` (BBT) or ``1.02.03.04`` (SMPTE); '' if blank."""

        text = "".join(self._digits)
        groups = (text[a:b].strip() for a, b in TIMECODE_GROUPS)
        return ".".join(g for g in groups if g)

    def assignment(self) -> str:
        """The two assignment characters, e.g. ``PN`` or ``SE``."""

        return "".join(self._assign).strip()

    def strip_layout(self) -> bool:
        """A dot on the second assignment character: channel-strip (flipped) layout."""

        return self._assign_dots[1]
