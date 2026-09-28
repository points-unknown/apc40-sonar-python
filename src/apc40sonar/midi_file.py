"""Sequencer patterns to and from Standard MIDI Files.

Export writes format 1 with a single track. (Cakewalk splits a format-0 file
into one track per MIDI channel, so a channel-10 drum pattern arrived as ten
tracks, nine of them empty.) The pattern repeats to fill *bars* bars of 4/4
(16 sixteenth steps per bar), wrapping exactly as playback does, with the
same half-step gate. There is no tempo event: dropped into a Cakewalk
track, the notes follow the project's tempo.

Import reads any format 0/1 file, snaps note starts to the nearest
sixteenth from the first bar that has notes, and maps each note number to a
lane (existing lanes keep their names; new notes get new lanes).
"""

from __future__ import annotations

from pathlib import Path

from . import sequencer as sq

PPQ = 480
TICKS_PER_STEP = PPQ // 4  # a sixteenth
STEPS_PER_BAR = 16


def _varlen(value: int) -> bytes:
    """MIDI variable-length quantity."""

    out = [value & 0x7F]
    value >>= 7
    while value:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    return bytes(reversed(out))


def pattern_events(pattern: dict, bars: int) -> list[tuple[int, int, int, int]]:
    """(tick, status, note, velocity) events for *bars* bars of the pattern, sorted.

    *pattern* is :meth:`Sequencer.to_dict` output. At equal ticks Note Offs
    come first, so a note repeated on the next step is not cut short.
    """

    steps = pattern["steps"]
    gate = TICKS_PER_STEP // 2
    events = []
    for position in range(max(1, bars) * STEPS_PER_BAR):
        step = position % steps
        tick = position * TICKS_PER_STEP
        for lane in pattern["lanes"]:
            velocity = lane["steps"][step] if step < len(lane["steps"]) else 0
            if not velocity:
                continue
            channel = (lane["channel"] - 1) & 0x0F
            events.append((tick, 0x90 | channel, lane["note"], velocity))
            events.append((tick + gate, 0x80 | channel, lane["note"], 0))
    # Note Off (0x8n) sorts before Note On (0x9n) at the same tick.
    events.sort(key=lambda e: (e[0], e[1] & 0xF0, e[2]))
    return events


def to_midi_bytes(pattern: dict, bars: int, *, name: str = "APC40 pattern") -> bytes:
    track = bytearray()
    title = name.encode("latin-1", "replace")[:127]
    track += b"\x00\xff\x03" + _varlen(len(title)) + title  # track name
    track += b"\x00\xff\x58\x04\x04\x02\x18\x08"  # time signature 4/4
    last = 0
    for tick, status, note, velocity in pattern_events(pattern, bars):
        track += _varlen(tick - last) + bytes((status, note, velocity))
        last = tick
    end = max(1, bars) * STEPS_PER_BAR * TICKS_PER_STEP
    track += _varlen(max(0, end - last)) + b"\xff\x2f\x00"  # end of track
    header = b"MThd" + (6).to_bytes(4, "big") + (1).to_bytes(2, "big") + (1).to_bytes(2, "big")
    header += PPQ.to_bytes(2, "big")
    return header + b"MTrk" + len(track).to_bytes(4, "big") + bytes(track)


def export(seq: sq.Sequencer, directory: Path, bars: int, stamp: str) -> Path:
    """Write the current pattern to ``<directory>/pattern-<stamp>.mid``; return the path."""

    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"pattern-{stamp}.mid"
    path.write_bytes(to_midi_bytes(seq.to_dict(), bars))
    return path


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------


class MidiFileError(ValueError):
    """Not a Standard MIDI File this importer understands."""


def read_notes(data: bytes) -> tuple[int, list[tuple[int, int, int, int]]]:
    """(ticks per quarter, [(tick, channel 1-16, note, velocity)]) note starts, sorted."""

    if data[:4] != b"MThd" or len(data) < 14:
        raise MidiFileError("not a MIDI file")
    header_len = int.from_bytes(data[4:8], "big")
    tracks = int.from_bytes(data[10:12], "big")
    division = int.from_bytes(data[12:14], "big")
    if division & 0x8000 or division == 0:
        raise MidiFileError("SMPTE-timed MIDI files are not supported")
    notes: list[tuple[int, int, int, int]] = []
    i = 8 + header_len
    for _ in range(tracks):
        if data[i:i + 4] != b"MTrk":
            raise MidiFileError("damaged MIDI file (track header)")
        length = int.from_bytes(data[i + 4:i + 8], "big")
        notes += _track_notes(data[i + 8:i + 8 + length])
        i += 8 + length
    notes.sort()
    return division, notes


