"""Mixer engine: APC40 <-> MCU translation, knob modes, and feedback rendering.

The engine owns no ports. It is constructed with:

* *apc_out* - an :class:`apc40.Apc40Output` (renders APC40 LEDs/rings), and
* *mcu_send* - a callable that transmits one raw MIDI message to Cakewalk
  (the ``APC40-MCU`` cable).

Input is fed in as raw messages through :meth:`Engine.on_apc_message` and
:meth:`Engine.on_mcu_message`; the caller's run loop owns the ports and the
timing. Momentary flashes are serviced by :meth:`Engine.tick`.

Behavior mirrors the validated Lua engine (``reference/apc40-sonar.lua``)
except where the Python rewrite is explicitly cleaner, chiefly that MCU
buttons now use real Note On (press) / Note Off (release) pairs.
"""

from __future__ import annotations

from typing import Callable, Sequence

from . import apc40 as apc
from . import mcu

KNOB_MODES = ("pan", "send_a", "send_b", "send_c")

KNOB_MODE_NOTE = {
    "pan": apc.NOTE_PAN,
    "send_a": apc.NOTE_SEND_A,
    "send_b": apc.NOTE_SEND_B,
    "send_c": apc.NOTE_SEND_C,
}

KNOB_MODE_ASSIGN = {
    "pan": mcu.NOTE_ASSIGN_PAN,
    "send_a": mcu.NOTE_ASSIGN_SEND,
    "send_b": mcu.NOTE_ASSIGN_SEND,
    "send_c": mcu.NOTE_ASSIGN_SEND,
}

KNOB_MODE_RING_STYLE = {
    "pan": apc.RING_PAN,
    "send_a": apc.RING_VOLUME,
    "send_b": apc.RING_VOLUME,
    "send_c": apc.RING_VOLUME,
}

# MCU ring mode (bits 5-4) -> APC40 ring style.
RING_STYLE_FROM_MCU = {
    mcu.RING_MODE_SINGLE: apc.RING_SINGLE,
    mcu.RING_MODE_PAN: apc.RING_PAN,
    mcu.RING_MODE_VOLUME: apc.RING_VOLUME,
    mcu.RING_MODE_CENTERED: apc.RING_VOLUME,
}

# APC40 per-track buttons -> MCU button base (add the track index 0-7).
APC_TRACK_BUTTONS = {
    apc.NOTE_RECORD_ARM: mcu.NOTE_REC1,
    apc.NOTE_SOLO: mcu.NOTE_SOLO1,
    apc.NOTE_ACTIVATOR: mcu.NOTE_MUTE1,
    apc.NOTE_TRACK_SELECT: mcu.NOTE_SELECT1,
    apc.NOTE_CLIP_STOP: mcu.NOTE_VPOT_PUSH1,
}

# APC40 global buttons -> MCU notes (channel 0).
APC_GLOBAL_BUTTONS = {
    apc.NOTE_PLAY: mcu.NOTE_PLAY,
    apc.NOTE_STOP: mcu.NOTE_STOP,
    apc.NOTE_RECORD: mcu.NOTE_RECORD,
    apc.NOTE_UP: mcu.NOTE_UP,
    apc.NOTE_DOWN: mcu.NOTE_DOWN,
    apc.NOTE_LEFT: mcu.NOTE_LEFT,
    apc.NOTE_RIGHT: mcu.NOTE_RIGHT,
    apc.NOTE_UTIL_METRONOME: mcu.NOTE_CLICK,
}


