"""Mixer engine: APC40 <-> MCU translation, knob modes, and feedback rendering.

The engine owns no ports. It is constructed with:

* *apc_out* - an :class:`apc40.Apc40Output` (renders APC40 LEDs/rings), and
* *mcu_send* - a callable that transmits one raw MIDI message to Cakewalk
  (the ``APC40-IN`` cable).

Input is fed in as raw messages through :meth:`Engine.on_apc_message` and
:meth:`Engine.on_mcu_message`; the caller's run loop owns the ports and the
timing. Momentary flashes and level-meter decay are serviced by
:meth:`Engine.tick`.

Behavior mirrors the validated Lua engine (``reference/apc40-sonar.lua``)
except where the Python rewrite is explicitly cleaner, chiefly that MCU
buttons now use real Note On (press) / Note Off (release) pairs.
"""

from __future__ import annotations

import logging
from typing import Callable, Sequence

from . import apc40 as apc
from . import mcu

log = logging.getLogger(__name__)

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

# Cakewalk lists 4 parameters per send (enable, level, ...) and the knobs sit on
# one of them across 8 tracks; the level of send n is parameter 4*(n-1) + 1.
KNOB_MODE_SEND_PARAM = {"send_a": 1, "send_b": 5, "send_c": 9}

# MCU assignment LED -> Cakewalk assignment name (from its feedback).
ASSIGN_LED = {mcu.NOTE_ASSIGN_PAN: "pan", mcu.NOTE_ASSIGN_SEND: "send"}

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

# In Generic Mode the Record Arm / Solo / Activator buttons LATCH: the device
# sends Note On when the button turns on and Note Off when it turns off (it does
# not send an immediate off on release). Both edges are therefore a discrete
# state change and each must emit exactly one MCU button press, or Cakewalk will
# ignore the "off" edge and the button will appear to need two presses to clear.
APC_TRACK_TOGGLES = {
    apc.NOTE_RECORD_ARM: mcu.NOTE_REC1,
    apc.NOTE_SOLO: mcu.NOTE_SOLO1,
    apc.NOTE_ACTIVATOR: mcu.NOTE_MUTE1,
}

# Track Selection is a radio group: only the "on" edge selects a track. The
# "off" edge fires when a different track is chosen and must not re-select.
APC_TRACK_SELECT = apc.NOTE_TRACK_SELECT
APC_TRACK_SELECT_NOTE = mcu.NOTE_SELECT1

# Momentary per-track buttons: act on the press edge only.
APC_TRACK_MOMENTARY = {
    apc.NOTE_CLIP_STOP: mcu.NOTE_VPOT_PUSH1,
}

# Track level meters on the clip grid. Each track's column is a bottom-up bar:
# row 5 is the lowest segment and row 1 the highest. Entries are
# (grid row, minimum MCU meter level, color). MCU levels: 3 >= -40 dB,
# 5 >= -20 dB, 7 >= -10 dB, 9 >= -6 dB, 12 = 0 dB, 13 = over.
METER_SEGMENTS = (
    (5, 3, apc.CLIP_GREEN),
    (4, 5, apc.CLIP_GREEN),
    (3, 7, apc.CLIP_GREEN),
    (2, 9, apc.CLIP_YELLOW),
    (1, 12, apc.CLIP_RED),
)
METER_CLIP_COLOR = apc.CLIP_RED  # Clip Stop LED while a track's clip is latched

# MCU buttons Cakewalk acts on at *release*: they need a release it can see.
# Loop toggles on release; the cursor keys auto-repeat (0.4 s, then every
# 50-500 ms) until Cakewalk sees their release.
CAKEWALK_RELEASE_BUTTONS = frozenset(
    {mcu.NOTE_CW_LOOP, mcu.NOTE_UP, mcu.NOTE_DOWN, mcu.NOTE_LEFT, mcu.NOTE_RIGHT}
)

# Crossfader zoom: at or below this position the slider fits the project;
# it re-arms once the slider is back above ZOOM_FIT_REARM.
ZOOM_FIT_AT = 1
ZOOM_FIT_REARM = 10
ZOOM_STEP_LIMIT = 4  # max zoom steps per crossfader event

