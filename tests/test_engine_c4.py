"""Engine tests for the Mackie Control C4 (plug-in control on the Device knobs)."""

from __future__ import annotations

import random

from apc40sonar import apc40 as apc
from apc40sonar import c4
from apc40sonar import engine as engine_mod
from apc40sonar import mcu
from apc40sonar import sequencer as sq

from test_engine import Recorder, click, knob_dump, settle

RESET = c4.with_shift([c4.SLOT_DOWN, c4.BANK_LEFT])


class C4Recorder(Recorder):
    def __init__(self) -> None:
        super().__init__()
        self.c4_msgs: list[tuple[int, ...]] = []

    def c4_send(self, message) -> None:
        self.c4_msgs.append(tuple(message))


def make_engine(**kwargs):
    rec = C4Recorder()
    out = apc.Apc40Output(rec.apc_send)
    eng = engine_mod.Engine(out, rec.mcu_send, c4_send=rec.c4_send, **kwargs)
    return eng, rec


def send_leds(eng, on=()):
    """Cakewalk's full LED refresh: every C4 LED, *on* lit."""
    for led in range(9):
        eng.on_c4_message((0x90, led, 0x7F if led in on else 0x00))


def ready_engine(**kwargs):
    """An engine whose C4 finished setup (from Cakewalk's defaults)."""
    eng, rec = make_engine(**kwargs)
    eng.c4_connect()
    send_leds(eng, on=(c4.CHANNEL_STRIP,))
    settle(eng)
    assert eng.c4_state == "ready"
    rec.c4_msgs.clear()
    rec.mcu_msgs.clear()
    rec.apc_msgs.clear()
    return eng, rec


def lcd(offset, text, row=0):
    return (0xF0, 0x00, 0x00, 0x66, 0x17, 0x30 + row, offset, *text.encode("ascii"), 0xF7)


# ---------------------------------------------------------------------------
# Handshake and setup
# ---------------------------------------------------------------------------


def test_connect_sends_wake_up_then_the_serial_reply():
    eng, rec = make_engine()
    eng.c4_connect()
    assert rec.c4_msgs == [c4.wake_up(), c4.serial_reply()]
    assert eng.c4_state == "waiting"


def test_no_setup_presses_before_the_leds_are_known():
    eng, rec = make_engine()
    eng.c4_connect()
    settle(eng, 100)
    assert rec.c4_msgs == [c4.wake_up(), c4.serial_reply()]


def test_setup_from_cakewalks_defaults_assigns_plugin():
    eng, rec = make_engine()
    eng.c4_connect()
    rec.c4_msgs.clear()
    send_leds(eng, on=(c4.CHANNEL_STRIP,))
    settle(eng)
    assert rec.c4_msgs == c4.assign_plugin_macro() + RESET
    assert eng.c4_state == "ready"


def test_setup_turns_channel_strip_on_and_waits_for_its_led():
    eng, rec = make_engine()
    eng.c4_connect()
    rec.c4_msgs.clear()
    send_leds(eng)
    settle(eng)
    assert rec.c4_msgs == c4.click(c4.CHANNEL_STRIP)

    rec.c4_msgs.clear()
    settle(eng, 10)
    assert rec.c4_msgs == []  # waits for the LEDs to answer

    eng.on_c4_message((0x90, c4.CHANNEL_STRIP, 0x7F))
    settle(eng)
    assert rec.c4_msgs == c4.assign_plugin_macro() + RESET


def test_setup_leaves_track_and_function_modes():
    eng, rec = make_engine()
    eng.c4_connect()
    rec.c4_msgs.clear()
    send_leds(eng, on=(c4.CHANNEL_STRIP, c4.TRACK, c4.FUNCTION))
    settle(eng)
    assert rec.c4_msgs == [c4.button_release(c4.TRACK)] + c4.click(c4.FUNCTION)


def test_setup_gives_up_waiting_and_continues():
    eng, rec = make_engine()
    eng.c4_connect()
    send_leds(eng)
    settle(eng, engine_mod.C4_SETUP_TIMEOUT_FRAMES * (engine_mod.C4_SETUP_ATTEMPTS + 2))
    assert eng.c4_state == "ready"
    clicks = [m for m in rec.c4_msgs if m == c4.button_press(c4.CHANNEL_STRIP)]
    assert len(clicks) == engine_mod.C4_SETUP_ATTEMPTS


