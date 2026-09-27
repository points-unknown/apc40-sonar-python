"""HUD snapshot: the immutable picture of engine state the on-screen HUD shows.

The engine builds a :class:`HudSnapshot` (see ``Engine.hud_snapshot``); the
publisher serializes it to JSON and the HUD process rebuilds it with
:func:`from_dict`. Pure data - no sockets, no Tk.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields

STRIPS = 8

KNOB_MODE_LABELS = {
    "pan": "PAN",
    "send_a": "SEND A (1)",
    "send_b": "SEND B (2)",
    "send_c": "SEND C (3)",
}

KNOB_MODE_TOASTS = {
    "pan": "Pan",
    "send_a": "Send A",
    "send_b": "Send B",
    "send_c": "Send C",
}


def _blank(value=""):
    return (value,) * STRIPS


@dataclass(frozen=True)
class HudSnapshot:
    """Everything the HUD displays. Equal snapshots need no resend."""

    knob_mode: str = "pan"
    mixer: bool = True
    shift: bool = False
    transport: str = "stop"  # "stop" / "play" / "record"
    loop: bool = False
    zoom: bool = False
    cakewalk_meters: bool = False
    cakewalk_active: bool = False  # MCU feedback seen recently
    assign: str | None = None  # Cakewalk assignment from its LEDs
    rec: tuple[bool, ...] = _blank(False)
    solo: tuple[bool, ...] = _blank(False)
    mute: tuple[bool, ...] = _blank(False)
    selected_strip: int | None = None  # 0-7, from the Select LEDs
    selected_track: int | None = None  # 1-based, from Cakewalk's temp message
    selected_name: str = ""
    bank_offset: int | None = None  # tracks before strip 1, derived
    bank_exact: bool = False  # False: adjusted by Bank/Channel presses since
    lcd_seen: bool = False
    lcd: tuple[str, ...] = ("", "")
    strip_names: tuple[str, ...] = _blank()
    strip_values: tuple[str, ...] = _blank()
    strip_peek: tuple[str, ...] = _blank()  # V-pot value peek over the name
    timecode: str = ""
    assignment: str = ""  # 2-char assignment display
    strip_layout: bool = False  # Cakewalk knobs flipped to channel-strip layout
    meter_levels: tuple[int, ...] = _blank(0)
    meter_clips: tuple[bool, ...] = _blank(False)
    toasts: tuple[tuple[int, str], ...] = ()  # (id, text), oldest first


def to_dict(snapshot: HudSnapshot) -> dict:
    return asdict(snapshot)


def from_dict(data: dict) -> HudSnapshot:
    """Rebuild a snapshot from decoded JSON, ignoring unknown keys.

    JSON turns tuples into lists; they are converted back so snapshots compare
    equal. Missing keys keep their defaults, so an older or newer engine still
    renders.
    """

    values = {}
    for field in fields(HudSnapshot):
        if field.name not in data:
            continue
        value = data[field.name]
        if field.name == "toasts":
            value = tuple((int(i), str(t)) for i, t in value)
        elif isinstance(value, list):
            value = tuple(value)
        values[field.name] = value
    return HudSnapshot(**values)