# Frames without Device knob messages that end a knob dump burst.
KNOB_DUMP_QUIET_FRAMES = 2

# APC40 global buttons -> MCU notes (channel 0). Cakewalk treats the MCU
# cursor buttons as keyboard arrow keys; Bank Left/Right moves the 8-strip
# window by 8 tracks.
APC_GLOBAL_BUTTONS = {
    apc.NOTE_PLAY: mcu.NOTE_PLAY,
    apc.NOTE_RECORD: mcu.NOTE_RECORD,
    apc.NOTE_UP: mcu.NOTE_UP,
    apc.NOTE_DOWN: mcu.NOTE_DOWN,
    apc.NOTE_LEFT: mcu.NOTE_BANK_LEFT,
    apc.NOTE_RIGHT: mcu.NOTE_BANK_RIGHT,
    # Loop on/off: Cakewalk mode has no metronome button; its note 89 (the
    # standard MCU "Click") toggles transport loop and its LED shows loop state.
    apc.NOTE_UTIL_METRONOME: mcu.NOTE_CW_LOOP,
}

# Shift + APC40 button -> MCU note. Channel Left/Right moves the window by
# one track.
APC_SHIFT_BUTTONS = {
    apc.NOTE_LEFT: mcu.NOTE_CHANNEL_LEFT,
    apc.NOTE_RIGHT: mcu.NOTE_CHANNEL_RIGHT,
    # Metronome on/off via Mackie F1, which the Cakewalk preset assigns to
    # "Metronome During Record". Cakewalk reports no state for it.
    apc.NOTE_UTIL_METRONOME: mcu.NOTE_F1,
}

# Cue Level: max jog messages per knob event. Cakewalk ignores the jog value's
# magnitude, so a fast turn is sent as several single steps.
CUE_JOG_STEP_LIMIT = 4