def test_serial_query_is_answered_and_restarts_setup():
    eng, rec = ready_engine()
    query = (0xF0, 0x00, 0x00, 0x66, 0x17, 0x1A, 0x00, 0xF7)
    eng.on_c4_message(query)
    assert rec.c4_msgs == [c4.serial_reply()]
    assert eng.c4_state == "waiting"

    rec.c4_msgs.clear()
    send_leds(eng, on=(c4.CHANNEL_STRIP,))
    settle(eng)
    assert rec.c4_msgs == c4.assign_plugin_macro() + RESET


def test_without_a_c4_port_connect_does_nothing():
    rec = Recorder()
    eng = engine_mod.Engine(apc.Apc40Output(rec.apc_send), rec.mcu_send)
    eng.c4_connect()
    assert eng.c4_state == "off"


# ---------------------------------------------------------------------------
# Device knobs
# ---------------------------------------------------------------------------


def test_device_knob_turns_c4_row_one():
    eng, rec = ready_engine()
    eng.on_apc_message((0xB0, apc.CC_DEVICE_KNOB1 + 2, 60))
    eng.on_apc_message((0xB0, apc.CC_DEVICE_KNOB1 + 2, 62))
    eng.on_apc_message((0xB0, apc.CC_DEVICE_KNOB1 + 2, 61))
    assert rec.c4_msgs == []  # sent at the end of the frame
    eng.tick()
    assert rec.c4_msgs == [c4.vpot_delta(0, 2, 2), c4.vpot_delta(0, 2, -1)]
    assert rec.mcu_msgs == []


def test_device_knob_speed_is_limited():
    eng, rec = ready_engine(c4_knob_step_limit=2, knob_noise_threshold=0)
    eng.on_apc_message((0xB0, apc.CC_DEVICE_KNOB1, 60))
    eng.on_apc_message((0xB0, apc.CC_DEVICE_KNOB1, 70))
    eng.tick()
    assert rec.c4_msgs == [c4.vpot_delta(0, 0, 2)]


def test_device_knobs_do_nothing_before_the_c4_is_ready():
    eng, rec = make_engine()
    eng.c4_connect()
    rec.c4_msgs.clear()
    eng.on_apc_message((0xB0, apc.CC_DEVICE_KNOB1, 60))
    eng.on_apc_message((0xB0, apc.CC_DEVICE_KNOB1, 61))
    eng.tick()
    assert rec.c4_msgs == [] and rec.mcu_msgs == []


def test_device_knobs_drive_the_c4_in_every_mode():
    seq = sq.Sequencer(lambda m: None, lanes=[sq.Lane(36, 10)])
    eng, rec = ready_engine(sequencer=seq)
    eng.on_apc_message((0xB0, apc.CC_DEVICE_KNOB1, 60))
    for i, mode in enumerate(("tracking", "sequencer", "mixing")):
        eng.set_mode(mode)
        rec.c4_msgs.clear()
        eng.on_apc_message((0xB0, apc.CC_DEVICE_KNOB1, 61 + i))
        eng.tick()
        assert rec.c4_msgs == [c4.vpot_delta(0, 0, 1)], mode


def test_held_sequencer_pad_still_takes_the_device_knobs():
    seq = sq.Sequencer(lambda m: None, lanes=[sq.Lane(36, 10)])
    eng, rec = ready_engine(sequencer=seq)
    eng.set_mode("sequencer")
    eng.on_apc_message((0x90, apc.NOTE_CLIP_ROW1, 127))  # hold step 1
    eng.on_apc_message((0xB0, apc.CC_DEVICE_KNOB1, 60))
    eng.on_apc_message((0xB0, apc.CC_DEVICE_KNOB1, 65))
    assert rec.c4_msgs == []
    assert seq.velocity(0, 0) > 0


