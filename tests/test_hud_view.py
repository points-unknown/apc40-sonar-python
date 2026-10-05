"""Unit tests for apc40sonar.hud_view and hud_state (HUD view model, no Tk)."""

from __future__ import annotations

import json
from dataclasses import replace

from apc40sonar import hud_state
from apc40sonar import hud_view as hv
from apc40sonar.hud_state import HudSnapshot


def test_snapshot_round_trips_through_json():
    snap = HudSnapshot(
        knob_mode="send_c",
        transport="play",
        selected_strip=3,
        bank_offset=8,
        rec=(True,) + (False,) * 7,
        toasts=((4, "Bank >"), (5, "Send C")),
    )
    data = json.loads(json.dumps(hud_state.to_dict(snap)))
    assert hud_state.from_dict(data) == snap


def test_from_dict_ignores_unknown_and_keeps_defaults_for_missing_keys():
    snap = hud_state.from_dict({"knob_mode": "send_a", "from_the_future": 1})
    assert snap.knob_mode == "send_a"
    assert snap.transport == "stop"


def test_mode_labels_and_colors():
    assert hv.mode_label(HudSnapshot(knob_mode="pan")) == ("PAN", hv.MODE_COLORS["pan"])
    assert hv.mode_label(HudSnapshot(knob_mode="send_b"))[0] == "SEND B (2)"
    colors = {hv.mode_label(HudSnapshot(knob_mode=m))[1] for m in hud_state.KNOB_MODE_LABELS}
    assert len(colors) == 4  # each mode is distinct
    assert hv.mode_label(HudSnapshot(mixer=False))[0] == "DEVICE"


def test_bank_label():
    assert hv.bank_label(HudSnapshot()) == "Tracking | Trk ?"
    assert hv.bank_label(HudSnapshot(bank_offset=8, bank_exact=True)) == "Tracking | Trk 9-16"
    assert hv.bank_label(HudSnapshot(bank_offset=9, bank_exact=False)) == "Tracking | Trk ~10-17"
    assert hv.bank_label(HudSnapshot(mode="mixing", buses=True)) == "Mixing | Buses"


def test_selection_label():
    assert hv.selection_label(HudSnapshot()) == ""
    assert hv.selection_label(HudSnapshot(selected_track=12, selected_name="Vocals")) == "Sel 12 Vocals"
    assert hv.selection_label(HudSnapshot(selected_strip=2, selected_name="OH")) == "Sel strip 3 OH"
    assert hv.selection_label(HudSnapshot(selected_track=4)) == "Sel 4"


def test_status_line_priorities():
    active = HudSnapshot(cakewalk_active=True)
    assert hv.status_label(active, {}, linked=True)[0] == ""
    assert hv.status_label(active, {}, linked=False)[0].startswith("no link")
    assert hv.status_label(None, {}, linked=True)[0].startswith("no link")
    assert hv.status_label(HudSnapshot(), {}, linked=True)[0] == "Cakewalk idle"
    assert "feedback port" in hv.status_label(active, {"mcu_in": False}, linked=True)[0]
    text, color = hv.status_label(replace(active, strip_layout=True), {}, linked=True)
    assert text.startswith("Strip layout!") and color == hv.WARN


def test_build_view_badges_and_transport():
    snap = HudSnapshot(transport="record", loop=True, shift=True, cakewalk_active=True)
    view = hv.build_view(snap, linked=True, toast="Send B")
    assert view.transport_text.endswith("REC")
    badges = dict(view.badges)
    assert badges["LOOP"] != hv.DIM and badges["SHIFT"] != hv.DIM
    assert badges["ZOOM"] == hv.DIM and badges["METERS"] == hv.DIM
    assert view.toast == "Send B"


def test_build_view_greys_out_without_link():
    snap = HudSnapshot(loop=True, transport="play")
    view = hv.build_view(snap, linked=False, toast="Send B")
    assert view.mode_color == hv.DIM
    assert view.transport_color == hv.DIM
    assert all(color == hv.DIM for _n, color in view.badges)
    assert view.toast == ""
    assert view.status_text.startswith("no link")

    empty = hv.build_view(None)
    assert empty.status_text.startswith("no link")
    assert not empty.show_strips


def test_strip_views_prefer_the_peek_and_mark_selection():
    snap = HudSnapshot(
        lcd_seen=True,
        strip_names=("Kick", "Snare") + ("",) * 6,
        strip_peek=("", "-3.0") + ("",) * 6,
        strip_values=("C", "L12") + ("",) * 6,
        selected_strip=1,
        meter_levels=(0, 9) + (0,) * 6,
        solo=(False, True) + (False,) * 6,
    )
    view = hv.build_view(snap)
    kick, snare = view.strips[:2]
    assert (kick.name, kick.peek, kick.selected) == ("Kick", False, False)
    assert (snare.name, snare.peek, snare.selected) == ("-3.0", True, True)
    assert (snare.value, snare.level, snare.solo) == ("L12", 9, True)
    assert view.show_strips


def test_meter_color_thresholds():
    assert hv.meter_color(3) == hv.METER_GREEN
    assert hv.meter_color(9) == hv.METER_YELLOW
    assert hv.meter_color(12) == hv.METER_RED


