"""HUD view model: snapshot -> the strings and colors the HUD window shows.

Pure functions only, so the whole display logic is unit-testable; the Tk
window (``hud.py``) just copies a :class:`HudView` into its widgets.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .hud_state import KNOB_MODE_LABELS, HudSnapshot

BG = "#16181c"
PANEL = "#1f2228"
FG = "#e6e6e6"
DIM = "#5b606b"
SELECTED_BG = "#2f3540"
WARN = "#f87171"

MODE_COLORS = {
    "pan": "#f0a030",  # amber
    "send_a": "#36c5e0",  # cyan
    "send_b": "#a78bfa",  # violet
    "send_c": "#4ade80",  # green
}
DEVICE_COLOR = "#f472b6"

TRANSPORT = {
    "stop": ("■ STOP", "#9ca3af"),
    "play": ("▶ PLAY", "#4ade80"),
    "record": ("● REC", "#f87171"),
}

BADGE_ON = {"LOOP": "#fbbf24", "ZOOM": "#60a5fa", "METERS": "#4ade80", "SHIFT": "#f0a030"}

REC_COLOR, SOLO_COLOR, MUTE_COLOR = "#f87171", "#facc15", "#60a5fa"
METER_GREEN, METER_YELLOW, METER_RED = "#4ade80", "#facc15", "#f87171"
METER_MAX = 13

LINK_TIMEOUT = 3.0  # seconds without a datagram before the HUD shows "no link"
MARGIN = 12


@dataclass(frozen=True)
class StripView:
    name: str
    value: str
    peek: bool  # name cell currently shows Cakewalk's value peek
    level: int  # 0-13
    clipped: bool
    selected: bool
    rec: bool
    solo: bool
    mute: bool


@dataclass(frozen=True)
class HudView:
    mode_text: str
    mode_color: str
    bank_text: str
    selection_text: str
    transport_text: str
    transport_color: str
    badges: tuple[tuple[str, str], ...]  # (text, color); dim when off
    time_text: str
    assignment_text: str
    status_text: str  # link / warning line, "" when all is well
    status_color: str
    toast: str
    strips: tuple[StripView, ...]
    show_strips: bool


def mode_label(snapshot: HudSnapshot) -> tuple[str, str]:
    if not snapshot.mixer:
        return "DEVICE", DEVICE_COLOR
    return (
        KNOB_MODE_LABELS.get(snapshot.knob_mode, snapshot.knob_mode.upper()),
        MODE_COLORS.get(snapshot.knob_mode, FG),
    )


def bank_label(snapshot: HudSnapshot, strips: int = 8) -> str:
    offset = snapshot.bank_offset
    if offset is None:
        return "Trk ?"
    prefix = "" if snapshot.bank_exact else "~"
    return f"Trk {prefix}{offset + 1}-{offset + strips}"


def selection_label(snapshot: HudSnapshot) -> str:
    name = snapshot.selected_name
    if snapshot.selected_track is not None:
        text = f"Sel {snapshot.selected_track}"
    elif snapshot.selected_strip is not None:
        text = f"Sel strip {snapshot.selected_strip + 1}"
    else:
        return ""
    return f"{text} {name}" if name else text


def status_label(snapshot: HudSnapshot | None, info: dict, linked: bool) -> tuple[str, str]:
    if not linked or snapshot is None:
        return "no link to apc40sonar", DIM
    if snapshot.strip_layout:
        return "Strip layout! (Cakewalk knobs flipped)", WARN
    if info.get("mcu_in") is False:
        return "no Cakewalk feedback port", WARN
    if info.get("mcu_out") is False:
        return "no Cakewalk control port", WARN
    if not snapshot.cakewalk_active:
        return "Cakewalk idle", DIM
    return "", DIM


def _at(values: Sequence, index: int, default):
    return values[index] if index < len(values) else default


def strip_views(snapshot: HudSnapshot) -> tuple[StripView, ...]:
    views = []
    for i, name in enumerate(snapshot.strip_names):
        peek = _at(snapshot.strip_peek, i, "")
        views.append(
            StripView(
                name=peek or name,
                value=_at(snapshot.strip_values, i, ""),
                peek=bool(peek),
                level=_at(snapshot.meter_levels, i, 0),
                clipped=_at(snapshot.meter_clips, i, False),
                selected=snapshot.selected_strip == i,
                rec=_at(snapshot.rec, i, False),
                solo=_at(snapshot.solo, i, False),
                mute=_at(snapshot.mute, i, False),
            )
        )
    return tuple(views)


def build_view(
    snapshot: HudSnapshot | None,
    info: dict | None = None,
    *,
    linked: bool = True,
    toast: str = "",
) -> HudView:
    """Everything the window shows. With no link, the last state is greyed out."""

    info = info or {}
    status_text, status_color = status_label(snapshot, info, linked)
    if snapshot is None:
        snapshot = HudSnapshot()
        linked = False

    mode_text, mode_color = mode_label(snapshot)
    transport_text, transport_color = TRANSPORT.get(snapshot.transport, TRANSPORT["stop"])
    active = {
        "LOOP": snapshot.loop,
        "ZOOM": snapshot.zoom,
        "METERS": snapshot.cakewalk_meters,
        "SHIFT": snapshot.shift,
    }
    badges = tuple((name, BADGE_ON[name] if on and linked else DIM) for name, on in active.items())
    if not linked:
        mode_color = transport_color = DIM
        toast = ""

    return HudView(
        mode_text=mode_text,
        mode_color=mode_color,
        bank_text=bank_label(snapshot),
        selection_text=selection_label(snapshot),
        transport_text=transport_text,
        transport_color=transport_color,
        badges=badges,
        time_text=snapshot.timecode,
        assignment_text=f"Assign {snapshot.assignment}" if snapshot.assignment else "",
        status_text=status_text,
        status_color=status_color,
        toast=toast,
        strips=strip_views(snapshot),
        show_strips=snapshot.lcd_seen,
    )


def meter_color(level: int) -> str:
    if level >= 12:
        return METER_RED
    if level >= 9:
        return METER_YELLOW
    return METER_GREEN


class ToastTracker:
    """Pick the toast to show: the newest one not seen before, for *duration* s.

    Toasts already in the first snapshot are history (the HUD started late)
    and are not shown. A drop in the toast ids means the engine restarted.
    """

    def __init__(self, duration: float) -> None:
        self.duration = duration
        self._seen: int | None = None
        self._text = ""
        self._until = 0.0

    def update(self, toasts: Sequence[tuple[int, str]] | None, now: float) -> str:
        if toasts is not None:
            newest = max((i for i, _t in toasts), default=0)
            if self._seen is None or newest < self._seen:
                self._seen = newest
            else:
                fresh = [(i, t) for i, t in toasts if i > self._seen]
                if fresh:
                    self._seen = fresh[-1][0]
                    self._text = fresh[-1][1]
                    self._until = now + self.duration
        return self._text if now < self._until else ""


def parse_position(text: str) -> tuple[str, tuple[int, int] | None]:
    """``"top-right"`` -> ``("top-right", None)``; ``"100,40"`` -> ``("xy", (100, 40))``."""

    text = text.strip().lower()
    if "," in text:
        x, _sep, y = text.partition(",")
        try:
            return "xy", (int(x), int(y))
        except ValueError:
            return "top-right", None
    if text in ("top-left", "top-right", "bottom-left", "bottom-right"):
        return text, None
    return "top-right", None


def place_window(
    position: str,
    area: tuple[int, int, int, int],
    size: tuple[int, int],
    margin: int = MARGIN,
) -> tuple[int, int]:
    """Top-left corner for a window of *size* in the monitor work *area* (l, t, r, b)."""

    left, top, right, bottom = area
    width, height = size
    corner, xy = parse_position(position)
    if corner == "xy" and xy is not None:
        return left + xy[0], top + xy[1]
    x = left + margin if corner.endswith("left") else right - width - margin
    y = top + margin if corner.startswith("top") else bottom - height - margin
    return x, y
