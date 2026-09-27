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


def test_latching_toggle_clicks_on_both_edges():
    # Record Arm in Generic Mode is a latch: Note On = on, Note Off = off.
    # Each edge must emit one MCU press, else turning it off is ignored.
    eng, rec, _ = make_engine()

    eng.on_apc_message((0x92, apc.NOTE_RECORD_ARM, 127))  # track 3 arm on
    eng.on_apc_message((0x92, apc.NOTE_RECORD_ARM, 0))  # track 3 arm off

    note = mcu.NOTE_REC1 + 2
    click = [mcu.button_press(note), mcu.button_release(note)]
    assert rec.mcu_msgs == click + click


def test_track1_arm_sends_standard_mcu_rec_note_zero():
    # Cakewalk's Mackie Control ignores note 0, so track 1 will not arm over the
    # surface (documented limitation); the app still emits the standard message
    # for hosts that do honor it.
    eng, rec, _ = make_engine()
    eng.on_apc_message((0x90, apc.NOTE_RECORD_ARM, 127))
    assert rec.mcu_msgs == [mcu.button_press(0), mcu.button_release(0)]


def test_clip_stop_is_momentary_press_edge_only():
    eng, rec, _ = make_engine()

    eng.on_apc_message((0x91, apc.NOTE_CLIP_STOP, 127))
    eng.on_apc_message((0x91, apc.NOTE_CLIP_STOP, 0))

    note = mcu.NOTE_VPOT_PUSH1 + 1
    assert rec.mcu_msgs == [mcu.button_press(note), mcu.button_release(note)]


def test_track_select_is_press_edge_only():
    # The "off" edge fires when another track is chosen; it must not re-select.
    eng, rec, _ = make_engine()

    eng.on_apc_message((0x93, apc.NOTE_TRACK_SELECT, 127))
    eng.on_apc_message((0x93, apc.NOTE_TRACK_SELECT, 0))

    note = mcu.NOTE_SELECT1 + 3
    assert rec.mcu_msgs == [mcu.button_press(note), mcu.button_release(note)]


def test_track_knob_wraparound_is_a_small_step():
    eng, rec, _ = make_engine()
    eng.on_apc_message((0xB0, apc.CC_TRACK_KNOB1, 127))  # baseline at top
    eng.on_apc_message((0xB0, apc.CC_TRACK_KNOB1, 1))  # wraps to bottom = +2
    assert rec.mcu_msgs == [mcu.vpot_delta(1, 2)]


def test_track_knob_large_turn_is_clamped_to_step_limit():
    # Noise gate disabled so the clamp itself is exercised.
    eng, rec, _ = make_engine(knob_step_limit=3, knob_noise_threshold=0)
    eng.on_apc_message((0xB0, apc.CC_TRACK_KNOB1, 0))
    eng.on_apc_message((0xB0, apc.CC_TRACK_KNOB1, 40))
    assert rec.mcu_msgs == [mcu.vpot_delta(1, 3)]


def test_track_knob_ignores_ring_reference_jump():
    # A feedback-driven re-reference (e.g. 51 -> 68) is not movement: drop it,
    # then continue from the resynced baseline.
    eng, rec, _ = make_engine(knob_noise_threshold=6)
    eng.on_apc_message((0xB0, apc.CC_TRACK_KNOB1, 51))  # baseline
    eng.on_apc_message((0xB0, apc.CC_TRACK_KNOB1, 68))  # +17 jump, dropped
    assert rec.mcu_msgs == []
    eng.on_apc_message((0xB0, apc.CC_TRACK_KNOB1, 67))  # -1 from resync
    assert rec.mcu_msgs == [mcu.vpot_delta(1, -1)]


def test_transport_numbers_are_translated_not_passed_through():
    eng, rec, _ = make_engine()

    eng.on_apc_message((0x90, apc.NOTE_PLAY, 127))
    eng.on_apc_message((0x90, apc.NOTE_STOP, 127))
    eng.on_apc_message((0x90, apc.NOTE_RECORD, 127))

    assert rec.mcu_msgs == [
        mcu.button_press(mcu.NOTE_PLAY),
        mcu.button_release(mcu.NOTE_PLAY),
        mcu.button_press(mcu.NOTE_STOP),
        mcu.button_release(mcu.NOTE_STOP),
        mcu.button_press(mcu.NOTE_RECORD),
        mcu.button_release(mcu.NOTE_RECORD),
    ]


