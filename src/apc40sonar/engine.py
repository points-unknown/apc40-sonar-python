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
from collections import deque
from typing import Callable, Sequence

from . import apc40 as apc
from . import c4
from . import hud_state
from . import mcu
from . import mcu_display
from . import sequencer as sq

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
    {
        mcu.NOTE_CW_LOOP,
        mcu.NOTE_UP,
        mcu.NOTE_DOWN,
        mcu.NOTE_LEFT,
        mcu.NOTE_RIGHT,
        mcu.NOTE_REWIND,  # in marker navigation Rew/FF repeat until released
        mcu.NOTE_FORWARD,
    }
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
    # Loop on/off on Rec Quantize: Cakewalk's note 89 (the standard MCU
    # "Click") toggles transport loop and its LED shows loop state.
    apc.NOTE_UTIL_REC_QUANT: mcu.NOTE_CW_LOOP,
    # Auto-punch on/off via Mackie F2, which the preset assigns to Cakewalk's
    # auto-punch toggle. Cakewalk reports no auto-punch state (no LED).
    apc.NOTE_UTIL_METRONOME: mcu.NOTE_F2,
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

# Playhead steps: one Mackie jog message moves Cakewalk's now time by one unit,
# chosen by the modifier held with it (M1 measure, M2 beat, M3 tick; none = the
# preset's Jog Wheel Resolution). Cakewalk reads only the direction, so a step
# of N units is N messages.
JOG_UNIT_MODIFIER = {
    "measure": mcu.NOTE_M1,
    "beat": mcu.NOTE_M2,
    "tick": mcu.NOTE_M3,
    "jog": None,
}

# Jog messages allowed per frame (20 ms) across all playhead moves. Cakewalk
# moves one unit per message, so fine tick steps are many messages; a fast
# spin must never flood the loopMIDI cable (its flood protection disables the
# port until loopMIDI is restarted). Excess steps in a frame are dropped.
JOG_BUDGET_PER_FRAME = 48

# Nudge - / + move the playhead back / forward.
APC_NUDGE_FORWARD = {apc.NOTE_NUDGE_MINUS: False, apc.NOTE_NUDGE_PLUS: True}

# Buttons whose LED flashes to acknowledge a press (no host feedback exists).
APC_FLASH_ON_PRESS = frozenset({apc.NOTE_LEFT, apc.NOTE_RIGHT})

# MCU per-strip LED notes: (first note, HUD key, APC40 per-track button).
STRIP_LEDS = (
    (mcu.NOTE_REC1, "rec", apc.NOTE_RECORD_ARM),
    (mcu.NOTE_SOLO1, "solo", apc.NOTE_SOLO),
    (mcu.NOTE_MUTE1, "mute", apc.NOTE_ACTIVATOR),
    (mcu.NOTE_SELECT1, "select", apc.NOTE_TRACK_SELECT),
)

# Surface navigation presses -> (strip window move, HUD toast). Cakewalk does
# not report the window offset, so the HUD shows it as provisional until the
# next track select confirms it.
BANK_MOVES = {
    mcu.NOTE_BANK_LEFT: (-8, "Bank <"),
    mcu.NOTE_BANK_RIGHT: (8, "Bank >"),
    mcu.NOTE_CHANNEL_LEFT: (-1, "Channel <"),
    mcu.NOTE_CHANNEL_RIGHT: (1, "Channel >"),
}

# Other presses with no Cakewalk feedback, echoed as HUD toasts.
PRESS_TOASTS = {
    mcu.NOTE_F1: "Metronome (rec) toggled",
    mcu.NOTE_F2: "Auto-punch toggled",
}

# Scene buttons select the mode.
MODES = ("tracking", "sequencer", "mixing")
MODE_SCENE = {"tracking": apc.NOTE_SCENE1, "sequencer": apc.NOTE_SCENE1 + 1, "mixing": apc.NOTE_SCENE1 + 2}
SCENE_MODE = {note: mode for mode, note in MODE_SCENE.items()}
MODE_TOASTS = {"tracking": "Tracking mode", "sequencer": "Step sequencer mode", "mixing": "Mixing mode"}

# Step sequencer: pad color per step level, and the Bank Select arrows, which
# page steps (Left/Right) and lanes (Up/Down) instead of moving Cakewalk.
SEQ_LEVEL_COLOR = {"normal": apc.CLIP_GREEN, "accent": apc.CLIP_YELLOW, "soft": apc.CLIP_RED}
# Shown when Cakewalk plays but sends no MIDI clock: the setting is per project,
# so every new project starts without it.
SEQ_NO_CLOCK = (
    "Cakewalk is playing but sends no clock. In this project set Preferences > Project > MIDI: "
    "tick Transmit MIDI Start/Continue/Stop/Clock and pick APC40-CLOCK (saved per project)."
)

SEQ_PAGE_MOVES = {
    apc.NOTE_LEFT: ("steps", -1),
    apc.NOTE_RIGHT: ("steps", 1),
    apc.NOTE_UP: ("lanes", -1),
    apc.NOTE_DOWN: ("lanes", 1),
}

# In Generic Mode the first four utility buttons (58-61) LATCH: the APC40
# lights its own LED and sends Note On on one press, and turns it off and
# sends Note Off on the next. Both edges are one press of a one-shot action,
# and the engine forces the LED back off so the buttons stay dark.
APC_LATCHING_UTILITY = frozenset({
    apc.NOTE_UTIL_CLIP_TRACK,
    apc.NOTE_UTIL_DEVICE_ONOFF,
    apc.NOTE_UTIL_LEFT_ARROW,
    apc.NOTE_UTIL_RIGHT_ARROW,
})

# Utility-row buttons that change with the mode; the rest of the row (62-65)
# works the same in every mode. In Mixing, 58-61 control the plug-in (C4).
TRACKING_ONLY = frozenset({
    apc.NOTE_UTIL_CLIP_TRACK,
    apc.NOTE_UTIL_DEVICE_ONOFF,
    apc.NOTE_UTIL_LEFT_ARROW,
    apc.NOTE_UTIL_RIGHT_ARROW,
})

# What the Device Control knobs drive in each mode: "c4" = 8 parameters of
# the selected track's plug-in, through Cakewalk's Mackie Control C4 surface.
# A held pad in the Step Sequencer still takes them for velocity.
DEVICE_KNOB_TARGET = {"tracking": "c4", "sequencer": "c4", "mixing": "c4"}

# Cakewalk's own parameter offset: how far each C4 page button moves it.
C4_OFFSET_STEP = {c4.BANK_LEFT: -8, c4.BANK_RIGHT: 8, c4.PARAM_LEFT: -1, c4.PARAM_RIGHT: 1}

# C4 setup: LED state counts as known once the LEDs have been quiet this long;
# presses that get no LED answer are re-checked after the timeout.
C4_LED_QUIET_FRAMES = 3
C4_SETUP_TIMEOUT_FRAMES = 50
C4_SETUP_ATTEMPTS = 4
# A track select reaches Cakewalk on the main surface's cable; the C4 reset
# waits this long so its banner names the new track.
C4_RESET_DELAY_FRAMES = 3
# This many Device knobs on one bank within one frame = a Track Selection dump.
C4_DUMP_KNOBS = 3

# A plug-in whose first parameter is its on/off switch (ProChannel modules say
# "Enable", Cakewalk's own effects "Bypass"; the value reads On / Off): the
# Device knobs start at parameter 2 and Device On/Off presses it. Cakewalk's
# labels are cut to 6 characters.
C4_SWITCH_LABELS = frozenset({"enable", "enabld", "bypass", "on", "off", "on/off", "power", "active"})
C4_SWITCH_VALUES = frozenset({"on", "off"})
# Device On/Off after Cakewalk's offset moved: go to offset 0, press the
# switch, return. Each step waits this long for Cakewalk to rebind, and for its LCD to
# go quiet; a step gives up after the timeout.
C4_HOP_SETTLE_FRAMES = 5
C4_HOP_QUIET_FRAMES = 3
C4_HOP_TIMEOUT_FRAMES = 40

# Cakewalk navigation-mode LEDs (none lit = normal navigation).
NAV_LEDS = {
    mcu.NOTE_CW_MARKER: "marker",
    mcu.NOTE_CW_LOOP_NAV: "loop",
    mcu.NOTE_CW_SELECT_NAV: "select",
    mcu.NOTE_CW_PUNCH_NAV: "punch",
}

