"""Unit tests for apc40sonar.engine (mixer core, knob modes, feedback)."""

from __future__ import annotations

from apc40sonar import apc40 as apc
from apc40sonar import engine as engine_mod
from apc40sonar import mcu


class Recorder:
    """Collects the raw MIDI messages the engine emits."""

    def __init__(self) -> None:
        self.apc_msgs: list[tuple[int, ...]] = []
        self.mcu_msgs: list[tuple[int, ...]] = []

    def apc_send(self, message) -> None:
        self.apc_msgs.append(tuple(message))

    def mcu_send(self, message) -> None:
        self.mcu_msgs.append(tuple(message))


def make_engine(**kwargs):
    rec = Recorder()
    out = apc.Apc40Output(rec.apc_send)
    eng = engine_mod.Engine(out, rec.mcu_send, **kwargs)
    return eng, rec, out


# ---------------------------------------------------------------------------
# Encoder path (APC40 -> MCU)
# ---------------------------------------------------------------------------


def test_fader_maps_to_pitch_bend_on_the_track_channel():
    eng, rec, _ = make_engine()
    eng.on_apc_message((0xB3, apc.CC_TRACK_LEVEL, 127))
    assert rec.mcu_msgs == [mcu.fader_from_7bit(3, 127)]


def test_track_knob_is_delta_encoded_first_read_sets_baseline():
    eng, rec, _ = make_engine()

    eng.on_apc_message((0xB0, apc.CC_TRACK_KNOB1, 10))
    assert rec.mcu_msgs == []

    eng.on_apc_message((0xB0, apc.CC_TRACK_KNOB1, 13))
    assert rec.mcu_msgs == [mcu.vpot_delta(1, 3)]


def test_device_knob_only_drives_vpots_in_device_mode():
    eng, rec, _ = make_engine()

    eng.on_apc_message((0xB0, apc.CC_DEVICE_KNOB1, 5))
    assert rec.mcu_msgs == []  # mix mode ignores Device Control knobs

    eng.mixer = False
    eng.on_apc_message((0xB0, apc.CC_DEVICE_KNOB1, 5))
    assert rec.mcu_msgs == []  # baseline read

    eng.on_apc_message((0xB0, apc.CC_DEVICE_KNOB1, 4))
    assert rec.mcu_msgs == [mcu.vpot_delta(1, -1)]


def test_strip_button_press_and_release_use_real_notes():
    eng, rec, _ = make_engine()

    eng.on_apc_message((0x92, apc.NOTE_RECORD_ARM, 127))  # track 3 arm press
    eng.on_apc_message((0x92, apc.NOTE_RECORD_ARM, 0))  # release

    assert rec.mcu_msgs == [
        mcu.button_press(mcu.NOTE_REC1 + 2),
        mcu.button_release(mcu.NOTE_REC1 + 2),
    ]


def test_clip_stop_maps_to_vpot_push():
    eng, rec, _ = make_engine()
    eng.on_apc_message((0x91, apc.NOTE_CLIP_STOP, 127))
    assert rec.mcu_msgs == [mcu.button_press(mcu.NOTE_VPOT_PUSH1 + 1)]


def test_transport_numbers_are_translated_not_passed_through():
    eng, rec, _ = make_engine()

    eng.on_apc_message((0x90, apc.NOTE_PLAY, 127))
    eng.on_apc_message((0x90, apc.NOTE_STOP, 127))
    eng.on_apc_message((0x90, apc.NOTE_RECORD, 127))

    assert rec.mcu_msgs == [
        mcu.button_press(mcu.NOTE_PLAY),
        mcu.button_press(mcu.NOTE_STOP),
        mcu.button_press(mcu.NOTE_RECORD),
    ]


def test_grid_pad_lights_green_while_held():
    eng, rec, _ = make_engine()

    eng.on_apc_message((0x94, apc.NOTE_CLIP_ROW1 + 2, 127))  # track 5, row 3
    eng.on_apc_message((0x94, apc.NOTE_CLIP_ROW1 + 2, 0))

    assert rec.apc_msgs == [(0x94, 55, apc.CLIP_GREEN), (0x84, 55, 0)]
    assert rec.mcu_msgs == []


# ---------------------------------------------------------------------------
# Knob modes
# ---------------------------------------------------------------------------


def test_knob_mode_pan_lights_leds_sets_style_and_centers_rings():
    eng, rec, _ = make_engine()

    eng.set_knob_mode("pan")

    assert rec.mcu_msgs == [
        mcu.button_press(mcu.NOTE_ASSIGN_PAN),
        mcu.button_release(mcu.NOTE_ASSIGN_PAN),
    ]
    assert (0x90, apc.NOTE_PAN, 127) in rec.apc_msgs
    for note in (apc.NOTE_SEND_A, apc.NOTE_SEND_B, apc.NOTE_SEND_C):
        assert (0x80, note, 0) in rec.apc_msgs

    styles = [m for m in rec.apc_msgs if m[1] in range(56, 64)]
    assert styles and all(m[2] == apc.RING_PAN for m in styles)

    centered = [m for m in rec.apc_msgs if m[1] in range(48, 56)]
    assert len(centered) == 8
    assert all(m[2] == 63 for m in centered)


