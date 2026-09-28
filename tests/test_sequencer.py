from apc40sonar import sequencer as sq


def make(steps=16, lanes=None):
    sent = []
    seq = sq.Sequencer(sent.append, steps=steps, lanes=lanes or (sq.Lane(36), sq.Lane(38)))
    return seq, sent


def clocks(seq, n):
    for _ in range(n):
        seq.on_clock([sq.CLOCK])


def test_tap_cycles_off_normal_accent_soft_off():
    seq, _ = make()

    assert [seq.cycle(0, 0) for _ in range(4)] == [100, 127, 60, 0]


def test_level_is_the_nearest_band():
    seq, _ = make()
    seq.set_velocity(0, 0, 110)
    assert seq.level(0, 0) == "normal"
    seq.set_velocity(0, 0, 120)
    assert seq.level(0, 0) == "accent"
    seq.set_velocity(0, 0, 0)
    assert seq.level(0, 0) is None


def test_tap_from_an_exact_velocity_moves_to_the_next_band():
    seq, _ = make()
    seq.set_velocity(0, 0, 118)  # nearest: accent

    assert seq.cycle(0, 0) == 60


def test_first_clock_after_start_plays_step_one():
    seq, sent = make()
    seq.cycle(0, 0)
    seq.on_clock([sq.START])
    assert sent == []

    clocks(seq, 1)

    assert sent == [(0x99, 36, 100)]
    assert seq.playing_step == 0


def test_note_off_after_half_a_step():
    seq, sent = make()
    seq.cycle(0, 0)
    seq.on_clock([sq.START])

    clocks(seq, 3)
    assert sent == [(0x99, 36, 100)]
    clocks(seq, 1)  # clock 3 = half of a 6-clock step
    assert sent == [(0x99, 36, 100), (0x89, 36, 0)]


def test_steps_advance_every_six_clocks_and_wrap():
    seq, sent = make(steps=2)
    seq.cycle(1, 1)  # snare on step 2
    seq.on_clock([sq.START])

    clocks(seq, 7)
    assert seq.playing_step == 1
    assert (0x99, 38, 100) in sent

    clocks(seq, 6)  # 13 clocks: step 1 again (pattern of 2 steps)
    assert seq.playing_step == 0


def test_stop_ends_sounding_notes_and_hides_the_playhead():
    seq, sent = make()
    seq.cycle(0, 0)
    seq.on_clock([sq.START])
    clocks(seq, 1)

    seq.on_clock([sq.STOP])

    assert sent[-1] == (0x89, 36, 0)
    assert seq.playing_step is None
    clocks(seq, 12)
    assert len(sent) == 2  # no clocks play while stopped


def test_song_position_then_continue_plays_from_there():
    seq, sent = make()
    seq.cycle(0, 5)
    # SPP counts sixteenths: 5 -> step 6 (LSB 5, MSB 0)
    seq.on_clock([sq.SONG_POSITION, 5, 0])
    seq.on_clock([sq.CONTINUE])

    clocks(seq, 1)

    assert seq.playing_step == 5
    assert sent == [(0x99, 36, 100)]


def test_song_position_maps_onto_the_pattern_length():
    seq, _ = make(steps=16)
    seq.on_clock([sq.SONG_POSITION, 20 & 0x7F, 20 >> 7])  # bar 2, step 5
    seq.on_clock([sq.CONTINUE])

    clocks(seq, 1)

    assert seq.playing_step == 4


def test_retrigger_ends_the_previous_note_first():
    seq, sent = make(steps=1)
    seq.cycle(0, 0)
    seq.gate_clocks = 10  # longer than a step
    seq.on_clock([sq.START])

    clocks(seq, 7)

    assert sent == [(0x99, 36, 100), (0x89, 36, 0), (0x99, 36, 100)]


def test_lane_channel_sets_the_status_byte():
    seq, sent = make(lanes=(sq.Lane(60, channel=1),))
    seq.cycle(0, 0)
    seq.on_clock([sq.START])

    clocks(seq, 1)

    assert sent == [(0x90, 60, 100)]