def test_toast_tracker_skips_history_then_shows_new_toasts_for_the_duration():
    tracker = hv.ToastTracker(1.0)
    assert tracker.update(((1, "Pan"),), now=0.0) == ""  # history at startup

    assert tracker.update(((1, "Pan"), (2, "Send B")), now=1.0) == "Send B"
    assert tracker.update(None, now=1.5) == "Send B"
    assert tracker.update(((1, "Pan"), (2, "Send B")), now=1.9) == "Send B"  # no repeat
    assert tracker.update(None, now=2.1) == ""

    # Two new toasts in one snapshot: the newest wins.
    assert tracker.update(((2, "Send B"), (3, "Bank >"), (4, "Bank <")), now=3.0) == "Bank <"


def test_toast_tracker_handles_an_engine_restart():
    tracker = hv.ToastTracker(1.0)
    tracker.update(((50, "old"),), now=0.0)
    assert tracker.update(((1, "Pan"),), now=1.0) == ""  # ids dropped: new history
    assert tracker.update(((1, "Pan"), (2, "Send A")), now=2.0) == "Send A"


def test_parse_position():
    assert hv.parse_position("Top-Left") == ("top-left", None)
    assert hv.parse_position("100, 40") == ("xy", (100, 40))
    assert hv.parse_position("middle") == ("top-right", None)
    assert hv.parse_position("a,b") == ("top-right", None)


def test_place_window_corners_and_xy():
    area = (0, 0, 1920, 1040)
    assert hv.place_window("top-right", area, (400, 80)) == (1920 - 400 - 12, 12)
    assert hv.place_window("bottom-left", area, (400, 80)) == (12, 1040 - 80 - 12)
    # x,y is relative to the chosen monitor.
    assert hv.place_window("100,40", (1920, 0, 3840, 1040), (400, 80)) == (2020, 40)


def test_shift_badge_text_follows_the_shift_state():
    for state, text in (("held", "SHIFT"), ("once", "SHIFT 1x"), ("locked", "SHIFT LOCK")):
        view = hv.build_view(HudSnapshot(shift=True, shift_state=state), {}, linked=True)
        assert view.shift_text == text



def test_plugin_line_follows_the_c4_state():
    assert hv.build_view(HudSnapshot()).plugin_text == ""
    assert "connecting" in hv.build_view(HudSnapshot(c4_state="waiting")).plugin_text
    ready = HudSnapshot(c4_state="ready")
    assert hv.build_view(ready).plugin_text == "Plug-in knobs: select a track"
    named = replace(ready, c4_slot=2, c4_plugin="Sonitus Delay", c4_strip='Track 3: "Vox"')
    assert hv.build_view(named).plugin_text == 'FX 2: Sonitus Delay  (Track 3: "Vox")'
    empty = replace(ready, c4_slot=4, c4_plugin=None)
    assert hv.build_view(empty).plugin_text == "FX 4: (empty slot)"


def test_parameters_show_only_with_a_ready_c4():
    labels = ("Mix", "Time") + ("",) * 6
    values = ("50%", "250ms") + ("",) * 6
    snap = HudSnapshot(c4_labels=labels, c4_values=values)
    assert hv.build_view(snap).params == ()
    view = hv.build_view(replace(snap, c4_state="ready"))
    assert view.params[:2] == (("Mix", "50%"), ("Time", "250ms"))


def test_c4_fields_round_trip_through_json():
    snap = HudSnapshot(c4_state="ready", c4_slot=1, c4_plugin=None, c4_labels=("a",) * 8)
    data = json.loads(json.dumps(hud_state.to_dict(snap)))
    assert hud_state.from_dict(data) == snap


def test_corner_margin_is_the_inverse_of_place_window():
    area = (0, 0, 3072, 1680)
    size = (600, 120)
    for position in ("top-right", "top-left", "bottom-right", "bottom-left"):
        margin = hv.corner_margin(position, area, size, (2000, 30))
        assert hv.place_window(position, area, size, margin) == (2000, 30)


def test_a_right_anchored_window_grows_to_the_left():
    area = (0, 0, 3072, 1680)
    margin = hv.corner_margin("top-right", area, (600, 120), (2000, 30))
    x, y = hv.place_window("top-right", area, (1400, 120), margin)
    assert x + 1400 == 2000 + 600 and y == 30


def test_plugin_line_shows_the_switch():
    snap = HudSnapshot(c4_state="ready", c4_slot=5, c4_plugin="TrueVerb", c4_switch="Bypass: Off")
    assert hv.build_view(snap).plugin_text == "FX 5: TrueVerb  [Bypass: Off]"


def test_a_window_on_a_missing_monitor_is_not_on_screen():
    areas = [(0, 0, 3072, 1680)]
    assert hv.on_screen((2000, 12), (900, 130), areas)
    assert hv.on_screen((3060, 12), (900, 130), areas) is False  # only 12 px left on screen
    assert hv.on_screen((2000, -12), (900, 130), areas)  # dragged a little above the top edge
    assert hv.on_screen((4000, 12), (900, 130), areas) is False  # a second monitor that is gone
    assert hv.on_screen((4000, 12), (900, 130), areas + [(3072, 0, 5632, 1440)])


def test_long_text_is_cut_so_the_hud_keeps_its_size():
    assert hv.fit("short", 10) == "short"
    assert hv.fit("Bus 1: Master | FX 2: ProChannel EQ", 12) == "Bus 1: Mast\u2026"
    view = hv.build_view(HudSnapshot(), toast="x" * 80)
    assert len(view.toast) == hv.TOAST_CHARS


def test_bank_text_fits_the_longest_mode_and_estimated_range():
    snap = HudSnapshot(mode="sequencer", bank_offset=16, bank_exact=False)
    assert hv.build_view(snap).bank_text == "Sequencer | Trk ~17-24"