def test_knob_mode_send_bypasses_centering():
    eng, rec, _ = make_engine()

    eng.set_knob_mode("send_a")

    assert rec.mcu_msgs == [
        mcu.button_press(mcu.NOTE_ASSIGN_SEND),
        mcu.button_release(mcu.NOTE_ASSIGN_SEND),
    ]
    assert (0x90, apc.NOTE_SEND_A, 127) in rec.apc_msgs

    styles = [m for m in rec.apc_msgs if m[1] in range(56, 64)]
    assert styles and all(m[2] == apc.RING_VOLUME for m in styles)
    assert not [m for m in rec.apc_msgs if m[1] in range(48, 56)]


def test_unknown_knob_mode_raises():
    eng, _, _ = make_engine()
    try:
        eng.set_knob_mode("nope")
    except ValueError:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected ValueError")


# ---------------------------------------------------------------------------
# Feedback path (MCU -> APC40)
# ---------------------------------------------------------------------------


def test_feedback_strip_led_on_then_off():
    eng, rec, _ = make_engine()

    eng.on_mcu_message((0x90, mcu.NOTE_MUTE1 + 2, 127))  # track 3 mute on
    eng.on_mcu_message((0x90, mcu.NOTE_MUTE1 + 2, 0))  # off

    assert rec.apc_msgs == [
        (0x92, apc.NOTE_ACTIVATOR, 127),
        (0x82, apc.NOTE_ACTIVATOR, 0),
    ]


def test_feedback_transport_and_click():
    eng, rec, _ = make_engine()

    eng.on_mcu_message((0x90, mcu.NOTE_PLAY, 127))
    eng.on_mcu_message((0x90, mcu.NOTE_CLICK, 127))

    assert (0x90, apc.NOTE_PLAY, 127) in rec.apc_msgs
    assert (0x90, apc.NOTE_UTIL_METRONOME, 127) in rec.apc_msgs


def test_feedback_blink_velocity_renders_as_on():
    eng, rec, _ = make_engine()
    eng.on_mcu_message((0x90, mcu.NOTE_SOLO1, 1))  # blink
    assert rec.apc_msgs == [(0x90, apc.NOTE_SOLO, 127)]


def test_feedback_ring_routes_to_track_rings_in_mix_mode():
    eng, rec, _ = make_engine()

    eng.on_mcu_message((0xB0, mcu.CC_RING1 + 2, mcu.ring_byte(mcu.RING_MODE_PAN, 11)))

    assert rec.apc_msgs == [(0xB0, apc.track_ring_cc(3), 127)]


def test_feedback_ring_routes_to_device_rings_in_device_mode():
    eng, rec, _ = make_engine()
    eng.mixer = False

    eng.on_mcu_message((0xB0, mcu.CC_RING1, mcu.ring_byte(mcu.RING_MODE_VOLUME, 0)))

    assert (0xB0, apc.device_ring_cc(1), 0) in rec.apc_msgs
    assert (0xB0, apc.device_ring_style_cc(1), apc.RING_VOLUME) in rec.apc_msgs


def test_fader_feedback_is_ignored():
    eng, rec, _ = make_engine()
    eng.on_mcu_message((0xE0, 0, 127))
    assert rec.apc_msgs == []
    assert rec.mcu_msgs == []


# ---------------------------------------------------------------------------
# Flashes and baseline
# ---------------------------------------------------------------------------


def test_tap_tempo_flashes_off_after_ticks():
    eng, rec, _ = make_engine(flash_frames=2)

    eng.on_apc_message((0x90, apc.NOTE_TAP_TEMPO, 127))
    assert (0x90, apc.NOTE_TAP_TEMPO, 127) in rec.apc_msgs

    eng.tick()
    assert (0x80, apc.NOTE_TAP_TEMPO, 0) not in rec.apc_msgs

    eng.tick()
    assert rec.apc_msgs[-1] == (0x80, apc.NOTE_TAP_TEMPO, 0)


def test_stop_all_clips_sends_stop_and_flashes():
    eng, rec, _ = make_engine(flash_frames=1)

    eng.on_apc_message((0x90, apc.NOTE_STOP_ALL_CLIPS, 127))

    assert mcu.button_press(mcu.NOTE_STOP) in rec.mcu_msgs
    assert (0x90, apc.NOTE_STOP, 127) in rec.apc_msgs
    assert (0x91, apc.NOTE_CLIP_STOP, apc.CLIP_GREEN_BLINK) in rec.apc_msgs

    eng.tick()
    assert (0x80, apc.NOTE_STOP, 0) in rec.apc_msgs


def test_render_baseline_sets_master_scene5_and_pan_mode():
    eng, rec, _ = make_engine()

    eng.render_baseline()

    assert (0x90, apc.NOTE_MASTER, 127) in rec.apc_msgs
    assert (0x90, apc.NOTE_SCENE1 + 4, 127) in rec.apc_msgs
    assert eng.knob_mode == "pan"

    # clear_all() zeroes the device ring styles first, so assert the *final*
    # value written per style CC rather than every intermediate message.
    device_styles = {m[1]: m[2] for m in rec.apc_msgs if m[1] in range(24, 32)}
    assert set(device_styles) == set(range(24, 32))
    assert all(value == apc.RING_PAN for value in device_styles.values())

    device_positions = {m[1]: m[2] for m in rec.apc_msgs if m[1] in range(16, 24)}
    assert set(device_positions) == set(range(16, 24))
    assert all(value == 63 for value in device_positions.values())