def test_bank_switch_dump_sends_no_c4_turns():
    eng, rec = ready_engine()
    knob_dump(eng, 0, value=40)
    settle(eng)
    rec.c4_msgs.clear()
    knob_dump(eng, 3, value=42)  # bank 3's own positions, close to bank 0's
    knob_dump(eng, 0, value=43)  # back to bank 0 with nearby values
    settle(eng)
    assert [m for m in rec.c4_msgs if m[0] == 0xB0] == []


def test_same_bank_dump_sends_no_c4_turns():
    eng, rec = ready_engine()
    eng.on_apc_message((0xB0, apc.CC_DEVICE_KNOB1, 40))
    eng.tick()
    knob_dump(eng, 0, value=42)  # Track Selection 1 again: same bank, re-referenced values
    settle(eng)
    assert [m for m in rec.c4_msgs if m[0] == 0xB0] == []


def test_a_dump_split_over_two_frames_sends_no_c4_turns():
    eng, rec = ready_engine()
    knob_dump(eng, 0, value=40)
    settle(eng)
    rec.c4_msgs.clear()
    for cc in range(apc.CC_DEVICE_KNOB1, apc.CC_DEVICE_KNOB1 + 7):
        eng.on_apc_message((0xB0, cc, 42))
    eng.tick()
    eng.on_apc_message((0xB0, apc.CC_DEVICE_KNOB1 + 7, 42))  # the last one, a frame later
    settle(eng)
    assert [m for m in rec.c4_msgs if m[0] == 0xB0] == []


def test_knob_turns_work_again_after_a_dump():
    eng, rec = ready_engine()
    knob_dump(eng, 0, value=40)
    settle(eng)
    rec.c4_msgs.clear()
    eng.on_apc_message((0xB0, apc.CC_DEVICE_KNOB1 + 4, 41))
    eng.tick()
    assert rec.c4_msgs == [c4.vpot_delta(0, 4, 1)]


def test_two_knobs_turned_together_both_move():
    eng, rec = ready_engine()
    for cc in (apc.CC_DEVICE_KNOB1, apc.CC_DEVICE_KNOB1 + 1):
        eng.on_apc_message((0xB0, cc, 40))
    eng.tick()
    for cc in (apc.CC_DEVICE_KNOB1, apc.CC_DEVICE_KNOB1 + 1):
        eng.on_apc_message((0xB0, cc, 41))
    eng.tick()
    assert rec.c4_msgs == [c4.vpot_delta(0, 0, 1), c4.vpot_delta(0, 1, 1)]


# ---------------------------------------------------------------------------
# Rings
# ---------------------------------------------------------------------------


def test_c4_ring_shows_on_the_current_bank():
    eng, rec = ready_engine()
    eng.on_apc_message((0xB5, apc.CC_DEVICE_KNOB1, 0))  # bank 5
    rec.apc_msgs.clear()
    eng.on_c4_message((0xB0, c4.CC_RING1 + 1, mcu.ring_byte(mcu.RING_MODE_VOLUME, 11)))
    assert (0xB5, apc.device_ring_style_cc(2), apc.RING_VOLUME) in rec.apc_msgs
    assert (0xB5, apc.device_ring_cc(2), 127) in rec.apc_msgs


def test_unbound_c4_ring_turns_the_ring_off():
    eng, rec = ready_engine()
    eng.on_c4_message((0xB0, c4.CC_RING1, 0x00))
    assert (0xB0, apc.device_ring_style_cc(1), apc.RING_OFF) in rec.apc_msgs


def test_rings_of_other_rows_wait_until_paged_to():
    eng, rec = ready_engine()
    eng.on_c4_message((0xB0, c4.CC_RING1 + 8, 0x25))
    assert rec.apc_msgs == []


def test_rings_are_redrawn_on_a_new_bank_after_its_dump():
    eng, rec = ready_engine()
    eng.on_c4_message((0xB0, c4.CC_RING1, mcu.ring_byte(mcu.RING_MODE_PAN, 6)))
    rec.apc_msgs.clear()
    knob_dump(eng, 2)
    assert not any(m[0] == 0xB2 for m in rec.apc_msgs)  # not during the dump
    settle(eng)
    assert (0xB2, apc.device_ring_style_cc(1), apc.RING_PAN) in rec.apc_msgs
    assert (0xB2, apc.device_ring_cc(1), mcu.ring_value_to_position(6)) in rec.apc_msgs


