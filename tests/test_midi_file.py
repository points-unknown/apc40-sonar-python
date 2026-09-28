from apc40sonar import midi_file as mx
from apc40sonar import sequencer as sq


def pattern(steps, rows, channel=10):
    return {"steps": steps, "lanes": [{"note": n, "channel": channel, "steps": r} for n, r in rows]}


def parse_track(data: bytes):
    """(tick, status, note, velocity) note events from a format-0 file."""
    assert data[:4] == b"MThd"
    assert int.from_bytes(data[8:10], "big") == 1  # format 1: Cakewalk makes one track
    assert int.from_bytes(data[10:12], "big") == 1
    assert int.from_bytes(data[12:14], "big") == mx.PPQ
    assert data[14:18] == b"MTrk"
    track = data[22:22 + int.from_bytes(data[18:22], "big")]
    events, i, tick = [], 0, 0
    while i < len(track):
        delta = 0
        while True:
            byte = track[i]
            i += 1
            delta = (delta << 7) | (byte & 0x7F)
            if byte < 0x80:
                break
        tick += delta
        status = track[i]
        if status == 0xFF:
            length = track[i + 2]
            if track[i + 1] == 0x2F:
                return events, tick
            i += 3 + length
            continue
        events.append((tick, status, track[i + 1], track[i + 2]))
        i += 3
    raise AssertionError("no end of track")


def test_one_bar_of_kick_on_the_beats():
    kick = [100, 0, 0, 0] * 4
    events, end = parse_track(mx.to_midi_bytes(pattern(16, [(36, kick)]), bars=1))

    ons = [e for e in events if e[1] == 0x99]
    assert [e[0] for e in ons] == [0, 480, 960, 1440]
    assert (60, 0x89, 36, 0) in events  # half a sixteenth later
    assert end == 4 * mx.PPQ


def test_short_patterns_wrap_to_fill_the_bars():
    events, _ = parse_track(mx.to_midi_bytes(pattern(3, [(38, [90, 0, 0])]), bars=1))

    ons = [e[0] // mx.TICKS_PER_STEP for e in events if e[1] & 0xF0 == 0x90]
    assert ons == [0, 3, 6, 9, 12, 15]


def test_velocity_and_channel_are_kept():
    events, _ = parse_track(mx.to_midi_bytes(pattern(1, [(42, [64])], channel=1), bars=1))

    assert events[0] == (0, 0x90, 42, 64)


def test_export_writes_a_file(tmp_path):
    seq = sq.Sequencer(lambda m: None)
    seq.cycle(0, 0)

    path = mx.export(seq, tmp_path / "out", 2, "20260927-120000")

    assert path.name == "pattern-20260927-120000.mid"
    events, end = parse_track(path.read_bytes())
    assert len([e for e in events if e[1] == 0x99]) == 2
    assert end == 8 * mx.PPQ


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------

import pytest  # noqa: E402


def current(*notes):
    return {"steps": 16, "lanes": [{"note": n, "channel": 10, "name": "", "steps": [0] * 16} for n in notes]}


def test_export_then_import_round_trips():
    kick = [100, 0, 0, 0] * 4
    snare = [0, 0, 0, 0, 127, 0, 0, 0] * 2
    data = mx.to_midi_bytes(pattern(16, [(36, kick), (38, snare)]), bars=1)

    result, summary = mx.import_pattern(data, current(36, 38))

    assert result["steps"] == 16
    assert result["lanes"][0]["steps"] == kick
    assert result["lanes"][1]["steps"] == snare
    assert summary.startswith("6 notes, 16 steps")


def test_import_keeps_lane_names_and_adds_lanes_for_new_notes():
    data = mx.to_midi_bytes(pattern(16, [(51, [80] + [0] * 15), (36, [100] + [0] * 15)]), bars=1)
    now = current(36)
    now["lanes"][0]["name"] = "My kick"

    result, summary = mx.import_pattern(data, now)

    assert [(lane["note"], lane["name"]) for lane in result["lanes"]] == [(36, "My kick"), (51, "")]
    assert "1 new lane" in summary


def test_import_starts_at_the_bar_of_the_first_note_and_snaps_to_sixteenths():
    # One note in bar 3, a few ticks late on its second sixteenth.
    tick = 2 * 4 * mx.PPQ + mx.TICKS_PER_STEP + 7
    track = mx._varlen(tick) + bytes((0x99, 38, 90)) + b"\x00\xff\x2f\x00"
    data = b"MThd" + (6).to_bytes(4, "big") + b"\x00\x00\x00\x01" + mx.PPQ.to_bytes(2, "big")
    data += b"MTrk" + len(track).to_bytes(4, "big") + track

    result, _ = mx.import_pattern(data, current(38))

    assert result["lanes"][0]["steps"][1] == 90
    assert result["steps"] == 16


def test_import_reads_running_status_and_other_tracks():
    # Format 1: a conductor track, then notes using running status.
    conductor = b"\x00\xff\x51\x03\x07\xa1\x20\x00\xff\x2f\x00"
    notes = b"\x00\x99\x24\x64" + mx._varlen(mx.TICKS_PER_STEP) + b"\x26\x50" + b"\x00\xff\x2f\x00"
    data = b"MThd" + (6).to_bytes(4, "big") + b"\x00\x01\x00\x02" + mx.PPQ.to_bytes(2, "big")
    for track in (conductor, notes):
        data += b"MTrk" + len(track).to_bytes(4, "big") + track

    result, _ = mx.import_pattern(data, current(36, 38))

    assert result["lanes"][0]["steps"][0] == 100
    assert result["lanes"][1]["steps"][1] == 80


def test_long_files_are_cut_at_64_steps():
    # 6 different bars: bar n has a hit on step n + 1.
    rows = [0] * 96
    for bar in range(6):
        rows[bar * 16 + bar] = 100
    track_pattern = {"steps": 96, "lanes": [{"note": 36, "channel": 10, "steps": rows}]}
    data = mx.to_midi_bytes(track_pattern, bars=6)

    result, summary = mx.import_pattern(data, current(36))

    assert result["steps"] == 64
    assert "2 notes past step 64 left out" in summary


def test_a_repeating_clip_comes_in_as_one_cycle():
    two_bars = [100] + [0] * 15 + [0, 0, 0, 0, 90] + [0] * 11
    data = mx.to_midi_bytes(pattern(32, [(36, two_bars)]), bars=4)

    result, summary = mx.import_pattern(data, current(36))

    assert result["steps"] == 32
    assert result["lanes"][0]["steps"] == two_bars
    assert "repeats every 2 bars" in summary


def test_bad_files_raise_a_clear_error():
    with pytest.raises(mx.MidiFileError):
        mx.import_pattern(b"not midi", current(36))
    empty = mx.to_midi_bytes(pattern(16, [(36, [0] * 16)]), bars=1)
    with pytest.raises(mx.MidiFileError, match="no notes"):
        mx.import_pattern(empty, current(36))
