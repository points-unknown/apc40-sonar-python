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
        env_path=resolved,
    )