def test_all_notes_off_flushes_pending():
    seq, sent = make()
    seq.cycle(0, 0)
    seq.on_clock([sq.START])
    clocks(seq, 1)

    seq.all_notes_off()

    assert sent[-1] == (0x89, 36, 0)


# ---------------------------------------------------------------------------
# Editing, save / load
# ---------------------------------------------------------------------------


def test_every_edit_bumps_the_version():
    seq, _ = make()
    versions = [seq.version]
    for edit in (
        lambda: seq.cycle(0, 0),
        lambda: seq.set_velocity(0, 1, 50),
        lambda: seq.set_lane(0, note=40),
        lambda: seq.add_lane(),
        lambda: seq.remove_lane(2),
        lambda: seq.set_steps(32),
        lambda: seq.set_channel(1),
        lambda: seq.clear(),
    ):
        edit()
        versions.append(seq.version)
    assert versions == sorted(set(versions))


def test_lane_name_follows_the_note_until_renamed():
    seq, _ = make()
    assert seq.lanes[0].label == "Kick"

    seq.set_lane(0, note=38)
    assert seq.lanes[0].label == "Snare"

    seq.set_lane(0, name="Big snare")
    seq.set_lane(0, note=40)
    assert seq.lanes[0].label == "Big snare"

    seq.set_lane(0, name="")
    assert seq.lanes[0].label == "Snare 2"


def test_non_drum_notes_get_a_note_name():
    assert sq.default_name(90) == "F#6"
    assert sq.note_label(36) == "C2"


def test_shortening_keeps_hidden_steps_until_saved():
    seq, _ = make(steps=16)
    seq.set_velocity(0, 12, 90)

    seq.set_steps(8)
    assert seq.to_dict()["lanes"][0]["steps"] == [0] * 8
    seq.set_steps(16)
    assert seq.velocity(0, 12) == 90


def test_add_remove_and_move_lanes_keep_rows_together():
    seq, _ = make()
    seq.cycle(1, 3)  # snare, step 4
    seq.add_lane()
    assert seq.lanes[2].note == 39 and seq.velocity(2, 0) == 0

    seq.move_lane(1, -1)
    assert seq.lanes[0].note == 38 and seq.velocity(0, 3) == 100

    seq.remove_lane(0)
    assert [lane.note for lane in seq.lanes] == [36, 39]
    seq.remove_lane(0)
    seq.remove_lane(0)  # the last lane stays
    assert len(seq.lanes) == 1


def test_removing_a_sounding_lane_ends_its_note():
    seq, sent = make()
    seq.cycle(0, 0)
    seq.on_clock([sq.START])
    clocks(seq, 1)

    seq.remove_lane(0)

    assert sent[-1] == (0x89, 36, 0)


def test_save_and_load_round_trip():
    seq, _ = make()
    seq.set_lane(1, name="Snappy")
    seq.set_velocity(1, 5, 77)
    seq.set_steps(12)
    data = seq.to_dict()

    other, _ = make()
    assert other.load_dict(data)

    assert other.steps == 12
    assert other.lanes[1].label == "Snappy"
    assert other.velocity(1, 5) == 77


def test_malformed_saves_are_rejected_unchanged():
    seq, _ = make()
    seq.cycle(0, 0)

    assert not seq.load_dict({"steps": 16})
    assert not seq.load_dict({"steps": "x", "lanes": []})
    assert not seq.load_dict({"steps": 16, "lanes": []})
    assert seq.velocity(0, 0) == 100


# ---------------------------------------------------------------------------
# Drum maps
# ---------------------------------------------------------------------------


