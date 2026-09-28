"""Step sequencer: a pattern of note lanes played in sync with Cakewalk's clock.

Cakewalk transmits MIDI Clock (24 per quarter note), Start / Continue / Stop
and Song Position Pointer on a loopMIDI cable. :meth:`Sequencer.on_clock`
consumes those and emits Note On/Off through the *send* callable on a
separate cable, which a Cakewalk MIDI or instrument track records.

Timing follows the clock, not the app's 20 ms run loop: the caller feeds
clock messages straight from the MIDI input callback, so each note goes out
the moment its clock arrives. Pattern edits come from the run loop on
another thread; a lock keeps the two apart, and every edit bumps
:attr:`Sequencer.version` so the editor window and autosave see it.

Clock semantics (MIDI 1.0): after Start the song position is 0 and the
*next* clock is the downbeat. Song Position Pointer counts sixteenths
(6 clocks each); after it, the next clock plays at that position.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, replace
from typing import Callable, Sequence

CLOCK = 0xF8
START = 0xFA
CONTINUE = 0xFB
STOP = 0xFC
SONG_POSITION = 0xF2

CLOCKS_PER_SIXTEENTH = 6

MAX_STEPS = 64
MAX_LANES = 32

# Step levels a pad tap cycles through: off -> normal -> accent -> soft -> off.
LEVELS = ("normal", "accent", "soft")

# General MIDI percussion key map (channel 10).
GM_DRUMS = {
    35: "Kick 2", 36: "Kick", 37: "Rim", 38: "Snare", 39: "Clap", 40: "Snare 2",
    41: "Low floor tom", 42: "Closed hat", 43: "High floor tom", 44: "Pedal hat",
    45: "Low tom", 46: "Open hat", 47: "Low-mid tom", 48: "Hi-mid tom", 49: "Crash",
    50: "High tom", 51: "Ride", 52: "China", 53: "Ride bell", 54: "Tambourine",
    55: "Splash", 56: "Cowbell", 57: "Crash 2", 58: "Vibraslap", 59: "Ride 2",
    60: "Hi bongo", 61: "Low bongo", 62: "Mute hi conga", 63: "Open hi conga",
    64: "Low conga", 65: "High timbale", 66: "Low timbale", 67: "High agogo",
    68: "Low agogo", 69: "Cabasa", 70: "Maracas", 71: "Short whistle",
    72: "Long whistle", 73: "Short guiro", 74: "Long guiro", 75: "Claves",
    76: "Hi wood block", 77: "Low wood block", 78: "Mute cuica", 79: "Open cuica",
    80: "Mute triangle", 81: "Open triangle",
}

NOTE_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")


def note_label(note: int) -> str:
    """``C1``-style name (Cakewalk numbering: note 60 = C4)."""

    return f"{NOTE_NAMES[note % 12]}{note // 12 - 1}"


def default_name(note: int) -> str:
    return GM_DRUMS.get(note, note_label(note))


@dataclass(frozen=True)
class Lane:
    """One sequencer row: a MIDI note on a channel (1-16), with a display name."""

    note: int
    channel: int = 10
    name: str = ""

    @property
    def label(self) -> str:
        return self.name or default_name(self.note)


# General MIDI drums on channel 10: kick, snare, closed hat, open hat, clap,
# rim, low / mid / high tom, crash.
DEFAULT_LANES = tuple(Lane(n) for n in (36, 38, 42, 46, 39, 37, 45, 47, 50, 49))
DEFAULT_VELOCITIES = {"normal": 100, "accent": 127, "soft": 60}

# Built-in drum maps (lane notes/names/channels without steps). Saved maps are
# JSON files written by the editor window; see map_to_dict / map_from_dict.
DRUM_MAPS = {
    "General MIDI (10)": DEFAULT_LANES,
    "General MIDI extended (16)": tuple(
        Lane(n) for n in (36, 38, 42, 46, 39, 37, 45, 47, 50, 49, 44, 51, 53, 57, 54, 56)
    ),
}

# Addictive Drums 2 (XLN Audio keymap, June 2021; stick articulations only).
# AD2 is not General MIDI: e.g. 42 is snare side stick and the hi-hat is 48-59.
AD2_CORE = (
    (36, "Kick"), (38, "Snare"), (37, "Snare rimshot"), (42, "Snare side stick"),
    (49, "HH closed tip"), (50, "HH closed shaft"), (54, "HH open A"), (56, "HH open C"),
    (48, "HH pedal"), (71, "Tom 1"), (69, "Tom 2"), (67, "Tom 3"), (65, "Tom 4"),
    (60, "Ride tip"), (61, "Ride bell"), (77, "Cymbal 1"),
)
AD2_MORE = (
    (43, "Snare shallow"), (44, "Snare rim click"), (75, "Snare sticks"), (51, "HH closed 2 tip"),
    (53, "HH closed bell"), (55, "HH open B"), (57, "HH open D"), (58, "HH open bell"),
    (59, "HH pedal open"), (62, "Ride shaft"), (63, "Ride choke"), (78, "Cymbal 1 choke"),
    (79, "Cymbal 2"), (81, "Cymbal 3"), (84, "Ride 2 tip"), (89, "Cymbal 4"),
)
DRUM_MAPS["Addictive Drums 2 (16)"] = tuple(Lane(n, 10, name) for n, name in AD2_CORE)
DRUM_MAPS["Addictive Drums 2 (32)"] = tuple(Lane(n, 10, name) for n, name in AD2_CORE + AD2_MORE)


def map_to_dict(name: str, lanes: Sequence[Lane]) -> dict:
    return {
        "drum_map": name,
        "lanes": [{"note": lane.note, "channel": lane.channel, "name": lane.name} for lane in lanes],
    }


def map_from_dict(data: dict) -> list[Lane]:
    """Lanes from a saved drum map (or a pattern file); ValueError when malformed."""

    try:
        lanes = [
            Lane(
                max(0, min(127, int(item["note"]))),
                max(1, min(16, int(item.get("channel", 10)))),
                str(item.get("name", "")),
            )
            for item in data["lanes"][:MAX_LANES]
        ]
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"not a drum map: {exc}") from None
    if not lanes:
        raise ValueError("the drum map has no lanes")
    return lanes


class Sequencer:
    """Pattern (lanes x steps x velocity) and the clock-driven player."""

    def __init__(
        self,
        send: Callable[[Sequence[int]], None],
        *,
        lanes: Sequence[Lane] = DEFAULT_LANES,
        steps: int = 16,
        velocities: dict[str, int] | None = None,
        step_clocks: int = CLOCKS_PER_SIXTEENTH,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._send = send
        self._now = clock
        self.lanes = tuple(lanes)[:MAX_LANES] or DEFAULT_LANES
        self.steps = max(1, min(MAX_STEPS, steps))
        self.velocities = dict(DEFAULT_VELOCITIES if velocities is None else velocities)
        self.step_clocks = max(1, step_clocks)
        self.gate_clocks = max(1, self.step_clocks // 2)
        # velocity per [lane][step]; 0 = off
        self._pattern = [[0] * self.steps for _ in self.lanes]
        self._lock = threading.RLock()
        self.version = 0  # bumped by every edit
        self.running = False
        self._position = 0  # clocks since song start; the next clock plays here
        self._playing_step: int | None = None
        # Clock timing, for drawing the playhead ahead of the clock (display_step).
        self._last_clock_time: float | None = None
        self._clock_period: float | None = None  # seconds per MIDI clock, smoothed
        self._pending_offs: dict[tuple[int, int], int] = {}  # (status, note) -> due clock

    # ------------------------------------------------------------------
    # Pattern editing (run loop thread)
    # ------------------------------------------------------------------

    def _edited(self) -> None:
        self.version += 1

    def velocity(self, lane: int, step: int) -> int:
        return self._pattern[lane][step]

    def set_velocity(self, lane: int, step: int, velocity: int) -> None:
        with self._lock:
            if lane < len(self.lanes) and step < self.steps:
                self._pattern[lane][step] = max(0, min(127, velocity))
                self._edited()

    def cycle(self, lane: int, step: int) -> int:
        """Pad tap: off -> normal -> accent -> soft -> off. Returns the new velocity."""

        with self._lock:
            level = self.level(lane, step)
            if level is None:
                new = self.velocities["normal"]
            else:
                index = LEVELS.index(level) + 1
                new = self.velocities[LEVELS[index]] if index < len(LEVELS) else 0
            self._pattern[lane][step] = new
            self._edited()
            return new

    def level(self, lane: int, step: int) -> str | None:
        """The level band nearest the step's velocity; None when off."""

        velocity = self._pattern[lane][step]
        if velocity == 0:
            return None
        return min(LEVELS, key=lambda name: abs(self.velocities[name] - velocity))

    def clear(self) -> None:
        with self._lock:
            self._pattern = [[0] * self.steps for _ in self.lanes]
            self._edited()

    def set_lane(self, lane: int, *, note: int | None = None, name: str | None = None) -> None:
        """Change a lane's note and/or name. An empty name follows the note (GM drum name)."""

        with self._lock:
            if not 0 <= lane < len(self.lanes):
                return
            current = self.lanes[lane]
            changes: dict = {}
            if note is not None:
                changes["note"] = max(0, min(127, note))
            if name is not None:
                changes["name"] = "" if name.strip() == default_name(changes.get("note", current.note)) else name.strip()
            self._replace_lanes(lane, replace(current, **changes))

    def _replace_lanes(self, lane: int, new: Lane) -> None:
        lanes = list(self.lanes)
        old = lanes[lane]
        lanes[lane] = new
        self.lanes = tuple(lanes)
        if old.note != new.note or old.channel != new.channel:
            self._end_note(old)
        self._edited()

    def set_channel(self, channel: int) -> None:
        """Put every lane on MIDI *channel* (1-16)."""

        with self._lock:
            channel = max(1, min(16, channel))
            self._flush_offs()
            self.lanes = tuple(replace(lane, channel=channel) for lane in self.lanes)
            self._edited()

    def add_lane(self, note: int | None = None) -> None:
        with self._lock:
            if len(self.lanes) >= MAX_LANES:
                return
            last = self.lanes[-1] if self.lanes else Lane(36)
            if note is None:
                note = min(127, last.note + 1)
            self.lanes = self.lanes + (Lane(note, last.channel),)
            self._pattern.append([0] * self.steps)
            self._edited()

    def remove_lane(self, lane: int) -> None:
        with self._lock:
            if len(self.lanes) <= 1 or not 0 <= lane < len(self.lanes):
                return
            self._end_note(self.lanes[lane])
            self.lanes = self.lanes[:lane] + self.lanes[lane + 1:]
            del self._pattern[lane]
            self._edited()

    def move_lane(self, lane: int, delta: int) -> None:
        with self._lock:
            target = lane + delta
            if not (0 <= lane < len(self.lanes) and 0 <= target < len(self.lanes)):
                return
            lanes = list(self.lanes)
            lanes[lane], lanes[target] = lanes[target], lanes[lane]
            self.lanes = tuple(lanes)
            self._pattern[lane], self._pattern[target] = self._pattern[target], self._pattern[lane]
            self._edited()

    def apply_map(self, lanes: Sequence[Lane]) -> None:
        """Give row *i* the note/name/channel of map lane *i*, keeping every row's steps.

        A longer map adds empty rows; with a shorter map the extra rows stay as they are.
        """

        with self._lock:
            self._flush_offs()
            lanes = list(lanes)[:MAX_LANES]
            current = list(self.lanes)
            for index, lane in enumerate(lanes):
                if index < len(current):
                    current[index] = lane
                else:
                    current.append(lane)
                    self._pattern.append([0] * self.steps)
            self.lanes = tuple(current)
            self._edited()

    def set_steps(self, steps: int) -> None:
        """Change the pattern length.

        Shortening keeps the hidden steps in memory, so lengthening again
        brings them back; saving writes only the current length.
        """

        with self._lock:
            steps = max(1, min(MAX_STEPS, steps))
            if steps == self.steps:
                return
            self._pattern = [row + [0] * (steps - len(row)) for row in self._pattern]
            self.steps = steps
            self._edited()

    # ------------------------------------------------------------------
    # Save / load
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        with self._lock:
            return {
                "steps": self.steps,
                "lanes": [
                    {"note": lane.note, "channel": lane.channel, "name": lane.name, "steps": row[: self.steps]}
                    for lane, row in zip(self.lanes, self._pattern)
                ],
            }

    def load_dict(self, data: dict) -> bool:
        """Replace the pattern with a saved one. False (and unchanged) when malformed."""

        try:
            steps = max(1, min(MAX_STEPS, int(data["steps"])))
            lanes, rows = [], []
            for item in data["lanes"][:MAX_LANES]:
                lanes.append(
                    Lane(
                        max(0, min(127, int(item["note"]))),
                        max(1, min(16, int(item.get("channel", 10)))),
                        str(item.get("name", "")),
                    )
                )
                row = [max(0, min(127, int(v))) for v in item.get("steps", [])]
                rows.append((row + [0] * steps)[:steps])
        except (KeyError, TypeError, ValueError):
            return False
        if not lanes:
            return False
        with self._lock:
            self._flush_offs()
            self.lanes = tuple(lanes)
            self._pattern = rows
            self.steps = steps
            self._edited()
        return True

    @property
    def playing_step(self) -> int | None:
        """The step now sounding, or None while stopped."""

        return self._playing_step if self.running else None

    def display_step(self, lead: float) -> int | None:
        """The step playing *lead* seconds from now, or None while stopped.

        The LEDs and the editor show the playhead a little after the clock
        (run loop, USB, window redraw); drawing it *lead* seconds ahead, at
        the tempo measured from the clock, cancels that delay.
        """

        with self._lock:
            if not self.running or self._playing_step is None:
                return None
            period, last = self._clock_period, self._last_clock_time
            if not lead or period is None or last is None:
                return self._playing_step
            elapsed = min(self._now() - last, 4 * period)  # the clock may pause
            position = self._position - 1 + (elapsed + lead) / period
            return int(position // self.step_clocks) % self.steps

    # ------------------------------------------------------------------
    # Clock input (MIDI callback thread)
    # ------------------------------------------------------------------

    def on_clock(self, message: Sequence[int]) -> None:
        """Handle one realtime / song-position message from Cakewalk."""

        if not message:
            return
        status = message[0]
        with self._lock:
            if status == CLOCK:
                if self.running:
                    self._clock()
            elif status == START:
                self._flush_offs()
                self._position = 0
                self._last_clock_time = None
                self.running = True
            elif status == CONTINUE:
                self.running = True
            elif status == STOP:
                self.running = False
                self._flush_offs()
            elif status == SONG_POSITION and len(message) >= 3:
                self._flush_offs()
                sixteenths = message[1] | (message[2] << 7)
                self._position = sixteenths * CLOCKS_PER_SIXTEENTH

    def _clock(self) -> None:
        now = self._now()
        last = self._last_clock_time
        if last is not None and 0 < now - last < 0.25:  # ignore pauses (below 10 BPM)
            period = now - last
            previous = self._clock_period
            self._clock_period = period if previous is None else previous + (period - previous) * 0.1
        self._last_clock_time = now
        position = self._position
        self._position += 1
        for key, due in list(self._pending_offs.items()):
            if due <= position:
                del self._pending_offs[key]
                self._send((key[0] - 0x10, key[1], 0))  # Note Off
        if position % self.step_clocks:
            return
        step = (position // self.step_clocks) % self.steps
        self._playing_step = step
        for lane, row in zip(self.lanes, self._pattern):
            velocity = row[step]
            if not velocity:
                continue
            status = 0x90 | ((lane.channel - 1) & 0x0F)
            key = (status, lane.note)
            if key in self._pending_offs:  # retrigger: end the previous note first
                del self._pending_offs[key]
                self._send((status - 0x10, lane.note, 0))
            self._send((status, lane.note, velocity))
            self._pending_offs[key] = position + self.gate_clocks

    def _end_note(self, lane: Lane) -> None:
        key = (0x90 | ((lane.channel - 1) & 0x0F), lane.note)
        if self._pending_offs.pop(key, None) is not None:
            self._send((key[0] - 0x10, key[1], 0))

    def _flush_offs(self) -> None:
        for status, note in self._pending_offs:
            self._send((status - 0x10, note, 0))
        self._pending_offs.clear()

    def all_notes_off(self) -> None:
        """End every sounding note (on exit)."""

        with self._lock:
            self._flush_offs()
