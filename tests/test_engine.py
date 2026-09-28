"""Unit tests for apc40sonar.engine (mixer core, knob modes, feedback)."""

from __future__ import annotations

from apc40sonar import apc40 as apc
from apc40sonar import engine as engine_mod
from apc40sonar import sequencer as sq
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


def click(note):
    return [mcu.button_press(note), mcu.button_release(note)]


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

    # Cakewalk's assignment is unknown at first: step through Dynamics so the
    # Pan press is a switch, never a re-press (which flips the layout).
    assert rec.mcu_msgs == [
        mcu.button_press(mcu.NOTE_CW_DYNAMICS),
        mcu.button_release(mcu.NOTE_CW_DYNAMICS),
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

    eng.on_mcu_message((0x90, mcu.NOTE_ASSIGN_PAN, 127))  # Cakewalk is in Pan
    eng.set_knob_mode("send_a")

    assert rec.mcu_msgs[:2] == click(mcu.NOTE_ASSIGN_SEND)
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
    mcu.cakewalk_release(mcu.NOTE_M2),
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


def test_cakewalk_release_is_note_on_velocity_zero():
    # Cakewalk drops 0x80 for switches, which would leave M2 stuck on.
    assert mcu.cakewalk_release(mcu.NOTE_M2) == (0x90, 71, 0)


def test_shift_is_tracked_and_sends_nothing():
    eng, rec, _ = make_engine()

    eng.on_apc_message((0x90, apc.NOTE_SHIFT, 127))
    assert eng.shift_state == "held"
    eng.on_apc_message((0x80, apc.NOTE_SHIFT, 0))
    assert eng.shift_state == "once"  # a tap arms a one-shot

    assert rec.apc_msgs == []  # the APC40's Shift has no LED
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


def test_master_fader_maps_to_pitch_bend_channel_8():
    eng, rec, _ = make_engine()

    eng.on_apc_message((0xB0, apc.CC_MASTER_LEVEL, 127))
    eng.on_apc_message((0xB0, apc.CC_MASTER_LEVEL, 0))

    assert rec.mcu_msgs == [(0xE8, 127, 127), (0xE8, 0, 0)]


def test_master_fader_channel_is_not_significant():
    eng, rec, _ = make_engine()

    eng.on_apc_message((0xB8, apc.CC_MASTER_LEVEL, 64))

    assert rec.mcu_msgs == [mcu.fader_from_7bit(8, 64)]


# ---------------------------------------------------------------------------
# Track banking: Bank Select Left/Right and Shift + Left/Right
# ---------------------------------------------------------------------------


def test_bank_left_right_move_the_strip_window_by_eight():
    eng, rec, _ = make_engine()

    eng.on_apc_message((0x90, apc.NOTE_RIGHT, 127))
    eng.on_apc_message((0x80, apc.NOTE_RIGHT, 127))
    eng.on_apc_message((0x90, apc.NOTE_LEFT, 127))

    assert rec.mcu_msgs == click(mcu.NOTE_BANK_RIGHT) + click(mcu.NOTE_BANK_LEFT)


def test_shift_left_right_move_the_strip_window_by_one():
    eng, rec, _ = make_engine()

    eng.on_apc_message((0x90, apc.NOTE_SHIFT, 127))
    eng.on_apc_message((0x90, apc.NOTE_RIGHT, 127))
    eng.on_apc_message((0x90, apc.NOTE_LEFT, 127))

    assert rec.mcu_msgs == click(mcu.NOTE_CHANNEL_RIGHT) + click(mcu.NOTE_CHANNEL_LEFT)


def test_up_down_still_send_cursor_keys_with_or_without_shift():
    eng, rec, _ = make_engine()

    eng.on_apc_message((0x90, apc.NOTE_UP, 127))
    eng.on_apc_message((0x90, apc.NOTE_SHIFT, 127))
    eng.on_apc_message((0x90, apc.NOTE_DOWN, 127))

    # Cursor keys release with Note On velocity 0: Cakewalk auto-repeats them
    # until it sees a release, and it drops real Note Offs.
    assert rec.mcu_msgs == [
        (0x90, mcu.NOTE_UP, 127), (0x90, mcu.NOTE_UP, 0),
        (0x90, mcu.NOTE_DOWN, 127), (0x90, mcu.NOTE_DOWN, 0),
    ]


def test_bank_arrow_led_flashes_to_acknowledge():
    eng, rec, _ = make_engine(flash_frames=1)

    eng.on_apc_message((0x90, apc.NOTE_RIGHT, 127))
    assert (0x90, apc.NOTE_RIGHT, 127) in rec.apc_msgs

    eng.tick()
    assert rec.apc_msgs[-1] == (0x80, apc.NOTE_RIGHT, 0)


# ---------------------------------------------------------------------------
# Loop, metronome, Stop x2 and Cue Level jog
# ---------------------------------------------------------------------------


def test_shift_metronome_sends_f1_without_touching_the_loop_led():
    eng, rec, _ = make_engine()

    eng.on_apc_message((0x90, apc.NOTE_SHIFT, 127))
    eng.on_apc_message((0x98, apc.NOTE_UTIL_METRONOME, 127))  # Master bank

    assert rec.mcu_msgs == click(mcu.NOTE_F1)
    assert all(m[1] != apc.NOTE_UTIL_METRONOME for m in rec.apc_msgs)


def test_rec_quantize_led_no_longer_follows_mcu_note_86():
    # Note 86 is Cakewalk's Select-navigation LED, not Cycle.
    eng, rec, _ = make_engine()

    eng.on_mcu_message((0x90, 86, 127))

    assert rec.apc_msgs == []


def test_single_stop_only_stops():
    eng, rec, _ = make_engine(stop_double_frames=5)

    eng.on_apc_message((0x90, apc.NOTE_STOP, 127))

    assert rec.mcu_msgs == click(mcu.NOTE_STOP)


def test_double_stop_returns_to_start():
    eng, rec, _ = make_engine(stop_double_frames=5)

    eng.on_apc_message((0x90, apc.NOTE_STOP, 127))
    eng.on_apc_message((0x80, apc.NOTE_STOP, 127))
    for _ in range(3):
        eng.tick()
    eng.on_apc_message((0x90, apc.NOTE_STOP, 127))

    assert rec.mcu_msgs == click(mcu.NOTE_STOP) * 2 + click(mcu.NOTE_CW_HOME)


def test_slow_second_stop_does_not_return_to_start():
    eng, rec, _ = make_engine(stop_double_frames=5)

    eng.on_apc_message((0x90, apc.NOTE_STOP, 127))
    for _ in range(6):
        eng.tick()
    eng.on_apc_message((0x90, apc.NOTE_STOP, 127))

    assert rec.mcu_msgs == click(mcu.NOTE_STOP) * 2


def test_triple_stop_does_not_go_home_twice():
    eng, rec, _ = make_engine(stop_double_frames=5)

    for _ in range(3):
        eng.on_apc_message((0x90, apc.NOTE_STOP, 127))

    assert rec.mcu_msgs.count(mcu.button_press(mcu.NOTE_CW_HOME)) == 1


# ---------------------------------------------------------------------------
# Crossfader zoom
# ---------------------------------------------------------------------------


def cw_click(note):
    """A click Cakewalk sees both edges of (release = Note On velocity 0)."""
    return [(0x90, note, 127), (0x90, note, 0)]


def fader(eng, value):
    eng.on_apc_message((0xB0, apc.CC_CROSSFADER, value))


def test_first_crossfader_reading_only_sets_the_baseline():
    eng, rec, _ = make_engine()

    fader(eng, 64)

    assert rec.mcu_msgs == []


def test_crossfader_right_enters_zoom_mode_and_zooms_in():
    eng, rec, _ = make_engine(zoom_step_units=8)
    fader(eng, 64)

    fader(eng, 72)

    assert rec.mcu_msgs == click(mcu.NOTE_ZOOM) + cw_click(mcu.NOTE_RIGHT)


def test_small_moves_accumulate_into_one_step():
    eng, rec, _ = make_engine(zoom_step_units=8)
    fader(eng, 64)

    for value in (66, 68, 70):
        fader(eng, value)
    assert rec.mcu_msgs == []
    fader(eng, 72)

    assert rec.mcu_msgs == click(mcu.NOTE_ZOOM) + cw_click(mcu.NOTE_RIGHT)


def test_crossfader_left_zooms_out_without_reentering_zoom_mode():
    eng, rec, _ = make_engine(zoom_step_units=8)
    fader(eng, 64)

    fader(eng, 56)
    fader(eng, 48)

    assert rec.mcu_msgs == click(mcu.NOTE_ZOOM) + cw_click(mcu.NOTE_LEFT) * 2


def test_zoom_mode_is_left_after_the_slider_goes_idle():
    eng, rec, _ = make_engine(zoom_step_units=8, zoom_idle_frames=3)
    fader(eng, 64)
    fader(eng, 72)
    rec.mcu_msgs.clear()

    for _ in range(2):
        eng.tick()
    assert rec.mcu_msgs == []
    eng.tick()

    assert rec.mcu_msgs == click(mcu.NOTE_ZOOM)
    for _ in range(5):
        eng.tick()
    assert rec.mcu_msgs == click(mcu.NOTE_ZOOM)  # only once


def test_zoom_led_already_on_is_not_toggled_off_by_us():
    # If the user turned zoom mode on themselves, the crossfader uses it and
    # leaves it alone.
    eng, rec, _ = make_engine(zoom_step_units=8, zoom_idle_frames=1)
    eng.on_mcu_message((0x90, mcu.NOTE_ZOOM, 127))
    fader(eng, 64)

    fader(eng, 72)
    eng.tick()
    eng.tick()

    assert rec.mcu_msgs == cw_click(mcu.NOTE_RIGHT)


def test_crossfader_fully_left_fits_the_project_once():
    eng, rec, _ = make_engine(zoom_step_units=100)  # no ordinary steps
    fader(eng, 20)

    fader(eng, 1)
    fader(eng, 0)  # end-of-travel jitter: no second fit

    fit = [
        *click(mcu.NOTE_ZOOM),
        (0x90, mcu.NOTE_M4, 127),
        *cw_click(mcu.NOTE_RIGHT),
        (0x90, mcu.NOTE_M4, 0),
    ]
    assert rec.mcu_msgs == fit


def test_fit_rearms_after_the_slider_comes_back_up():
    eng, rec, _ = make_engine(zoom_step_units=100)
    fader(eng, 20)
    fader(eng, 0)
    fader(eng, 11)  # re-arm
    rec.mcu_msgs.clear()

    fader(eng, 0)

    assert (0x90, mcu.NOTE_M4, 127) in rec.mcu_msgs


def test_fast_sweep_is_capped():
    eng, rec, _ = make_engine(zoom_step_units=2)
    fader(eng, 20)

    fader(eng, 120)

    steps = [m for m in rec.mcu_msgs if m == (0x90, mcu.NOTE_RIGHT, 127)]
    assert len(steps) == engine_mod.ZOOM_STEP_LIMIT


# ---------------------------------------------------------------------------
# Send A / B / C select their own send
# ---------------------------------------------------------------------------


def send_param(steps_8, steps_1):
    """Edit on, first parameter, step to the target, Edit off."""
    return [
        *click(mcu.NOTE_CW_EDIT),
        (0x90, mcu.NOTE_M1, 127),
        *click(mcu.NOTE_BANK_LEFT),
        (0x90, mcu.NOTE_M1, 0),
        *click(mcu.NOTE_BANK_RIGHT) * steps_8,
        *click(mcu.NOTE_CHANNEL_RIGHT) * steps_1,
        *click(mcu.NOTE_CW_EDIT),
    ]


def in_pan(eng, rec):
    eng.on_mcu_message((0x90, mcu.NOTE_ASSIGN_PAN, 127))
    rec.mcu_msgs.clear()


def test_send_a_b_c_point_the_knobs_at_send_1_2_3_levels():
    for mode, param in (("send_a", (0, 1)), ("send_b", (0, 5)), ("send_c", (1, 1))):
        eng, rec, _ = make_engine()
        in_pan(eng, rec)

        eng.set_knob_mode(mode)

        assert rec.mcu_msgs == click(mcu.NOTE_ASSIGN_SEND) + send_param(*param), mode


def test_switching_between_sends_never_repeats_assign_send():
    eng, rec, _ = make_engine()
    in_pan(eng, rec)

    eng.set_knob_mode("send_a")
    eng.set_knob_mode("send_b")
    eng.set_knob_mode("send_b")  # pressing again just re-anchors

    presses = [m for m in rec.mcu_msgs if m == mcu.button_press(mcu.NOTE_ASSIGN_SEND)]
    assert len(presses) == 1
    assert rec.mcu_msgs[-len(send_param(0, 5)):] == send_param(0, 5)


def test_pan_is_not_repressed_when_cakewalk_is_already_in_pan():
    eng, rec, _ = make_engine()
    in_pan(eng, rec)

    eng.set_knob_mode("pan")

    assert rec.mcu_msgs == []


def test_send_to_pan_switches_back_once():
    eng, rec, _ = make_engine()
    in_pan(eng, rec)
    eng.set_knob_mode("send_c")
    rec.mcu_msgs.clear()

    eng.set_knob_mode("pan")

    assert rec.mcu_msgs == click(mcu.NOTE_ASSIGN_PAN)


def test_edit_already_on_is_not_toggled_off_before_selecting():
    eng, rec, _ = make_engine()
    in_pan(eng, rec)
    eng.on_mcu_message((0x90, mcu.NOTE_CW_EDIT, 127))  # user left Edit on

    eng.set_knob_mode("send_a")

    # No leading Edit press; the sequence still ends by leaving Edit mode.
    expected = click(mcu.NOTE_ASSIGN_SEND) + send_param(0, 1)[2:]
    assert rec.mcu_msgs == expected


def test_assignment_follows_cakewalk_leds():
    eng, rec, _ = make_engine()
    eng.on_mcu_message((0x90, mcu.NOTE_ASSIGN_SEND, 127))
    rec.mcu_msgs.clear()

    eng.set_knob_mode("send_a")

    assert mcu.button_press(mcu.NOTE_ASSIGN_SEND) not in rec.mcu_msgs


def test_send_button_press_on_apc_selects_its_send():
    eng, rec, _ = make_engine()
    in_pan(eng, rec)

    eng.on_apc_message((0x90, apc.NOTE_SEND_B, 127))

    assert eng.knob_mode == "send_b"
    assert rec.mcu_msgs == click(mcu.NOTE_ASSIGN_SEND) + send_param(0, 5)


# ---------------------------------------------------------------------------
# Track Selection in Generic Mode: detected from the Device knob dump
# ---------------------------------------------------------------------------


def knob_dump(eng, channel, value=0):
    for cc in range(apc.CC_DEVICE_KNOB1, apc.CC_DEVICE_KNOB1 + 8):
        eng.on_apc_message((0xB0 | channel, cc, value))


def settle(eng, frames=3):
    for _ in range(frames):
        eng.tick()


def test_track_selection_dump_selects_that_track():
    eng, rec, _ = make_engine()

    knob_dump(eng, 2)  # Track Selection 3 pressed
    assert rec.mcu_msgs == []  # waits for the burst to end
    settle(eng)

    assert rec.mcu_msgs == click(mcu.NOTE_SELECT1 + 2)


def test_pressing_the_same_track_again_selects_it_again():
    eng, rec, _ = make_engine()

    knob_dump(eng, 4)
    settle(eng)
    knob_dump(eng, 4)
    settle(eng)

    assert rec.mcu_msgs == click(mcu.NOTE_SELECT1 + 4) * 2


def test_whole_surface_dump_is_ignored():
    eng, rec, _ = make_engine()

    for channel in range(9):
        knob_dump(eng, channel)
    settle(eng)

    assert rec.mcu_msgs == []


def test_single_device_knob_turn_is_not_a_selection():
    eng, rec, _ = make_engine()

    eng.on_apc_message((0xB3, apc.CC_DEVICE_KNOB1 + 2, 40))
    eng.on_apc_message((0xB3, apc.CC_DEVICE_KNOB1 + 2, 41))
    settle(eng)

    assert rec.mcu_msgs == []


# ---------------------------------------------------------------------------
# Device Control banks: per-bank knob baselines and ring channel
# ---------------------------------------------------------------------------


def test_bank_switch_dump_is_not_read_as_device_knob_movement():
    eng, rec, _ = make_engine()
    eng.mixer = False

    eng.on_apc_message((0xB0, apc.CC_DEVICE_KNOB1, 10))  # bank 0 baseline
    eng.on_apc_message((0xB3, apc.CC_DEVICE_KNOB1, 12))  # bank 3's own value
    eng.on_apc_message((0xB0, apc.CC_DEVICE_KNOB1, 10))  # back to bank 0

    assert rec.mcu_msgs == []


def test_device_knob_turn_is_relative_to_its_own_bank():
    eng, rec, _ = make_engine()
    eng.mixer = False

    eng.on_apc_message((0xB0, apc.CC_DEVICE_KNOB1, 10))
    eng.on_apc_message((0xB3, apc.CC_DEVICE_KNOB1, 50))
    eng.on_apc_message((0xB3, apc.CC_DEVICE_KNOB1, 51))  # turn on bank 3

    assert rec.mcu_msgs == [mcu.vpot_delta(1, 1)]


def test_device_ring_feedback_goes_to_the_current_bank():
    eng, rec, _ = make_engine()
    eng.mixer = False
    eng.on_apc_message((0xB5, apc.CC_DEVICE_KNOB1, 0))  # bank 5 is showing

    eng.on_mcu_message((0xB0, mcu.CC_RING1, mcu.ring_byte(mcu.RING_MODE_VOLUME, 11)))

    assert (0xB5, apc.device_ring_cc(1), 127) in rec.apc_msgs
    assert (0xB5, apc.device_ring_style_cc(1), apc.RING_VOLUME) in rec.apc_msgs


def test_utility_row_press_updates_the_current_bank():
    eng, _, _ = make_engine()

    eng.on_apc_message((0x98, apc.NOTE_UTIL_DETAIL_VIEW, 127))

    assert eng.device_bank == 8


def test_baseline_centers_device_rings_on_every_bank():
    eng, rec, _ = make_engine()

    eng.render_baseline()

    for bank in range(apc.DEVICE_BANKS):
        assert (0xB0 | bank, apc.device_ring_cc(1), 63) in rec.apc_msgs


# ---------------------------------------------------------------------------
# HUD snapshot
# ---------------------------------------------------------------------------


def lcd_sysex(offset, text):
    return (0xF0, 0x00, 0x00, 0x66, 0x14, 0x12, offset, *text.encode("ascii"), 0xF7)


def lcd_cells(names):
    return "".join(f"{name[:6]:<6} " for name in names)


def track_message(number, name):
    return lcd_sysex(0, f'Track {number}: "{name}"'.center(56))


def toast_texts(eng):
    return [text for _id, text in eng.hud_snapshot().toasts]


def test_hud_snapshot_follows_knob_mode_and_shift():
    eng, _, _ = make_engine()
    eng.set_knob_mode("send_b")
    eng.on_apc_message((0x90, apc.NOTE_SHIFT, 127))
    snap = eng.hud_snapshot()
    assert (snap.knob_mode, snap.shift, snap.mixer) == ("send_b", True, True)
    assert toast_texts(eng)[-1] == "Send B"


def test_hud_snapshot_stores_transport_loop_and_zoom_leds():
    eng, _, _ = make_engine()
    assert eng.hud_snapshot().transport == "stop"

    eng.on_mcu_message(mcu.note_on(mcu.NOTE_PLAY, 127))
    eng.on_mcu_message(mcu.note_on(mcu.NOTE_CW_LOOP, 127))
    eng.on_mcu_message(mcu.note_on(mcu.NOTE_ZOOM, 127))
    snap = eng.hud_snapshot()
    assert (snap.transport, snap.loop, snap.zoom) == ("play", True, True)

    eng.on_mcu_message(mcu.note_on(mcu.NOTE_RECORD, 127))
    assert eng.hud_snapshot().transport == "record"

    eng.on_mcu_message(mcu.note_on(mcu.NOTE_RECORD, 0))
    eng.on_mcu_message(mcu.note_on(mcu.NOTE_PLAY, 0))
    eng.on_mcu_message(mcu.note_on(mcu.NOTE_CW_LOOP, 0))
    snap = eng.hud_snapshot()
    assert (snap.transport, snap.loop) == ("stop", False)


def test_hud_snapshot_stores_strip_leds_and_selection():
    eng, rec, _ = make_engine()
    eng.on_mcu_message(mcu.note_on(mcu.NOTE_REC1 + 1, 127))
    eng.on_mcu_message(mcu.note_on(mcu.NOTE_SOLO1 + 2, 127))
    eng.on_mcu_message(mcu.note_on(mcu.NOTE_MUTE1 + 3, 1))  # blink counts as on
    eng.on_mcu_message(mcu.note_on(mcu.NOTE_SELECT1 + 4, 127))
    snap = eng.hud_snapshot()
    assert snap.rec[1] and snap.solo[2] and snap.mute[3]
    assert snap.selected_strip == 4
    # The LEDs still reach the APC40.
    assert (0x91, apc.NOTE_RECORD_ARM, apc.LED_ON) in rec.apc_msgs

    eng.on_mcu_message(mcu.note_on(mcu.NOTE_SELECT1 + 5, 127))
    assert eng.hud_snapshot().selected_strip is None  # two lit: ambiguous


def test_hud_meters_and_cakewalk_activity():
    eng, _, _ = make_engine(link_idle_frames=10)
    snap = eng.hud_snapshot()
    assert not snap.cakewalk_active and not snap.cakewalk_meters

    eng.on_mcu_message(mcu.meter_message(2, 9))
    snap = eng.hud_snapshot()
    assert snap.cakewalk_active and snap.cakewalk_meters
    assert snap.meter_levels[2] == 9

    run_frames(eng, 11)
    assert not eng.hud_snapshot().cakewalk_active


def test_hud_meters_decay_even_with_the_grid_meters_off():
    eng, _, _ = make_engine(meters=False, meter_decay_frames=1)
    eng.on_mcu_message(mcu.meter_message(0, 5))
    eng.tick()
    assert eng.hud_snapshot().meter_levels[0] == 4


def test_hud_toasts_for_actions_without_feedback():
    eng, _, _ = make_engine(stop_double_frames=5)
    eng.on_apc_message((0x90, apc.NOTE_RIGHT, 127))
    eng.on_apc_message((0x90, apc.NOTE_SHIFT, 127))
    eng.on_apc_message((0x90, apc.NOTE_LEFT, 127))
    eng.on_apc_message((0x90, apc.NOTE_UTIL_METRONOME, 127))
    eng.on_apc_message((0x80, apc.NOTE_SHIFT, 0))
    eng.on_apc_message((0x90, apc.NOTE_STOP, 127))
    eng.on_apc_message((0x90, apc.NOTE_STOP, 127))
    eng.on_apc_message((0x90, apc.NOTE_STOP_ALL_CLIPS, 127))
    assert toast_texts(eng) == [
        "Bank >",
        "Channel <",
        "Metronome (rec) toggled",
        "Go to start",
        "Stop all",
    ]
    ids = [i for i, _t in eng.hud_snapshot().toasts]
    assert ids == sorted(ids) and len(set(ids)) == len(ids)


def test_hud_toast_for_meter_toggle_and_zoom_fit():
    eng, _, _ = make_engine()
    press_shift_detail(eng)
    assert toast_texts(eng)[-1] == "Cakewalk meters on"

    eng.on_apc_message((0xB0, apc.CC_CROSSFADER, 60))
    eng.on_apc_message((0xB0, apc.CC_CROSSFADER, 0))
    assert toast_texts(eng)[-1] == "Zoom: fit project"


def test_hud_toast_history_is_bounded():
    eng, _, _ = make_engine()
    for i in range(20):
        eng.toast(f"t{i}")
    toasts = eng.hud_snapshot().toasts
    assert len(toasts) == engine_mod.TOAST_HISTORY
    assert toasts[-1] == (20, "t19")


def test_hud_snapshot_is_equal_when_nothing_changed():
    eng, _, _ = make_engine()
    first = eng.hud_snapshot()
    assert eng.hud_snapshot() == first
    eng.on_mcu_message(mcu.note_on(mcu.NOTE_PLAY, 127))
    assert eng.hud_snapshot() != first


def test_hud_lcd_names_values_and_timecode():
    eng, _, _ = make_engine()
    names = ["Kick", "Snare", "OH", "Bass", "Gtr L", "Gtr R", "Vocals", "Pad"]
    eng.on_mcu_message(lcd_sysex(0, lcd_cells(names)))
    eng.on_mcu_message(lcd_sysex(56, lcd_cells(["C", "L12", "R5", "", "", "", "", ""])))
    for index, char in enumerate(" 3702  000"):
        code = ord(char)
        eng.on_mcu_message(mcu.control_change(73 - index, code - 0x40 if code >= 0x40 else code))
    eng.on_mcu_message(mcu.control_change(75, 0x13))  # S
    eng.on_mcu_message(mcu.control_change(74, 0x05))  # E

    snap = eng.hud_snapshot()
    assert snap.lcd_seen
    assert snap.strip_names == tuple(names)
    assert snap.strip_values[:3] == ("C", "L12", "R5")
    assert snap.timecode == "37.02.000"
    assert (snap.assignment, snap.strip_layout) == ("SE", False)


def test_timecode_ccs_do_not_reach_the_rings():
    eng, rec, _ = make_engine()
    eng.on_mcu_message(mcu.control_change(64, 0x30))
    assert rec.apc_msgs == []


def test_hud_vpot_peek_is_not_taken_for_a_name():
    eng, _, _ = make_engine(peek_frames=10)
    eng.on_mcu_message(lcd_sysex(0, lcd_cells(["Kick", "Snare", "", "", "", "", "", ""])))

    eng.on_apc_message((0xB0, apc.CC_TRACK_KNOB1 + 1, 10))
    eng.on_apc_message((0xB0, apc.CC_TRACK_KNOB1 + 1, 11))  # turn knob 2
    eng.on_mcu_message(lcd_sysex(7, " -3.0 "))
    snap = eng.hud_snapshot()
    assert snap.strip_names[1] == "Snare"
    assert snap.strip_peek[1] == "-3.0"

    eng.on_mcu_message(lcd_sysex(7, "Snare "))  # Cakewalk restores the name
    snap = eng.hud_snapshot()
    assert (snap.strip_names[1], snap.strip_peek[1]) == ("Snare", "")

    # A rename long after any knob turn is a new name.
    run_frames(eng, 11)
    eng.on_mcu_message(lcd_sysex(7, "Snr2  "))
    assert eng.hud_snapshot().strip_names[1] == "Snr2"


def test_hud_stale_peek_expires_to_a_name():
    eng, _, _ = make_engine(peek_frames=5)
    eng.on_apc_message((0xB0, apc.CC_TRACK_KNOB1, 10))
    eng.on_apc_message((0xB0, apc.CC_TRACK_KNOB1, 11))
    eng.on_mcu_message(lcd_sysex(0, "Kick  "))
    assert eng.hud_snapshot().strip_peek[0] == "Kick"
    run_frames(eng, 6)
    snap = eng.hud_snapshot()
    assert (snap.strip_names[0], snap.strip_peek[0]) == ("Kick", "")


def test_hud_track_message_sets_selection_and_bank_offset():
    eng, _, _ = make_engine()
    eng.on_mcu_message(lcd_sysex(0, lcd_cells(["A", "B", "C", "Vocals", "E", "F", "G", "H"])))

    # Track Selection on strip 4; Cakewalk lights Select 4 and names track 12.
    eng.on_apc_message((0x93, apc.NOTE_TRACK_SELECT, 127))
    eng.on_mcu_message(mcu.note_on(mcu.NOTE_SELECT1 + 3, 127))
    eng.on_mcu_message(track_message(12, "Vocals"))

    snap = eng.hud_snapshot()
    assert (snap.bank_offset, snap.bank_exact) == (8, True)
    assert (snap.selected_track, snap.selected_name) == (12, "Vocals")
    assert toast_texts(eng)[-1] == 'Track 12: "Vocals"'
    # The temp message does not overwrite the strip names.
    assert snap.strip_names[3] == "Vocals"


def test_hud_bank_offset_from_select_led_when_message_comes_first():
    eng, _, _ = make_engine()
    eng.on_mcu_message(track_message(3, "Bass"))
    assert eng.hud_snapshot().bank_offset is None
    eng.on_mcu_message(mcu.note_on(mcu.NOTE_SELECT1 + 2, 127))
    assert eng.hud_snapshot().bank_offset == 0


def test_hud_bank_moves_make_the_offset_provisional():
    eng, _, _ = make_engine()
    eng.on_apc_message((0x90, apc.NOTE_TRACK_SELECT, 127))
    eng.on_mcu_message(track_message(1, "Kick"))
    assert eng.hud_snapshot().bank_offset == 0

    eng.on_apc_message((0x90, apc.NOTE_RIGHT, 127))  # Bank >
    snap = eng.hud_snapshot()
    assert (snap.bank_offset, snap.bank_exact) == (8, False)

    eng.on_apc_message((0x90, apc.NOTE_SHIFT, 127))
    eng.on_apc_message((0x90, apc.NOTE_LEFT, 127))  # Channel <
    eng.on_apc_message((0x80, apc.NOTE_SHIFT, 0))
    assert eng.hud_snapshot().bank_offset == 7

    eng.on_apc_message((0x90, apc.NOTE_LEFT, 127))  # Bank <, clamped at 0
    assert eng.hud_snapshot().bank_offset == 0


def test_hud_send_param_moves_do_not_count_as_bank_moves():
    eng, _, _ = make_engine()
    eng.on_apc_message((0x90, apc.NOTE_TRACK_SELECT, 127))
    eng.on_mcu_message(track_message(1, "Kick"))
    eng.set_knob_mode("send_c")  # Edit mode + Bank/Channel parameter moves
    snap = eng.hud_snapshot()
    assert (snap.bank_offset, snap.bank_exact) == (0, True)


def test_hud_strip_layout_dot_is_reported():
    eng, _, _ = make_engine()
    eng.on_mcu_message(mcu.control_change(74, 0x40 | 0x0E))
    assert eng.hud_snapshot().strip_layout


def test_non_lcd_sysex_is_ignored():
    eng, rec, _ = make_engine()
    eng.on_mcu_message((0xF0, 0x7E, 0x00, 0x06, 0x01, 0xF7))
    assert not eng.hud_snapshot().lcd_seen
    assert rec.apc_msgs == [] and rec.mcu_msgs == []


# ---------------------------------------------------------------------------
# Nudge -/+ = Rewind / Fast Forward, held through
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Playhead steps: Cue, Shift + Cue and Nudge sizes from .env
# ---------------------------------------------------------------------------


def jogs(forward, n, modifier=None):
    """n jog messages, wrapped in a held Mackie modifier when given."""
    body = [mcu.jog(forward)] * n
    if modifier is None:
        return body
    return [mcu.button_press(modifier), *body, mcu.cakewalk_release(modifier)]


def test_cue_moves_by_the_cue_step_with_its_unit_modifier():
    eng, rec, _ = make_engine(cue_step=(1, "beat"))

    eng.on_apc_message((0xB0, apc.CC_CUE_LEVEL, 1))  # +1 detent
    eng.on_apc_message((0xB0, apc.CC_CUE_LEVEL, 127))  # -1 detent

    assert rec.mcu_msgs == jogs(True, 1, mcu.NOTE_M2) + jogs(False, 1, mcu.NOTE_M2)


def test_shift_cue_uses_the_fine_step():
    eng, rec, _ = make_engine(shift_cue_step=(30, "tick"))
    eng.on_apc_message((0x90, apc.NOTE_SHIFT, 127))

    eng.on_apc_message((0xB0, apc.CC_CUE_LEVEL, 1))

    assert rec.mcu_msgs == jogs(True, 30, mcu.NOTE_M3)


def test_jog_unit_uses_the_preset_resolution_without_a_modifier():
    eng, rec, _ = make_engine(cue_step=(2, "jog"))

    eng.on_apc_message((0xB0, apc.CC_CUE_LEVEL, 1))

    assert rec.mcu_msgs == jogs(True, 2)


def test_fast_cue_turn_is_capped_in_detents():
    eng, rec, _ = make_engine(cue_step=(2, "measure"))

    eng.on_apc_message((0xB0, apc.CC_CUE_LEVEL, 128 - 20))  # -20 detents

    limit = engine_mod.CUE_JOG_STEP_LIMIT
    assert rec.mcu_msgs == jogs(False, 2 * limit, mcu.NOTE_M1)


def test_nudge_press_moves_one_nudge_step():
    eng, rec, _ = make_engine(nudge_step=(1, "measure"))

    eng.on_apc_message((0x90, apc.NOTE_NUDGE_MINUS, 127))
    eng.on_apc_message((0x80, apc.NOTE_NUDGE_MINUS, 127))
    eng.on_apc_message((0x90, apc.NOTE_NUDGE_PLUS, 127))
    eng.on_apc_message((0x80, apc.NOTE_NUDGE_PLUS, 127))

    assert rec.mcu_msgs == jogs(False, 1, mcu.NOTE_M1) + jogs(True, 1, mcu.NOTE_M1)


def test_nudge_held_repeats_after_the_hold_delay():
    eng, rec, _ = make_engine(nudge_step=(1, "beat"), nudge_hold_frames=3, nudge_repeat_frames=2)

    eng.on_apc_message((0x90, apc.NOTE_NUDGE_PLUS, 127))
    for _ in range(2):
        eng.tick()
    assert rec.mcu_msgs == jogs(True, 1, mcu.NOTE_M2)  # still inside the hold delay

    for _ in range(5):  # frames 3..7: repeats at 3, 5, 7
        eng.tick()
    assert rec.mcu_msgs == jogs(True, 1, mcu.NOTE_M2) * 4

    eng.on_apc_message((0x80, apc.NOTE_NUDGE_PLUS, 127))
    for _ in range(10):
        eng.tick()
    assert rec.mcu_msgs == jogs(True, 1, mcu.NOTE_M2) * 4  # stopped on release


# ---------------------------------------------------------------------------
# Shift latching: hold / tap = one-shot / double-tap = lock
# ---------------------------------------------------------------------------


def shift_tap(eng):
    eng.on_apc_message((0x90, apc.NOTE_SHIFT, 127))
    eng.on_apc_message((0x80, apc.NOTE_SHIFT, 0))


def press(eng, note, channel=0):
    eng.on_apc_message((0x90 | channel, note, 127))
    eng.on_apc_message((0x80 | channel, note, 0))


def test_held_shift_then_release_is_not_a_tap():
    eng, _, _ = make_engine()

    eng.on_apc_message((0x90, apc.NOTE_SHIFT, 127))
    press(eng, apc.NOTE_RIGHT)  # Shift + Right combo
    eng.on_apc_message((0x80, apc.NOTE_SHIFT, 0))

    assert eng.shift_state == "off"


def test_one_shot_shifts_the_next_button_then_clears():
    eng, rec, _ = make_engine()
    shift_tap(eng)

    press(eng, apc.NOTE_RIGHT)  # shifted: channel right
    press(eng, apc.NOTE_RIGHT)  # not shifted: bank right

    assert rec.mcu_msgs == click(mcu.NOTE_CHANNEL_RIGHT) + click(mcu.NOTE_BANK_RIGHT)
    assert eng.shift_state == "off"


def test_one_shot_is_used_up_by_a_button_without_a_shift_function():
    eng, rec, _ = make_engine()
    shift_tap(eng)

    press(eng, apc.NOTE_PLAY)  # no Shift combo: normal Play, one-shot gone
    press(eng, apc.NOTE_RIGHT)

    assert rec.mcu_msgs == click(mcu.NOTE_PLAY) + click(mcu.NOTE_BANK_RIGHT)


def test_one_shot_expires():
    eng, _, _ = make_engine(shift_oneshot_frames=5)
    shift_tap(eng)

    for _ in range(4):
        eng.tick()
    assert eng.shift_state == "once"
    eng.tick()
    assert eng.shift_state == "off"


def test_double_tap_locks_until_the_next_tap():
    eng, rec, _ = make_engine(shift_double_frames=10)
    shift_tap(eng)
    eng.tick()
    shift_tap(eng)
    assert eng.shift_state == "locked"

    press(eng, apc.NOTE_RIGHT)
    press(eng, apc.NOTE_RIGHT)
    assert rec.mcu_msgs == click(mcu.NOTE_CHANNEL_RIGHT) * 2
    for _ in range(500):
        eng.tick()
    assert eng.shift_state == "locked"  # no expiry when locked

    shift_tap(eng)
    assert eng.shift_state == "off"


def test_slow_second_tap_cancels_the_one_shot():
    eng, _, _ = make_engine(shift_double_frames=3)
    shift_tap(eng)
    for _ in range(5):
        eng.tick()

    shift_tap(eng)

    assert eng.shift_state == "off"


def test_one_shot_does_not_apply_to_the_cue_knob():
    eng, rec, _ = make_engine(cue_step=(1, "beat"), shift_cue_step=(30, "tick"))
    shift_tap(eng)

    eng.on_apc_message((0xB0, apc.CC_CUE_LEVEL, 1))

    assert rec.mcu_msgs == jogs(True, 1, mcu.NOTE_M2)  # coarse step
    assert eng.shift_state == "once"  # still armed for a button


def test_locked_shift_applies_to_the_cue_knob():
    eng, rec, _ = make_engine(shift_cue_step=(30, "tick"), shift_double_frames=10)
    shift_tap(eng)
    shift_tap(eng)

    eng.on_apc_message((0xB0, apc.CC_CUE_LEVEL, 1))

    assert rec.mcu_msgs == jogs(True, 30, mcu.NOTE_M3)


def test_hud_snapshot_reports_the_shift_state():
    eng, _, _ = make_engine()
    shift_tap(eng)

    snap = eng.hud_snapshot()

    assert snap.shift and snap.shift_state == "once"


# ---------------------------------------------------------------------------
# Modes (Scene buttons), Tracking utility row, Master = Tracks / Buses
# ---------------------------------------------------------------------------


def cw_press(note):
    """A Cakewalk button that needs a visible release (Note On 0)."""
    return [(0x90, note, 127), (0x90, note, 0)]


def with_mod(modifier, note):
    return [mcu.button_press(modifier), *click(note), mcu.cakewalk_release(modifier)]


def nav(nav_note, inner):
    """Enter a navigation mode, run *inner*, press it again to leave."""
    return [*click(nav_note), *inner, *click(nav_note)]


def tap(eng, note, channel=0):
    """One physical press of a latching utility button (58-61): one edge."""
    eng.on_apc_message((0x90 | channel, note, 127))


def test_render_baseline_starts_in_tracking_with_scene_1_lit():
    eng, rec, _ = make_engine()

    eng.render_baseline()

    assert eng.mode == "tracking"
    assert eng.knob_mode == "pan"
    assert (0x90, apc.NOTE_SCENE1, 127) in rec.apc_msgs
    for scene in apc.SCENE_NOTES[1:]:
        assert rec.apc_msgs[-1] != (0x90, scene, 127)
    assert (0x90, apc.NOTE_MASTER, 127) not in rec.apc_msgs  # the APC40 owns Master's LED

    device_styles = {m[1]: m[2] for m in rec.apc_msgs if m[1] in range(24, 32)}
    assert set(device_styles) == set(range(24, 32))
    assert all(value == apc.RING_PAN for value in device_styles.values())


def test_scene_buttons_select_the_mode_and_light_one_scene():
    eng, rec, _ = make_engine()

    eng.on_apc_message((0x90, apc.NOTE_SCENE1 + 2, 127))  # Scene 3 = Mixing
    assert eng.mode == "mixing"
    lit = {m[1] for m in rec.apc_msgs if m[0] == 0x90 and m[1] in apc.SCENE_NOTES}
    assert lit == {apc.NOTE_SCENE1 + 2}

    eng.on_apc_message((0x90, apc.NOTE_SCENE1, 127))  # Scene 1 = Tracking
    assert eng.mode == "tracking"


def test_step_sequencer_scene_needs_its_output_port():
    eng, _, _ = make_engine()

    eng.on_apc_message((0x90, apc.NOTE_SCENE1 + 1, 127))

    assert eng.mode == "tracking"
    assert any("SEQ_OUT_PORT" in text for _, text in eng.hud_snapshot().toasts)


def test_scene_release_reasserts_the_mode_led():
    eng, rec, _ = make_engine()
    rec.apc_msgs.clear()

    eng.on_apc_message((0x80, apc.NOTE_SCENE1 + 3, 127))  # the APC40 blanks it

    assert (0x90, apc.NOTE_SCENE1, 127) in rec.apc_msgs


def test_rec_quantize_toggles_loop_with_a_visible_release():
    eng, rec, _ = make_engine()

    for bank in (0, 8):
        press(eng, apc.NOTE_UTIL_REC_QUANT, channel=bank)

    assert rec.mcu_msgs == cw_press(mcu.NOTE_CW_LOOP) * 2


def test_loop_feedback_lights_rec_quantize_and_is_reasserted_on_release():
    eng, rec, _ = make_engine()

    eng.on_mcu_message((0x90, mcu.NOTE_CW_LOOP, 127))
    assert (0x90, apc.NOTE_UTIL_REC_QUANT, 127) in rec.apc_msgs
    rec.apc_msgs.clear()

    eng.on_apc_message((0x88, apc.NOTE_UTIL_REC_QUANT, 127))  # release on the Master bank

    assert rec.apc_msgs == [(0x90 | bank, apc.NOTE_UTIL_REC_QUANT, 127) for bank in range(9)]


def test_metronome_button_is_auto_punch_and_shift_is_the_metronome():
    eng, rec, _ = make_engine()

    press(eng, apc.NOTE_UTIL_METRONOME)
    eng.on_apc_message((0x90, apc.NOTE_SHIFT, 127))
    press(eng, apc.NOTE_UTIL_METRONOME)

    assert rec.mcu_msgs == click(mcu.NOTE_F2) + click(mcu.NOTE_F1)


def test_undo_and_redo():
    eng, rec, _ = make_engine()

    tap(eng, apc.NOTE_UTIL_CLIP_TRACK)
    eng.on_apc_message((0x90, apc.NOTE_SHIFT, 127))
    tap(eng, apc.NOTE_UTIL_CLIP_TRACK)

    assert rec.mcu_msgs == click(mcu.NOTE_CW_UNDO) + click(mcu.NOTE_CW_REDO)


def test_insert_marker():
    eng, rec, _ = make_engine()

    tap(eng, apc.NOTE_UTIL_DEVICE_ONOFF)

    assert rec.mcu_msgs == with_mod(mcu.NOTE_M1, mcu.NOTE_CW_MARKER)


def test_arrows_jump_between_markers_and_return_to_normal_navigation():
    eng, rec, _ = make_engine()

    tap(eng, apc.NOTE_UTIL_LEFT_ARROW)
    tap(eng, apc.NOTE_UTIL_RIGHT_ARROW)

    assert rec.mcu_msgs == (
        nav(mcu.NOTE_CW_MARKER, cw_press(mcu.NOTE_REWIND))
        + nav(mcu.NOTE_CW_MARKER, cw_press(mcu.NOTE_FORWARD))
    )


def test_marker_navigation_already_on_is_not_toggled_off_first():
    eng, rec, _ = make_engine()
    eng.on_mcu_message((0x90, mcu.NOTE_CW_MARKER, 127))  # Cakewalk already in marker nav

    tap(eng, apc.NOTE_UTIL_RIGHT_ARROW)

    assert rec.mcu_msgs == [*cw_press(mcu.NOTE_FORWARD), *click(mcu.NOTE_CW_MARKER)]


def test_shift_arrows_go_to_selection_start_and_end():
    eng, rec, _ = make_engine()
    eng.on_apc_message((0x90, apc.NOTE_SHIFT, 127))

    tap(eng, apc.NOTE_UTIL_LEFT_ARROW)
    tap(eng, apc.NOTE_UTIL_RIGHT_ARROW)

    assert rec.mcu_msgs == (
        nav(mcu.NOTE_CW_SELECT_NAV, cw_press(mcu.NOTE_REWIND))
        + nav(mcu.NOTE_CW_SELECT_NAV, cw_press(mcu.NOTE_FORWARD))
    )


def test_loop_and_punch_from_selection():
    eng, rec, _ = make_engine()

    press(eng, apc.NOTE_UTIL_DETAIL_VIEW)
    press(eng, apc.NOTE_UTIL_OVERDUB)

    assert rec.mcu_msgs == (
        with_mod(mcu.NOTE_M2, mcu.NOTE_CW_LOOP_NAV) + with_mod(mcu.NOTE_M2, mcu.NOTE_CW_PUNCH_NAV)
    )


def test_shift_nudge_sets_selection_start_and_end():
    eng, rec, _ = make_engine()
    eng.on_apc_message((0x90, apc.NOTE_SHIFT, 127))

    press(eng, apc.NOTE_NUDGE_MINUS)
    press(eng, apc.NOTE_NUDGE_PLUS)

    def edge(button):
        return nav(mcu.NOTE_CW_SELECT_NAV, [
            mcu.button_press(mcu.NOTE_M1), *cw_press(button), mcu.cakewalk_release(mcu.NOTE_M1),
        ])

    assert rec.mcu_msgs == edge(mcu.NOTE_REWIND) + edge(mcu.NOTE_FORWARD)


def test_mixing_mode_reserves_58_to_61_but_keeps_the_rest():
    eng, rec, _ = make_engine()
    eng.set_mode("mixing")

    for note in (apc.NOTE_UTIL_CLIP_TRACK, apc.NOTE_UTIL_DEVICE_ONOFF,
                 apc.NOTE_UTIL_LEFT_ARROW, apc.NOTE_UTIL_RIGHT_ARROW):
        press(eng, note)
    assert rec.mcu_msgs == []

    press(eng, apc.NOTE_UTIL_REC_QUANT)  # loop still works
    assert rec.mcu_msgs == cw_press(mcu.NOTE_CW_LOOP)


def press_master(eng):
    """Master sends no note in Generic Mode, only its bank's knob dump."""
    knob_dump(eng, 8)
    settle(eng)


def test_master_toggles_tracks_and_buses():
    eng, rec, _ = make_engine()

    press_master(eng)
    assert rec.mcu_msgs == click(mcu.NOTE_CW_AUX)
    eng.on_mcu_message((0x90, mcu.NOTE_CW_AUX, 127))  # Cakewalk confirms buses

    press_master(eng)
    assert rec.mcu_msgs == click(mcu.NOTE_CW_AUX) + click(mcu.NOTE_CW_TRACK)


def test_master_note_alone_does_nothing():
    eng, rec, _ = make_engine()

    press(eng, apc.NOTE_MASTER)
    settle(eng)

    assert rec.mcu_msgs == []


def test_hud_snapshot_reports_mode_and_buses():
    eng, _, _ = make_engine()
    eng.set_mode("mixing")
    press_master(eng)

    snap = eng.hud_snapshot()

    assert snap.mode == "mixing" and snap.buses


def test_jog_budget_caps_messages_per_frame():
    # A fast spin with a fine step must not flood the loopMIDI cable.
    eng, rec, _ = make_engine(shift_cue_step=(40, "tick"))
    eng.on_apc_message((0x90, apc.NOTE_SHIFT, 127))

    for _ in range(5):
        eng.on_apc_message((0xB0, apc.CC_CUE_LEVEL, 4))  # 4 detents x 40 ticks each
    jogs_sent = [m for m in rec.mcu_msgs if m[1] == mcu.CC_JOG]
    assert len(jogs_sent) == engine_mod.JOG_BUDGET_PER_FRAME

    eng.tick()  # new frame, new budget
    eng.on_apc_message((0xB0, apc.CC_CUE_LEVEL, 1))
    jogs_sent = [m for m in rec.mcu_msgs if m[1] == mcu.CC_JOG]
    assert len(jogs_sent) == engine_mod.JOG_BUDGET_PER_FRAME + 40


def test_modifier_is_always_released_even_when_capped():
    eng, rec, _ = make_engine(shift_cue_step=(40, "tick"))
    eng.on_apc_message((0x90, apc.NOTE_SHIFT, 127))

    for _ in range(3):
        eng.on_apc_message((0xB0, apc.CC_CUE_LEVEL, 4))

    presses = rec.mcu_msgs.count(mcu.button_press(mcu.NOTE_M3))
    releases = rec.mcu_msgs.count(mcu.cakewalk_release(mcu.NOTE_M3))
    assert presses == releases


def test_latching_utility_buttons_act_on_both_edges_and_stay_dark():
    # 58-61 latch in Generic Mode: Note On lights the LED, the next press sends
    # Note Off. Each edge is one press, and the LED is forced back off.
    eng, rec, _ = make_engine()

    eng.on_apc_message((0x90, apc.NOTE_UTIL_RIGHT_ARROW, 127))  # 1st press (latch on)
    eng.on_apc_message((0x80, apc.NOTE_UTIL_RIGHT_ARROW, 127))  # 2nd press (latch off)

    one_jump = nav(mcu.NOTE_CW_MARKER, cw_press(mcu.NOTE_FORWARD))
    assert rec.mcu_msgs == one_jump * 2
    leds = [m for m in rec.apc_msgs if m[1] == apc.NOTE_UTIL_RIGHT_ARROW]
    assert leds and all(m[0] & 0xF0 == 0x80 for m in leds)  # only "off" writes


def test_latching_undo_works_on_every_press():
    eng, rec, _ = make_engine()

    for status in (0x90, 0x80, 0x90):
        eng.on_apc_message((status, apc.NOTE_UTIL_CLIP_TRACK, 127))

    assert rec.mcu_msgs == click(mcu.NOTE_CW_UNDO) * 3



# ---------------------------------------------------------------------------
# Step sequencer (Scene 2)
# ---------------------------------------------------------------------------


def make_seq_engine(steps=16, lanes=sq.DEFAULT_LANES):
    notes = []
    seq = sq.Sequencer(notes.append, steps=steps, lanes=lanes)
    eng, rec, out = make_engine(sequencer=seq, seq_indicator_frames=3, seq_hold_frames=5, seq_clock_frames=5,
                                   seq_display_lead_ms=0)
    eng.on_apc_message((0x90, apc.NOTE_SCENE1 + 1, 127))
    rec.apc_msgs.clear()
    rec.mcu_msgs.clear()
    return eng, rec, seq, notes


def tap_pad(eng, track, row):
    """Grid pad for track 0-7, row 1-5."""
    eng.on_apc_message((0x90 | track, apc.NOTE_CLIP_ROW1 + row - 1, 127))
    eng.on_apc_message((0x80 | track, apc.NOTE_CLIP_ROW1 + row - 1, 0))


def pad_color(rec, track, row):
    note = apc.NOTE_CLIP_ROW1 + row - 1
    writes = [m for m in rec.apc_msgs if m[1] == note and m[0] & 0x0F == track and m[0] & 0xE0 == 0x80]
    last = writes[-1]
    return last[2] if last[0] & 0xF0 == 0x90 else 0


def stop_row(rec):
    """Clip Stop state per track from the latest writes."""
    row = {}
    for m in rec.apc_msgs:
        if m[1] == apc.NOTE_CLIP_STOP and m[0] & 0xE0 == 0x80:
            row[m[0] & 0x0F] = m[2] if m[0] & 0xF0 == 0x90 else 0
    return row


def test_sequencer_mode_draws_the_pattern_and_leaves_meters_alone():
    eng, rec, seq, _ = make_seq_engine()

    assert eng.mode == "sequencer"
    eng.on_mcu_message((0xD0, 0x0C))  # a loud meter on strip 1
    assert rec.apc_msgs == []


def test_pad_tap_cycles_the_step_and_its_color():
    eng, rec, seq, _ = make_seq_engine()

    tap_pad(eng, 2, 1)
    assert seq.velocity(0, 2) == 100
    assert pad_color(rec, 2, 1) == apc.CLIP_GREEN
    tap_pad(eng, 2, 1)
    assert pad_color(rec, 2, 1) == apc.CLIP_YELLOW
    tap_pad(eng, 2, 1)
    assert pad_color(rec, 2, 1) == apc.CLIP_RED
    tap_pad(eng, 2, 1)
    assert pad_color(rec, 2, 1) == apc.CLIP_OFF and seq.velocity(0, 2) == 0
    assert rec.mcu_msgs == []


def test_arrows_page_steps_and_lanes_instead_of_cakewalk():
    eng, rec, seq, _ = make_seq_engine()

    press(eng, apc.NOTE_RIGHT)  # steps 9-16
    press(eng, apc.NOTE_DOWN)  # lanes 6-10
    tap_pad(eng, 0, 1)

    assert seq.velocity(5, 8) == 100
    assert rec.mcu_msgs == []


def test_pages_stop_at_the_pattern_edges():
    eng, _, seq, _ = make_seq_engine(steps=16)

    for _ in range(3):
        press(eng, apc.NOTE_RIGHT)
    press(eng, apc.NOTE_LEFT)
    press(eng, apc.NOTE_LEFT)  # past the first page
    tap_pad(eng, 0, 1)

    assert seq.velocity(0, 0) == 100


def test_pads_past_the_last_lane_do_nothing():
    eng, _, seq, _ = make_seq_engine(lanes=(sq.Lane(36), sq.Lane(38)))

    tap_pad(eng, 0, 3)  # row 3 has no lane

    assert all(seq.velocity(lane, 0) == 0 for lane in range(2))


def test_clip_stop_row_follows_the_playhead():
    eng, rec, seq, _ = make_seq_engine()

    seq.on_clock([sq.START])
    for _ in range(7):
        seq.on_clock([sq.CLOCK])  # step 2
    eng.tick()

    assert stop_row(rec)[1] == apc.CLIP_GREEN
    assert stop_row(rec).get(0, apc.CLIP_OFF) == apc.CLIP_OFF

    seq.on_clock([sq.STOP])
    eng.tick()
    assert set(stop_row(rec).values()) == {apc.CLIP_OFF}


def test_page_change_briefly_shows_the_page_number():
    eng, rec, seq, _ = make_seq_engine()

    press(eng, apc.NOTE_RIGHT)  # step page 2
    assert stop_row(rec)[1] == apc.CLIP_GREEN

    for _ in range(3):
        eng.tick()
    assert stop_row(rec)[1] == apc.CLIP_OFF


def test_clip_stop_presses_do_not_push_vpots_in_the_sequencer():
    eng, rec, _, _ = make_seq_engine()

    press(eng, apc.NOTE_CLIP_STOP, channel=3)

    assert rec.mcu_msgs == []


def test_hold_pad_and_turn_a_device_knob_sets_velocity():
    eng, rec, seq, _ = make_seq_engine()
    pad = apc.NOTE_CLIP_ROW1

    eng.on_apc_message((0x90, pad, 127))  # hold step 1, lane 1
    eng.on_apc_message((0xB0, apc.CC_DEVICE_KNOB1, 64))  # baseline
    eng.on_apc_message((0xB0, apc.CC_DEVICE_KNOB1, 74))  # +10
    eng.on_apc_message((0x80, pad, 0))  # release: no cycle after a knob turn

    assert seq.velocity(0, 0) == 110
    assert pad_color(rec, 0, 1) == apc.CLIP_GREEN  # nearest band: normal
    assert rec.mcu_msgs == []


def test_device_knob_without_a_held_pad_is_not_velocity():
    eng, _, seq, _ = make_seq_engine()

    eng.on_apc_message((0xB0, apc.CC_DEVICE_KNOB1, 64))
    eng.on_apc_message((0xB0, apc.CC_DEVICE_KNOB1, 74))

    assert seq.velocity(0, 0) == 0


def test_leaving_the_sequencer_restores_the_meter_grid():
    eng, rec, seq, _ = make_seq_engine()
    tap_pad(eng, 0, 5)
    eng.on_mcu_message((0xD0, 0x05))  # strip 1 at level 5 (grid rows 4-5)

    eng.on_apc_message((0x90, apc.NOTE_SCENE1, 127))  # Tracking

    assert pad_color(rec, 0, 5) == apc.CLIP_GREEN  # meter segment, not the step
    assert pad_color(rec, 0, 1) == apc.CLIP_OFF
    assert eng.mode == "tracking"


def test_editor_commands_edit_the_pattern_and_redraw_the_grid():
    eng, rec, seq, _ = make_seq_engine()

    assert eng.seq_command({"op": "cycle", "lane": 0, "step": 0})
    assert pad_color(rec, 0, 1) == apc.CLIP_GREEN
    assert eng.seq_command({"op": "velocity", "lane": 0, "step": 0, "velocity": 127})
    assert pad_color(rec, 0, 1) == apc.CLIP_YELLOW
    assert eng.seq_command({"op": "lane", "lane": 0, "note": 40})
    assert seq.lanes[0].note == 40
    assert not eng.seq_command({"op": "nonsense"})
    assert not eng.seq_command({"op": "cycle"})


def test_editor_view_command_moves_the_apc40_page():
    eng, _, seq, _ = make_seq_engine()

    eng.seq_command({"op": "view", "step_page": 1, "lane_page": 1})
    tap_pad(eng, 0, 1)

    assert seq.velocity(5, 8) == 100


def test_shrinking_the_pattern_pulls_the_page_back():
    eng, _, seq, _ = make_seq_engine(steps=32)
    for _ in range(3):
        press(eng, apc.NOTE_RIGHT)  # steps 25-32

    eng.seq_command({"op": "steps", "steps": 8})

    assert eng.seq_state()["step_page"] == 0


def test_seq_state_carries_labels_page_and_playhead():
    eng, _, seq, _ = make_seq_engine()
    seq.on_clock([sq.START])
    seq.on_clock([sq.CLOCK])

    state = eng.seq_state()

    assert state["lanes"][0]["label"] == "Kick"
    assert state["playing"] == 0
    assert (state["page_steps"], state["page_lanes"]) == (8, 5)
    assert len(state["lanes"][0]["steps"]) == 16


def test_editor_load_command_replaces_the_pattern():
    eng, rec, seq, _ = make_seq_engine()

    ok = eng.seq_command({"op": "load", "pattern": {"steps": 8, "lanes": [{"note": 38, "steps": [127] + [0] * 7}]}})

    assert ok and seq.steps == 8 and seq.lanes[0].note == 38
    assert pad_color(rec, 0, 1) == apc.CLIP_YELLOW
    assert not eng.seq_command({"op": "load", "pattern": {"steps": 8}})


def test_editor_map_command_applies_a_drum_map():
    eng, _, seq, _ = make_seq_engine()
    seq.cycle(0, 0)

    assert eng.seq_command({"op": "map", "drum_map": "Kit", "lanes": [{"note": 35, "name": "Deep"}]})

    assert seq.lanes[0].label == "Deep" and seq.velocity(0, 0) == 100
    assert eng.seq_state()["status"] == "Drum map: Kit"
    assert not eng.seq_command({"op": "map", "lanes": []})


def hold_pad(eng, track, row, frames):
    eng.on_apc_message((0x90 | track, apc.NOTE_CLIP_ROW1 + row - 1, 127))
    for _ in range(frames):
        eng.tick()
    eng.on_apc_message((0x80 | track, apc.NOTE_CLIP_ROW1 + row - 1, 0))


def test_holding_a_lit_pad_turns_it_off_without_cycling():
    eng, rec, seq, _ = make_seq_engine()
    tap_pad(eng, 0, 1)
    tap_pad(eng, 0, 1)  # accent

    eng.on_apc_message((0x90, apc.NOTE_CLIP_ROW1, 127))
    for _ in range(5):
        eng.tick()
    assert seq.velocity(0, 0) == 0  # off at the 1 s mark, before release
    assert pad_color(rec, 0, 1) == apc.CLIP_OFF

    eng.on_apc_message((0x80, apc.NOTE_CLIP_ROW1, 0))
    assert seq.velocity(0, 0) == 0  # the release does not cycle it back on


def test_a_short_hold_still_cycles():
    eng, _, seq, _ = make_seq_engine()
    tap_pad(eng, 0, 1)

    hold_pad(eng, 0, 1, 4)

    assert seq.velocity(0, 0) == 127  # normal -> accent


def test_holding_an_off_pad_turns_it_on_at_release():
    eng, _, seq, _ = make_seq_engine()

    hold_pad(eng, 0, 1, 20)

    assert seq.velocity(0, 0) == 100


def test_a_knob_turn_during_a_hold_cancels_hold_to_clear():
    eng, _, seq, _ = make_seq_engine()
    tap_pad(eng, 0, 1)

    eng.on_apc_message((0x90, apc.NOTE_CLIP_ROW1, 127))
    eng.on_apc_message((0xB0, apc.CC_DEVICE_KNOB1, 64))
    eng.on_apc_message((0xB0, apc.CC_DEVICE_KNOB1, 70))
    for _ in range(10):
        eng.tick()
    eng.on_apc_message((0x80, apc.NOTE_CLIP_ROW1, 0))

    assert seq.velocity(0, 0) == 106


def test_playing_without_a_clock_warns_how_to_fix_it():
    eng, _, seq, _ = make_seq_engine()
    eng.on_mcu_message((0x90, mcu.NOTE_PLAY, 127))  # Cakewalk plays

    for _ in range(6):
        eng.tick()

    state = eng.seq_state()
    assert state["status_warn"] and "APC40-CLOCK" in state["status"]

    seq.on_clock([sq.START])  # the clock arrives: the warning goes away
    eng.tick()
    assert not eng.seq_state()["status_warn"]


def test_no_warning_while_the_clock_runs():
    eng, _, seq, _ = make_seq_engine()
    seq.on_clock([sq.START])
    eng.on_mcu_message((0x90, mcu.NOTE_PLAY, 127))

    for _ in range(10):
        eng.tick()

    assert eng.seq_state()["status"] == ""


def test_editor_lead_command_sets_the_display_lead():
    eng, _, _, _ = make_seq_engine()

    assert eng.seq_command({"op": "lead", "ms": 80})
    assert eng.seq_state()["lead_ms"] == 80
    eng.seq_command({"op": "lead", "ms": 9999})
    assert eng.seq_state()["lead_ms"] == 500