# Buttons whose LED flashes to acknowledge a press (no host feedback exists).
APC_FLASH_ON_PRESS = frozenset({apc.NOTE_LEFT, apc.NOTE_RIGHT})


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
        knob_step_limit: int = 3,
        knob_noise_threshold: int = 4,
        meters: bool = True,
        meter_decay_frames: int = 15,
        meter_settle_frames: int = 25,
        stop_double_frames: int = 20,
        zoom_step_units: int = 6,
        zoom_idle_frames: int = 15,
    ) -> None:
        self.apc = apc_out
        self._mcu_send = mcu_send
        self.tracks = tracks
        self.rows = rows
        self.flash_frames = flash_frames
        # Maximum V-pot steps emitted per knob event. The APC40 knobs report an
        # absolute 0-127 position that wraps; without a limit a wrap or a fast
        # turn produces a large delta and the parameter jumps around.
        self.knob_step_limit = knob_step_limit
        # Steps larger than this are treated as noise/re-reference rather than
        # movement. 0 disables the gate.
        self.knob_noise_threshold = knob_noise_threshold
        # Level meters own the clip grid (and the Clip Stop LEDs as clip
        # indicators). A real MCU decays its meters locally at about one
        # division per 300 ms; Cakewalk relies on that, so decay here too.
        self.meters = meters
        self.meter_decay_frames = max(1, meter_decay_frames)
        # Cakewalk sends every strip's meter on each surface refresh (50-75 ms)
        # while its meters are on, silence included. Meter traffic within this
        # many frames therefore means "Cakewalk meters on".
        self.meter_settle_frames = max(2, meter_settle_frames)
        # A second Stop press within this many frames also returns to the start.
        self.stop_double_frames = stop_double_frames
        # Crossfader travel per zoom step, and how long after the last movement
        # Cakewalk's zoom mode is switched back off.
        self.zoom_step_units = max(1, zoom_step_units)
        self.zoom_idle_frames = max(1, zoom_idle_frames)

        self.knob_mode = "pan"
        self.mixer = True  # True: Track Control knobs drive the V-pots
        self.bank = 0  # informational track-bank offset
        self.show_running = False
        self.shift = False
        # Cakewalk's current assignment ("pan", "send", another, or None =
        # unknown) and Edit mode, both from its LEDs. Pressing the assignment
        # that is already active flips Cakewalk's knobs to single-track
        # (channel strip) layout, which it never reports, so the engine only
        # presses an assignment button when switching.
        self._cw_assign: str | None = None
        self._cw_edit = False
        # Last loop LED state from Cakewalk, shown on the Metronome button.
        self._loop_led = apc.LED_OFF

        self._track_knob_abs: dict[int, int] = {}
        self._device_knob_abs: dict[int, int] = {}
        self._flashes: list[dict] = []
        self._meter_level = [0] * tracks
        self._meter_age = [0] * tracks
        self._meter_clip = [False] * tracks
        self._frame = 0
        self._last_meter_frame: int | None = None
        self._meter_toggle: dict | None = None
        self._last_stop_frame: int | None = None
        self._crossfader: int | None = None
        self._zoom_accum = 0
        self._zoom_mode = False  # Cakewalk's zoom mode, from its Zoom LED
        self._zoom_owned = False  # True while we turned zoom mode on
        self._zoom_last_frame = 0
        self._zoom_fit_armed = True
        # Generic Mode Track Selection sends no note: the APC40 switches its
        # Device Control bank and dumps all eight Device knob positions
        # (CC 16-23) on the new bank's channel. A burst of those is collected
        # here and turned into a select once it goes quiet.
        self._knob_dump: dict[int, set[int]] = {}
        self._knob_dump_frame = 0

    # ------------------------------------------------------------------
    # MCU output helpers
    # ------------------------------------------------------------------

    def _send_mcu(self, message: tuple[int, int, int] | None) -> None:
        if message is not None:
            self._mcu_send(message)

    def _mcu_click(self, note: int) -> None:
        """Emit one MCU button press: real Note On followed by real Note Off.

        The MCU treats a note "bang" as a single button press, so this is one
        toggle in Cakewalk. It is used for both momentary APC40 buttons and for
        each edge of a latching APC40 toggle button. Buttons Cakewalk acts on
        at release (Loop) get a Note On velocity 0 release instead, because
        Cakewalk drops real Note Offs.
        """

        self._send_mcu(mcu.button_press(note))
        if note in CAKEWALK_RELEASE_BUTTONS:
            self._send_mcu(mcu.cakewalk_release(note))
        else:
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

        # Master fader (channel not significant) -> MCU master fader. Cakewalk
        # binds it to the hardware outputs by default; the Mackie Control
        # Master Fader setting must be Bus + Master bus. No fader touch is needed.
        if cc == apc.CC_MASTER_LEVEL:
            self._send_mcu(mcu.fader_from_7bit(mcu.FADER_MASTER_CHANNEL, value))
            return

        # Device Control knobs report on the selected bank's channel (0-8) and
        # drive the V-pots in device mode.
        if apc.CC_DEVICE_KNOB1 <= cc < apc.CC_DEVICE_KNOB1 + self.tracks:
            if channel < apc.DEVICE_BANKS:
                self._knob_dump.setdefault(channel, set()).add(cc)
                self._knob_dump_frame = self._frame
            if channel < apc.DEVICE_BANKS and not self.mixer:
                self._relative_knob(self._device_knob_abs, cc - apc.CC_DEVICE_KNOB1 + 1, value)
            return

        # Cue Level (relative, channel not significant) -> jog: moves the now
        # time by Cakewalk's Jog Wheel Resolution per step.
        # Crossfader (absolute, channel not significant) -> horizontal zoom.
        if cc == apc.CC_CROSSFADER:
            self._on_crossfader(value)
            return

        if cc == apc.CC_CUE_LEVEL:
            delta = value - 128 if value > 63 else value
            for _ in range(min(abs(delta), CUE_JOG_STEP_LIMIT)):
                self._send_mcu(mcu.jog(delta > 0))
            return

        if channel != 0:
            return

        # Track Control knobs (absolute) -> relative V-pot delta, mix mode only.
        if apc.CC_TRACK_KNOB1 <= cc < apc.CC_TRACK_KNOB1 + self.tracks and self.mixer:
            self._relative_knob(self._track_knob_abs, cc - apc.CC_TRACK_KNOB1 + 1, value)

    def _relative_knob(self, store: dict[int, int], index: int, value7: int) -> None:
        previous = store.get(index)
        store[index] = value7
        if previous is None:
            return

        delta = (value7 - previous) % 128
        if delta > 64:
            delta -= 128

        # Whenever the host writes an endless encoder's LED ring (Cakewalk
        # feedback arrives each refresh), the APC40 re-references that encoder's
        # absolute value. The next reading then jumps by an amount that is not
        # physical movement. Electrical blips look the same. Drop those events
        # (the position is already resynced above) instead of turning them into
        # a hard V-pot step, which is what made the parameter leap around.
        threshold = self.knob_noise_threshold
        if threshold and abs(delta) > threshold:
            return

        limit = self.knob_step_limit
        if delta > limit:
            delta = limit
        elif delta < -limit:
            delta = -limit
        if delta:
            self._send_mcu(mcu.vpot_delta(index, delta))

    def on_apc_note(self, channel: int, note: int, velocity: int) -> None:
        pressed = velocity > 0
        per_track_end = apc.NOTE_CLIP_ROW1 + self.rows - 1

        # Per-track controls arrive on channels 0-7.
        if channel < self.tracks and apc.NOTE_RECORD_ARM <= note <= per_track_end:
            if note >= apc.NOTE_CLIP_ROW1:
                if self.meters:
                    return  # the grid is a level-meter display
                # Grid pads are momentary green until grid modes are added.
                row = note - apc.NOTE_CLIP_ROW1 + 1
                self.apc.clip_pad(channel, row, apc.CLIP_GREEN if pressed else apc.CLIP_OFF)
                return
            toggle = APC_TRACK_TOGGLES.get(note)
            if toggle is not None:
                # Note: Cakewalk's Mackie Control ignores MCU Rec note 0, so
                # Track 1 (channel 0) cannot be armed from the surface; arm it
                # from the Cakewalk UI instead.
                self._mcu_click(toggle + channel)
                return

            if note == APC_TRACK_SELECT:
                if pressed:
                    self._mcu_click(APC_TRACK_SELECT_NOTE + channel)
                return

            momentary = APC_TRACK_MOMENTARY.get(note)
            if momentary is not None:
                if pressed:
                    self._mcu_click(momentary + channel)
                return
            return

        # The Device Control button row (58-65: Clip/Track ... Detail View,
        # Rec Quantize, Overdub, Metronome) reports on the selected bank's
        # channel, 0-7 for Tracks 1-8 or 8 for Master. It is still one global
        # control, so fold the bank channel away.
        if note in apc.NOTE_UTIL_ROW and channel < apc.DEVICE_BANKS:
            channel = 0

        # Other global controls are always on channel 0, which Track 1 also
        # uses, so this must run after the per-track branch above.
        if channel != 0:
            return

        # The Metronome button is momentary: the APC40 switches its own LED off
        # on release, which can land after Cakewalk's loop LED update (during
        # playback Cakewalk refreshes fast enough to beat the finger). Re-assert
        # the loop state on every release.
        if note == apc.NOTE_UTIL_METRONOME and not pressed:
            self.apc.global_note(apc.NOTE_UTIL_METRONOME, self._loop_led, force=True)
            return

        if note == apc.NOTE_SHIFT:
            self.shift = pressed
            self.apc.global_note(apc.NOTE_SHIFT, apc.LED_ON if pressed else apc.LED_OFF, force=True)
            return

        # Shift layer: mapped combos replace the button's normal action;
        # unmapped ones fall through unchanged.
        if self.shift and pressed:
            if note == apc.NOTE_UTIL_DETAIL_VIEW:
                self.toggle_cakewalk_meters()
                return
            shifted = APC_SHIFT_BUTTONS.get(note)
            if shifted is not None:
                self._mcu_click(shifted)
                if note in APC_FLASH_ON_PRESS:
                    self._flash_global(note)
                return

        if note == apc.NOTE_STOP and pressed:
            self._on_stop_press()
            return

        mcu_note = APC_GLOBAL_BUTTONS.get(note)
        if mcu_note is not None:
            if pressed:
                self._mcu_click(mcu_note)
                if note in APC_FLASH_ON_PRESS:
                    self._flash_global(note)
            return

        if not pressed:
            return

        # Local-only actions below (press edge only).
        if note == apc.NOTE_STOP_ALL_CLIPS:
            self._mcu_click(mcu.NOTE_STOP)
            self.clear_meter_clips()
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
    # Crossfader zoom
    # ------------------------------------------------------------------

    def _on_crossfader(self, value: int) -> None:
        """Zoom Cakewalk horizontally: right = in, left = out, far left = fit.

        Cakewalk's zoom mode turns the Left/Right cursor keys into Ctrl+Left /
        Ctrl+Right (zoom out / in), and Zoom + M4 + Right into "fit project".
        The engine enters zoom mode on the first movement and leaves it once
        the slider has been idle (see :meth:`_zoom_idle`).
        """

        previous = self._crossfader
        self._crossfader = value
        if value > ZOOM_FIT_REARM:
            self._zoom_fit_armed = True
        if previous is None:
            return  # first reading only sets the baseline

        if value <= ZOOM_FIT_AT and self._zoom_fit_armed:
            self._zoom_fit_armed = False
            self._zoom_accum = 0
            self._enter_zoom_mode()
            self._send_mcu(mcu.button_press(mcu.NOTE_M4))
            self._mcu_click(mcu.NOTE_RIGHT)
            self._send_mcu(mcu.cakewalk_release(mcu.NOTE_M4))
            return

        self._zoom_accum += value - previous
        steps = 0
        units = self.zoom_step_units
        while abs(self._zoom_accum) >= units and steps < ZOOM_STEP_LIMIT:
            zoom_in = self._zoom_accum > 0
            self._zoom_accum -= units if zoom_in else -units
            self._enter_zoom_mode()
            self._mcu_click(mcu.NOTE_RIGHT if zoom_in else mcu.NOTE_LEFT)
            steps += 1
        if steps == ZOOM_STEP_LIMIT:
            self._zoom_accum = 0  # drop the excess of a very fast sweep

    def _enter_zoom_mode(self) -> None:
        self._zoom_last_frame = self._frame
        if not self._zoom_mode:
            self._mcu_click(mcu.NOTE_ZOOM)
            self._zoom_mode = True  # Cakewalk's Zoom LED confirms shortly
            self._zoom_owned = True

    def _zoom_idle(self) -> None:
        """Leave zoom mode once the crossfader has been still for a while."""

        if not self._zoom_owned:
            return
        if self._frame - self._zoom_last_frame < self.zoom_idle_frames:
            return
        self._zoom_owned = False
        if self._zoom_mode:
            self._mcu_click(mcu.NOTE_ZOOM)
            self._zoom_mode = False

    def _settle_knob_dump(self) -> None:
        """Turn a finished Device knob dump into a Track Selection press.

        A burst holding all eight Device knobs on exactly one channel is a
        Track Selection press for that track (channel 8 = Master: no track).
        A single knob turn never sends all eight, and a dump spanning several
        channels (a whole-surface dump) is ignored.
        """

        if not self._knob_dump or self._frame - self._knob_dump_frame < KNOB_DUMP_QUIET_FRAMES:
            return
        dump, self._knob_dump = self._knob_dump, {}
        if len(dump) != 1:
            return
        (channel, ccs), = dump.items()
        if len(ccs) == self.tracks and channel < self.tracks:
            self._mcu_click(APC_TRACK_SELECT_NOTE + channel)

    def _on_stop_press(self) -> None:
        """Stop; a second press soon after also goes to the start (MCU Home)."""

        self._mcu_click(mcu.NOTE_STOP)
        last = self._last_stop_frame
        if last is not None and self._frame - last <= self.stop_double_frames:
            self._mcu_click(mcu.NOTE_CW_HOME)
            self._last_stop_frame = None  # a third press starts a new pair
        else:
            self._last_stop_frame = self._frame

    # ------------------------------------------------------------------
    # Knob modes
    # ------------------------------------------------------------------

    def set_knob_mode(self, mode: str) -> None:
        """Select a Track Control knob mode and render its LEDs and rings."""

        if mode not in KNOB_MODE_NOTE:
            raise ValueError(f"unknown knob mode: {mode!r}")

        self.knob_mode = mode
        self._select_assignment(KNOB_MODE_ASSIGN[mode])
        if mode in KNOB_MODE_SEND_PARAM:
            self._select_send_param(KNOB_MODE_SEND_PARAM[mode])

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

    def _select_assignment(self, note: int) -> None:
        """Make *note*'s assignment active without ever re-pressing it.

        When the current assignment is unknown (startup), step through
        Dynamics first, which this app never uses, so the final press is
        always a switch and never a layout flip.
        """

        target = ASSIGN_LED[note]
        if self._cw_assign == target:
            return
        if self._cw_assign is None:
            self._mcu_click(mcu.NOTE_CW_DYNAMICS)
        self._mcu_click(note)
        self._cw_assign = target

    def _select_send_param(self, param: int) -> None:
        """Point the send knobs at parameter *param* (1, 5, 9 = sends 1-3).

        Edit mode turns Bank/Channel Left/Right into parameter moves: M1 +
        Bank Left goes to the first parameter, Bank Right is +8 and Channel
        Right +1. Cakewalk stops at the last parameter a track has.
        """

        if not self._cw_edit:
            self._mcu_click(mcu.NOTE_CW_EDIT)
        self._send_mcu(mcu.button_press(mcu.NOTE_M1))
        self._mcu_click(mcu.NOTE_BANK_LEFT)
        self._send_mcu(mcu.cakewalk_release(mcu.NOTE_M1))
        eights, ones = divmod(param, 8)
        for _ in range(eights):
            self._mcu_click(mcu.NOTE_BANK_RIGHT)
        for _ in range(ones):
            self._mcu_click(mcu.NOTE_CHANNEL_RIGHT)
        self._mcu_click(mcu.NOTE_CW_EDIT)  # leave Edit mode
        self._cw_edit = False

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
        elif decoded.kind == "pressure":
            self.on_mcu_meter(decoded.value)

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
        elif note in ASSIGN_LED:
            if state != "off":
                self._cw_assign = ASSIGN_LED[note]
            elif self._cw_assign == ASSIGN_LED[note]:
                self._cw_assign = "other"
        elif note == mcu.NOTE_CW_EDIT:
            self._cw_edit = state != "off"
        elif note == mcu.NOTE_ZOOM:
            self._zoom_mode = state != "off"
        elif note == mcu.NOTE_CW_LOOP:
            self._loop_led = on
            self.apc.global_note(apc.NOTE_UTIL_METRONOME, on, force=True)

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
    # Level meters
    # ------------------------------------------------------------------

    def on_mcu_meter(self, value: int) -> None:
        """Apply one MCU channel-meter update (Channel Pressure value)."""

        self._last_meter_frame = self._frame
        meter = mcu.decode_meter(value)
        track = meter.strip
        if track >= self.tracks:
            return

        if meter.level == mcu.METER_OVERLOAD_SET:
            self._set_meter_clip(track, True)
            return
        if meter.level == mcu.METER_OVERLOAD_CLEAR:
            self._set_meter_clip(track, False)
            return

        level = min(meter.level, mcu.METER_LEVEL_MAX)
        self._meter_level[track] = level
        self._meter_age[track] = 0
        if level >= mcu.METER_LEVEL_MAX:
            # Latch clipping locally too: not every host sends the overload flag.
            self._set_meter_clip(track, True)
        self._render_meter_bar(track)

    def cakewalk_meters_on(self) -> bool:
        """True while Cakewalk is streaming meter data (its Meters setting is on)."""

        last = self._last_meter_frame
        return last is not None and self._frame - last <= self.meter_settle_frames

    def toggle_cakewalk_meters(self) -> None:
        """Turn Cakewalk's Mackie Control meters on or off with one press.

        Cakewalk cycles Off -> Signal LEDs -> Signal LEDs + Meters -> Off on
        M2 + Name/Value. Both "on" states stream the same meter data, so turning
        off may take a second step; :meth:`tick` decides that once the result
        of the first step is visible in the meter traffic.
        """

        if self._meter_toggle is not None:
            return  # a toggle is still settling
        want_on = not self.cakewalk_meters_on()
        self._step_cakewalk_meters()
        self._meter_toggle = {"start": self._frame, "want_on": want_on}
        self._flash_global(apc.NOTE_UTIL_DETAIL_VIEW)
        log.info("Cakewalk meters: turning %s", "on" if want_on else "off")

    def _step_cakewalk_meters(self) -> None:
        """Send one M2 + Name/Value press: Cakewalk's meter-mode step."""

        self._send_mcu(mcu.button_press(mcu.NOTE_M2))
        self._mcu_click(mcu.NOTE_NAME_VALUE)
        self._send_mcu(mcu.cakewalk_release(mcu.NOTE_M2))

    def _settle_meter_toggle(self) -> None:
        toggle = self._meter_toggle
        if toggle is None or self._frame - toggle["start"] < self.meter_settle_frames:
            return
        self._meter_toggle = None

        # Only traffic from the second half of the window reflects the new
        # state; earlier messages may predate Cakewalk handling the step.
        last = self._last_meter_frame
        flowing = last is not None and last > toggle["start"] + self.meter_settle_frames // 2

        if not toggle["want_on"] and flowing:
            self._step_cakewalk_meters()  # was Signal LEDs, now LEDs + Meters -> Off
        elif toggle["want_on"] and not flowing:
            log.warning(
                "Cakewalk sent no meters after the toggle; set the Mackie Control "
                "surface protocol to the default (not Universal/HUI) or enable "
                "Meters on its property page"
            )

    def meter_level(self, track: int) -> int:
        """Current (decayed) meter level 0-13 for *track* (0-based)."""

        return self._meter_level[track]

    def meter_clipped(self, track: int) -> bool:
        return self._meter_clip[track]

    def clear_meter_clips(self) -> None:
        """Release every latched clip indicator (Stop All Clips does this)."""

        for track in range(self.tracks):
            self._set_meter_clip(track, False)

    def _set_meter_clip(self, track: int, clipped: bool) -> None:
        if self._meter_clip[track] == clipped:
            return
        self._meter_clip[track] = clipped
        self._render_meter_clip(track)

    def _render_meter_bar(self, track: int) -> None:
        if not self.meters:
            return
        level = self._meter_level[track]
        for row, threshold, color in METER_SEGMENTS:
            self.apc.clip_pad(track, row, color if level >= threshold else apc.CLIP_OFF)

    def _render_meter_clip(self, track: int, *, force: bool = False) -> None:
        if not self.meters:
            return
        state = METER_CLIP_COLOR if self._meter_clip[track] else apc.CLIP_OFF
        self.apc.clip_stop(track, state, force=force)

    def _decay_meters(self) -> None:
        for track in range(self.tracks):
            if self._meter_level[track] == 0:
                continue
            self._meter_age[track] += 1
            if self._meter_age[track] >= self.meter_decay_frames:
                self._meter_age[track] = 0
                self._meter_level[track] -= 1
                self._render_meter_bar(track)

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
                if self._meter_clip[track]:
                    self._render_meter_clip(track, force=True)

        self._schedule_flash(frames, off)

    def tick(self) -> None:
        """Advance meter decay and pending flashes by one frame. Call from the run loop."""

        self._frame += 1
        self._settle_meter_toggle()
        self._zoom_idle()
        self._settle_knob_dump()
        if self.meters:
            self._decay_meters()
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
        self._meter_level = [0] * self.tracks
        self._meter_age = [0] * self.tracks
        self._meter_clip = [False] * self.tracks
        for knob in range(1, self.tracks + 1):
            self.apc.ring_style(apc.device_ring_style_cc(knob), apc.RING_PAN, force=True)
            self.apc.ring_position(apc.device_ring_cc(knob), 63, force=True)
        self.apc.global_note(apc.NOTE_MASTER, apc.LED_ON, force=True)
        self.apc.global_note(apc.NOTE_SCENE1 + 4, apc.LED_ON, force=True)  # Scene 5
        self.set_knob_mode("pan")