def test_apply_map_changes_notes_and_keeps_steps():
    seq, _ = make()  # lanes 36, 38
    seq.cycle(0, 0)
    seq.cycle(1, 4)

    seq.apply_map([sq.Lane(35, 10, "Kick A"), sq.Lane(40, 10), sq.Lane(51, 10)])

    assert [lane.note for lane in seq.lanes] == [35, 40, 51]
    assert seq.lanes[0].label == "Kick A"
    assert seq.velocity(0, 0) == 100 and seq.velocity(1, 4) == 100
    assert seq.velocity(2, 0) == 0


def test_shorter_map_leaves_the_extra_rows_alone():
    seq, _ = make(lanes=(sq.Lane(36), sq.Lane(38), sq.Lane(42)))
    seq.cycle(2, 3)

    seq.apply_map([sq.Lane(35)])

    assert [lane.note for lane in seq.lanes] == [35, 38, 42]
    assert seq.velocity(2, 3) == 100


def test_drum_map_dict_round_trip_and_validation():
    lanes = list(sq.DRUM_MAPS["General MIDI extended (16)"])
    data = sq.map_to_dict("Mine", lanes)

    assert data["drum_map"] == "Mine"
    assert sq.map_from_dict(data) == lanes
    for bad in ({}, {"lanes": []}, {"lanes": [{"name": "x"}]}):
        try:
            sq.map_from_dict(bad)
        except ValueError:
            continue
        raise AssertionError(f"accepted {bad}")


def test_a_pattern_file_also_reads_as_a_drum_map():
    seq, _ = make()
    seq.set_lane(1, name="Snappy")

    lanes = sq.map_from_dict(seq.to_dict())

    assert [lane.label for lane in lanes] == ["Kick", "Snappy"]


def test_addictive_drums_2_maps_fit_and_have_unique_notes():
    for name in ("Addictive Drums 2 (16)", "Addictive Drums 2 (32)"):
        lanes = sq.DRUM_MAPS[name]
        notes = [lane.note for lane in lanes]
        assert len(notes) == len(set(notes)) <= sq.MAX_LANES
        assert all(lane.name for lane in lanes)
    assert len(sq.DRUM_MAPS["Addictive Drums 2 (32)"]) == 32
    assert sq.DRUM_MAPS["Addictive Drums 2 (16)"][3] == sq.Lane(42, 10, "Snare side stick")


# ---------------------------------------------------------------------------
# Playhead drawn ahead of the clock
# ---------------------------------------------------------------------------

def timed(steps=16):
    now = [0.0]
    seq = sq.Sequencer(lambda m: None, steps=steps, clock=lambda: now[0])
    return seq, now


def run_clocks(seq, now, n, period=0.02):
    for _ in range(n):
        now[0] += period
        seq.on_clock([sq.CLOCK])


def test_display_step_without_lead_is_the_playing_step():
    seq, now = timed()
    seq.on_clock([sq.START])
    run_clocks(seq, now, 8)

    assert seq.display_step(0) == seq.playing_step == 1


def test_display_step_leads_by_the_measured_tempo():
    seq, now = timed()
    seq.on_clock([sq.START])
    run_clocks(seq, now, 6)  # clocks 0-5 at 20 ms: step 1, next step at clock 6

    assert seq.display_step(0) == 0
    assert seq.display_step(0.01) == 0  # half a clock ahead: still step 1
    assert seq.display_step(0.03) == 1  # the next clock (6) is within the lead
    now[0] += 0.015  # time passes between clocks
    assert seq.display_step(0.01) == 1


def test_display_step_wraps_and_stops():
    seq, now = timed(steps=2)
    seq.on_clock([sq.START])
    run_clocks(seq, now, 12)  # at clock 11: step 2 of 2

    assert seq.display_step(0.03) == 0  # wraps to step 1
    seq.on_clock([sq.STOP])
    assert seq.display_step(0.03) is None


def test_a_long_pause_does_not_skew_the_tempo():
    seq, now = timed()
    seq.on_clock([sq.START])
    run_clocks(seq, now, 3)
    now[0] += 5.0  # paused
    run_clocks(seq, now, 3)

    assert abs(seq._clock_period - 0.02) < 1e-9
