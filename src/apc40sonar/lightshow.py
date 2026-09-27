"""Startup lightshow.

Purpose (deliberately simpler than the Lua original): prove that the Python app
can drive the APC40 and then leave the surface in a known-ready state.

It lights **every host-addressable control** at least once - the 8x5 clip grid,
Clip Stop, the four strip LEDs per track, the utility row, Master, Scenes,
transport, Pan/Send mode buttons, and both LED-ring banks - then blacks out.
The caller renders the resting/ready state afterwards via
``Engine.render_baseline()`` (Pan mode, centered rings, Master + Scene 5 lit).

The Stop All Clips button has no host-addressable LED and is not used.
"""

from __future__ import annotations

import time
from typing import Callable, Iterator

from . import apc40 as apc

FRAME_MS = 50

# The four single-color LEDs on each channel strip.
_STRIP_LEDS = (apc.NOTE_RECORD_ARM, apc.NOTE_SOLO, apc.NOTE_ACTIVATOR, apc.NOTE_TRACK_SELECT)

# The six clip color/state values used by the chase.
_CLIP_STATES = (apc.CLIP_GREEN, apc.CLIP_GREEN_BLINK, apc.CLIP_RED,
                apc.CLIP_RED_BLINK, apc.CLIP_YELLOW, apc.CLIP_YELLOW_BLINK)


def _light_globals(apc_out: apc.Apc40Output) -> None:
    for note in apc.NOTE_UTIL_ROW:
        apc_out.global_note(note, apc.LED_ON, force=True)
    for note in apc.SCENE_NOTES:
        apc_out.global_note(note, apc.LED_ON, force=True)
    apc_out.global_note(apc.NOTE_MASTER, apc.LED_ON, force=True)
    for note in apc.TRANSPORT_NOTES:
        apc_out.global_note(note, apc.LED_ON, force=True)
    for note in (apc.NOTE_PAN, apc.NOTE_SEND_A, apc.NOTE_SEND_B, apc.NOTE_SEND_C):
        apc_out.global_note(note, apc.LED_ON, force=True)


def light_everything(apc_out: apc.Apc40Output) -> None:
    """Light every host-addressable LED and set both ring banks."""

    for track in range(apc.TRACKS):
        for row in range(1, apc.ROWS + 1):
            apc_out.clip_pad(track, row, apc.CLIP_GREEN, force=True)
        apc_out.clip_stop(track, apc.CLIP_GREEN, force=True)
        for note in _STRIP_LEDS:
            apc_out.strip_led(track, note, apc.LED_ON, force=True)

    _light_globals(apc_out)

    for knob in range(1, apc.TRACKS + 1):
        apc_out.ring_style(apc.device_ring_style_cc(knob), apc.RING_VOLUME, force=True)
        apc_out.ring_position(apc.device_ring_cc(knob), 64, force=True)
        apc_out.ring_style(apc.track_ring_style_cc(knob), apc.RING_SINGLE, force=True)
        apc_out.ring_position(apc.track_ring_cc(knob), 64, force=True)


def _color_chase(apc_out: apc.Apc40Output, step: int) -> None:
    """Grid and Clip Stops cycle color; strip LEDs and globals stay lit."""

    for track in range(apc.TRACKS):
        state = _CLIP_STATES[(step + track) % len(_CLIP_STATES)]
        for row in range(1, apc.ROWS + 1):
            apc_out.clip_pad(track, row, state, force=True)
        apc_out.clip_stop(track, state, force=True)
        for note in _STRIP_LEDS:
            apc_out.strip_led(track, note, apc.LED_ON, force=True)

    _light_globals(apc_out)


def _ring_sweep(apc_out: apc.Apc40Output, step: int) -> None:
    """Move both ring banks through a full sweep."""

    for knob in range(1, apc.TRACKS + 1):
        position = round(step / 4 * 127)
        apc_out.ring_style(apc.track_ring_style_cc(knob), apc.RING_VOLUME, force=True)
        apc_out.ring_position(apc.track_ring_cc(knob), position, force=True)
        apc_out.ring_style(apc.device_ring_style_cc(knob), apc.RING_VOLUME, force=True)
        apc_out.ring_position(apc.device_ring_cc(knob), (position + knob * 15) % 128, force=True)


def frames() -> Iterator[Callable[[apc.Apc40Output], None]]:
    """Yield the show one frame at a time (each frame is a render function)."""

    yield lambda out: out.clear_all()
    for step in range(len(_CLIP_STATES)):
        yield lambda out, s=step: _color_chase(out, s)
    for step in range(5):
        yield lambda out, s=step: _ring_sweep(out, s)
    yield light_everything
    yield lambda out: out.clear_all()


def goodbye_frames() -> Iterator[Callable[[apc.Apc40Output], None]]:
    """Exit animation: the grid fills red, then drains away top to bottom."""

    def fill(out: apc.Apc40Output) -> None:
        for track in range(apc.TRACKS):
            for row in range(1, apc.ROWS + 1):
                out.clip_pad(track, row, apc.CLIP_RED, force=True)
            out.clip_stop(track, apc.CLIP_RED, force=True)

    def drain(out: apc.Apc40Output, rows: int) -> None:
        for track in range(apc.TRACKS):
            for row in range(1, rows + 1):
                out.clip_pad(track, row, apc.CLIP_OFF, force=True)

    yield fill
    for rows in range(1, apc.ROWS + 1):
        yield lambda out, r=rows: drain(out, r)
    yield lambda out: out.clear_all()


def goodbye(
    apc_out: apc.Apc40Output,
    *,
    frame_ms: int = FRAME_MS,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Play the exit animation and leave the panel dark (app not running)."""

    for frame in goodbye_frames():
        frame(apc_out)
        sleep(frame_ms / 1000.0)


def play(
    apc_out: apc.Apc40Output,
    *,
    frame_ms: int = FRAME_MS,
    sleep: Callable[[float], None] = time.sleep,
    on_frame: Callable[[int], None] | None = None,
) -> None:
    """Run the whole show, then clear. *sleep* is injectable for tests."""

    for index, frame in enumerate(frames()):
        frame(apc_out)
        if on_frame is not None:
            on_frame(index)
        sleep(frame_ms / 1000.0)
    apc_out.clear_all()