def test_grid_pad_lights_green_while_held_when_meters_are_off():
    eng, rec, _ = make_engine(meters=False)

    eng.on_apc_message((0x94, apc.NOTE_CLIP_ROW1 + 2, 127))  # track 5, row 3
    eng.on_apc_message((0x94, apc.NOTE_CLIP_ROW1 + 2, 0))

    assert rec.apc_msgs == [(0x94, 55, apc.CLIP_GREEN), (0x84, 55, 0)]
    assert rec.mcu_msgs == []


def test_grid_pads_do_not_draw_over_the_meters():
    eng, rec, _ = make_engine()

    eng.on_apc_message((0x94, apc.NOTE_CLIP_ROW1 + 2, 127))

    assert rec.apc_msgs == []


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


# ---------------------------------------------------------------------------
# Level meters (MCU channel pressure -> clip grid)
# ---------------------------------------------------------------------------


def grid_state(rec, track):
    """Final color per grid row (1-5) for *track*, from the emitted messages."""

    state = {row: apc.CLIP_OFF for row in range(1, apc.ROWS + 1)}
    for status, note, value in rec.apc_msgs:
        if status & 0x0F != track or not apc.NOTE_CLIP_ROW1 <= note < apc.NOTE_CLIP_ROW1 + apc.ROWS:
            continue
        state[note - apc.NOTE_CLIP_ROW1 + 1] = value if status & 0xF0 == 0x90 else apc.CLIP_OFF
    return state


def clip_stop_state(rec, track):
    state = apc.CLIP_OFF
    for status, note, value in rec.apc_msgs:
        if status & 0x0F == track and note == apc.NOTE_CLIP_STOP:
            state = value if status & 0xF0 == 0x90 else apc.CLIP_OFF
    return state


def test_meter_renders_a_bottom_up_bar_in_the_track_column():
    eng, rec, _ = make_engine()

    eng.on_mcu_message(mcu.meter_message(2, 9))  # track 3, -6 dB

    assert grid_state(rec, 2) == {
        5: apc.CLIP_GREEN,
        4: apc.CLIP_GREEN,
        3: apc.CLIP_GREEN,
        2: apc.CLIP_YELLOW,
        1: apc.CLIP_OFF,
    }
    assert grid_state(rec, 1) == {row: apc.CLIP_OFF for row in range(1, 6)}
    assert rec.mcu_msgs == []


def test_meter_decays_one_level_per_decay_period():
    eng, rec, _ = make_engine(meter_decay_frames=2)

    eng.on_mcu_message(mcu.meter_message(0, 5))
    assert grid_state(rec, 0)[4] == apc.CLIP_GREEN

    eng.tick()
    assert eng.meter_level(0) == 5
    eng.tick()
    assert eng.meter_level(0) == 4
    assert grid_state(rec, 0)[4] == apc.CLIP_OFF
    assert grid_state(rec, 0)[5] == apc.CLIP_GREEN

    for _ in range(8):
        eng.tick()
    assert eng.meter_level(0) == 0
    assert grid_state(rec, 0)[5] == apc.CLIP_OFF


def test_new_meter_value_restarts_decay():
    eng, _, _ = make_engine(meter_decay_frames=2)

    eng.on_mcu_message(mcu.meter_message(0, 5))
    eng.tick()
    eng.on_mcu_message(mcu.meter_message(0, 5))
    eng.tick()
    assert eng.meter_level(0) == 5


def test_meter_steady_state_sends_no_duplicate_led_writes():
    eng, rec, _ = make_engine()

    eng.on_mcu_message(mcu.meter_message(0, 7))
    count = len(rec.apc_msgs)
    eng.on_mcu_message(mcu.meter_message(0, 8))  # same segments lit

    assert len(rec.apc_msgs) == count