class Engine:
    """Translate APC40 controls to MCU messages and MCU feedback to LEDs."""

    def __init__(
        self,
        apc_out: apc.Apc40Output,
        mcu_send: Callable[[Sequence[int]], None],
        *,
        tracks: int = apc.TRACKS,
        rows: int = apc.ROWS,
        flash_frames: int = 6,
    ) -> None:
        self.apc = apc_out
        self._mcu_send = mcu_send
        self.tracks = tracks
        self.rows = rows
        self.flash_frames = flash_frames

        self.knob_mode = "pan"
        self.mixer = True  # True: Track Control knobs drive the V-pots
        self.bank = 0  # informational track-bank offset
        self.show_running = False

        self._track_knob_abs: dict[int, int] = {}
        self._device_knob_abs: dict[int, int] = {}
        self._flashes: list[dict] = []

    # ------------------------------------------------------------------
    # MCU output helpers
    # ------------------------------------------------------------------

    def _send_mcu(self, message: tuple[int, int, int] | None) -> None:
        if message is not None:
            self._mcu_send(message)

    def _mcu_button(self, note: int, pressed: bool) -> None:
        """Forward a button press/release as a real Note On / Note Off pair."""

        self._send_mcu(mcu.button_press(note) if pressed else mcu.button_release(note))

    def _mcu_click(self, note: int) -> None:
        """A synthetic button click (for mode changes triggered internally)."""

        self._send_mcu(mcu.button_press(note))
        self._send_mcu(mcu.button_release(note))

    # ------------------------------------------------------------------
    # APC40 input
    # ------------------------------------------------------------------

    def on_apc_message(self, message: Sequence[int]) -> None:
        decoded = mcu.decode(message)
        if decoded is None:
            return
        if decoded.kind in ("note_on", "note_off"):
            velocity = decoded.value if decoded.kind == "note_on" else 0
            self.on_apc_note(decoded.channel, decoded.number, velocity)
        elif decoded.kind == "cc":
            self.on_apc_cc(decoded.channel, decoded.number, decoded.value)

    def on_apc_cc(self, channel: int, cc: int, value: int) -> None:
        # Channel faders -> MCU Pitch Bend (7-bit scaled to 14-bit).
        if cc == apc.CC_TRACK_LEVEL and channel < self.tracks:
            self._send_mcu(mcu.fader_from_7bit(channel, value))
            return

        if channel != 0:
            return

        # Track Control knobs (absolute) -> relative V-pot delta, mix mode only.
        if apc.CC_TRACK_KNOB1 <= cc < apc.CC_TRACK_KNOB1 + self.tracks and self.mixer:
            self._relative_knob(self._track_knob_abs, cc - apc.CC_TRACK_KNOB1 + 1, value)
            return

        # Device Control knobs drive the V-pots in device mode.
        if apc.CC_DEVICE_KNOB1 <= cc < apc.CC_DEVICE_KNOB1 + self.tracks and not self.mixer:
            self._relative_knob(self._device_knob_abs, cc - apc.CC_DEVICE_KNOB1 + 1, value)

    def _relative_knob(self, store: dict[int, int], index: int, value7: int) -> None:
        previous = store.get(index)
        if previous is not None:
            self._send_mcu(mcu.vpot_delta(index, value7 - previous))
        store[index] = value7

    def on_apc_note(self, channel: int, note: int, velocity: int) -> None:
        pressed = velocity > 0
        per_track_end = apc.NOTE_CLIP_ROW1 + self.rows - 1

        # Per-track controls arrive on channels 0-7.
        if channel < self.tracks and apc.NOTE_RECORD_ARM <= note <= per_track_end:
            if note >= apc.NOTE_CLIP_ROW1:
                # Grid pads are momentary green until grid modes are added.
                row = note - apc.NOTE_CLIP_ROW1 + 1
                self.apc.clip_pad(channel, row, apc.CLIP_GREEN if pressed else apc.CLIP_OFF)
                return
            base = APC_TRACK_BUTTONS.get(note)
            if base is not None:
                self._mcu_button(base + channel, pressed)
            return

        # Global controls are always on channel 0, which Track 1 also uses,
        # so this must run after the per-track branch above.
        if channel != 0:
            return

        mcu_note = APC_GLOBAL_BUTTONS.get(note)
        if mcu_note is not None:
            self._mcu_button(mcu_note, pressed)
            return

        if not pressed:
            return

        # Local-only actions below (press edge only).
        if note == apc.NOTE_STOP_ALL_CLIPS:
            self._mcu_click(mcu.NOTE_STOP)
            self.flash_stop_all()
        elif note == apc.NOTE_PAN:
            self.set_knob_mode("pan")
        elif note == apc.NOTE_SEND_A:
            self.set_knob_mode("send_a")
        elif note == apc.NOTE_SEND_B:
            self.set_knob_mode("send_b")
        elif note == apc.NOTE_SEND_C:
            self.set_knob_mode("send_c")
        elif note in apc.SCENE_NOTES:
            self.apc.global_note(note, apc.LED_ON)  # provisional scene indication
        elif note == apc.NOTE_MASTER:
            self.apc.global_note(apc.NOTE_MASTER, apc.LED_ON)
        elif note == apc.NOTE_TAP_TEMPO:
            self._flash_global(apc.NOTE_TAP_TEMPO)

    # ------------------------------------------------------------------
    # Knob modes
    # ------------------------------------------------------------------

    def set_knob_mode(self, mode: str) -> None:
        """Select a Track Control knob mode and render its LEDs and rings."""

        if mode not in KNOB_MODE_NOTE:
            raise ValueError(f"unknown knob mode: {mode!r}")

        self.knob_mode = mode
        self._mcu_click(KNOB_MODE_ASSIGN[mode])

        # Exactly one mode button lit; the device toggles them locally, so the
        # writes must be forced past the change cache.
        selected = KNOB_MODE_NOTE[mode]
        for note in KNOB_MODE_NOTE.values():
            self.apc.global_note(note, apc.LED_ON if note == selected else apc.LED_OFF, force=True)

        # All eight Track Control rings adopt the mode's display style.
        style = KNOB_MODE_RING_STYLE[mode]
        for knob in range(1, self.tracks + 1):
            self.apc.ring_style(apc.track_ring_style_cc(knob), style, force=True)

        # Pan style centers at 63/64; center the rings until MCU feedback
        # provides real values, so the display matches a centered pan.
        if mode == "pan":
            for knob in range(1, self.tracks + 1):
                self.apc.ring_position(apc.track_ring_cc(knob), 63, force=True)

    # ------------------------------------------------------------------
    # MCU feedback
    # ------------------------------------------------------------------

    def on_mcu_message(self, message: Sequence[int]) -> None:
        decoded = mcu.decode(message)
        if decoded is None:
            return
        if decoded.kind in ("note_on", "note_off"):
            velocity = decoded.value if decoded.kind == "note_on" else 0
            self.on_mcu_note(decoded.number, velocity)
        elif decoded.kind == "cc":
            self.on_mcu_cc(decoded.number, decoded.value)
        elif decoded.kind == "pitch_bend":
            self.on_mcu_pitch(decoded.channel, decoded.value)

    def on_mcu_note(self, note: int, velocity: int) -> None:
        """Render an MCU LED note onto the APC40. Feedback is authoritative."""

        state = mcu.led_state(velocity)
        on = apc.LED_ON if state != "off" else apc.LED_OFF

        if mcu.NOTE_REC1 <= note < mcu.NOTE_REC1 + self.tracks:
            self.apc.strip_led(note - mcu.NOTE_REC1, apc.NOTE_RECORD_ARM, on, force=True)
        elif mcu.NOTE_SOLO1 <= note < mcu.NOTE_SOLO1 + self.tracks:
            self.apc.strip_led(note - mcu.NOTE_SOLO1, apc.NOTE_SOLO, on, force=True)
        elif mcu.NOTE_MUTE1 <= note < mcu.NOTE_MUTE1 + self.tracks:
            self.apc.strip_led(note - mcu.NOTE_MUTE1, apc.NOTE_ACTIVATOR, on, force=True)
        elif mcu.NOTE_SELECT1 <= note < mcu.NOTE_SELECT1 + self.tracks:
            self.apc.strip_led(note - mcu.NOTE_SELECT1, apc.NOTE_TRACK_SELECT, on, force=True)
        elif note == mcu.NOTE_PLAY:
            self.apc.global_note(apc.NOTE_PLAY, on, force=True)
        elif note == mcu.NOTE_STOP:
            self.apc.global_note(apc.NOTE_STOP, on, force=True)
        elif note == mcu.NOTE_RECORD:
            self.apc.global_note(apc.NOTE_RECORD, on, force=True)
        elif note == mcu.NOTE_CLICK:
            self.apc.global_note(apc.NOTE_UTIL_METRONOME, on, force=True)
        elif note == mcu.NOTE_CYCLE:
            self.apc.global_note(apc.NOTE_UTIL_REC_QUANT, on, force=True)  # provisional

    def on_mcu_cc(self, cc: int, value: int) -> None:
        if not (mcu.CC_RING1 <= cc < mcu.CC_RING1 + self.tracks):
            return

        index = cc - mcu.CC_RING1 + 1
        ring = mcu.decode_ring(value)
        position = mcu.ring_value_to_position(ring.value)

        if self.mixer:
            self.apc.ring_position(apc.track_ring_cc(index), position)
        else:
            self.apc.ring_position(apc.device_ring_cc(index), position)
            self.apc.ring_style(
                apc.device_ring_style_cc(index),
                RING_STYLE_FROM_MCU[ring.mode],
                force=True,
            )

    def on_mcu_pitch(self, channel: int, value: int) -> None:
        """Fader feedback is intentionally ignored: APC40 faders are not motorized."""

        return

    # ------------------------------------------------------------------
    # Flashes
    # ------------------------------------------------------------------

    def _schedule_flash(self, frames: int, off: Callable[[], None]) -> None:
        self._flashes.append({"n": frames, "off": off})

    def _flash_global(self, note: int, frames: int | None = None) -> None:
        frames = self.flash_frames if frames is None else frames
        self.apc.global_note(note, apc.LED_ON, force=True)
        self._schedule_flash(frames, lambda: self.apc.global_note(note, apc.LED_OFF, force=True))

    def flash_stop_all(self, frames: int | None = None) -> None:
        """Acknowledge Stop All Clips (no host LED exists): flash Stop + Clip Stops."""

        frames = self.flash_frames if frames is None else frames
        self.apc.global_note(apc.NOTE_STOP, apc.LED_ON, force=True)
        for track in range(self.tracks):
            self.apc.clip_stop(track, apc.CLIP_GREEN_BLINK, force=True)

        def off() -> None:
            self.apc.global_note(apc.NOTE_STOP, apc.LED_OFF, force=True)
            for track in range(self.tracks):
                self.apc.clip_stop(track, apc.CLIP_OFF, force=True)

        self._schedule_flash(frames, off)

    def tick(self) -> None:
        """Advance pending flashes by one frame. Call from the run loop."""

        if not self._flashes:
            return
        remaining: list[dict] = []
        for flash in self._flashes:
            flash["n"] -= 1
            if flash["n"] <= 0:
                flash["off"]()
            else:
                remaining.append(flash)
        self._flashes = remaining

    # ------------------------------------------------------------------
    # Baseline
    # ------------------------------------------------------------------

    def render_baseline(self) -> None:
        """Draw the resting mixer surface and select Pan mode."""

        self.apc.clear_all()
        for knob in range(1, self.tracks + 1):
            self.apc.ring_style(apc.device_ring_style_cc(knob), apc.RING_PAN, force=True)
            self.apc.ring_position(apc.device_ring_cc(knob), 63, force=True)
        self.apc.global_note(apc.NOTE_MASTER, apc.LED_ON, force=True)
        self.apc.global_note(apc.NOTE_SCENE1 + 4, apc.LED_ON, force=True)  # Scene 5
        self.set_knob_mode("pan")
