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
}

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
        env_path=resolved,
    )
