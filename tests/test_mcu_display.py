"""Unit tests for apc40sonar.mcu_display (MCU LCD and 7-segment decoding)."""

from __future__ import annotations

from apc40sonar import mcu_display as md


def lcd_sysex(offset: int, text: str, device: int = 0x14) -> tuple[int, ...]:
    return (0xF0, 0x00, 0x00, 0x66, device, 0x12, offset, *text.encode("ascii"), 0xF7)


def cells(names) -> str:
    return "".join(f"{name[:6]:<6} " for name in names)


def test_parse_lcd_sysex_accepts_the_device_family_only():
    assert md.parse_lcd_sysex(lcd_sysex(3, "Kick")) == (3, "Kick")
    assert md.parse_lcd_sysex(lcd_sysex(0, "X", device=0x10)) == (0, "X")
    assert md.parse_lcd_sysex(lcd_sysex(0, "X", device=0x17)) == (0, "X")
    assert md.parse_lcd_sysex(lcd_sysex(0, "X", device=0x20)) is None
    assert md.parse_lcd_sysex((0xF0, 0x00, 0x00, 0x66, 0x14, 0x13, 0, 0x41, 0xF7)) is None
    assert md.parse_lcd_sysex(lcd_sysex(112, "X")) is None  # past the end


def test_lcd_buffer_patches_partial_spans():
    lcd = md.LcdBuffer()
    assert not lcd.seen
    lcd.apply(lcd_sysex(0, cells(["Kick", "Snare", "OH", "Bass", "Gtr L", "Gtr R", "Vocals", "Pad"])))
    assert lcd.seen
    assert lcd.cell(0, 0) == "Kick"
    assert lcd.cell(0, 7) == "Pad"

    # Cakewalk sends only the changed characters: "Snare" -> "Snap" plus a blank.
    lcd.apply(lcd_sysex(7 + 3, "p "))
    assert lcd.cell(0, 1) == "Snap"
    assert lcd.cell(0, 2) == "OH"

    # Lower line at offset 56.
    lcd.apply(lcd_sysex(56 + 7, " -6.5 "))
    assert lcd.cell(1, 1) == "-6.5"
    assert lcd.line(1).startswith("       ")


def test_lcd_buffer_clips_overlong_text_and_maps_non_ascii():
    lcd = md.LcdBuffer()
    lcd.apply((0xF0, 0x00, 0x00, 0x66, 0x14, 0x12, 110, 0x41, 0x05, 0x42, 0xF7))
    assert lcd.line(1)[-2:] == "A "  # 0x05 -> space, 0x42 past the end dropped


def test_temp_message_detection():
    lcd = md.LcdBuffer()
    lcd.apply(lcd_sysex(0, cells(["Kick", "Snare", "OH", "Bass", "", "", "", ""])))
    assert lcd.temp_message() is None

    lcd.apply(lcd_sysex(0, 'Track 12: "Vocals"'.center(56)))
    assert lcd.temp_message() == 'Track 12: "Vocals"'

    lcd.apply(lcd_sysex(0, "Master Fader = Bus 1".center(56)))
    assert lcd.temp_message() == "Master Fader = Bus 1"

    lcd.apply(lcd_sysex(0, " " * 56))
    assert lcd.temp_message() is None


def test_parse_track_message():
    assert md.parse_track_message('Track 5: "Vocals"') == ("Track", 5, "Vocals")
    assert md.parse_track_message('Bus 2: "Drums "') == ("Bus", 2, "Drums")
    assert md.parse_track_message("Master Fader = Bus 1") is None


def test_decode_segment_folds_letters_and_reads_the_dot():
    assert md.decode_segment(0x01) == ("A", False)  # 'A' folded down by 0x40
    assert md.decode_segment(0x10) == ("P", False)
    assert md.decode_segment(0x33) == ("3", False)
    assert md.decode_segment(0x20) == (" ", False)
    assert md.decode_segment(0x40 | 0x05) == ("E", True)


def timecode_ccs(text: str):
    """CCs for 10 timecode characters, left to right (CC 73 is leftmost)."""

    for index, char in enumerate(text):
        code = ord(char)
        value = code - 0x40 if code >= 0x40 else code
        yield 73 - index, value


def test_seven_seg_bbt_timecode_ordering():
    seg = md.SevenSeg()
    assert seg.timecode() == ""
    for cc, value in timecode_ccs(" 3702  000"):
        assert seg.apply(cc, value)
    assert seg.seen
    assert seg.timecode() == "37.02.000"

    # Only changed digits are sent: tick 000 -> 480 (CC 66-64 are the tick).
    seg.apply(66, ord("4"))
    seg.apply(65, ord("8"))
    assert seg.timecode() == "37.02.480"


def test_seven_seg_smpte_timecode():
    seg = md.SevenSeg()
    for cc, value in timecode_ccs("  1020304 "):
        seg.apply(cc, value)
    assert seg.timecode() == "1.02.03.04"


def test_seven_seg_assignment_and_strip_layout_dot():
    seg = md.SevenSeg()
    seg.apply(75, 0x10)  # P
    seg.apply(74, 0x0E)  # N
    assert seg.assignment() == "PN"
    assert not seg.strip_layout()

    seg.apply(74, 0x40 | 0x0E)  # N with a dot: channel-strip layout
    assert seg.strip_layout()


def test_seven_seg_ignores_other_ccs():
    seg = md.SevenSeg()
    assert not seg.apply(48, 5)
    assert not seg.apply(63, 5)
    assert not seg.apply(76, 5)
    assert not seg.seen