def test_rings_are_not_drawn_in_c4_track_mode():
    eng, rec = ready_engine()
    eng.on_c4_message((0x90, c4.TRACK, 0x7F))
    eng.on_c4_message((0xB0, c4.CC_RING1, 0x46))  # an on/off indicator
    assert rec.apc_msgs == []
    eng.on_c4_message((0x90, c4.TRACK, 0x00))  # back to normal: redraw
    assert rec.apc_msgs != []


def test_rings_come_back_after_a_velocity_hold():
    seq = sq.Sequencer(lambda m: None, lanes=[sq.Lane(36, 10)])
    eng, rec = ready_engine(sequencer=seq)
    eng.on_c4_message((0xB0, c4.CC_RING1, mcu.ring_byte(mcu.RING_MODE_VOLUME, 3)))
    eng.set_mode("sequencer")
    eng.on_apc_message((0x90, apc.NOTE_CLIP_ROW1, 127))
    eng.on_apc_message((0xB0, apc.CC_DEVICE_KNOB1, 60))
    eng.on_apc_message((0xB0, apc.CC_DEVICE_KNOB1, 64))
    rec.apc_msgs.clear()
    eng.on_apc_message((0x80, apc.NOTE_CLIP_ROW1, 0))
    assert (0xB0, apc.device_ring_cc(1), mcu.ring_value_to_position(3)) in rec.apc_msgs


# ---------------------------------------------------------------------------
# Mixing utility row
# ---------------------------------------------------------------------------


def edge(eng, note, channel=0):
    """One edge of a latching utility button (= one press)."""
    eng.on_apc_message((0x90 | channel, note, 127))


def test_clip_track_steps_plugins_from_their_first_parameters():
    eng, rec = ready_engine()
    eng.set_mode("mixing")
    edge(eng, apc.NOTE_UTIL_CLIP_TRACK, channel=4)  # any Device Control bank
    assert rec.c4_msgs == c4.click(c4.SLOT_UP) + c4.with_shift([c4.BANK_LEFT])
    rec.c4_msgs.clear()
    eng.on_apc_message((0x90, apc.NOTE_SHIFT, 127))
    edge(eng, apc.NOTE_UTIL_CLIP_TRACK)
    eng.on_apc_message((0x80, apc.NOTE_SHIFT, 0))
    assert rec.c4_msgs == c4.click(c4.SLOT_DOWN) + c4.with_shift([c4.BANK_LEFT])
    assert rec.mcu_msgs == []


def fill_rows(eng, count):
    """Cakewalk's LCDs for a plug-in with *count* parameters P1, P2, ..."""
    for row in range(4):
        names = [f"P{8 * row + c + 1}" if 8 * row + c < count else "" for c in range(8)]
        eng.on_c4_message(lcd(0, "".join(f"{n:<7}" for n in names).ljust(56), row))
        eng.on_c4_message(lcd(56, "".join(f"{'v' if n else '':<7}" for n in names).ljust(56), row))


def turn_knob1(eng):
    eng.on_apc_message((0xB0, apc.CC_DEVICE_KNOB1, 60))
    eng.tick()
    eng.on_apc_message((0xB0, apc.CC_DEVICE_KNOB1, 61))
    eng.tick()


def test_arrows_page_the_knobs_over_the_32_bound_parameters():
    eng, rec = ready_engine()
    eng.set_mode("mixing")
    fill_rows(eng, 20)
    edge(eng, apc.NOTE_UTIL_RIGHT_ARROW)
    assert rec.c4_msgs == []  # paged in the app: Cakewalk binds all 32 already
    turn_knob1(eng)
    assert rec.c4_msgs == [c4.vpot_delta(1, 0, 1)]  # parameter 9 = row 2, column 1
    assert eng.hud_snapshot().c4_labels[:2] == ("P9", "P10")
    assert eng.hud_snapshot().toasts[-1][1] == "Parameters 9-16"