def _track_notes(track: bytes) -> list[tuple[int, int, int, int]]:
    notes = []
    i, tick, status = 0, 0, 0
    try:
        while i < len(track):
            delta = 0
            while True:
                byte = track[i]
                i += 1
                delta = (delta << 7) | (byte & 0x7F)
                if byte < 0x80:
                    break
            tick += delta
            if track[i] & 0x80:
                status = track[i]
                i += 1
            if status == 0xFF:  # meta: type, length, data
                i += 1
                length = 0
                while True:
                    byte = track[i]
                    i += 1
                    length = (length << 7) | (byte & 0x7F)
                    if byte < 0x80:
                        break
                i += length
                status = 0
            elif status in (0xF0, 0xF7):  # sysex
                length = 0
                while True:
                    byte = track[i]
                    i += 1
                    length = (length << 7) | (byte & 0x7F)
                    if byte < 0x80:
                        break
                i += length
                status = 0
            else:
                kind = status & 0xF0
                size = 1 if kind in (0xC0, 0xD0) else 2
                args = track[i:i + size]
                i += size
                if kind == 0x90 and len(args) == 2 and args[1] > 0:
                    notes.append((tick, (status & 0x0F) + 1, args[0], args[1]))
    except IndexError:
        raise MidiFileError("damaged MIDI file (truncated track)") from None
    return notes


def _repeat_length(rows: list[list[int]], steps: int) -> int:
    """The shortest whole-bar length whose repeats rebuild every row exactly."""

    for length in range(STEPS_PER_BAR, steps, STEPS_PER_BAR):
        if steps % length == 0 and all(
            row[i] == row[i % length] for row in rows for i in range(length, steps)
        ):
            return length
    return steps


def import_pattern(data: bytes, current: dict) -> tuple[dict, str]:
    """A pattern dict (for :meth:`Sequencer.load_dict`) from MIDI file *data*.

    *current* is the present pattern: its lanes are kept (names, order) and
    their steps replaced; notes without a lane get new lanes, lowest first.
    Returns the pattern and a one-line summary for the editor.
    """

    ppq, notes = read_notes(data)
    if not notes:
        raise MidiFileError("the file has no notes")
    step_ticks = ppq / 4
    bar_ticks = ppq * 4
    start = int(notes[0][0] // bar_ticks) * bar_ticks  # the bar the first note is in
    placed = [(round((tick - start) / step_ticks), ch, note, vel) for tick, ch, note, vel in notes]
    last = max(step for step, *_ in placed)
    steps = min(sq.MAX_STEPS, -(-(last + 1) // STEPS_PER_BAR) * STEPS_PER_BAR)
    dropped = sum(1 for step, *_ in placed if step >= steps)

    lanes = [dict(note=lane["note"], channel=lane["channel"], name=lane.get("name", ""), steps=[0] * steps)
             for lane in current["lanes"]]
    by_note = {}
    for index, lane in enumerate(lanes):
        by_note.setdefault(lane["note"], index)
    channels = {}
    for step, ch, note, vel in placed:
        channels.setdefault(note, ch)
    added = 0
    for note in sorted(channels):
        if note not in by_note and len(lanes) < sq.MAX_LANES:
            by_note[note] = len(lanes)
            lanes.append(dict(note=note, channel=channels[note], name="", steps=[0] * steps))
            added += 1
    skipped = {note for note in channels if note not in by_note}
    for step, _ch, note, vel in placed:
        lane = by_note.get(note)
        if lane is not None and step < steps:
            row = lanes[lane]["steps"]
            row[step] = max(row[step], vel)

    # A clip that repeats the same bars (e.g. 4 x the same bar) comes in as one cycle.
    full = steps
    steps = _repeat_length([lane["steps"] for lane in lanes], steps)
    if steps != full:
        for lane in lanes:
            lane["steps"] = lane["steps"][:steps]

    summary = f"{len(notes)} notes, {steps} steps"
    if steps != full:
        summary += f" (the clip repeats every {steps // STEPS_PER_BAR} bar{'s' if steps > STEPS_PER_BAR else ''})"
    if added:
        summary += f", {added} new lane{'s' if added > 1 else ''}"
    if dropped:
        summary += f"; {dropped} notes past step {sq.MAX_STEPS} left out"
    if skipped:
        summary += f"; notes {sorted(skipped)} left out (lane limit {sq.MAX_LANES})"
    return {"steps": steps, "lanes": lanes}, summary
