"""Runtime configuration for the APC40 <-> Cakewalk integration.

Port names are deliberately **not** hard-coded. Windows renames loopMIDI
cables between iterations (a reboot, a re-added port, or a different virtual
MIDI driver all change the visible names), so the names live in an editable
``.env`` file and are read at startup.

Lookup order for the ``.env`` file:

1. the path in the ``APC40SONAR_ENV`` environment variable, if set;
2. ``.env`` in the current working directory;
3. ``config/.env`` in the current working directory.

Recognized keys (all optional; defaults match the documented topology):

    APC40_PORT        physical controller       default: Akai APC40
    MCU_OUT_PORT      app -> Cakewalk            default: APC40-IN
    MCU_IN_PORT       Cakewalk -> app            default: APC40-OUT
    APC40_CLIENT_NAME client name shown to WinMM default: apc40sonar
    APC40_MODE        APC40 operating mode        default: generic
    KNOB_STEP_LIMIT   max V-pot steps per knob event default: 3
    KNOB_NOISE_THRESHOLD  steps above this are ignored  default: 4
    METERS            track level meters on the grid default: on
    METER_DECAY_MS    meter fall time per segment     default: 300
    ZOOM_STEP_UNITS   crossfader travel per zoom step default: 6
    ZOOM_IDLE_MS      leave Cakewalk zoom mode after  default: 300
    HUD               launch the on-screen HUD        default: on
    HUD_PORT          HUD UDP port on 127.0.0.1       default: 47040
    HUD_POSITION      top-left/top-right/bottom-*/x,y default: top-right
    HUD_MONITOR       monitor index for placement     default: 0
    HUD_MARGIN        x,y gap from the corner, pixels default: 50,12
    HUD_OPACITY       window alpha 0.2-1.0            default: 0.85
    HUD_TOPMOST       keep the HUD above other windows default: on
    HUD_CLICK_THROUGH mouse passes through the HUD    default: off
    HUD_LAYOUT        compact / expanded              default: compact
    HUD_TOAST_MS      toast duration                  default: 1200
    HUD_LCD           capture Cakewalk's MCU displays default: on
    CUE_STEP          playhead move per Cue detent     default: 1 beat
    SHIFT_CUE_STEP    ... per detent with Shift held   default: 30 tick
    NUDGE_STEP        playhead move per Nudge press    default: 1 measure
    NUDGE_REPEAT_MS   repeat interval while Nudge held default: 150
    SHIFT_ONESHOT_MS  tapped Shift expires after       default: 3000
    LONG_PRESS_MS     hold this long = a long press    default: 1000
    SEQ_OUT_PORT      sequencer notes, app -> Cakewalk default: APC40-SEQ
    CLOCK_IN_PORT     MIDI clock, Cakewalk -> app      default: APC40-CLOCK
    SEQ_NOTES         one MIDI note per lane           default: GM drums (10 lanes)
    SEQ_CHANNEL       MIDI channel 1-16 for all lanes  default: 10
    SEQ_STEPS         pattern length in 1/16 steps     default: 16
    SEQ_VELOCITIES    normal accent soft               default: 100 127 60
    SEQ_EDITOR        editor window in Scene 2          default: on
    SEQ_EDITOR_PORT   editor UDP port (commands: +1)    default: 47041
    SEQ_DIR           saved pattern + .mid exports      default: patterns
    SEQ_DISPLAY_LEAD_MS  playhead drawn this far ahead  default: 40
    C4_OUT_PORT       C4 surface, app -> Cakewalk    default: C4-IN
    C4_IN_PORT        C4 surface, Cakewalk -> app    default: C4-OUT
    C4                plug-in control via the C4      default: on
    C4_KNOB_STEP_LIMIT  max C4 V-pot speed per event  default: 3
    C4_RESET_ON_SELECT  first plug-in/page on select  default: on

SEQ_NOTES / SEQ_CHANNEL / SEQ_STEPS only shape a new pattern: once the editor
or the APC40 changed it, ``SEQ_DIR/current.json`` is loaded instead. A
relative ``SEQ_DIR`` is relative to the ``.env`` file's folder.

Playhead steps are ``<count> <unit>``: unit ``measure``, ``beat``, ``tick``
(1/960 beat at Cakewalk's default resolution) or ``jog`` (the Mackie preset's
Jog Wheel Resolution). Measure and beat steps snap to the grid.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ENV_VAR = "APC40SONAR_ENV"

DEFAULTS = {
    "APC40_PORT": "Akai APC40",
    "MCU_OUT_PORT": "APC40-IN",
    "MCU_IN_PORT": "APC40-OUT",
    "APC40_CLIENT_NAME": "apc40sonar",
    "APC40_MODE": "generic",
    "KNOB_STEP_LIMIT": "3",
    "KNOB_NOISE_THRESHOLD": "4",
    "METERS": "on",
    "METER_DECAY_MS": "300",
    "ZOOM_STEP_UNITS": "6",
    "ZOOM_IDLE_MS": "300",
    "HUD": "on",
    "HUD_PORT": "47040",
    "HUD_POSITION": "top-right",
    "HUD_MONITOR": "0",
    "HUD_MARGIN": "50,12",
    "HUD_OPACITY": "0.85",
    "HUD_TOPMOST": "on",
    "HUD_CLICK_THROUGH": "off",
    "HUD_LAYOUT": "compact",
    "HUD_TOAST_MS": "1200",
    "HUD_LCD": "on",
    "CUE_STEP": "1 beat",
    "SHIFT_CUE_STEP": "30 tick",
    "NUDGE_STEP": "1 measure",
    "NUDGE_REPEAT_MS": "150",
    "SHIFT_ONESHOT_MS": "3000",
    "LONG_PRESS_MS": "1000",
    "SEQ_OUT_PORT": "APC40-SEQ",
    "CLOCK_IN_PORT": "APC40-CLOCK",
    "SEQ_NOTES": "36 38 42 46 39 37 45 47 50 49",
    "SEQ_CHANNEL": "10",
    "SEQ_STEPS": "16",
    "SEQ_VELOCITIES": "100 127 60",
    "SEQ_EDITOR": "on",
    "SEQ_EDITOR_PORT": "47041",
    "SEQ_DIR": "patterns",
    "SEQ_DISPLAY_LEAD_MS": "40",
    "C4_OUT_PORT": "C4-IN",
    "C4_IN_PORT": "C4-OUT",
    "C4": "on",
    "C4_KNOB_STEP_LIMIT": "3",
    "C4_RESET_ON_SELECT": "on",
}

STEP_UNITS = ("measure", "beat", "tick", "jog")
# Each unit is one MIDI message (Cakewalk moves 1 tick per jog), so a large count
# floods the loopMIDI cable; loopMIDI's flood protection then disables it.
STEP_COUNT_MAX = 48

HUD_LAYOUTS = ("compact", "expanded")

TRUE_WORDS = frozenset({"1", "on", "true", "yes"})
FALSE_WORDS = frozenset({"0", "off", "false", "no"})


@dataclass(frozen=True)
class Config:
    """Port names and options resolved from the environment/``.env``."""

    apc40_port: str
    mcu_out_port: str
    mcu_in_port: str
    client_name: str
    apc40_mode: str
    knob_step_limit: int
    knob_noise_threshold: int
    meters: bool = True
    meter_decay_ms: int = 300
    zoom_step_units: int = 6
    zoom_idle_ms: int = 300
    hud: bool = True
    hud_port: int = 47040
    hud_position: str = "top-right"
    hud_monitor: int = 0
    hud_margin: tuple[int, int] = (50, 12)
    hud_opacity: float = 0.85
    hud_topmost: bool = True
    hud_click_through: bool = False
    hud_layout: str = "compact"
    hud_toast_ms: int = 1200
    hud_lcd: bool = True
    cue_step: tuple[int, str] = (1, "beat")
    shift_cue_step: tuple[int, str] = (30, "tick")
    nudge_step: tuple[int, str] = (1, "measure")
    nudge_repeat_ms: int = 150
    shift_oneshot_ms: int = 3000
    long_press_ms: int = 1000
    seq_out_port: str = "APC40-SEQ"
    clock_in_port: str = "APC40-CLOCK"
    seq_notes: tuple[int, ...] = (36, 38, 42, 46, 39, 37, 45, 47, 50, 49)
    seq_channel: int = 10
    seq_steps: int = 16
    seq_velocities: tuple[int, int, int] = (100, 127, 60)
    seq_editor: bool = True
    seq_editor_port: int = 47041
    seq_dir: Path = Path("patterns")
    seq_display_lead_ms: int = 40
    c4_out_port: str = "C4-IN"
    c4_in_port: str = "C4-OUT"
    c4: bool = True
    c4_knob_step_limit: int = 3
    c4_reset_on_select: bool = True
    env_path: Path | None = None


def parse_env(text: str) -> dict[str, str]:
    """Parse a minimal ``KEY=VALUE`` dotenv document.

    Supports blank lines, ``#`` comments, an optional ``export`` prefix, and
    single- or double-quoted values. Malformed lines without ``=`` are ignored
    rather than raising, so a stray comment cannot stop the app from starting.
    """

    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        key, sep, value = line.partition("=")
        if not sep:
            continue
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def find_env_file(cwd: Path | None = None, environ: dict[str, str] | None = None) -> Path | None:
    """Return the first existing ``.env`` path, or ``None``."""

    environ = os.environ if environ is None else environ
    cwd = Path.cwd() if cwd is None else cwd

    override = environ.get(ENV_VAR)
    if override:
        candidate = Path(override)
        return candidate if candidate.is_file() else None

    for candidate in (cwd / ".env", cwd / "config" / ".env"):
        if candidate.is_file():
            return candidate

    return None


def _as_int(values: dict[str, str], key: str, default: int) -> int:
    """Parse an integer setting (decimal or 0x-prefixed), falling back to *default*."""

    try:
        return int(str(values[key]).strip(), 0)
    except (KeyError, ValueError):
        return default


def _as_float(values: dict[str, str], key: str, default: float) -> float:
    """Parse a decimal setting, falling back to *default*."""

    try:
        return float(str(values[key]).strip())
    except (KeyError, ValueError):
        return default


def _as_pair(values: dict[str, str], key: str, default: tuple[int, int]) -> tuple[int, int]:
    """Parse ``"x,y"`` (or one number for both) as two integers, falling back to *default*."""

    parts = str(values.get(key, "")).replace(",", " ").split()
    try:
        numbers = [int(p) for p in parts]
    except ValueError:
        return default
    if len(numbers) == 1:
        return numbers[0], numbers[0]
    if len(numbers) == 2:
        return numbers[0], numbers[1]
    return default


def _as_choice(values: dict[str, str], key: str, choices: tuple[str, ...], default: str) -> str:
    """Parse one of *choices* (case-insensitive), falling back to *default*."""

    text = str(values.get(key, "")).strip().lower()
    return text if text in choices else default


def parse_step(text: str) -> tuple[int, str] | None:
    """Parse a playhead step such as ``"1 beat"``, ``"30 ticks"`` or ``"measure"``.

    Returns ``(count, unit)`` or ``None`` when the text is not a valid step.
    """

    parts = text.strip().lower().split()
    if len(parts) == 1:
        parts = ["1", parts[0]]
    if len(parts) != 2:
        return None
    count_text, unit = parts
    unit = unit[:-1] if unit.endswith("s") else unit
    try:
        count = int(count_text)
    except ValueError:
        return None
    if unit not in STEP_UNITS or not 1 <= count <= STEP_COUNT_MAX:
        return None
    return count, unit


def _as_ints(values: dict[str, str], key: str, low: int, high: int) -> tuple[int, ...] | None:
    """Parse a space/comma-separated list of integers in [low, high]; None if invalid."""

    try:
        numbers = tuple(int(part) for part in str(values.get(key, "")).replace(",", " ").split())
    except ValueError:
        return None
    if not numbers or any(not low <= n <= high for n in numbers):
        return None
    return numbers


def _as_step(values: dict[str, str], key: str, default: str) -> tuple[int, str]:
    """Parse a playhead step setting, falling back to *default*."""

    step = parse_step(str(values.get(key, "")))
    if step is None:
        step = parse_step(default)
    assert step is not None
    return step


def _as_bool(values: dict[str, str], key: str, default: bool) -> bool:
    """Parse an on/off setting, falling back to *default* for unknown words."""

    text = str(values.get(key, "")).strip().lower()
    if text in TRUE_WORDS:
        return True
    if text in FALSE_WORDS:
        return False
    return default


def load_config(
    env_path: Path | None = None,
    cwd: Path | None = None,
    environ: dict[str, str] | None = None,
) -> Config:
    """Build a :class:`Config` from defaults overlaid with ``.env`` values.

    An explicit *env_path* is honored even if it does not exist (so callers can
    report the missing path); otherwise :func:`find_env_file` is used. Values
    already present in the process environment take precedence over the file.
    """

    environ = os.environ if environ is None else environ

    if env_path is not None:
        resolved = env_path if env_path.is_file() else None
    else:
        resolved = find_env_file(cwd=cwd, environ=environ)

    values = dict(DEFAULTS)
    if resolved is not None:
        values.update(parse_env(resolved.read_text(encoding="utf-8")))

    # Process environment wins over the file, so a one-off override is easy.
    for key in DEFAULTS:
        if key in environ and environ[key]:
            values[key] = environ[key]

    return Config(
        apc40_port=values["APC40_PORT"],
        mcu_out_port=values["MCU_OUT_PORT"],
        mcu_in_port=values["MCU_IN_PORT"],
        client_name=values["APC40_CLIENT_NAME"],
        apc40_mode=values["APC40_MODE"],
        knob_step_limit=_as_int(values, "KNOB_STEP_LIMIT", 3),
        knob_noise_threshold=_as_int(values, "KNOB_NOISE_THRESHOLD", 4),
        meters=_as_bool(values, "METERS", True),
        meter_decay_ms=_as_int(values, "METER_DECAY_MS", 300),
        zoom_step_units=_as_int(values, "ZOOM_STEP_UNITS", 6),
        zoom_idle_ms=_as_int(values, "ZOOM_IDLE_MS", 300),
        hud=_as_bool(values, "HUD", True),
        hud_port=_as_int(values, "HUD_PORT", 47040),
        hud_position=str(values["HUD_POSITION"]).strip().lower() or "top-right",
        hud_monitor=max(0, _as_int(values, "HUD_MONITOR", 0)),
        hud_margin=_as_pair(values, "HUD_MARGIN", (50, 12)),
        hud_opacity=min(max(_as_float(values, "HUD_OPACITY", 0.85), 0.2), 1.0),
        hud_topmost=_as_bool(values, "HUD_TOPMOST", True),
        hud_click_through=_as_bool(values, "HUD_CLICK_THROUGH", False),
        hud_layout=_as_choice(values, "HUD_LAYOUT", HUD_LAYOUTS, "compact"),
        hud_toast_ms=max(0, _as_int(values, "HUD_TOAST_MS", 1200)),
        hud_lcd=_as_bool(values, "HUD_LCD", True),
        cue_step=_as_step(values, "CUE_STEP", DEFAULTS["CUE_STEP"]),
        shift_cue_step=_as_step(values, "SHIFT_CUE_STEP", DEFAULTS["SHIFT_CUE_STEP"]),
        nudge_step=_as_step(values, "NUDGE_STEP", DEFAULTS["NUDGE_STEP"]),
        nudge_repeat_ms=_as_int(values, "NUDGE_REPEAT_MS", 150),
        shift_oneshot_ms=_as_int(values, "SHIFT_ONESHOT_MS", 3000),
        long_press_ms=min(5000, max(200, _as_int(values, "LONG_PRESS_MS", 1000))),
        seq_out_port=values["SEQ_OUT_PORT"],
        clock_in_port=values["CLOCK_IN_PORT"],
        seq_notes=_as_ints(values, "SEQ_NOTES", 0, 127) or Config.seq_notes,
        seq_channel=min(16, max(1, _as_int(values, "SEQ_CHANNEL", 10))),
        seq_steps=min(64, max(1, _as_int(values, "SEQ_STEPS", 16))),
        seq_velocities=_velocities(_as_ints(values, "SEQ_VELOCITIES", 1, 127)),
        seq_editor=_as_bool(values, "SEQ_EDITOR", True),
        seq_editor_port=_as_int(values, "SEQ_EDITOR_PORT", 47041),
        seq_dir=_as_dir(values["SEQ_DIR"], resolved, cwd),
        seq_display_lead_ms=min(500, max(0, _as_int(values, "SEQ_DISPLAY_LEAD_MS", 40))),
        c4_out_port=values["C4_OUT_PORT"],
        c4_in_port=values["C4_IN_PORT"],
        c4=_as_bool(values, "C4", True),
        c4_knob_step_limit=min(15, max(1, _as_int(values, "C4_KNOB_STEP_LIMIT", 3))),
        c4_reset_on_select=_as_bool(values, "C4_RESET_ON_SELECT", True),
        env_path=resolved,
    )


def _velocities(numbers: tuple[int, ...] | None) -> tuple[int, int, int]:
    """normal / accent / soft velocities; the default unless exactly three."""

    if numbers is None or len(numbers) != 3:
        return Config.seq_velocities
    return numbers  # type: ignore[return-value]


def _as_dir(text: str, env_path: Path | None, cwd: Path | None) -> Path:
    """A folder setting; relative paths are relative to the .env file's folder."""

    path = Path(str(text).strip() or "patterns")
    if path.is_absolute():
        return path
    base = env_path.parent if env_path is not None else (Path.cwd() if cwd is None else cwd)
    return base / path