def test_paging_stops_where_the_parameters_end():
    eng, rec = ready_engine()
    eng.set_mode("mixing")
    fill_rows(eng, 12)
    edge(eng, apc.NOTE_UTIL_RIGHT_ARROW)
    edge(eng, apc.NOTE_UTIL_RIGHT_ARROW)
    assert eng.hud_snapshot().c4_labels[:4] == ("P9", "P10", "P11", "P12")
    assert eng.hud_snapshot().toasts[-1][1] == "No more parameters"
    edge(eng, apc.NOTE_UTIL_LEFT_ARROW)
    edge(eng, apc.NOTE_UTIL_LEFT_ARROW)
    assert eng.hud_snapshot().c4_labels[0] == "P1"
    assert eng.hud_snapshot().toasts[-1][1] == "First parameters"
    assert rec.c4_msgs == []


def test_shift_arrows_move_by_one_parameter():
    eng, _ = ready_engine()
    eng.set_mode("mixing")
    fill_rows(eng, 20)
    eng.on_apc_message((0x90, apc.NOTE_SHIFT, 127))
    edge(eng, apc.NOTE_UTIL_RIGHT_ARROW)
    eng.on_apc_message((0x80, apc.NOTE_SHIFT, 0))
    assert eng.hud_snapshot().c4_labels[0] == "P2"


def test_past_32_parameters_the_arrows_move_cakewalks_offset():
    eng, rec = ready_engine()
    eng.set_mode("mixing")
    fill_rows(eng, 32)
    for _ in range(3):
        edge(eng, apc.NOTE_UTIL_RIGHT_ARROW)
    assert rec.c4_msgs == []
    assert eng.hud_snapshot().c4_labels[0] == "P25"
    edge(eng, apc.NOTE_UTIL_RIGHT_ARROW)
    assert rec.c4_msgs == c4.click(c4.BANK_RIGHT)
    assert eng.hud_snapshot().toasts[-1][1] == "Parameters 33-40"


def show_params(eng, labels, values):
    eng.on_c4_message(lcd(0, "".join(f"{t:<7}" for t in labels).ljust(56)))
    eng.on_c4_message(lcd(56, "".join(f"{t:<7}" for t in values).ljust(56)))


def test_device_on_off_without_a_switch_does_nothing():
    eng, rec = ready_engine()
    eng.set_mode("mixing")
    show_params(eng, ["LFFreq", "LMFFrq"], ["79.6Hz", "317.0H"])
    edge(eng, apc.NOTE_UTIL_DEVICE_ONOFF)
    assert rec.c4_msgs == [] and rec.mcu_msgs == []
    assert eng.hud_snapshot().toasts[-1][1] == "This plug-in has no on/off switch"


def test_knobs_skip_the_switch():
    eng, rec = ready_engine()
    show_params(eng, ["Bypass", "DecyTm", "LwDmpR"], ["Off", "1.1Sec", "0.80x"])
    eng.on_apc_message((0xB0, apc.CC_DEVICE_KNOB1, 60))
    eng.tick()
    eng.on_apc_message((0xB0, apc.CC_DEVICE_KNOB1, 61))  # knob 1 = parameter 2
    eng.on_apc_message((0xB0, apc.CC_DEVICE_KNOB1 + 7, 60))
    eng.tick()
    eng.on_apc_message((0xB0, apc.CC_DEVICE_KNOB1 + 7, 61))  # knob 8 = parameter 9
    eng.tick()
    assert rec.c4_msgs == [c4.vpot_delta(0, 1, 1), c4.vpot_delta(1, 0, 1)]
    snap = eng.hud_snapshot()
    assert snap.c4_labels[:2] == ("DecyTm", "LwDmpR")
    assert snap.c4_switch == "Bypass: Off"


def test_switch_found_by_its_on_off_value_alone():
    eng, _ = ready_engine()
    show_params(eng, ["Tube", "Drive"], ["On", "0.0%"])
    assert eng.hud_snapshot().c4_labels[0] == "Drive"