def test_overload_flag_latches_clip_stop_red_until_cleared():
    eng, rec, _ = make_engine()

    eng.on_mcu_message(mcu.meter_message(4, mcu.METER_OVERLOAD_SET))
    assert eng.meter_clipped(4)
    assert clip_stop_state(rec, 4) == apc.CLIP_RED

    eng.on_mcu_message(mcu.meter_message(4, mcu.METER_OVERLOAD_CLEAR))
    assert not eng.meter_clipped(4)
    assert clip_stop_state(rec, 4) == apc.CLIP_OFF


def test_over_level_latches_clip_without_host_overload_flag():
    eng, rec, _ = make_engine()

    eng.on_mcu_message(mcu.meter_message(1, mcu.METER_LEVEL_MAX))

    assert eng.meter_clipped(1)
    assert clip_stop_state(rec, 1) == apc.CLIP_RED
    assert grid_state(rec, 1)[1] == apc.CLIP_RED


def test_stop_all_clips_releases_clip_latches():
    eng, rec, _ = make_engine(flash_frames=1)
    eng.on_mcu_message(mcu.meter_message(1, mcu.METER_OVERLOAD_SET))

    eng.on_apc_message((0x90, apc.NOTE_STOP_ALL_CLIPS, 127))
    eng.tick()

    assert not eng.meter_clipped(1)
    assert clip_stop_state(rec, 1) == apc.CLIP_OFF


def test_clip_latch_survives_the_stop_all_flash_when_it_reclips():
    eng, rec, _ = make_engine(flash_frames=2)

    eng.on_apc_message((0x90, apc.NOTE_STOP_ALL_CLIPS, 127))
    eng.on_mcu_message(mcu.meter_message(3, mcu.METER_OVERLOAD_SET))
    eng.tick()
    eng.tick()

    assert clip_stop_state(rec, 3) == apc.CLIP_RED


def test_meters_off_tracks_state_but_draws_nothing():
    eng, rec, _ = make_engine(meters=False)

    eng.on_mcu_message(mcu.meter_message(0, mcu.METER_LEVEL_MAX))
    eng.tick()

    assert eng.meter_level(0) == mcu.METER_LEVEL_MAX
    assert rec.apc_msgs == []


def test_render_baseline_resets_meters():
    eng, _, _ = make_engine()
    eng.on_mcu_message(mcu.meter_message(0, 10))
    eng.on_mcu_message(mcu.meter_message(0, mcu.METER_OVERLOAD_SET))

    eng.render_baseline()

    assert eng.meter_level(0) == 0
    assert not eng.meter_clipped(0)


# ---------------------------------------------------------------------------
# Shift layer: Shift + Detail View toggles Cakewalk's meters
# ---------------------------------------------------------------------------

METER_STEP = [
    mcu.button_press(mcu.NOTE_M2),
    mcu.button_press(mcu.NOTE_NAME_VALUE),
    mcu.button_release(mcu.NOTE_NAME_VALUE),
    mcu.modifier_release(mcu.NOTE_M2),
]


def press_shift_detail(eng):
    eng.on_apc_message((0x90, apc.NOTE_SHIFT, 127))
    eng.on_apc_message((0x90, apc.NOTE_UTIL_DETAIL_VIEW, 127))
    eng.on_apc_message((0x80, apc.NOTE_UTIL_DETAIL_VIEW, 0))
    eng.on_apc_message((0x80, apc.NOTE_SHIFT, 0))


def run_frames(eng, frames, meter_every=None):
    """Tick *frames* times, feeding a meter message every *meter_every* frames."""

    for frame in range(frames):
        if meter_every and frame % meter_every == 0:
            eng.on_mcu_message(mcu.meter_message(0, 0))
        eng.tick()


def test_modifier_release_is_note_on_velocity_zero():
    # Cakewalk drops 0x80 for switches, which would leave M2 stuck on.
    assert mcu.modifier_release(mcu.NOTE_M2) == (0x90, 71, 0)


def test_shift_lights_while_held_and_sends_nothing():
    eng, rec, _ = make_engine()

    eng.on_apc_message((0x90, apc.NOTE_SHIFT, 127))
    assert eng.shift
    eng.on_apc_message((0x80, apc.NOTE_SHIFT, 0))
    assert not eng.shift

    assert rec.apc_msgs == [(0x90, apc.NOTE_SHIFT, 127), (0x80, apc.NOTE_SHIFT, 0)]
    assert rec.mcu_msgs == []


