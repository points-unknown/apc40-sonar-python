"""Unit tests for apc40sonar.mcu (encoding, decoding, LED states)."""

from __future__ import annotations

from apc40sonar import mcu


def test_button_press_and_release_are_real_note_events():
    assert mcu.button_press(mcu.NOTE_MUTE1) == (0x90, 16, 127)
    # Real Note Off (0x80), not Note On velocity 0 - the double-toggle fix.
    assert mcu.button_release(mcu.NOTE_MUTE1) == (0x80, 16, 0)


def test_pitch_bend_encoding():
    assert mcu.pitch_bend(0, 0) == (0xE0, 0, 0)
    assert mcu.pitch_bend(0, 16383) == (0xE0, 127, 127)
    assert mcu.pitch_bend(8, 8192) == (0xE8, 8192 & 0x7F, (8192 >> 7) & 0x7F)


def test_fader_from_7bit_scales_to_14bit():
    assert mcu.fader_from_7bit(0, 0) == (0xE0, 0, 0)
    assert mcu.fader_from_7bit(0, 127) == (0xE0, 127, 127)

    message = mcu.fader_from_7bit(3, 64)
    value14 = message[1] | (message[2] << 7)
    assert abs(value14 - round(64 / 127 * 16383)) <= 1


def test_vpot_delta_signs_and_addressing():
    assert mcu.vpot_delta(1, 0) is None
    assert mcu.vpot_delta(1, 1) == (0xB0, 16, 0x01)
    assert mcu.vpot_delta(1, -1) == (0xB0, 16, 0x41)
    assert mcu.vpot_delta(8, 5) == (0xB0, 23, 5)


def test_vpot_delta_is_clamped_to_one_message():
    assert mcu.vpot_delta(1, 500)[2] == 0x3F
    assert mcu.vpot_delta(1, -500)[2] == 0x7F


def test_ring_byte_round_trip():
    for mode in (0, 1, 2, 3):
        for value in (0, 5, 11):
            ring = mcu.decode_ring(mcu.ring_byte(mode, value))
            assert (ring.mode, ring.value, ring.led) == (mode, value, False)

    assert mcu.decode_ring(mcu.ring_byte(1, 3, led=True)).led is True


def test_ring_value_to_position_scaling():
    assert mcu.ring_value_to_position(0) == 0
    assert mcu.ring_value_to_position(11) == 127
    assert 57 <= mcu.ring_value_to_position(5) <= 59
    assert mcu.ring_value_to_position(99) == 127  # clamped


def test_led_state_convention():
    assert mcu.led_state(0) == "off"
    assert mcu.led_state(2) == "off"  # any even value is off
    assert mcu.led_state(1) == "blink"
    assert mcu.led_state(63) == "blink"
    assert mcu.led_state(127) == "solid"


def test_decode_note_on_and_note_off():
    on = mcu.decode((0x90, 48, 100))
    assert (on.kind, on.number, on.value, on.channel) == ("note_on", 48, 100, 0)

    off = mcu.decode((0x84, 52, 0))
    assert (off.kind, off.number, off.channel) == ("note_off", 52, 4)


def test_decode_normalizes_note_on_velocity_zero():
    decoded = mcu.decode((0x90, 48, 0))
    assert decoded.kind == "note_off"


def test_decode_cc_and_pitch_bend():
    cc = mcu.decode((0xB2, 48, 65))
    assert (cc.kind, cc.number, cc.value, cc.channel) == ("cc", 48, 65, 2)

    pitch = mcu.decode((0xE1, 0x40, 0x40))
    assert pitch.kind == "pitch_bend"
    assert pitch.value == 0x40 | (0x40 << 7)


def test_decode_passes_sysex_and_ignores_other_system_messages():
    sysex = mcu.decode((0xF0, 0x00, 0xF7))
    assert sysex is not None
    assert (sysex.kind, sysex.raw) == ("sysex", (0xF0, 0x00, 0xF7))

    assert mcu.decode((0xF0, 0x00, 0x01)) is None  # truncated SysEx
    assert mcu.decode((0xF8, 0x00)) is None


def test_channel_pressure_decodes_as_meter():
    decoded = mcu.decode(mcu.meter_message(7, 0x0C))
    assert decoded is not None
    assert decoded.kind == "pressure"
    assert decoded.value == 0x7C

    meter = mcu.decode_meter(decoded.value)
    assert (meter.strip, meter.level) == (7, 0x0C)
    assert mcu.decode_meter(0x3E).level == mcu.METER_OVERLOAD_SET