def test_skipped_switch_shifts_the_rings():
    eng, rec = ready_engine()
    eng.on_c4_message((0xB0, c4.CC_RING1 + 1, mcu.ring_byte(mcu.RING_MODE_VOLUME, 11)))
    eng.on_c4_message((0xB0, c4.CC_RING1 + 8, 0x00))
    show_params(eng, ["Enable", "Drive"], ["Off", "0.0%"])
    assert (0xB0, apc.device_ring_cc(1), 127) in rec.apc_msgs  # parameter 2 on knob 1
    assert (0xB0, apc.device_ring_style_cc(8), apc.RING_OFF) in rec.apc_msgs  # parameter 9: none


def test_device_on_off_presses_the_switch_on_the_first_page():
    eng, rec = ready_engine()
    eng.set_mode("mixing")
    show_params(eng, ["Enable", "Drive"], ["Off", "0.0%"])
    edge(eng, apc.NOTE_UTIL_DEVICE_ONOFF)
    assert rec.c4_msgs == c4.click(c4.VPOT_PUSH1)
    show_params(eng, ["Enable", "Drive"], ["On", "0.0%"])  # Cakewalk shows the new state
    settle(eng, 10)
    assert eng.hud_snapshot().toasts[-1][1] == "Enable: On"
    assert eng._c4_hop is None


def test_device_on_off_after_paging_in_the_app_just_pushes():
    eng, rec = ready_engine()
    eng.set_mode("mixing")
    fill_rows(eng, 20)
    show_params(eng, ["Bypass", "P2"], ["Off", "v"])
    edge(eng, apc.NOTE_UTIL_RIGHT_ARROW)
    edge(eng, apc.NOTE_UTIL_DEVICE_ONOFF)
    assert rec.c4_msgs == c4.click(c4.VPOT_PUSH1)


def test_device_on_off_past_32_parameters_goes_back_and_returns():
    eng, rec = ready_engine()
    eng.set_mode("mixing")
    fill_rows(eng, 32)
    show_params(eng, ["Bypass", "P2"], ["Off", "v"])
    for _ in range(4):
        edge(eng, apc.NOTE_UTIL_RIGHT_ARROW)  # the 4th moves Cakewalk's offset
    rec.c4_msgs.clear()

    edge(eng, apc.NOTE_UTIL_DEVICE_ONOFF)
    assert rec.c4_msgs == c4.with_shift([c4.BANK_LEFT])  # to offset 0
    eng.on_apc_message((0xB0, apc.CC_DEVICE_KNOB1, 60))
    eng.tick()
    eng.on_apc_message((0xB0, apc.CC_DEVICE_KNOB1, 61))  # turned meanwhile: ignored
    show_params(eng, ["Bypass", "P2"], ["Off", "v"])
    rec.c4_msgs.clear()
    settle(eng, 6)  # Cakewalk rebinds, its LCD goes quiet
    assert rec.c4_msgs == c4.click(c4.VPOT_PUSH1)
    rec.c4_msgs.clear()
    show_params(eng, ["Bypass", "P2"], ["On", "v"])
    settle(eng, 10)
    assert rec.c4_msgs == c4.click(c4.BANK_RIGHT)  # back where it was
    settle(eng, 10)
    assert eng._c4_hop is None
    assert eng.hud_snapshot().toasts[-1][1] == "Bypass: On"


def test_page_buttons_wait_while_device_on_off_runs():
    eng, rec = ready_engine()
    eng.set_mode("mixing")
    fill_rows(eng, 20)
    show_params(eng, ["Enable", "P2"], ["Off", "v"])
    edge(eng, apc.NOTE_UTIL_DEVICE_ONOFF)
    rec.c4_msgs.clear()
    edge(eng, apc.NOTE_UTIL_RIGHT_ARROW)
    assert eng.hud_snapshot().c4_labels[0] == "P2"  # not paged


def test_tracking_utility_row_is_unchanged():
    eng, rec = ready_engine()
    edge(eng, apc.NOTE_UTIL_CLIP_TRACK)
    assert rec.c4_msgs == []
    assert rec.mcu_msgs == click(mcu.NOTE_CW_UNDO)


def test_mixing_buttons_without_a_c4_send_nothing():
    eng, rec = make_engine()
    eng.set_mode("mixing")
    edge(eng, apc.NOTE_UTIL_RIGHT_ARROW)
    assert rec.c4_msgs == [] and rec.mcu_msgs == []


