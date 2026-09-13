"""Unit tests for apc40sonar.apc40 (message building and output rendering)."""

from __future__ import annotations

from apc40sonar import apc40 as apc


def test_note_builders_set_channel_and_data():
    assert apc.note_on(0, 48, 127) == (0x90, 48, 127)
    assert apc.note_on(7, 57, 1) == (0x97, 57, 1)
    assert apc.note_off(3, 52) == (0x83, 52, 0)
    assert apc.control_change(0, 55, 63) == (0xB0, 55, 63)


def test_builders_mask_out_of_range_data():
    assert apc.note_on(0, 200, 300) == (0x90, 200 & 0x7F, 300 & 0x7F)
    assert apc.control_change(0, 200, 300) == (0xB0, 200 & 0x7F, 300 & 0x7F)


def test_ring_cc_helpers_cover_all_eight_knobs():
    assert [apc.track_ring_cc(k) for k in range(1, 9)] == list(range(48, 56))
    assert [apc.track_ring_style_cc(k) for k in range(1, 9)] == list(range(56, 64))
    assert [apc.device_ring_cc(k) for k in range(1, 9)] == list(range(16, 24))
    assert [apc.device_ring_style_cc(k) for k in range(1, 9)] == list(range(24, 32))


def test_output_dedupes_identical_writes():
    sent: list[tuple[int, ...]] = []
    out = apc.Apc40Output(sent.append)

    out.note(0, apc.NOTE_RECORD_ARM, apc.LED_ON)
    out.note(0, apc.NOTE_RECORD_ARM, apc.LED_ON)

    assert sent == [(0x90, 48, 127)]


def test_output_force_always_writes():
    sent: list[tuple[int, ...]] = []
    out = apc.Apc40Output(sent.append)

    out.note(0, apc.NOTE_MASTER, apc.LED_ON, force=True)
    out.note(0, apc.NOTE_MASTER, apc.LED_ON, force=True)

    assert sent == [(0x90, 80, 127), (0x90, 80, 127)]


def test_output_uses_real_note_off_for_off():
    sent: list[tuple[int, ...]] = []
    out = apc.Apc40Output(sent.append)

    out.note(2, apc.NOTE_CLIP_STOP, apc.CLIP_OFF)

    assert sent == [(0x82, 52, 0)]


def test_clip_pad_and_clip_stop_addressing():
    sent: list[tuple[int, ...]] = []
    out = apc.Apc40Output(sent.append)

    out.clip_pad(1, 3, apc.CLIP_RED)  # track 2, row 3 -> ch1 note55
    out.clip_stop(4, apc.CLIP_GREEN_BLINK)  # ch4 note52

    assert sent == [(0x91, 55, 3), (0x94, 52, 2)]


def test_cc_dedupes_and_force_resends():
    sent: list[tuple[int, ...]] = []
    out = apc.Apc40Output(sent.append)

    out.ring_position(48, 10)
    out.ring_position(48, 10)
    out.ring_style(56, apc.RING_PAN, force=True)
    out.ring_style(56, apc.RING_PAN, force=True)

    assert sent == [(0xB0, 48, 10), (0xB0, 56, 3), (0xB0, 56, 3)]


def test_clear_all_turns_everything_off():
    sent: list[tuple[int, ...]] = []
    out = apc.Apc40Output(sent.append)

    out.clear_all()

    # Every write is an off/zero value.
    assert all(message[2] == 0 for message in sent)

    note_offs = [m for m in sent if (m[0] & 0xF0) == 0x80]
    cc_offs = [m for m in sent if (m[0] & 0xF0) == 0xB0]

    # 8 tracks * (5 pads + 1 clip stop + 4 strip LEDs) = 80
    # + utility 8 + master 1 + scenes 5 + transport/nav 11 + pan/send 4 = 109
    assert len(note_offs) == 109
    # 8 knobs * (track position + track style + device position + device style) = 32
    assert len(cc_offs) == 32
