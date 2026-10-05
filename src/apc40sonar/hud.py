"""On-screen HUD: a small always-on-top tkinter window fed by UDP snapshots.

Runs as its own process so a crash, hang or window drag can never stall the
MIDI loop. The main app launches it unless ``HUD=off``; it can also be started
by hand to attach to a running app::

    uv run python -m apc40sonar.hud [--layout expanded] [--position 100,40]

Options default to the ``HUD_*`` keys in ``.env``. Drag the window with the
left mouse button; right-click for layout, opacity and Quit.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Sequence

from . import config as config_module
from . import hud_link
from . import hud_state
from . import hud_view as hv

log = logging.getLogger(__name__)

POLL_MS = 30
TOPMOST_REFRESH_MS = 2000
PARENT_CHECK_MS = 2000

FONT_UI = "Segoe UI"
FONT_MONO = "Consolas"

METER_WIDTH = 58
METER_HEIGHT = 12

POSITION_FILE = ".hud-position.json"  # next to .env; where the HUD was dragged


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="apc40sonar.hud", description="apc40sonar on-screen HUD.")
    parser.add_argument("--env", type=Path, default=None, metavar="PATH", help="Path to the .env file.")
    parser.add_argument("--port", type=int, default=None, help="UDP port (HUD_PORT).")
    parser.add_argument("--position", default=None, help="top-left/top-right/bottom-left/bottom-right or x,y.")
    parser.add_argument("--monitor", type=int, default=None, help="Monitor index (HUD_MONITOR).")
    parser.add_argument("--margin", default=None, help="x,y gap from the corner in pixels (HUD_MARGIN).")
    parser.add_argument("--opacity", type=float, default=None, help="Window alpha 0.2-1.0.")
    parser.add_argument("--topmost", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--click-through", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--layout", choices=config_module.HUD_LAYOUTS, default=None)
    parser.add_argument("--toast-ms", type=int, default=None)
    parser.add_argument("--parent-pid", type=int, default=None, help="Exit when this process ends.")
    return parser


# ---------------------------------------------------------------------------
# Windows helpers (ctypes; all best effort)
# ---------------------------------------------------------------------------


def _set_dpi_aware() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor aware
    except Exception:  # noqa: BLE001
        pass


def _monitor_work_areas() -> list[tuple[int, int, int, int]]:
    """Work areas (l, t, r, b) of all monitors, primary first; [] if unknown."""

    if sys.platform != "win32":
        return []
    try:
        import ctypes
        from ctypes import wintypes

        class MONITORINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT),
                ("dwFlags", wintypes.DWORD),
            ]

        areas: list[tuple[bool, tuple[int, int, int, int]]] = []
        user32 = ctypes.windll.user32
        proc_type = ctypes.WINFUNCTYPE(
            ctypes.c_int, wintypes.HMONITOR, wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.LPARAM
        )

        def callback(hmonitor, _hdc, _rect, _data):
            info = MONITORINFO()
            info.cbSize = ctypes.sizeof(MONITORINFO)
            if user32.GetMonitorInfoW(hmonitor, ctypes.byref(info)):
                r = info.rcWork
                areas.append((bool(info.dwFlags & 1), (r.left, r.top, r.right, r.bottom)))
            return 1

        user32.EnumDisplayMonitors(None, None, proc_type(callback), 0)
        areas.sort(key=lambda item: not item[0])  # primary first
        return [area for _primary, area in areas]
    except Exception:  # noqa: BLE001
        return []


def _set_window_exstyle(root, *, click_through: bool) -> None:
    """No-activate (keep Cakewalk focused) and optional mouse click-through."""

    if sys.platform != "win32":
        return
    try:
        import ctypes

        GWL_EXSTYLE = -20
        WS_EX_LAYERED = 0x00080000
        WS_EX_TRANSPARENT = 0x00000020
        WS_EX_NOACTIVATE = 0x08000000
        WS_EX_TOOLWINDOW = 0x00000080
        user32 = ctypes.windll.user32
        hwnd = user32.GetParent(root.winfo_id()) or root.winfo_id()
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        style |= WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW
        if click_through:
            style |= WS_EX_LAYERED | WS_EX_TRANSPARENT
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
    except Exception:  # noqa: BLE001
        log.debug("could not set HUD window styles", exc_info=True)


def _pid_alive(pid: int) -> bool:
    if sys.platform == "win32":
        try:
            import ctypes

            SYNCHRONIZE = 0x00100000
            WAIT_TIMEOUT = 0x102
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(SYNCHRONIZE, False, pid)
            if not handle:
                return False
            try:
                return kernel32.WaitForSingleObject(handle, 0) == WAIT_TIMEOUT
            finally:
                kernel32.CloseHandle(handle)
        except Exception:  # noqa: BLE001
            return True
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


# ---------------------------------------------------------------------------
# Window
# ---------------------------------------------------------------------------


class HudApp:
    def __init__(
        self,
        receiver: hud_link.HudReceiver,
        *,
        position: str = "top-right",
        monitor: int = 0,
        opacity: float = 0.85,
        topmost: bool = True,
        click_through: bool = False,
        layout: str = "compact",
        toast_ms: int = 1200,
        parent_pid: int | None = None,
        state_path: Path | None = None,
        corner_margin: tuple[int, int] = (hv.MARGIN, hv.MARGIN),
    ) -> None:
        import tkinter as tk

        self.tk = tk
        self.receiver = receiver
        self.position = position
        self.monitor = monitor
        self.topmost = topmost
        self.click_through = click_through
        self.parent_pid = parent_pid
        self.toasts = hv.ToastTracker(toast_ms / 1000)
        self.snapshot: hud_state.HudSnapshot | None = None
        self.info: dict = {}
        self.last_rx: float | None = None
        self._dragged = False
        self._drag_from: tuple[int, int] | None = None
        self._size: tuple[int, int] | None = None
        self._params_shown = False  # the parameter row exists only with a C4
        # A dragged position, kept as the distance from the anchored corner so
        # the window grows away from it; saved in state_path for the next run.
        self.state_path = state_path
        self.margin: tuple[int, int] | None = None
        self.corner_margin = corner_margin  # the default gap from the corner (HUD_MARGIN)
        self._load_position()

        root = self.root = tk.Tk()
        root.title("apc40sonar HUD")
        root.overrideredirect(True)
        root.configure(bg=hv.BG)
        root.attributes("-alpha", opacity)
        root.attributes("-topmost", topmost)
        self.layout = tk.StringVar(value=layout)
        self.opacity = tk.DoubleVar(value=opacity)

        self._build()
        self._build_menu()
        self._apply_layout()
        root.update_idletasks()
        _set_window_exstyle(root, click_through=click_through)

        root.after(POLL_MS, self._poll)
        if topmost:
            root.after(TOPMOST_REFRESH_MS, self._refresh_topmost)
        if parent_pid:
            root.after(PARENT_CHECK_MS, self._check_parent)

    # -- widgets ---------------------------------------------------------

    def _label(self, parent, text="", *, size=10, bold=False, mono=False, fg=hv.FG, **kw):
        font = (FONT_MONO if mono else FONT_UI, size, "bold" if bold else "normal")
        return self.tk.Label(parent, text=text, font=font, fg=fg, bg=kw.pop("bg", hv.BG), **kw)

    def _build(self) -> None:
        tk = self.tk
        outer = self.outer = tk.Frame(self.root, bg=hv.BG, padx=10, pady=6)
        outer.pack(fill="both", expand=True)
        # The compact HUD on the right; the expanded rows grow out to its left,
        # so the window stays short (it fits in Cakewalk's top bar).
        core = self.core = tk.Frame(outer, bg=hv.BG)
        core.pack(side="right", anchor="n")
        extra = self.extra = tk.Frame(outer, bg=hv.BG)

        top = tk.Frame(core, bg=hv.BG)
        top.pack(fill="x")
        # Fixed widths (characters) so changing text never resizes the window.
        self.mode = self._label(top, size=15, bold=True, width=8, anchor="w")
        self.mode.pack(side="left")
        self.bank = self._label(top, size=10, fg="#b8bdc7", width=hv.BANK_CHARS, anchor="w")
        self.bank.pack(side="left", padx=(14, 0))
        self.selection = self._label(top, size=10, width=hv.SELECTION_CHARS, anchor="w")
        self.selection.pack(side="left", padx=(10, 0))
        self.transport = self._label(top, size=11, bold=True, width=7, anchor="e")
        self.transport.pack(side="right")

        mid = tk.Frame(core, bg=hv.BG)
        mid.pack(fill="x")
        self.time = self._label(mid, size=11, mono=True)
        self.time.pack(side="left")
        self.assignment = self._label(mid, size=9, mono=True, fg=hv.DIM)
        self.assignment.pack(side="left", padx=(10, 0))
        self.toast = self._label(mid, size=10, bold=True, fg="#ffffff", width=hv.TOAST_CHARS, anchor="e")
        self.toast.pack(side="right")
        self.badges = {}
        for name in reversed(("LOOP", "ZOOM", "METERS", "SHIFT")):
            badge = self._label(mid, name, size=8, bold=True, fg=hv.DIM)
            badge.pack(side="right", padx=(0, 6))
            self.badges[name] = badge

        self.status = self._label(core, size=8, fg=hv.DIM, anchor="w")
        self.status.pack(fill="x")
        self.plugin = self._label(core, size=9, fg=hv.DEVICE_COLOR, anchor="w")  # packed when set

        # Expanded: the 8 Device knob parameters above the 8 strips.
        params = self.params_frame = tk.Frame(extra, bg=hv.BG, pady=0)
        self.param_widgets = []
        for i in range(hud_state.STRIPS):
            cell = tk.Frame(params, bg=hv.PANEL, padx=3, pady=2)
            cell.grid(row=0, column=i, padx=1, sticky="nsew")
            name = self._label(cell, size=9, mono=True, bg=hv.PANEL, fg=hv.DEVICE_COLOR, width=7, anchor="w")
            name.pack(fill="x")
            value = self._label(cell, size=9, mono=True, bg=hv.PANEL, fg="#b8bdc7", width=7, anchor="w")
            value.pack(fill="x")
            self.param_widgets.append((name, value))

        strips = self.strips_frame = tk.Frame(extra, bg=hv.BG, pady=0)
        self.strip_widgets = []
        for i in range(hud_state.STRIPS):
            cell = tk.Frame(strips, bg=hv.PANEL, padx=3, pady=2)
            cell.grid(row=0, column=i, padx=1, sticky="nsew")
            name = self._label(cell, size=9, mono=True, bg=hv.PANEL, width=7, anchor="w")
            name.pack(fill="x")
            value = self._label(cell, size=9, mono=True, bg=hv.PANEL, fg="#b8bdc7", width=7, anchor="w")
            value.pack(fill="x")
            canvas = tk.Canvas(cell, width=METER_WIDTH, height=METER_HEIGHT, bg=hv.PANEL, highlightthickness=0)
            canvas.pack(fill="x", pady=(2, 0))
            self.strip_widgets.append((cell, name, value, canvas))

        for widget in self._all_widgets(self.root):
            widget.bind("<ButtonPress-1>", self._drag_start)
            widget.bind("<B1-Motion>", self._drag_move)
            widget.bind("<ButtonRelease-1>", self._drag_end)
            widget.bind("<Button-3>", self._popup)

    def _all_widgets(self, widget):
        yield widget
        for child in widget.winfo_children():
            yield from self._all_widgets(child)

    def _build_menu(self) -> None:
        tk = self.tk
        menu = self.menu = tk.Menu(self.root, tearoff=False)
        for layout in ("compact", "expanded"):
            menu.add_radiobutton(
                label=layout.capitalize(), variable=self.layout, value=layout, command=self._apply_layout
            )
        opacity = tk.Menu(menu, tearoff=False)
        for value in (1.0, 0.85, 0.7, 0.5):
            opacity.add_radiobutton(
                label=f"{round(value * 100)} %", variable=self.opacity, value=value, command=self._apply_opacity
            )
        menu.add_cascade(label="Opacity", menu=opacity)
        menu.add_command(label="Reset position", command=self._reset_position)
        menu.add_separator()
        menu.add_command(label="Quit HUD", command=self.root.destroy)

    # -- interaction -----------------------------------------------------

    def _drag_start(self, event) -> None:
        self._drag_from = (event.x_root - self.root.winfo_x(), event.y_root - self.root.winfo_y())

    def _drag_move(self, event) -> None:
        if self._drag_from is None:
            return
        dx, dy = self._drag_from
        self.root.geometry(f"+{event.x_root - dx}+{event.y_root - dy}")
        self._dragged = True

    def _drag_end(self, _event) -> None:
        """Keep the dragged spot: as a distance from the anchored corner, saved for next time."""

        self._drag_from = None
        if not self._dragged:
            return
        self._dragged = False
        root = self.root
        size = (root.winfo_reqwidth(), root.winfo_reqheight())
        self.margin = hv.corner_margin(self._corner(), self._area(), size, (root.winfo_x(), root.winfo_y()))
        self._save_position()

    def _reset_position(self) -> None:
        self.margin = None
        self._save_position()
        self._place()

    def _corner(self) -> str:
        corner, _xy = hv.parse_position(self.position)
        return "top-left" if corner == "xy" and self.margin is not None else self.position

    def _load_position(self) -> None:
        """A dragged position from an earlier run, if it was made with the same settings."""

        if self.state_path is None:
            return
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            if data.get("position") == self.position and data.get("monitor") == self.monitor:
                self.margin = (int(data["margin"][0]), int(data["margin"][1]))
        except (OSError, ValueError, KeyError, TypeError, IndexError):
            pass

    def _save_position(self) -> None:
        if self.state_path is None:
            return
        try:
            if self.margin is None:
                self.state_path.unlink(missing_ok=True)
            else:
                data = {"position": self.position, "monitor": self.monitor, "margin": list(self.margin)}
                self.state_path.write_text(json.dumps(data), encoding="utf-8")
        except OSError:
            log.warning("cannot save the HUD position to %s", self.state_path, exc_info=True)

    def _popup(self, event) -> None:
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()

    def _apply_opacity(self) -> None:
        self.root.attributes("-alpha", self.opacity.get())

    def _apply_layout(self) -> None:
        self.params_frame.pack_forget()
        if self.layout.get() == "expanded":
            self.extra.pack(side="right", anchor="n", padx=(0, 12))
            self.strips_frame.pack(fill="x")
            if self._params_shown:
                self.params_frame.pack(fill="x", before=self.strips_frame, pady=(0, 2))
        else:
            self.extra.pack_forget()
        self.root.update_idletasks()
        if not self._dragged:
            self._place()

    def _areas(self) -> list[tuple[int, int, int, int]]:
        root = self.root
        return _monitor_work_areas() or [(0, 0, root.winfo_screenwidth(), root.winfo_screenheight())]

    def _area(self) -> tuple[int, int, int, int]:
        areas = self._areas()
        return areas[self.monitor] if self.monitor < len(areas) else areas[0]

    def _place(self) -> None:
        root = self.root
        size = (root.winfo_reqwidth(), root.winfo_reqheight())
        area = self._area()
        x, y = hv.place_window(self._corner(), area, size, self.corner_margin if self.margin is None else self.margin)
        if self.margin is not None and not hv.on_screen((x, y), size, self._areas()):
            # Dragged onto a monitor that is gone or moved: back to the default spot.
            x, y = hv.place_window(self.position, area, size, self.corner_margin)
        root.geometry(f"+{x}+{y}")

    # -- periodic --------------------------------------------------------

    def _poll(self) -> None:
        now = time.monotonic()
        toasts = None
        try:
            payload = self.receiver.poll()
        except Exception:  # noqa: BLE001 - a bad packet must not kill the window
            log.exception("HUD receive failed")
            payload = None
        if payload is not None:
            try:
                self.snapshot = hud_state.from_dict(payload["state"])
                self.info = payload.get("info") or {}
                self.last_rx = now
                toasts = self.snapshot.toasts
            except Exception:  # noqa: BLE001
                log.exception("bad HUD snapshot")
        linked = self.last_rx is not None and now - self.last_rx < hv.LINK_TIMEOUT
        toast = self.toasts.update(toasts, now)
        self._render(hv.build_view(self.snapshot, self.info, linked=linked, toast=toast))
        self._keep_anchored()
        self.root.after(POLL_MS, self._poll)

    def _keep_anchored(self) -> None:
        """Re-place after a size change so a right/bottom anchor stays put."""

        size = (self.root.winfo_reqwidth(), self.root.winfo_reqheight())
        if size != self._size:
            self._size = size
            if not self._dragged:
                self._place()

    def _refresh_topmost(self) -> None:
        self.root.attributes("-topmost", True)
        self.root.after(TOPMOST_REFRESH_MS, self._refresh_topmost)

    def _check_parent(self) -> None:
        if not _pid_alive(self.parent_pid):
            self.root.destroy()
            return
        self.root.after(PARENT_CHECK_MS, self._check_parent)

    # -- rendering -------------------------------------------------------

    @staticmethod
    def _set(widget, **options) -> None:
        """Configure only what changed, so an idle HUD does no Tk work."""

        changed = {k: v for k, v in options.items() if widget.cget(k) != v}
        if changed:
            widget.configure(**changed)

    def _render(self, view: hv.HudView) -> None:
        s = self._set
        s(self.mode, text=view.mode_text, fg=view.mode_color)
        s(self.bank, text=view.bank_text)
        s(self.selection, text=view.selection_text)
        s(self.transport, text=view.transport_text, fg=view.transport_color)
        s(self.time, text=view.time_text)
        s(self.assignment, text=view.assignment_text)
        s(self.toast, text=view.toast)
        s(self.status, text=view.status_text, fg=view.status_color)
        for name, color in view.badges:
            s(self.badges[name], fg=color)
        s(self.badges["SHIFT"], text=view.shift_text)
        s(self.plugin, text=view.plugin_text)
        if bool(view.plugin_text) != bool(self.plugin.winfo_manager()):
            if view.plugin_text:
                self.plugin.pack(fill="x", after=self.status)
            else:
                self.plugin.pack_forget()
        if bool(view.params) != self._params_shown:
            self._params_shown = bool(view.params)
            self._apply_layout()

        if self.layout.get() != "expanded":
            return
        for (name, value), (label, text) in zip(self.param_widgets, view.params):
            s(name, text=label)
            s(value, text=text)
        for (cell, name, value, canvas), strip in zip(self.strip_widgets, view.strips):
            bg = hv.SELECTED_BG if strip.selected else hv.PANEL
            s(cell, bg=bg)
            s(name, text=strip.name if view.show_strips else "", bg=bg, fg="#ffffff" if strip.peek else hv.FG)
            s(value, text=strip.value if view.show_strips else "", bg=bg)
            s(canvas, bg=bg)
            self._draw_strip(canvas, strip)

    def _draw_strip(self, canvas, strip: hv.StripView) -> None:
        key = (strip.level, strip.clipped, strip.rec, strip.solo, strip.mute)
        if getattr(canvas, "_hud_key", None) == key:
            return
        canvas._hud_key = key
        canvas.delete("all")
        # R / S / M dots, then the meter bar.
        for i, (on, color) in enumerate(
            ((strip.rec, hv.REC_COLOR), (strip.solo, hv.SOLO_COLOR), (strip.mute, hv.MUTE_COLOR))
        ):
            x = 1 + i * 7
            canvas.create_rectangle(x, 3, x + 5, 8, fill=color if on else hv.BG, outline="")
        left = 23
        width = METER_WIDTH - left - 1
        canvas.create_rectangle(left, 3, left + width, 8, fill=hv.BG, outline="")
        if strip.level:
            filled = round(width * min(strip.level, hv.METER_MAX) / hv.METER_MAX)
            canvas.create_rectangle(left, 3, left + filled, 8, fill=hv.meter_color(strip.level), outline="")
        if strip.clipped:
            canvas.create_rectangle(left + width - 3, 1, left + width, 10, fill=hv.METER_RED, outline="")

    def run(self) -> None:
        self.root.mainloop()


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cfg = config_module.load_config(env_path=args.env)

    def pick(value, default):
        return default if value is None else value

    port = pick(args.port, cfg.hud_port)
    try:
        receiver = hud_link.HudReceiver(port)
    except OSError as exc:
        print(f"error: cannot listen on UDP {hud_link.HOST}:{port}: {exc}", file=sys.stderr)
        return 1

    _set_dpi_aware()
    app = HudApp(
        receiver,
        position=pick(args.position, cfg.hud_position),
        monitor=pick(args.monitor, cfg.hud_monitor),
        corner_margin=config_module._as_pair({"m": args.margin}, "m", cfg.hud_margin) if args.margin else cfg.hud_margin,
        opacity=min(max(pick(args.opacity, cfg.hud_opacity), 0.2), 1.0),
        topmost=pick(args.topmost, cfg.hud_topmost),
        click_through=pick(args.click_through, cfg.hud_click_through),
        layout=pick(args.layout, cfg.hud_layout),
        toast_ms=pick(args.toast_ms, cfg.hud_toast_ms),
        parent_pid=args.parent_pid,
        state_path=(cfg.env_path.parent if cfg.env_path else Path.cwd()) / POSITION_FILE,
    )
    try:
        app.run()
    finally:
        receiver.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