def test_next_plugin_past_the_last_wraps_to_the_first():
    eng, rec = ready_engine()
    eng.set_mode("mixing")
    edge(eng, apc.NOTE_UTIL_CLIP_TRACK)
    rec.c4_msgs.clear()
    eng.on_c4_message(lcd(0, 'Track 1: "Gtr", Plugin 3: --None--'.ljust(56)))
    assert rec.c4_msgs == RESET


def test_empty_slot_without_next_plugin_does_not_wrap():
    eng, rec = ready_engine()
    eng.on_c4_message(lcd(0, 'Track 1: "Gtr", Plugin 1: --None--'.ljust(56)))
    assert rec.c4_msgs == []


def test_banner_is_not_toasted_the_plugin_line_shows_it():
    eng, _ = ready_engine()
    before = eng.hud_snapshot().toasts
    eng.on_c4_message(lcd(0, 'Track 3: "Vox", Plugin 2: "Sonitus Delay"'.ljust(56)))
    snap = eng.hud_snapshot()
    assert snap.toasts == before
    assert (snap.c4_slot, snap.c4_plugin) == (2, "Sonitus Delay")


def test_track_selection_resets_to_the_first_plugin_and_page():
    eng, rec = ready_engine()
    knob_dump(eng, 2)
    settle(eng)
    assert rec.mcu_msgs == click(mcu.NOTE_SELECT1 + 2)
    assert rec.c4_msgs == []  # waits for Cakewalk to take the select
    settle(eng, engine_mod.C4_RESET_DELAY_FRAMES)
    assert rec.c4_msgs == RESET


def test_reset_on_select_can_be_turned_off():
    eng, rec = ready_engine(c4_reset_on_select=False)
    knob_dump(eng, 2)
    settle(eng, 10)
    assert rec.c4_msgs == []


def test_master_switch_to_buses_also_resets():
    eng, rec = ready_engine()
    knob_dump(eng, 8)
    settle(eng, 10)
    assert rec.mcu_msgs == click(mcu.NOTE_CW_AUX)
    assert rec.c4_msgs == RESET


# ---------------------------------------------------------------------------
# Safety and HUD
# ---------------------------------------------------------------------------


def test_only_whitelisted_c4_buttons_are_ever_sent():
    rng = random.Random(4)
    seq = sq.Sequencer(lambda m: None, lanes=[sq.Lane(36, 10)])
    eng, rec = ready_engine(sequencer=seq)
    for _ in range(3000):
        kind = rng.random()
        channel = rng.randrange(9)
        if kind < 0.5:
            status = rng.choice((0x90, 0x80))
            eng.on_apc_message((status | channel, rng.randrange(48, 102), rng.choice((0, 127))))
        elif kind < 0.9:
            eng.on_apc_message((0xB0 | channel, rng.randrange(7, 56), rng.randrange(128)))
        else:
            eng.on_c4_message(lcd(0, 'Track 1: "a", Plugin 2: --None--'.ljust(56)))
        eng.tick()
    notes = {m[1] for m in rec.c4_msgs if m[0] == 0x90}
    assert notes and notes <= c4.SWITCH_WHITELIST
    assert all(m[0] in (0x90, 0xB0) for m in rec.c4_msgs)


def test_hud_snapshot_reports_the_plugin_and_parameters():
    eng, _ = ready_engine()
    eng.on_c4_message(lcd(0, 'Track 3: "Vox", Plugin 2: "Sonitus Delay"'.ljust(56)))
    eng.on_c4_message(lcd(0, "Mix    Time   ".ljust(56)))
    eng.on_c4_message(lcd(56, "50%    250ms  "))
    snap = eng.hud_snapshot()
    assert snap.c4_state == "ready"
    assert (snap.c4_slot, snap.c4_plugin, snap.c4_strip) == (2, "Sonitus Delay", 'Track 3: "Vox"')
    assert snap.c4_labels[:2] == ("Mix", "Time")
    assert snap.c4_values[:2] == ("50%", "250ms")