TOAST_HISTORY = 8


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
        link_idle_frames: int = 250,
        peek_frames: int = 125,
        cue_step: tuple[int, str] = (1, "beat"),
        shift_cue_step: tuple[int, str] = (30, "tick"),
        nudge_step: tuple[int, str] = (1, "measure"),
        nudge_hold_frames: int = 20,
        nudge_repeat_frames: int = 8,
        shift_oneshot_frames: int = 150,
        shift_double_frames: int = 20,
        sequencer: sq.Sequencer | None = None,
        seq_indicator_frames: int = 25,
        seq_hold_frames: int = 50,
        seq_clock_frames: int = 75,
        seq_display_lead_ms: int = 40,
        c4_send: Callable[[Sequence[int]], None] | None = None,
        c4_knob_step_limit: int = 3,
        c4_reset_on_select: bool = True,
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
        # Playhead steps (count, unit) for Cue, Shift + Cue and Nudge; a held
        # Nudge repeats every nudge_repeat_frames after nudge_hold_frames.
        self.cue_step = cue_step
        self.shift_cue_step = shift_cue_step
        self.nudge_step = nudge_step
        self.nudge_hold_frames = max(1, nudge_hold_frames)
        self.nudge_repeat_frames = max(1, nudge_repeat_frames)
        self._nudge: dict | None = None  # the held Nudge button, if any
        self._jog_budget = JOG_BUDGET_PER_FRAME
        # HUD: Cakewalk counts as active while it sent feedback this recently,
        # and an LCD name change this soon after a V-pot turn is a value peek.
        self.link_idle_frames = link_idle_frames
        self.peek_frames = peek_frames

        self.knob_mode = "pan"
        self.mixer = True  # True: Track Control knobs drive the V-pots
        self.show_running = False
        # Shift (no LED on the APC40; the HUD shows it). Hold = shifted while
        # down; tap = one-shot for the next button press (expires after
        # shift_oneshot_frames); double-tap = locked until the next tap.
        self.shift_oneshot_frames = max(1, shift_oneshot_frames)
        self.shift_double_frames = max(1, shift_double_frames)
        self._shift_down = False
        self._shift_used = False  # a button was pressed while Shift was held
        self._shift_latch = "off"  # "off" / "once" / "locked"
        self._shift_tap_frame = 0
        self._shift_expire_frame = 0
        # Cakewalk's current assignment ("pan", "send", another, or None =
        # unknown) and Edit mode, both from its LEDs. Pressing the assignment
        # that is already active flips Cakewalk's knobs to single-track
        # (channel strip) layout, which it never reports, so the engine only
        # presses an assignment button when switching.
        self._cw_assign: str | None = None
        self._cw_edit = False
        self._cw_nav: str | None = None  # Cakewalk navigation mode, from its LEDs
        self._cw_buses = False  # strips show buses, from Cakewalk's Aux LED
        # Operating mode, selected with the Scene buttons; always Tracking at start.
        self.mode = "tracking"
        # Last loop LED state from Cakewalk, shown on the Metronome button.
        self._loop_led = apc.LED_OFF

        self._track_knob_abs: dict[int, int] = {}
        # Device knob positions per APC40 bank (channel 0-8): each bank keeps
        # its own positions, and a bank switch dumps that bank's values, so a
        # single shared baseline would read every switch as knob movement.
        self._device_knob_abs: dict[int, dict[int, int]] = {}
        # Current Device Control bank (channel 0-8), from the channel of the
        # latest Device knob or utility-row message. Device rings go here.
        self.device_bank = 0
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

        # HUD state: what Cakewalk reports (LEDs, LCD, 7-segments) and what
        # the engine did, kept for the on-screen display (hud_snapshot).
        self.lcd = mcu_display.LcdBuffer()
        self.seven_seg = mcu_display.SevenSeg()
        self._play_led = False
        self._record_led = False
        self._strip_leds = {key: [False] * tracks for _first, key, _note in STRIP_LEDS}
        self._last_mcu_frame: int | None = None
        self._toasts: deque[tuple[int, str]] = deque(maxlen=TOAST_HISTORY)
        self._toast_id = 0
        self._temp_message: str | None = None
        self._stable_names = [""] * tracks
        self._peek = [""] * tracks
        self._vpot_frame: list[int | None] = [None] * tracks
        self._selected_track: int | None = None
        self._selected_name = ""
        # Track number from Cakewalk's 'Track N: "name"' message, cleared by
        # a strip window move, and the strip this app last selected.
        self._pending_track: int | None = None
        self._select_press: tuple[int, int] | None = None  # (strip, frame)
        self.bank_offset: int | None = None
        self._bank_exact = False

        # Step sequencer (Scene 2); None when its output port is missing.
        # The grid shows one page of 5 lanes x 8 steps; the Clip Stop row is
        # the playhead, or briefly the page number after a page change.
        self.sequencer = sequencer
        self.seq_indicator_frames = max(1, seq_indicator_frames)
        self.seq_hold_frames = max(1, seq_hold_frames)  # hold a lit pad this long = off
        # Playing this long without a clock Start means Cakewalk sends no clock.
        self.seq_clock_frames = max(1, seq_clock_frames)
        self._seq_unclocked_since: int | None = None
        # Draw the playhead this far ahead of the clock (display delay).
        self.seq_display_lead_ms = max(0, seq_display_lead_ms)
        self._seq_step_page = 0
        self._seq_lane_page = 0
        self._seq_shown_step: int | None = None
        self._seq_indicator: tuple[str, int] | None = None  # (kind, page) on show
        self._seq_indicator_end = 0
        # Pads held down: (lane, step) -> the frame it was pressed, or None once
        # the hold did something (a Device knob set its velocity, or a long hold
        # turned it off), so its release no longer cycles the step.
        self._seq_held: dict[tuple[int, int], int | None] = {}
        self._seq_knob_abs: dict[int, int] = {}
        self.seq_status = ""  # last editor-visible message (e.g. the exported file)

        # Mackie Control C4 (plug-in control on the Device knobs); None when
        # its cable is missing. State: "off" (no handshake yet), "waiting"
        # (serial sent, setting up from its LEDs) or "ready".
        self._c4_send = c4_send
        self.c4_knob_step_limit = max(1, c4_knob_step_limit)
        self.c4_reset_on_select = c4_reset_on_select
        self.c4_state = "off"
        self.c4_display = c4.C4Display()
        self._c4_leds: dict[int, bool] = {}
        self._c4_led_frame: int | None = None  # last LED message
        self._c4_wait_since = 0  # handshake or last setup presses
        self._c4_attempts = 0
        self._c4_rings: list[int | None] = [None] * c4.VPOTS  # ring bytes of all 32 V-pots
        self._c4_rings_pending = False  # re-render once a bank dump is over
        self._c4_reset_at: int | None = None
        self._c4_wrap_pending = False  # a Next plug-in press may run past the last
        self._c4_knob_queue: list[tuple[int, int, int]] = []  # (bank, knob, value) this frame
        self._c4_dump_until = 0  # Device knob readings only set baselines until then
        self._c4_start: int | None = None  # V-pot under Device knob 1; None = first parameters
        self._c4_shown_window = 0  # the window the rings were drawn for
        self._c4_lcd_frame = 0  # last LCD write
        self._c4_page_moves: list[int] = []  # C4 offset buttons since offset 0, to return there
        self._c4_hop: dict | None = None  # Device On/Off in progress

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
        # drive the plug-in on the C4 (or the V-pots in device mode).
        if apc.CC_DEVICE_KNOB1 <= cc < apc.CC_DEVICE_KNOB1 + self.tracks:
            if channel < apc.DEVICE_BANKS:
                self._set_device_bank(channel)
                knob = cc - apc.CC_DEVICE_KNOB1 + 1
                if self._seq_held and self.mode == "sequencer":
                    self._seq_knob(knob, value)
                    return
                self._knob_dump.setdefault(channel, set()).add(cc)
                self._knob_dump_frame = self._frame
                if self._device_knobs_to_c4():
                    self._c4_knob_queue.append((channel, knob, value))  # see _c4_knobs
                elif not self.mixer:
                    self._relative_knob(self._device_knob_abs.setdefault(channel, {}), knob, value)
            return

        # Cue Level (relative, channel not significant) -> jog: moves the now
        # time by Cakewalk's Jog Wheel Resolution per step.
        # Crossfader (absolute, channel not significant) -> horizontal zoom.
        if cc == apc.CC_CROSSFADER:
            self._on_crossfader(value)
            return

        if cc == apc.CC_CUE_LEVEL:
            delta = value - 128 if value > 63 else value
            if delta:
                step = self.shift_cue_step if self.knob_shift else self.cue_step
                self._move_playhead(delta > 0, step, min(abs(delta), CUE_JOG_STEP_LIMIT))
            return

        if channel != 0:
            return

        # Track Control knobs (absolute) -> relative V-pot delta, mix mode only.
        if apc.CC_TRACK_KNOB1 <= cc < apc.CC_TRACK_KNOB1 + self.tracks and self.mixer:
            self._relative_knob(self._track_knob_abs, cc - apc.CC_TRACK_KNOB1 + 1, value)

    def _relative_knob(self, store: dict[int, int], index: int, value7: int) -> None:
        delta = self._knob_delta(store, index, value7, self.knob_step_limit)
        if delta:
            self._send_mcu(mcu.vpot_delta(index, delta))
            if index <= self.tracks:
                self._vpot_frame[index - 1] = self._frame

    def _knob_delta(self, store: dict[int, int], index: int, value7: int, limit: int) -> int:
        """Steps an absolute APC40 knob reading moved since the last one (0 = none)."""

        previous = store.get(index)
        store[index] = value7
        if previous is None:
            return 0

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
            return 0
        return max(-limit, min(limit, delta))

    def on_apc_note(self, channel: int, note: int, velocity: int) -> None:
        pressed = velocity > 0
        per_track_end = apc.NOTE_CLIP_ROW1 + self.rows - 1
        if note in APC_LATCHING_UTILITY and channel < apc.DEVICE_BANKS:
            pressed = True  # both edges of a latching button are one press

        if note == apc.NOTE_SHIFT:
            self._on_shift(pressed)
            return
        # Every button press takes the Shift state; a one-shot is used up by
        # the press whatever the button (even one without a Shift function).
        shifted = self._take_shift() if pressed else False

        # Per-track controls arrive on channels 0-7.
        if channel < self.tracks and apc.NOTE_RECORD_ARM <= note <= per_track_end:
            if self.mode == "sequencer":
                if note >= apc.NOTE_CLIP_ROW1:
                    self._seq_pad(channel, note - apc.NOTE_CLIP_ROW1, pressed)
                    return
                if note == apc.NOTE_CLIP_STOP:
                    return  # the playhead row is a display here
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
                    self._select_strip(channel)
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
            self._set_device_bank(channel)
            channel = 0

        # Other global controls are always on channel 0, which Track 1 also
        # uses, so this must run after the per-track branch above.
        if channel != 0:
            return

        # The Rec Quantize button (Loop on/off) is momentary: the APC40 switches
        # its own LED off on release, which can land after Cakewalk's loop LED
        # update (during playback Cakewalk refreshes fast enough to beat the
        # finger). Re-assert the loop state on every release. Scene LEDs (the
        # mode) likewise.
        if note == apc.NOTE_UTIL_REC_QUANT and not pressed:
            self.apc.global_note(apc.NOTE_UTIL_REC_QUANT, self._loop_led, force=True)
            return
        if note in apc.SCENE_NOTES and not pressed:
            self._render_mode_leds()
            return

        # Mode-dependent utility row (Tracking: editing, markers, selection).
        if pressed and self._on_mode_button(note, shifted):
            return

        if self.mode == "sequencer" and note in SEQ_PAGE_MOVES:
            if pressed:
                self._seq_page(*SEQ_PAGE_MOVES[note])
                self._flash_global(note)
            return

        # Shift layer: mapped combos replace the button's normal action;
        # unmapped ones fall through unchanged.
        if shifted:
            if note == apc.NOTE_UTIL_DETAIL_VIEW:
                self.toggle_cakewalk_meters()
                return
            if note in APC_NUDGE_FORWARD:
                self._set_selection_edge(APC_NUDGE_FORWARD[note])
                return
            shifted = APC_SHIFT_BUTTONS.get(note)
            if shifted is not None:
                self._mcu_click(shifted)
                self._after_press(shifted)
                if note in APC_FLASH_ON_PRESS:
                    self._flash_global(note)
                return

        if note == apc.NOTE_STOP and pressed:
            self._on_stop_press()
            return

        # Nudge: one step per press, repeating while held (see tick()).
        if note in APC_NUDGE_FORWARD:
            if pressed:
                forward = APC_NUDGE_FORWARD[note]
                self._move_playhead(forward, self.nudge_step)
                self._nudge = {"forward": forward, "next": self._frame + self.nudge_hold_frames}
            else:
                self._nudge = None
            return

        mcu_note = APC_GLOBAL_BUTTONS.get(note)
        if mcu_note is not None:
            if pressed:
                self._mcu_click(mcu_note)
                self._after_press(mcu_note)
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
            self.toast("Stop all")
        elif note == apc.NOTE_PAN:
            self.set_knob_mode("pan")
        elif note == apc.NOTE_SEND_A:
            self.set_knob_mode("send_a")
        elif note == apc.NOTE_SEND_B:
            self.set_knob_mode("send_b")
        elif note == apc.NOTE_SEND_C:
            self.set_knob_mode("send_c")
        elif note in SCENE_MODE:
            self.set_mode(SCENE_MODE[note])
        elif note in apc.SCENE_NOTES:
            self._render_mode_leds()  # Scenes 4-5: free
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
            self.toast("Zoom: fit project")
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
        if len(ccs) != self.tracks:
            return
        if channel < self.tracks:
            self._select_strip(channel)
        elif channel == apc.DEVICE_BANKS - 1:  # Master sends no note, only this dump
            self.toggle_strip_type()

    def _select_strip(self, strip: int) -> None:
        self._mcu_click(APC_TRACK_SELECT_NOTE + strip)
        self._select_press = (strip, self._frame)
        self._c4_schedule_reset()

    def _after_press(self, mcu_note: int) -> None:
        """HUD bookkeeping for a surface button this app just pressed."""

        move = BANK_MOVES.get(mcu_note)
        if move is not None:
            delta, label = move
            self.toast(label)
            self._pending_track = None
            if self.bank_offset is not None:
                self.bank_offset = max(0, self.bank_offset + delta)
                self._bank_exact = False
            return
        text = PRESS_TOASTS.get(mcu_note)
        if text is not None:
            self.toast(text)

    # ------------------------------------------------------------------
    # Shift
    # ------------------------------------------------------------------

    @property
    def shift_state(self) -> str:
        """``off`` / ``held`` / ``once`` / ``locked`` (held wins while down)."""

        return "held" if self._shift_down else self._shift_latch

    @property
    def shift(self) -> bool:
        """True when the next button press is shifted."""

        return self.shift_state != "off"

    @property
    def knob_shift(self) -> bool:
        """Shift for knobs and faders: only held or locked, never a one-shot."""

        return self._shift_down or self._shift_latch == "locked"

    def _on_shift(self, pressed: bool) -> None:
        if pressed:
            self._shift_down = True
            self._shift_used = False
            return
        self._shift_down = False
        if self._shift_used:
            return  # it was held for a combo, not tapped
        # A tap: off -> one-shot, quick second tap -> locked, otherwise off.
        if self._shift_latch == "once" and self._frame - self._shift_tap_frame <= self.shift_double_frames:
            self._shift_latch = "locked"
        elif self._shift_latch == "off":
            self._shift_latch = "once"
            self._shift_tap_frame = self._frame
            self._shift_expire_frame = self._frame + self.shift_oneshot_frames
        else:
            self._shift_latch = "off"

    def _take_shift(self) -> bool:
        """Shift state for one button press; uses up a one-shot."""

        if self._shift_down:
            self._shift_used = True
            return True
        if self._shift_latch == "once":
            self._shift_latch = "off"
            return True
        return self._shift_latch == "locked"

    def _expire_shift(self) -> None:
        if self._shift_latch == "once" and self._frame >= self._shift_expire_frame:
            self._shift_latch = "off"

    def _move_playhead(self, forward: bool, step: tuple[int, str], times: int = 1) -> None:
        """Move Cakewalk's now time by *times* x *step* (count, unit)."""

        count, unit = step
        total = min(count * times, self._jog_budget)
        if total <= 0:
            return  # this frame's budget is spent: drop the step
        self._jog_budget -= total
        modifier = JOG_UNIT_MODIFIER[unit]
        if modifier is not None:
            self._send_mcu(mcu.button_press(modifier))
        for _ in range(total):
            self._send_mcu(mcu.jog(forward))
        if modifier is not None:
            self._send_mcu(mcu.cakewalk_release(modifier))

    def _repeat_nudge(self) -> None:
        nudge = self._nudge
        if nudge is None or self._frame < nudge["next"]:
            return
        self._move_playhead(nudge["forward"], self.nudge_step)
        nudge["next"] = self._frame + self.nudge_repeat_frames

    # ------------------------------------------------------------------
    # Modes and the Tracking utility row
    # ------------------------------------------------------------------

    def set_mode(self, mode: str) -> None:
        """Select the operating mode (Scene 1 / 2 / 3)."""

        if mode == "sequencer" and self.sequencer is None:
            self.toast("Step sequencer: SEQ_OUT_PORT unavailable")
            self._render_mode_leds()
            return
        previous, self.mode = self.mode, mode
        self._render_mode_leds()
        self.toast(MODE_TOASTS[mode])
        if mode == "sequencer" and previous != "sequencer":
            self._render_seq(force=True)
        elif previous == "sequencer" and mode != "sequencer":
            self._seq_held.clear()
            self._render_grid_meters()
        self._render_c4_rings(force=True)

    def _render_mode_leds(self) -> None:
        lit = MODE_SCENE[self.mode]
        for note in apc.SCENE_NOTES:
            self.apc.global_note(note, apc.LED_ON if note == lit else apc.LED_OFF, force=True)

    def _on_mode_button(self, note: int, shifted: bool) -> bool:
        """Handle a mode-dependent utility-row press. True when handled."""

        if note in APC_LATCHING_UTILITY:
            self.apc.global_note(note, apc.LED_OFF, force=True)  # undo the local latch
        if note in TRACKING_ONLY and self.mode != "tracking":
            if self.mode == "mixing":
                self._on_c4_button(note, shifted)
            return True
        if note == apc.NOTE_UTIL_CLIP_TRACK:
            self._mcu_click(mcu.NOTE_CW_REDO if shifted else mcu.NOTE_CW_UNDO)
            self.toast("Redo" if shifted else "Undo")
        elif note == apc.NOTE_UTIL_DEVICE_ONOFF:
            if not shifted:
                self._with_modifier(mcu.NOTE_M1, mcu.NOTE_CW_MARKER)
                self.toast("Marker inserted")
        elif note in (apc.NOTE_UTIL_LEFT_ARROW, apc.NOTE_UTIL_RIGHT_ARROW):
            forward = note == apc.NOTE_UTIL_RIGHT_ARROW
            button = mcu.NOTE_FORWARD if forward else mcu.NOTE_REWIND
            if shifted:
                self._in_navigation(mcu.NOTE_CW_SELECT_NAV, lambda: self._mcu_click(button))
                self.toast("Go to selection end" if forward else "Go to selection start")
            else:
                self._in_navigation(mcu.NOTE_CW_MARKER, lambda: self._mcu_click(button))
                self.toast("Next marker" if forward else "Previous marker")
        elif note == apc.NOTE_UTIL_DETAIL_VIEW and not shifted:
            self._with_modifier(mcu.NOTE_M2, mcu.NOTE_CW_LOOP_NAV)
            self.toast("Loop <- selection")
        elif note == apc.NOTE_UTIL_OVERDUB:
            if not shifted:
                self._with_modifier(mcu.NOTE_M2, mcu.NOTE_CW_PUNCH_NAV)
                self.toast("Punch <- selection")
        else:
            return False
        return True

    def _with_modifier(self, modifier: int, note: int) -> None:
        """Press *note* while holding a Mackie modifier (M1-M4)."""

        self._send_mcu(mcu.button_press(modifier))
        self._mcu_click(note)
        self._send_mcu(mcu.cakewalk_release(modifier))

    def _in_navigation(self, nav_note: int, action: Callable[[], None]) -> None:
        """Run *action* in a Cakewalk navigation mode, then return to normal.

        Pressing a navigation button enters that mode, or leaves it (back to
        normal) when it is already active. The mode follows Cakewalk's LEDs.
        """

        target = next(name for n, name in NAV_LEDS.items() if n == nav_note)
        if self._cw_nav != target:
            self._mcu_click(nav_note)
        action()
        self._mcu_click(nav_note)  # active mode pressed again -> normal
        self._cw_nav = None

    def _set_selection_edge(self, end: bool) -> None:
        """Selection start (end) = playhead: Select navigation + M1 + Rew (FF)."""

        button = mcu.NOTE_FORWARD if end else mcu.NOTE_REWIND
        self._in_navigation(mcu.NOTE_CW_SELECT_NAV, lambda: self._with_modifier(mcu.NOTE_M1, button))
        self.toast("Selection end = playhead" if end else "Selection start = playhead")

    def toggle_strip_type(self) -> None:
        """Master: switch the 8 strips between tracks and buses."""

        if self._cw_buses:
            self._mcu_click(mcu.NOTE_CW_TRACK)
            self._cw_buses = False
            self.toast("Tracks")
        else:
            self._mcu_click(mcu.NOTE_CW_AUX)
            self._cw_buses = True
            self.toast("Buses")
        self._c4_schedule_reset()  # the C4 follows: plug-ins of a bus or a track

    def _on_stop_press(self) -> None:
        """Stop; a second press soon after also goes to the start (MCU Home)."""

        self._mcu_click(mcu.NOTE_STOP)
        last = self._last_stop_frame
        if last is not None and self._frame - last <= self.stop_double_frames:
            self._mcu_click(mcu.NOTE_CW_HOME)
            self._last_stop_frame = None  # a third press starts a new pair
            self.toast("Go to start")
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
        self.toast(hud_state.KNOB_MODE_TOASTS[mode])
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
        self._last_mcu_frame = self._frame
        if decoded.kind in ("note_on", "note_off"):
            velocity = decoded.value if decoded.kind == "note_on" else 0
            self.on_mcu_note(decoded.number, velocity)
        elif decoded.kind == "cc":
            self.on_mcu_cc(decoded.number, decoded.value)
        elif decoded.kind == "pitch_bend":
            self.on_mcu_pitch(decoded.channel, decoded.value)
        elif decoded.kind == "pressure":
            self.on_mcu_meter(decoded.value)
        elif decoded.kind == "sysex":
            self.on_mcu_sysex(decoded.raw)

    def on_mcu_note(self, note: int, velocity: int) -> None:
        """Render an MCU LED note onto the APC40. Feedback is authoritative."""

        state = mcu.led_state(velocity)
        on = apc.LED_ON if state != "off" else apc.LED_OFF

        for first, key, apc_note in STRIP_LEDS:
            if first <= note < first + self.tracks:
                strip = note - first
                self._strip_leds[key][strip] = state != "off"
                self.apc.strip_led(strip, apc_note, on, force=True)
                if key == "select":
                    self._on_select_led()
                return

        if note == mcu.NOTE_PLAY:
            self._play_led = state != "off"
            self.apc.global_note(apc.NOTE_PLAY, on, force=True)
        elif note == mcu.NOTE_STOP:
            self.apc.global_note(apc.NOTE_STOP, on, force=True)
        elif note == mcu.NOTE_RECORD:
            self._record_led = state != "off"
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
            self.apc.global_note(apc.NOTE_UTIL_REC_QUANT, on, force=True)
        elif note in NAV_LEDS:
            if state != "off":
                self._cw_nav = NAV_LEDS[note]
            elif self._cw_nav == NAV_LEDS[note]:
                self._cw_nav = None
        elif note == mcu.NOTE_CW_AUX:
            self._cw_buses = state != "off"
        elif note == mcu.NOTE_CW_TRACK and state != "off":
            self._cw_buses = False

    def on_mcu_cc(self, cc: int, value: int) -> None:
        if self.seven_seg.apply(cc, value):
            return  # timecode / assignment display, HUD only
        if not (mcu.CC_RING1 <= cc < mcu.CC_RING1 + self.tracks):
            return

        index = cc - mcu.CC_RING1 + 1
        ring = mcu.decode_ring(value)
        position = mcu.ring_value_to_position(ring.value)

        if self.mixer:
            self.apc.ring_position(apc.track_ring_cc(index), position)
        else:
            bank = self.device_bank
            self.apc.ring_position(apc.device_ring_cc(index), position, channel=bank)
            self.apc.ring_style(
                apc.device_ring_style_cc(index),
                RING_STYLE_FROM_MCU[ring.mode],
                channel=bank,
                force=True,
            )

    def on_mcu_pitch(self, channel: int, value: int) -> None:
        """Fader feedback is intentionally ignored: APC40 faders are not motorized."""

        return

    # ------------------------------------------------------------------
    # MCU LCD (HUD only)
    # ------------------------------------------------------------------

    def on_mcu_sysex(self, raw: Sequence[int]) -> None:
        """Apply Cakewalk's LCD text; other SysEx is ignored."""

        if not self.lcd.apply(raw):
            return
        message = self.lcd.temp_message()
        if message != self._temp_message:
            self._temp_message = message
            if message is not None:
                self._on_temp_message(message)
        if message is None:
            self._update_strip_names()

    def _on_temp_message(self, message: str) -> None:
        """Cakewalk's centered upper-line message, e.g. 'Track 5: "Vocals"'."""

        self.toast(message)
        parsed = mcu_display.parse_track_message(message)
        if parsed is None or parsed[0] != "Track":
            return
        _kind, number, name = parsed
        self._selected_track = number
        self._selected_name = name
        self._pending_track = number
        self._derive_bank()

    def _update_strip_names(self, *, expire: bool = False) -> None:
        """Track the upper-line names, telling a V-pot value peek from a name.

        Turning a V-pot makes Cakewalk show the value in that strip's name
        cell for about a second. A cell change shortly after this app turned
        that V-pot is a peek; any other change is a new name. *expire*
        re-evaluates only the peeks, once their window has passed.
        """

        for strip in range(self.tracks):
            text = self.lcd.cell(0, strip)
            if text == self._stable_names[strip]:
                self._peek[strip] = ""
                continue
            if expire and not self._peek[strip]:
                continue
            turned = self._vpot_frame[strip]
            if turned is not None and self._frame - turned <= self.peek_frames:
                self._peek[strip] = text
            else:
                self._stable_names[strip] = text
                self._peek[strip] = ""

    def _selected_strip(self) -> int | None:
        """The strip whose Select LED is the only one lit, else None."""

        lit = [i for i, on in enumerate(self._strip_leds["select"]) if on]
        return lit[0] if len(lit) == 1 else None

    def _on_select_led(self) -> None:
        strip = self._selected_strip()
        if strip is None:
            return
        if self.bank_offset is not None:
            self._selected_track = self.bank_offset + strip + 1
        self._selected_name = self._stable_names[strip]
        self._derive_bank()

    def _derive_bank(self) -> None:
        """Strip window offset = track number - 1 - strip, from a track select.

        Cakewalk never reports the offset, but a surface select lights the
        strip's Select LED and shows 'Track N: "name"'. The strip this app
        just pressed is preferred; otherwise a single lit Select LED.
        """

        number = self._pending_track
        if number is None:
            return
        strip = None
        press = self._select_press
        if press is not None and self._frame - press[1] <= self.peek_frames:
            strip = press[0]
        if strip is None:
            strip = self._selected_strip()
        if strip is None:
            return
        self.bank_offset = max(0, number - 1 - strip)
        self._bank_exact = True
        self._pending_track = None

    # ------------------------------------------------------------------
    # Mackie Control C4: plug-in parameters on the Device knobs
    # ------------------------------------------------------------------
    #
    # Cakewalk drops note 0, so the C4's Split button cannot be pressed and the
    # C4 stays unsplit: its 32 V-pots are parameters offset+0 ... offset+31 of
    # the selected strip's plug-in (V-pot n = row n // 8, column n % 8). The 8
    # Device knobs are a window onto those 32 that the app pages itself; only
    # past the 32nd parameter does it move Cakewalk's own offset.

    def _send_c4(self, messages: Sequence[Sequence[int]]) -> None:
        if self._c4_send is not None:
            for message in messages:
                self._c4_send(message)

    def c4_connect(self) -> None:
        """Start the C4 handshake: Wake-up (Cakewalk forgets an old serial),
        then the serial reply. Cakewalk answers with a full refresh."""

        if self._c4_send is None:
            return
        self._send_c4([c4.wake_up(), c4.serial_reply()])
        self._c4_wait()

    def _c4_wait(self) -> None:
        self.c4_state = "waiting"
        self._c4_leds.clear()
        self._c4_led_frame = None
        self._c4_wait_since = self._frame
        self._c4_attempts = 0

    def _device_knobs_to_c4(self) -> bool:
        return self.c4_state == "ready" and DEVICE_KNOB_TARGET.get(self.mode) == "c4"

    def _set_device_bank(self, channel: int) -> None:
        """Track the APC40's Device Control bank (0-8).

        A bank switch dumps the new bank's eight knob positions; those only
        set baselines (never turns), and the C4 rings are redrawn on the new
        bank once the dump is over.
        """

        if channel == self.device_bank:
            return
        self.device_bank = channel
        self._device_knob_abs.pop(channel, None)
        self._c4_rings_pending = True

    def on_c4_message(self, message: Sequence[int]) -> None:
        """Cakewalk's C4 output: the serial query, LEDs, rings and LCD text."""

        raw = tuple(message)
        if len(raw) < 2:
            return
        if raw[0] == 0xF0:
            if c4.is_serial_query(raw):
                self._send_c4([c4.serial_reply()])
                if self.c4_state != "waiting":
                    log.info("C4: Cakewalk asked for the serial; setting up again")
                    self._c4_wait()
                return
            parsed = c4.parse_lcd(raw)
            if parsed is not None:
                row, offset, text = parsed
                banner = self.c4_display.apply(offset, text, row)
                self._c4_lcd_frame = self._frame
                if banner is not None:
                    self._on_c4_banner()
                window = self._c4_window()
                if window != self._c4_shown_window:
                    self._render_c4_rings(force=True)  # the switch appeared or went
            return
        if len(raw) < 3:
            return
        status = raw[0] & 0xF0
        if status == 0x90:
            on = raw[2] != 0
            was = self._c4_leds.get(raw[1])
            if self.c4_state == "waiting":
                log.info("C4 LED %02X %s", raw[1], "on" if on else "off")
            self._c4_leds[raw[1]] = on
            self._c4_led_frame = self._frame
            if raw[1] in (c4.TRACK, c4.FUNCTION) and was and not on:
                self._render_c4_rings(force=True)
        elif status == 0xB0 and c4.CC_RING1 <= raw[1] < c4.CC_RING1 + c4.VPOTS:
            vpot = raw[1] - c4.CC_RING1
            self._c4_rings[vpot] = raw[2]
            knob = vpot - self._c4_window()
            if 0 <= knob < self.tracks:
                self._render_c4_ring(knob)

    def _c4_knobs(self) -> None:
        """Turn this frame's Device knob readings into C4 V-pot turns.

        Track Selection makes the APC40 send all eight positions at once, also
        for the bank already selected, and those can differ a little from the
        last readings (ring writes re-reference the knobs). A frame with several
        knobs on one bank is such a dump: it only sets baselines, as does
        anything shortly after it. Two hands never turn three knobs in 20 ms.
        """

        queue, self._c4_knob_queue = self._c4_knob_queue, []
        if not queue:
            return
        counts: dict[int, set[int]] = {}
        for bank, knob, _value in queue:
            counts.setdefault(bank, set()).add(knob)
        if any(len(knobs) >= C4_DUMP_KNOBS for knobs in counts.values()):
            self._c4_dump_until = self._frame + KNOB_DUMP_QUIET_FRAMES
        dump = self._frame < self._c4_dump_until
        for bank, knob, value in queue:
            store = self._device_knob_abs.setdefault(bank, {})
            if dump:
                store[knob] = value
                continue
            delta = self._knob_delta(store, knob, value, self.c4_knob_step_limit)
            vpot = self._c4_window() + knob - 1
            if delta and vpot < c4.VPOTS and self.c4_state == "ready" and self._c4_hop is None:
                self._c4_send(c4.vpot_delta(vpot // c4.COLS, vpot % c4.COLS, delta))

    def _c4_tick(self) -> None:
        self._c4_knobs()
        if self._c4_hop is not None:
            self._c4_hop_step()
        if self.c4_state == "waiting":
            led = self._c4_led_frame
            if led is not None and (
                (led >= self._c4_wait_since and self._frame - led >= C4_LED_QUIET_FRAMES)
                or self._frame - self._c4_wait_since >= C4_SETUP_TIMEOUT_FRAMES
            ):
                self._c4_setup_step()
        if self._c4_reset_at is not None and self._frame >= self._c4_reset_at:
            self._c4_reset_at = None
            self._c4_reset()
        if self._c4_rings_pending and self._frame - self._knob_dump_frame >= KNOB_DUMP_QUIET_FRAMES:
            self._c4_rings_pending = False
            self._render_c4_rings(force=True)

    def _c4_setup_step(self) -> None:
        """Bring the C4 to channel-strip mode with assignment Plugin.

        Its mode buttons toggle, so each press is decided from the LED state
        and confirmed by the next LED update before more presses.
        """

        leds = self._c4_leds
        presses: list[tuple[int, int, int]] = []
        if leds.get(c4.TRACK):
            presses.append(c4.button_release(c4.TRACK))
        if leds.get(c4.FUNCTION):
            presses += c4.click(c4.FUNCTION)
        if not presses and not leds.get(c4.CHANNEL_STRIP):
            presses += c4.click(c4.CHANNEL_STRIP)
        lit = sorted(led for led, on in leds.items() if on)
        pressed = [f"{m[1]:02X}" for m in presses if m[2]]
        if presses and self._c4_attempts < C4_SETUP_ATTEMPTS:
            self._c4_attempts += 1
            log.info("C4 setup: LEDs lit %s; pressing %s", lit, pressed)
            self._send_c4(presses)
            self._c4_wait_since = self._frame
            return
        if presses:
            log.warning("C4: its LEDs did not confirm the setup (lit %s, still needs %s); continuing anyway",
                        lit, pressed)
        self._send_c4(c4.assign_plugin_macro())
        self.c4_state = "ready"
        self._c4_reset()
        self._render_c4_rings(force=True)
        self.toast("Plug-in control ready")
        log.info("C4 ready: Device knobs control the selected track's plug-in")

    def _c4_schedule_reset(self) -> None:
        if self.c4_state == "ready" and self.c4_reset_on_select:
            self._c4_reset_at = self._frame + C4_RESET_DELAY_FRAMES

    def _c4_reset(self) -> None:
        """First plug-in, first parameters (M1 + Slot Down / Bank Left).

        The plug-in slot and Cakewalk's parameter offset are not per track,
        so a track with fewer plug-ins would otherwise leave the knobs on
        nothing. The Slot Down also makes Cakewalk show the track and plug-in
        banner.
        """

        if self.c4_state == "ready":
            self._send_c4(c4.with_shift([c4.SLOT_DOWN, c4.BANK_LEFT]))
            self._c4_first_page()

    def _c4_first_page(self) -> None:
        self._c4_start = None
        self._c4_page_moves.clear()

    # -- the knob window ---------------------------------------------------

    def _c4_window(self) -> int:
        """The V-pot (0-24) under Device knob 1."""

        if self._c4_start is not None:
            return self._c4_start
        return 1 if self._c4_switch_shown() else 0

    def _c4_offset(self) -> int:
        """Parameters Cakewalk's own offset was moved by (an upper bound: it clamps)."""

        return sum(C4_OFFSET_STEP[button] for button in self._c4_page_moves)

    def _c4_has_params(self, first: int) -> bool:
        display = self.c4_display
        return any(display.label(v) or display.value(v) for v in range(first, min(first + self.tracks, c4.VPOTS)))

    def _c4_page(self, step: int) -> None:
        """Mixing < / >: move the knob window by *step* (+/-8, or +/-1 with Shift).

        Inside the 32 bound V-pots the app only moves its window. Past them it
        moves Cakewalk's offset (Bank / Param Left / Right), for big plug-ins.
        """

        window = self._c4_window()
        last = c4.VPOTS - self.tracks
        floor = 0 if abs(step) == 1 else min(window, 1 if self._c4_switch_shown() else 0)
        if step > 0:
            if window < last:
                target = min(window + step, last)
                if not self._c4_has_params(target + self.tracks - 1 if step == 1 else target):
                    self.toast("No more parameters")
                    return
                self._c4_start = target
            elif self.c4_display.label(c4.VPOTS - 1) or self.c4_display.value(c4.VPOTS - 1):
                button = c4.BANK_RIGHT if step > 1 else c4.PARAM_RIGHT
                self._send_c4(c4.click(button))
                self._c4_page_moves.append(button)
                self._c4_start = window
            else:
                self.toast("No more parameters")
                return
        else:
            if window > floor:
                self._c4_start = max(window + step, floor)
            elif self._c4_page_moves:
                button = c4.BANK_LEFT if step < -1 else c4.PARAM_LEFT
                self._send_c4(c4.click(button))
                self._c4_page_moves.append(button)
                if self._c4_offset() <= 0:
                    self._c4_page_moves.clear()
                self._c4_start = window
            else:
                self.toast("First parameters")
                return
        self._render_c4_rings(force=True)
        first = self._c4_offset() + self._c4_window() + 1
        self.toast(f"Parameters {first}-{first + self.tracks - 1}")

    # -- buttons and banner ------------------------------------------------

    def _on_c4_button(self, note: int, shifted: bool) -> None:
        """Mixing utility row: 58 plug-in, 59 on/off, 60/61 parameters (Shift: by one)."""

        if self.c4_state != "ready":
            self.toast("Plug-in control: no C4 surface")
            return
        if self._c4_hop is not None:
            return  # Device On/Off is still moving Cakewalk's offset
        self._flash_global(note)
        if note == apc.NOTE_UTIL_DEVICE_ONOFF:
            self._c4_toggle_switch()
        elif note == apc.NOTE_UTIL_CLIP_TRACK:
            # A new plug-in starts on its first parameters.
            button = c4.SLOT_DOWN if shifted else c4.SLOT_UP
            self._send_c4(c4.click(button) + c4.with_shift([c4.BANK_LEFT]))
            self._c4_first_page()
            self._c4_wrap_pending = button == c4.SLOT_UP
            self.toast("Previous plug-in" if shifted else "Next plug-in")
        elif note in (apc.NOTE_UTIL_LEFT_ARROW, apc.NOTE_UTIL_RIGHT_ARROW):
            size = 1 if shifted else self.tracks
            self._c4_page(size if note == apc.NOTE_UTIL_RIGHT_ARROW else -size)

    def _on_c4_banner(self) -> None:
        """Cakewalk named the track and plug-in; past the last plug-in, wrap to the first."""

        display = self.c4_display
        if display.plugin is None and self._c4_wrap_pending:
            self._c4_wrap_pending = False
            self._c4_reset()
            return
        self._c4_wrap_pending = False
        # No toast: the HUD's plug-in line already shows this.
        log.info("C4: %s, FX %s: %s", display.strip, display.slot, display.plugin or "no plug-in")

    # -- rings -------------------------------------------------------------

    def _c4_rings_shown(self) -> bool:
        """C4 rings own the Device rings (not in its Track/Function modes or a velocity hold)."""

        if self.c4_state != "ready" or DEVICE_KNOB_TARGET.get(self.mode) != "c4":
            return False
        if self._c4_leds.get(c4.TRACK) or self._c4_leds.get(c4.FUNCTION):
            return False
        return not (self._seq_held and self.mode == "sequencer")

    def _render_c4_rings(self, *, force: bool = False) -> None:
        self._c4_shown_window = self._c4_window()
        for knob in range(self.tracks):
            self._render_c4_ring(knob, force=force)

    def _render_c4_ring(self, knob: int, *, force: bool = False) -> None:
        """Device ring *knob* (0-7) from the V-pot it controls (off: none)."""

        vpot = self._c4_window() + knob
        value = self._c4_rings[vpot] if vpot < c4.VPOTS else 0
        if value is None or not self._c4_rings_shown():
            return
        ring = mcu.decode_ring(value)
        style = apc.RING_OFF if value == 0 else RING_STYLE_FROM_MCU[ring.mode]
        bank = self.device_bank
        self.apc.ring_style(apc.device_ring_style_cc(knob + 1), style, channel=bank, force=force)
        position = mcu.ring_value_to_position(ring.value)
        self.apc.ring_position(apc.device_ring_cc(knob + 1), position, channel=bank, force=force)

    # -- the plug-in's on/off switch ---------------------------------------

    def _c4_switch_shown(self) -> bool:
        """The plug-in's first parameter is an on/off switch (by name, or an On / Off value).

        Only known while Cakewalk's offset is 0 (V-pot 1 = parameter 1).
        """

        if self._c4_page_moves:
            return False
        display = self.c4_display
        return display.label(0).lower() in C4_SWITCH_LABELS or display.value(0).lower() in C4_SWITCH_VALUES

    def c4_params(self) -> tuple[tuple[str, ...], tuple[str, ...]]:
        """Names and values of what the 8 Device knobs control, for the HUD."""

        display = self.c4_display
        vpots = [self._c4_window() + k for k in range(self.tracks)]
        return (tuple(display.label(v) if v < c4.VPOTS else "" for v in vpots),
                tuple(display.value(v) if v < c4.VPOTS else "" for v in vpots))

    def c4_switch_text(self) -> str:
        """'Bypass: Off' when the plug-in has an on/off switch, else ''."""

        if not self._c4_switch_shown():
            return ""
        return f"{self.c4_display.label(0) or 'On/off'}: {self.c4_display.value(0)}"

    def _c4_toggle_switch(self) -> None:
        """Device On/Off: push V-pot 1 (parameter 1, the plug-in's on/off switch).

        If Cakewalk's offset was moved (a plug-in with over 32 parameters), go
        back to offset 0 first, push, and replay the moves. Knob turns wait.
        """

        moves = list(self._c4_page_moves)
        if not moves:
            if not self._c4_switch_shown():
                self.toast("This plug-in has no on/off switch")
                return
            self._send_c4(c4.click(c4.VPOT_PUSH1))
            self._c4_hop = {"stage": "pushed", "sent": self._frame, "moves": []}
            return
        self._send_c4(c4.with_shift([c4.BANK_LEFT]))
        self._c4_page_moves.clear()
        self._c4_hop = {"stage": "first", "sent": self._frame, "moves": moves}

    def _c4_hop_step(self) -> None:
        hop = self._c4_hop
        waited = self._frame - hop["sent"]
        settled = waited >= C4_HOP_SETTLE_FRAMES and self._frame - self._c4_lcd_frame >= C4_HOP_QUIET_FRAMES
        if not settled and waited < C4_HOP_TIMEOUT_FRAMES:
            return
        stage = hop["stage"]
        if stage == "first":
            if self._c4_switch_shown():
                self._send_c4(c4.click(c4.VPOT_PUSH1))
                hop.update(stage="pushed", sent=self._frame)
                return
            self.toast("This plug-in has no on/off switch")
            stage = "pushed"  # nothing pressed: just go back
        elif stage == "pushed":
            self.toast(self.c4_switch_text() or "Plug-in on/off")
        if stage == "pushed" and hop["moves"]:
            self._send_c4([m for button in hop["moves"] for m in c4.click(button)])
            self._c4_page_moves = list(hop["moves"])
            hop.update(stage="back", sent=self._frame)
            return
        self._c4_hop = None
        self._render_c4_rings(force=True)

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
        self.toast("Cakewalk meters on" if want_on else "Cakewalk meters off")
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

    @property
    def _grid_meters(self) -> bool:
        """Meters own the clip grid (not while the sequencer does)."""

        return self.meters and self.mode != "sequencer"

    def _render_grid_meters(self) -> None:
        """Redraw the whole grid and Clip Stop row as meters (or dark)."""

        for track in range(self.tracks):
            for row in range(1, self.rows + 1):
                self.apc.clip_pad(track, row, apc.CLIP_OFF, force=True)
            self.apc.clip_stop(track, apc.CLIP_OFF, force=True)
            self._render_meter_bar(track)
            self._render_meter_clip(track, force=True)

    def _render_meter_bar(self, track: int) -> None:
        if not self._grid_meters:
            return
        level = self._meter_level[track]
        for row, threshold, color in METER_SEGMENTS:
            self.apc.clip_pad(track, row, color if level >= threshold else apc.CLIP_OFF)

    def _render_meter_clip(self, track: int, *, force: bool = False) -> None:
        if not self._grid_meters:
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
    # Step sequencer grid (Scene 2)
    # ------------------------------------------------------------------

    def _seq_cell(self, track: int, row: int) -> tuple[int, int] | None:
        """(lane, step) under grid *track* (0-7) / *row* (0-4); None past the pattern."""

        seq = self.sequencer
        lane = self._seq_lane_page * self.rows + row
        step = self._seq_step_page * self.tracks + track
        if seq is None or lane >= len(seq.lanes) or step >= seq.steps:
            return None
        return lane, step

    def _seq_pad(self, track: int, row: int, pressed: bool) -> None:
        """A tap cycles the step at release; hold + Device knob sets its velocity;
        holding a lit pad for ``seq_hold_frames`` turns it off (see _seq_holds)."""

        cell = self._seq_cell(track, row)
        if cell is None:
            return
        if pressed:
            self._seq_held[cell] = self._frame
            return
        if cell not in self._seq_held:
            return
        if self._seq_held.pop(cell) is not None:
            self.sequencer.cycle(*cell)
        self._render_seq_pad(track, row, force=True)
        if not self._seq_held:
            self._render_c4_rings(force=True)  # the velocity ring gives the knobs back

    def _seq_display_step(self) -> int | None:
        return self.sequencer.display_step(self.seq_display_lead_ms / 1000)

    def _seq_check_clock(self) -> None:
        """Warn when Cakewalk's Play LED is on but its clock never started the sequencer."""

        if self._play_led and not self.sequencer.running:
            if self._seq_unclocked_since is None:
                self._seq_unclocked_since = self._frame
            elif self._frame - self._seq_unclocked_since == self.seq_clock_frames:
                self.seq_status = SEQ_NO_CLOCK
                self.toast("No clock from Cakewalk: see the editor")
                log.warning("Cakewalk plays but sends no MIDI clock to the sequencer")
            return
        self._seq_unclocked_since = None
        if self.sequencer.running and self.seq_status == SEQ_NO_CLOCK:
            self.seq_status = ""

    def _seq_holds(self) -> None:
        """Turn off a lit step whose pad has been held long enough."""

        for cell, pressed_at in self._seq_held.items():
            if pressed_at is None or self._frame - pressed_at < self.seq_hold_frames:
                continue
            if self.sequencer.velocity(*cell):
                self.sequencer.set_velocity(*cell, 0)
                self._seq_held[cell] = None
                lane, step = cell
                self._render_seq_pad(step % self.tracks, lane % self.rows, force=True)
                self.toast("Step off")

    def _seq_knob(self, knob: int, value: int) -> None:
        """Device knob turned while pads are held: adjust their velocity."""

        previous = self._seq_knob_abs.get(knob)
        self._seq_knob_abs[knob] = value
        if previous is None:
            return
        delta = (value - previous) % 128
        if delta > 64:
            delta -= 128
        if not delta:
            return
        seq = self.sequencer
        shown = 0
        for cell in self._seq_held:
            current = seq.velocity(*cell) or seq.velocities["normal"]
            shown = max(1, min(127, current + delta))
            seq.set_velocity(*cell, shown)
            self._seq_held[cell] = None
            lane, step = cell
            self._render_seq_pad(step % self.tracks, lane % self.rows)
        self.apc.ring_style(apc.device_ring_style_cc(knob), apc.RING_VOLUME, channel=self.device_bank)
        self.apc.ring_position(apc.device_ring_cc(knob), shown, channel=self.device_bank)
        self.toast(f"Velocity {shown}")

    def _seq_page(self, kind: str, delta: int) -> None:
        seq = self.sequencer
        if kind == "steps":
            pages = -(-seq.steps // self.tracks)
            page = max(0, min(pages - 1, self._seq_step_page + delta))
            self._seq_step_page = page
            first = page * self.tracks + 1
            self.toast(f"Steps {first}-{min(first + self.tracks - 1, seq.steps)}")
        else:
            pages = -(-len(seq.lanes) // self.rows)
            page = max(0, min(pages - 1, self._seq_lane_page + delta))
            self._seq_lane_page = page
            first = page * self.rows + 1
            self.toast(f"Lanes {first}-{min(first + self.rows - 1, len(seq.lanes))}")
        self._seq_held.clear()
        self._seq_indicator = (kind, page)
        self._seq_indicator_end = self._frame + self.seq_indicator_frames
        self._render_seq()

    def _seq_tick(self) -> None:
        self._seq_holds()
        self._seq_check_clock()
        if self._seq_indicator is not None:
            if self._frame >= self._seq_indicator_end:
                self._seq_indicator = None
                self._render_seq_stop_row(force=True)
        elif self._seq_display_step() != self._seq_shown_step:
            self._render_seq_stop_row()

    def seq_command(self, cmd: dict) -> bool:
        """Apply one edit from the editor window. False for an unknown or bad command."""

        seq = self.sequencer
        if seq is None:
            return False
        op = cmd.get("op")
        try:
            if op == "cycle":
                seq.cycle(int(cmd["lane"]), int(cmd["step"]))
            elif op == "velocity":
                seq.set_velocity(int(cmd["lane"]), int(cmd["step"]), int(cmd["velocity"]))
            elif op == "lane":
                note = cmd.get("note")
                seq.set_lane(int(cmd["lane"]), note=None if note is None else int(note), name=cmd.get("name"))
            elif op == "add_lane":
                seq.add_lane()
            elif op == "remove_lane":
                seq.remove_lane(int(cmd["lane"]))
            elif op == "move_lane":
                seq.move_lane(int(cmd["lane"]), int(cmd["delta"]))
            elif op == "steps":
                seq.set_steps(int(cmd["steps"]))
            elif op == "channel":
                seq.set_channel(int(cmd["channel"]))
            elif op == "clear":
                seq.clear()
            elif op == "map":
                seq.apply_map(sq.map_from_dict(cmd))
                self.seq_status = f"Drum map: {cmd.get('drum_map') or 'applied'}"
            elif op == "lead":
                self.seq_display_lead_ms = max(0, min(500, int(cmd["ms"])))
            elif op == "status":
                self.seq_status = str(cmd["text"])[:300]
            elif op == "load":
                if not seq.load_dict(cmd["pattern"]):
                    return False
            elif op == "view":
                self._seq_step_page = int(cmd.get("step_page", self._seq_step_page))
                self._seq_lane_page = int(cmd.get("lane_page", self._seq_lane_page))
            else:
                return False
        except (KeyError, TypeError, ValueError, IndexError):
            return False
        if self.mode == "sequencer":
            self._render_seq()
        return True

    def seq_state(self) -> dict:
        """What the editor window shows: the pattern, playhead and APC40 page."""

        seq = self.sequencer
        if seq is None:
            return {}
        self._clamp_seq_pages()
        data = seq.to_dict()
        for lane, item in zip(seq.lanes, data["lanes"]):
            item["label"] = lane.label
        data.update(
            playing=self._seq_display_step(),
            lead_ms=self.seq_display_lead_ms,
            step_page=self._seq_step_page,
            lane_page=self._seq_lane_page,
            page_steps=self.tracks,
            page_lanes=self.rows,
            velocities=dict(seq.velocities),
            status=self.seq_status,
            status_warn=self.seq_status == SEQ_NO_CLOCK,
        )
        return data

    def _clamp_seq_pages(self) -> None:
        seq = self.sequencer
        step_pages = -(-seq.steps // self.tracks)
        lane_pages = -(-len(seq.lanes) // self.rows)
        self._seq_step_page = max(0, min(step_pages - 1, self._seq_step_page))
        self._seq_lane_page = max(0, min(lane_pages - 1, self._seq_lane_page))

    def _render_seq(self, *, force: bool = False) -> None:
        self._clamp_seq_pages()
        for track in range(self.tracks):
            for row in range(self.rows):
                self._render_seq_pad(track, row, force=force)
        self._render_seq_stop_row(force=True)

    def _render_seq_pad(self, track: int, row: int, *, force: bool = False) -> None:
        cell = self._seq_cell(track, row)
        level = None if cell is None else self.sequencer.level(*cell)
        color = apc.CLIP_OFF if level is None else SEQ_LEVEL_COLOR[level]
        self.apc.clip_pad(track, row + 1, color, force=force)

    def _render_seq_stop_row(self, *, force: bool = False) -> None:
        """Playhead on the Clip Stop row, or the page number after a page change.

        Step pages light solid and lane pages blink (the row has only green).
        """

        lit, color = None, apc.CLIP_GREEN
        if self._seq_indicator is not None:
            kind, lit = self._seq_indicator
            if kind == "lanes":
                color = apc.CLIP_GREEN_BLINK
        else:
            step = self._seq_display_step()
            self._seq_shown_step = step
            if step is not None and step // self.tracks == self._seq_step_page:
                lit = step % self.tracks
        for track in range(self.tracks):
            self.apc.clip_stop(track, color if track == lit else apc.CLIP_OFF, force=force)

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
            if self.mode == "sequencer":
                self._render_seq_stop_row(force=True)

        self._schedule_flash(frames, off)

    def tick(self) -> None:
        """Advance meter decay and pending flashes by one frame. Call from the run loop."""

        self._frame += 1
        self._jog_budget = JOG_BUDGET_PER_FRAME
        self._settle_meter_toggle()
        self._zoom_idle()
        self._settle_knob_dump()
        self._c4_tick()
        self._repeat_nudge()
        self._expire_shift()
        self._decay_meters()  # also keeps the HUD meters falling when the grid is off
        if self.mode == "sequencer":
            self._seq_tick()
        if any(self._peek) and self._temp_message is None:
            self._update_strip_names(expire=True)
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
    # HUD
    # ------------------------------------------------------------------

    def toast(self, text: str) -> None:
        """Queue a short HUD message acknowledging an action."""

        self._toast_id += 1
        self._toasts.append((self._toast_id, text))
        log.info("action: %s", text)  # the log shows what each press did

    def hud_snapshot(self) -> hud_state.HudSnapshot:
        """Immutable picture of the state the on-screen HUD shows."""

        leds = self._strip_leds
        last = self._last_mcu_frame
        if self._record_led:
            transport = "record"
        elif self._play_led:
            transport = "play"
        else:
            transport = "stop"
        return hud_state.HudSnapshot(
            knob_mode=self.knob_mode,
            mixer=self.mixer,
            shift=self.shift,
            shift_state=self.shift_state,
            mode=self.mode,
            buses=self._cw_buses,
            transport=transport,
            loop=self._loop_led != apc.LED_OFF,
            zoom=self._zoom_mode,
            cakewalk_meters=self.cakewalk_meters_on(),
            cakewalk_active=last is not None and self._frame - last <= self.link_idle_frames,
            assign=self._cw_assign,
            rec=tuple(leds["rec"]),
            solo=tuple(leds["solo"]),
            mute=tuple(leds["mute"]),
            selected_strip=self._selected_strip(),
            selected_track=self._selected_track,
            selected_name=self._selected_name,
            bank_offset=self.bank_offset,
            bank_exact=self._bank_exact,
            lcd_seen=self.lcd.seen,
            lcd=(self.lcd.line(0), self.lcd.line(1)),
            strip_names=tuple(self._stable_names),
            strip_values=tuple(self.lcd.cell(1, s) for s in range(self.tracks)),
            strip_peek=tuple(self._peek),
            timecode=self.seven_seg.timecode(),
            assignment=self.seven_seg.assignment(),
            strip_layout=self.seven_seg.strip_layout(),
            meter_levels=tuple(self._meter_level),
            meter_clips=tuple(self._meter_clip),
            c4_state=self.c4_state,
            c4_strip=self.c4_display.strip,
            c4_slot=self.c4_display.slot,
            c4_plugin=self.c4_display.plugin,
            c4_labels=self.c4_params()[0],
            c4_values=self.c4_params()[1],
            c4_switch=self.c4_switch_text(),
            toasts=tuple(self._toasts),
        )

    # ------------------------------------------------------------------
    # Baseline
    # ------------------------------------------------------------------

    def render_baseline(self) -> None:
        """Draw the resting mixer surface and select Pan mode."""

        self.apc.clear_all()
        self._meter_level = [0] * self.tracks
        self._meter_age = [0] * self.tracks
        self._meter_clip = [False] * self.tracks
        # Device rings are per bank: center them on all nine so every Track
        # Selection shows the same resting state.
        for bank in range(apc.DEVICE_BANKS):
            for knob in range(1, self.tracks + 1):
                self.apc.ring_style(apc.device_ring_style_cc(knob), apc.RING_PAN, channel=bank, force=True)
                self.apc.ring_position(apc.device_ring_cc(knob), 63, channel=bank, force=True)
        # Master's LED belongs to the APC40's Track Selection radio group.
        self.mode = "tracking"
        self._render_mode_leds()
        self.set_knob_mode("pan")