def test_detail_view_without_shift_does_not_toggle_meters():
    eng, rec, _ = make_engine()

    eng.on_apc_message((0x90, apc.NOTE_UTIL_DETAIL_VIEW, 127))

    assert rec.mcu_msgs == []


def test_shift_detail_turns_meters_on_with_one_step():
    eng, rec, _ = make_engine(meter_settle_frames=10)

    press_shift_detail(eng)
    assert rec.mcu_msgs == METER_STEP
    assert (0x90, apc.NOTE_UTIL_DETAIL_VIEW, 127) in rec.apc_msgs  # acknowledged

    run_frames(eng, 12, meter_every=2)  # Cakewalk starts streaming
    assert rec.mcu_msgs == METER_STEP
    assert eng.cakewalk_meters_on()


def test_shift_detail_turns_off_from_signal_leds_with_a_second_step():
    eng, rec, _ = make_engine(meter_settle_frames=10)
    run_frames(eng, 5, meter_every=2)
    assert eng.cakewalk_meters_on()

    press_shift_detail(eng)
    run_frames(eng, 12, meter_every=2)  # still streaming: now LEDs + Meters

    assert rec.mcu_msgs == METER_STEP + METER_STEP


def test_shift_detail_turns_off_from_both_with_one_step():
    eng, rec, _ = make_engine(meter_settle_frames=10)
    run_frames(eng, 5, meter_every=2)

    press_shift_detail(eng)
    run_frames(eng, 2, meter_every=1)  # stragglers sent before Cakewalk switched
    run_frames(eng, 10)  # then silence: meters are off

    assert rec.mcu_msgs == METER_STEP
    assert not eng.cakewalk_meters_on()


def test_repeat_press_while_settling_is_ignored():
    eng, rec, _ = make_engine(meter_settle_frames=10)

    press_shift_detail(eng)
    press_shift_detail(eng)

    assert rec.mcu_msgs == METER_STEP


def test_toggle_on_without_meter_traffic_warns(caplog):
    eng, rec, _ = make_engine(meter_settle_frames=4)

    press_shift_detail(eng)
    with caplog.at_level("WARNING", logger="apc40sonar.engine"):
        run_frames(eng, 5)

    assert rec.mcu_msgs == METER_STEP
    assert "no meters" in caplog.text


# ---------------------------------------------------------------------------
# Device Control banks: row 58-65 and knobs report on the bank channel (0-8)
# ---------------------------------------------------------------------------


def test_shift_detail_works_on_the_master_bank_channel():
    # Captured from hardware with the Master bank selected: Detail View
    # arrives on channel 8 and releases with Note Off velocity 127.
    eng, rec, _ = make_engine(meter_settle_frames=10)

    eng.on_apc_message((0x90, apc.NOTE_SHIFT, 127))
    eng.on_apc_message((0x98, apc.NOTE_UTIL_DETAIL_VIEW, 127))
    eng.on_apc_message((0x88, apc.NOTE_UTIL_DETAIL_VIEW, 127))
    eng.on_apc_message((0x80, apc.NOTE_SHIFT, 127))

    assert rec.mcu_msgs == METER_STEP


def test_metronome_works_from_any_bank_channel():
    eng, rec, _ = make_engine()

    for bank in (0, 3, 8):
        eng.on_apc_message((0x90 | bank, apc.NOTE_UTIL_METRONOME, 127))

    click = [mcu.button_press(mcu.NOTE_CLICK), mcu.button_release(mcu.NOTE_CLICK)]
    assert rec.mcu_msgs == click * 3


def test_utility_notes_outside_the_banks_are_ignored():
    eng, rec, _ = make_engine()

    eng.on_apc_message((0x99, apc.NOTE_UTIL_METRONOME, 127))  # channel 9

    assert rec.mcu_msgs == []


def test_device_knobs_follow_the_bank_channel_in_device_mode():
    eng, rec, _ = make_engine()
    eng.mixer = False

    eng.on_apc_message((0xB8, apc.CC_DEVICE_KNOB1, 5))  # Master bank, baseline
    eng.on_apc_message((0xB8, apc.CC_DEVICE_KNOB1, 6))

    assert rec.mcu_msgs == [mcu.vpot_delta(1, 1)]
