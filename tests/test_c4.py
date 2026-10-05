"""Unit tests for apc40sonar.c4 (Mackie Control C4 protocol)."""

from __future__ import annotations

from apc40sonar import c4


def lcd(row, offset, text):
    return (0xF0, 0x00, 0x00, 0x66, 0x17, 0x30 + row, offset, *text.encode("ascii"), 0xF7)


def test_vpot_delta_encodes_direction_and_speed():
    assert c4.vpot_delta(0, 0, 1) == (0xB0, 0x00, 0x01)
    assert c4.vpot_delta(0, 7, -1) == (0xB0, 0x07, 0x41)
    assert c4.vpot_delta(1, 2, 3) == (0xB0, 0x0A, 0x03)
    assert c4.vpot_delta(0, 0, 40) == (0xB0, 0x00, 15)  # clamped
    assert c4.vpot_delta(0, 0, -40) == (0xB0, 0x00, 0x4F)


def test_vpot_delta_never_sends_a_zero_speed():
    assert c4.vpot_delta(0, 0, 0) is None
    for delta in range(-20, 21):
        message = c4.vpot_delta(0, 3, delta)
        if message is not None:
            assert message[2] & 0x0F != 0


def test_buttons_press_at_7f_and_release_with_note_on_zero():
    assert c4.button_press(c4.SLOT_UP) == (0x90, 0x11, 0x7F)
    assert c4.button_release(c4.SLOT_UP) == (0x90, 0x11, 0x00)
    assert c4.click(c4.BANK_LEFT) == [(0x90, 0x09, 0x7F), (0x90, 0x09, 0x00)]


def test_serial_reply_and_wake_up_bytes():
    reply = c4.serial_reply()
    assert reply[:6] == (0xF0, 0x00, 0x00, 0x66, 0x17, 0x1B)
    assert len(reply) == 6 + 7 + 1 and reply[-1] == 0xF7
    assert c4.wake_up() == (0xF0, 0x00, 0x00, 0x66, 0x17, 0x01, 0xF7)


def test_serial_query_is_recognized():
    assert c4.is_serial_query((0xF0, 0x00, 0x00, 0x66, 0x17, 0x1A, 0x00, 0xF7))
    assert not c4.is_serial_query(lcd(0, 0, "Gain"))
    assert not c4.is_serial_query((0xF0, 0x7E, 0x00, 0x06, 0x01, 0xF7))


def test_assign_plugin_macro_holds_track_around_the_push():
    assert c4.assign_plugin_macro() == [
        (0x90, 0x06, 0x7F), (0x90, 0x2B, 0x7F), (0x90, 0x2B, 0x00), (0x90, 0x06, 0x00),
    ]


def test_with_shift_wraps_the_clicks_in_m1():
    assert c4.with_shift([c4.SLOT_DOWN]) == [
        (0x90, 0x0D, 0x7F), (0x90, 0x12, 0x7F), (0x90, 0x12, 0x00), (0x90, 0x0D, 0x00),
    ]


def test_parse_lcd_row_offset_and_text():
    assert c4.parse_lcd(lcd(0, 56, "50.0%")) == (0, 56, "50.0%")
    assert c4.parse_lcd(lcd(3, 0, "x")) == (3, 0, "x")


def test_parse_lcd_ignores_meters_and_other_sysex():
    assert c4.parse_lcd((0xF0, 0x00, 0x00, 0x66, 0x17, 0x20, 0x00, 0x01, 0xF7)) is None
    assert c4.parse_lcd((0xF0, 0x00, 0x00, 0x66, 0x17, 0x12, 0x00, 0x41, 0xF7)) is None
    assert c4.parse_lcd(lcd(0, 112, "x")) is None


def test_parse_lcd_clamps_text_at_the_end():
    _row, _offset, text = c4.parse_lcd(lcd(0, 110, "abc"))
    assert text == "ab"


def test_display_reads_all_four_rows():
    display = c4.C4Display()
    display.apply(0, "A      B      ".ljust(56), row=0)
    display.apply(0, "I      J      ".ljust(56), row=1)
    display.apply(56, "9v     10v    ", row=1)
    assert display.label(1) == "B"
    assert (display.label(8), display.value(9)) == ("I", "10v")
    assert display.label(31) == ""


def test_parse_banner():
    assert c4.parse_banner('Track 3: "Vox", Plugin 2: "Sonitus Delay"') == ('Track 3: "Vox"', 2, "Sonitus Delay")
    assert c4.parse_banner('Bus 1: "Drums", Plugin 4: --None--') == ('Bus 1: "Drums"', 4, None)
    assert c4.parse_banner('Track 12: "A long name", Plugin 1: "ProChannel Q') == (
        'Track 12: "A long name"', 1, "ProChannel Q")  # cut at 56 characters
    assert c4.parse_banner("Gain   Freq   Q") is None


def test_display_labels_values_and_banner():
    display = c4.C4Display()
    display.apply(0, "Gain   Freq   Q      ".ljust(56))
    display.apply(56, "0.0dB  1.2kHz 0.71   ")
    assert display.labels()[:3] == ("Gain", "Freq", "Q")
    assert display.values()[:3] == ("0.0dB", "1.2kHz", "0.71")

    banner = display.apply(0, 'Track 3: "Vox", Plugin 2: "Sonitus Delay"'.ljust(56))
    assert banner is not None
    assert (display.strip, display.slot, display.plugin) == ('Track 3: "Vox"', 2, "Sonitus Delay")
    assert display.labels() == ("",) * 8  # covered by the banner

    assert display.apply(0, "Mix    Time   ".ljust(56)) is None  # labels return
    assert display.labels()[:2] == ("Mix", "Time")
    assert display.slot == 2  # the plug-in stays known


def test_display_patches_partial_writes():
    display = c4.C4Display()
    display.apply(0, "Gain   Freq   ".ljust(56))
    display.apply(7, "Hz")
    assert display.labels()[:2] == ("Gain", "Hzeq")
