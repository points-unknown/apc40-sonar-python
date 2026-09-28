"""Step sequencer editor: a tkinter window showing and editing the app's pattern.

Runs as its own process (like the HUD) so a slow or crashed window can never
stall MIDI. The app launches it on entering the Step Sequencer (Scene 2) and
closes it on leaving; the pattern itself lives in the app, so the window and
the APC40 grid always agree. It can also be started by hand::

    uv run python -m apc40sonar.seq_editor

Mouse: click a cell = cycle it like a pad tap; right-click = clear; wheel =
velocity +/-5 (Shift: +/-1); click a step number or lane number = move the
APC40's 8 x 5 view there.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Sequence

from . import clipboard
from . import config as config_module
from . import midi_file
from . import seq_link
from . import sequencer as sq

POLL_MS = 30
PARENT_CHECK_MS = 2000
STALE_SECONDS = 2.5

CELL_W = 24
ROW_H = 26
HEADER_H = 22
LANE_W = 200

BG = "#1e1f24"
PANEL = "#2a2c33"
CELL_OFF = "#3a3d46"
CELL_OFF_BEAT = "#454955"
FG = "#e6e6e6"
DIM = "#8a8f99"
PLAYHEAD = "#ffffff"
VIEW = "#60a5fa"
LEVEL_COLORS = {"normal": "#4ade80", "accent": "#fbbf24", "soft": "#f87171"}

FONT_UI = "Segoe UI"
FONT_MONO = "Consolas"

HINT = (
    "Click: cycle   Right-click: clear   Wheel: velocity (Shift = fine)   Right-click a lane: move / remove   "
    "APC40: tap = cycle, hold 1 s = off, hold + any Device knob = velocity"
)
WARN = "#fbbf24"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="apc40sonar.seq_editor", description="apc40sonar step sequencer editor.")
    parser.add_argument("--env", type=Path, default=None, metavar="PATH", help="Path to the .env file.")
    parser.add_argument("--port", type=int, default=None, help="State port (SEQ_EDITOR_PORT); commands go to port + 1.")
    parser.add_argument("--dir", type=Path, default=None, help="Pattern folder (SEQ_DIR), for Open folder.")
    parser.add_argument("--parent-pid", type=int, default=None, help="Exit when this process ends.")
    return parser


# ---------------------------------------------------------------------------
# Pure helpers (tested without a display)
# ---------------------------------------------------------------------------


def nearest_level(velocity: int, velocities: dict[str, int]) -> str | None:
    if velocity <= 0:
        return None
    return min(sq.LEVELS, key=lambda name: abs(velocities[name] - velocity))


def _blend(color: str, background: str, amount: float) -> str:
    a = [int(color[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(background[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x * amount + y * (1 - amount)):02x}" for x, y in zip(a, b))


def cell_color(velocity: int, velocities: dict[str, int], step: int) -> str:
    """Level color, dimmer for quieter velocities; off cells mark every beat."""

    level = nearest_level(velocity, velocities)
    if level is None:
        return CELL_OFF_BEAT if step % 4 == 0 else CELL_OFF
    return _blend(LEVEL_COLORS[level], CELL_OFF, 0.45 + 0.55 * velocity / 127)


def wheel_velocity(current: int, up: bool, fine: bool, velocities: dict[str, int]) -> int:
    """New velocity after one wheel notch; an off step starts at the normal level."""

    if current <= 0:
        return velocities["normal"] if up else 0
    step = 1 if fine else 5
    return max(1, min(127, current + (step if up else -step)))


def _pid_alive(pid: int) -> bool:
    from .hud import _pid_alive as alive

    return alive(pid)


def _window_file(directory: Path) -> Path:
    return directory / "editor-window.txt"


def maps_dir(pattern_dir: Path) -> Path:
    return pattern_dir / "drum-maps"


def map_file_name(name: str) -> str:
    """A safe file name for a drum map called *name*."""

    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .") or "drum map"
    return f"{stem}.json"


def saved_maps(pattern_dir: Path) -> dict[str, Path]:
    """Saved drum maps by display name (the file name without .json)."""

    folder = maps_dir(pattern_dir)
    if not folder.is_dir():
        return {}
    return {path.stem: path for path in sorted(folder.glob("*.json"), key=lambda p: p.stem.lower())}


# ---------------------------------------------------------------------------
# The window
# ---------------------------------------------------------------------------


class EditorApp:
    def __init__(
        self,
        receiver: seq_link.Receiver,
        sender: seq_link.Sender,
        *,
        pattern_dir: Path,
        parent_pid: int | None = None,
    ) -> None:
        import tkinter as tk

        self.tk = tk
        self.receiver = receiver
        self.sender = sender
        self.pattern_dir = pattern_dir
        self.parent_pid = parent_pid
        self.state: dict | None = None
        self.last_rx: float | None = None
        self._grid_key = None
        self._lane_key = None
        self._lane_widgets: list[dict] = []
        self._save_geometry_job = None
        self._lanes_height = 0

        root = self.root = tk.Tk()
        # Sizes are for 96 dpi; scale them so the grid matches the fonts on high-DPI screens.
        scale = max(1.0, root.winfo_fpixels("1i") / 96)
        self.cell_w, self.row_h = round(CELL_W * scale), round(ROW_H * scale)
        self.header_h, self.lane_w = round(HEADER_H * scale), round(LANE_W * scale)
        root.title("APC40 Step Sequencer")
        root.configure(bg=BG)
        root.attributes("-topmost", True)
        self.topmost = tk.BooleanVar(value=True)
        self._restore_geometry()
        self._build()
        root.bind("<Configure>", self._on_configure)
        root.after(POLL_MS, self._poll)
        if parent_pid:
            root.after(PARENT_CHECK_MS, self._check_parent)

    # -- widgets ---------------------------------------------------------

    def _label(self, parent, text="", *, size=9, bold=False, fg=FG, bg=BG, mono=False, **kw):
        font = (FONT_MONO if mono else FONT_UI, size, "bold" if bold else "normal")
        return self.tk.Label(parent, text=text, font=font, fg=fg, bg=bg, **kw)

    def _button(self, parent, text, command, **kw):
        return self.tk.Button(
            parent, text=text, command=command, font=(FONT_UI, 9), fg=FG, bg=PANEL,
            activebackground=CELL_OFF_BEAT, activeforeground=FG, relief="flat", padx=8, **kw,
        )

    def _spinbox(self, parent, low, high, value, command, width=4):
        var = self.tk.StringVar(value=str(value))
        box = self.tk.Spinbox(
            parent, from_=low, to=high, width=width, textvariable=var, font=(FONT_MONO, 10),
            fg=FG, bg=PANEL, buttonbackground=PANEL, insertbackground=FG, relief="flat",
            command=command,
        )
        box.bind("<Return>", lambda _e: command())
        box.bind("<FocusOut>", lambda _e: command())
        return box, var

    def _build(self) -> None:
        tk = self.tk
        self.channel_var = tk.IntVar(value=10)
        self.length_var = tk.IntVar(value=16)
        self.map_var = tk.StringVar(value="")
        self.bars = 4  # the last export length; the toolbar Export reuses it
        self.lead_ms = 40
        self._build_menus()

        # One slim row for what is used all the time; everything else is in the menus.
        bar = tk.Frame(self.root, bg=BG, padx=8, pady=6)
        bar.pack(fill="x")
        self._label(bar, "Steps").pack(side="left")
        self.steps_box, self.steps_var = self._spinbox(bar, 1, sq.MAX_STEPS, 16, self._send_steps)
        self.steps_box.pack(side="left", padx=(4, 12))
        self.map_label = self._label(bar, "", fg=DIM)
        self.map_label.pack(side="left")
        self._button(bar, "Export .mid", self._quick_export).pack(side="right")
        self._button(bar, "Paste from Sonar", self._paste).pack(side="right", padx=(0, 6))

        body = tk.Frame(self.root, bg=BG, padx=8)
        body.pack(fill="both", expand=True)
        self.lanes_canvas = tk.Canvas(body, width=self.lane_w, bg=BG, highlightthickness=0)
        self.lanes_canvas.grid(row=0, column=0, sticky="ns")
        self.grid_canvas = tk.Canvas(body, bg=BG, highlightthickness=0)
        self.grid_canvas.grid(row=0, column=1, sticky="nsew")
        scroll = tk.Scrollbar(body, orient="horizontal", command=self.grid_canvas.xview)
        scroll.grid(row=1, column=1, sticky="ew")
        self.grid_canvas.configure(xscrollcommand=scroll.set)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        c = self.grid_canvas
        c.bind("<Button-1>", self._on_click)
        c.bind("<Button-3>", self._on_right_click)
        c.bind("<MouseWheel>", self._on_wheel)
        c.bind("<Motion>", self._on_motion)
        c.bind("<Leave>", lambda _e: self._set_hover(""))

        foot = tk.Frame(self.root, bg=BG, padx=8, pady=4)
        foot.pack(fill="x")
        self.status = self._label(foot, "Waiting for apc40sonar...", fg=DIM, anchor="w")
        self.status.pack(side="left", fill="x", expand=True)
        self.hover = self._label(foot, "", fg=FG, anchor="e", mono=True)
        self.hover.pack(side="right")

    # -- menus -----------------------------------------------------------

    def _build_menus(self) -> None:
        tk = self.tk
        menubar = tk.Menu(self.root)

        file = tk.Menu(menubar, tearoff=False)
        file.add_command(label="Paste from Sonar", accelerator="Ctrl+V", command=self._paste)
        file.add_command(label="Import .mid...", accelerator="Ctrl+O", command=self._pick_import)
        file.add_command(label="Export .mid...", accelerator="Ctrl+E", command=self._export_dialog)
        file.add_separator()
        file.add_command(label="Open patterns folder", command=self._open_folder)
        menubar.add_cascade(label="File", menu=file)

        pattern = tk.Menu(menubar, tearoff=False)
        pattern.add_command(label="Add lane", command=lambda: self._send({"op": "add_lane"}))
        pattern.add_command(label="Clear all steps...", command=self._confirm_clear)
        pattern.add_separator()
        length = tk.Menu(pattern, tearoff=False)
        for steps in (8, 16, 24, 32, 48, 64):
            length.add_radiobutton(
                label=f"{steps} steps ({steps / 16:g} bar{'' if steps == 16 else 's'})",
                variable=self.length_var, value=steps, command=lambda n=steps: self._send_length(n),
            )
        pattern.add_cascade(label="Length", menu=length)
        channel = tk.Menu(pattern, tearoff=False)
        for number in range(1, 17):
            channel.add_radiobutton(
                label=f"Channel {number}" + ("  (GM drums)" if number == 10 else ""),
                variable=self.channel_var, value=number,
                command=lambda n=number: self._send({"op": "channel", "channel": n}),
            )
        pattern.add_cascade(label="MIDI channel", menu=channel)
        menubar.add_cascade(label="Pattern", menu=pattern)

        self.map_menu = tk.Menu(menubar, tearoff=False, postcommand=self._fill_map_menu)
        menubar.add_cascade(label="Drum map", menu=self.map_menu)
        self._fill_map_menu()

        view = tk.Menu(menubar, tearoff=False)
        view.add_checkbutton(label="Always on top", variable=self.topmost, command=self._apply_topmost)
        view.add_command(label="Playhead lead...", command=self._lead_dialog)
        menubar.add_cascade(label="View", menu=view)

        self.root.configure(menu=menubar)
        for key, action in (("<Control-v>", self._paste), ("<Control-o>", self._pick_import),
                            ("<Control-e>", self._export_dialog)):
            self.root.bind_all(key, lambda e, a=action: self._shortcut(e, a))

    def _shortcut(self, event, action) -> None:
        """Menu shortcuts, except while typing (Ctrl+V in a lane name pastes text)."""

        if isinstance(event.widget, (self.tk.Entry, self.tk.Spinbox)):
            return
        action()

    def _fill_map_menu(self) -> None:
        menu = self.map_menu
        menu.delete(0, "end")
        self._saved_maps = saved_maps(self.pattern_dir)
        for name in sq.DRUM_MAPS:
            menu.add_radiobutton(label=name, variable=self.map_var, value=name,
                                 command=lambda n=name: self._apply_map(n))
        saved = [name for name in self._saved_maps if name not in sq.DRUM_MAPS]
        if saved:
            menu.add_separator()
            for name in saved:
                menu.add_radiobutton(label=name, variable=self.map_var, value=name,
                                     command=lambda n=name: self._apply_map(n))
        menu.add_separator()
        menu.add_command(label="Save current lanes as map...", command=self._save_map)
        menu.add_command(label="Import map...", command=self._import_map)
        menu.add_command(label="Export map...", command=self._export_map)

    def _lead_dialog(self) -> None:
        from tkinter import simpledialog

        value = simpledialog.askinteger(
            "Playhead lead",
            "Draw the playhead this many ms ahead of the clock\n"
            "(raise it if the lights trail the sound; default 40):",
            parent=self.root, initialvalue=self.lead_ms, minvalue=0, maxvalue=500,
        )
        if value is not None:
            self._send({"op": "lead", "ms": value})

    def _export_dialog(self) -> None:
        from tkinter import simpledialog

        bars = simpledialog.askinteger(
            "Export .mid", "How many bars? (the pattern repeats to fill them)",
            parent=self.root, initialvalue=self.bars, minvalue=1, maxvalue=256,
        )
        if bars is not None:
            self.bars = bars
            self._quick_export()

    def _quick_export(self) -> None:
        self._send({"op": "export", "bars": self.bars})

    # -- commands to the app ---------------------------------------------

    def _send(self, cmd: dict) -> None:
        self.sender.send("cmd", cmd)

    def _int(self, var, default: int) -> int:
        try:
            return int(var.get())
        except ValueError:
            return default

    def _send_steps(self) -> None:
        if self.state and self._int(self.steps_var, 0) != self.state["steps"]:
            self._send({"op": "steps", "steps": self._int(self.steps_var, self.state["steps"])})

    def _send_length(self, steps: int) -> None:
        self.steps_var.set(str(steps))
        self._send({"op": "steps", "steps": steps})

    def _paste(self) -> None:
        """Import the MIDI on the clipboard (a clip copied in Sonar)."""

        from tkinter import messagebox

        try:
            data = clipboard.get_midi()
        except clipboard.ClipboardError as exc:
            self._error("Paste", str(exc))
            return
        if data is None:
            self._error("Paste", "There is no MIDI on the clipboard. Copy a MIDI clip in Sonar first.")
            return
        if not messagebox.askyesno(
            "Paste pattern", "Replace the current steps with the copied MIDI? Lane names are kept.", parent=self.root
        ):
            return
        path = self.pattern_dir / "clipboard.mid"
        try:
            self.pattern_dir.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        except OSError as exc:
            self._error("Paste", f"Cannot write {path}: {exc}")
            return
        self._send({"op": "import", "path": str(path)})

    def _pick_import(self) -> None:
        from tkinter import filedialog, messagebox

        path = filedialog.askopenfilename(
            parent=self.root, title="Import a MIDI pattern", initialdir=self.pattern_dir,
            filetypes=[("MIDI files", "*.mid *.midi"), ("All files", "*.*")],
        )
        if not path:
            return
        if not messagebox.askyesno(
            "Import pattern", "Replace the current steps with this file? Lane names are kept.", parent=self.root
        ):
            return
        self._send({"op": "import", "path": path})

    # -- drum maps -------------------------------------------------------

    def _map_lanes(self, name: str) -> list[sq.Lane] | None:
        if name in sq.DRUM_MAPS:
            return list(sq.DRUM_MAPS[name])
        path = self._saved_maps.get(name)
        if path is None:
            return None
        try:
            return sq.map_from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError) as exc:
            self._error("Drum map", f"Cannot read {path.name}: {exc}")
            return None

    def _apply_map(self, name: str) -> None:
        lanes = self._map_lanes(name)
        if lanes is not None:
            self.map_var.set(name)
            self.map_label.configure(text=f"Drum map: {name}")
            self._send({"op": "map", **sq.map_to_dict(name, lanes)})

    def _current_lanes(self) -> list[sq.Lane]:
        return sq.map_from_dict(self.state) if self.state else []

    def _save_map(self) -> None:
        from tkinter import messagebox, simpledialog

        if not self.state:
            return
        name = simpledialog.askstring(
            "Save drum map", "Name for this drum map:", parent=self.root, initialvalue=self.map_var.get()
        )
        if not name or not name.strip():
            return
        name = name.strip()
        if name in sq.DRUM_MAPS:
            self._error("Save drum map", f"{name!r} is a built-in map; choose another name.")
            return
        path = maps_dir(self.pattern_dir) / map_file_name(name)
        if path.exists() and not messagebox.askyesno(
            "Save drum map", f"Replace the saved map {path.stem!r}?", parent=self.root
        ):
            return
        if self._write_map(path, path.stem):
            self.map_var.set(path.stem)
            self.map_label.configure(text=f"Drum map: {path.stem}")

    def _export_map(self) -> None:
        from tkinter import filedialog

        if not self.state:
            return
        path = filedialog.asksaveasfilename(
            parent=self.root, title="Export drum map", defaultextension=".json",
            initialfile=map_file_name(self.map_var.get() or "drum map"),
            filetypes=[("Drum map", "*.json"), ("All files", "*.*")],
        )
        if path:
            self._write_map(Path(path), Path(path).stem)

    def _write_map(self, path: Path, name: str) -> bool:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(sq.map_to_dict(name, self._current_lanes()), indent=1), encoding="utf-8")
        except (OSError, ValueError) as exc:
            self._error("Drum map", f"Cannot write {path}: {exc}")
            return False
        return True

    def _import_map(self) -> None:
        from tkinter import filedialog

        path = filedialog.askopenfilename(
            parent=self.root, title="Import drum map", filetypes=[("Drum map", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            lanes = sq.map_from_dict(data)
        except (OSError, ValueError) as exc:
            self._error("Import drum map", f"Cannot read {Path(path).name}: {exc}")
            return
        name = str(data.get("drum_map") or Path(path).stem)
        target = maps_dir(self.pattern_dir) / map_file_name(name)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(sq.map_to_dict(target.stem, lanes), indent=1), encoding="utf-8")
        except OSError as exc:
            self._error("Import drum map", f"Cannot save it to {target.parent}: {exc}")
            return
        self._saved_maps = saved_maps(self.pattern_dir)
        self._apply_map(target.stem)

    def _error(self, title: str, text: str) -> None:
        from tkinter import messagebox

        messagebox.showerror(title, text, parent=self.root)

    def _confirm_clear(self) -> None:
        from tkinter import messagebox

        if messagebox.askyesno("Clear pattern", "Turn every step off?", parent=self.root):
            self._send({"op": "clear"})

    def _open_folder(self) -> None:
        self.pattern_dir.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(self.pattern_dir)  # noqa: S606 - opens Explorer on our own folder

    def _apply_topmost(self) -> None:
        self.root.attributes("-topmost", self.topmost.get())

    # -- grid mouse ------------------------------------------------------

    def _cell_at(self, event) -> tuple[int, int] | None:
        if self.state is None:
            return None
        x = self.grid_canvas.canvasx(event.x)
        y = event.y - self.header_h
        step, lane = int(x // self.cell_w), int(y // self.row_h) if y >= 0 else -1
        if not 0 <= step < self.state["steps"]:
            return None
        return lane, step

    def _on_click(self, event) -> None:
        cell = self._cell_at(event)
        if cell is None:
            return
        lane, step = cell
        if lane < 0:  # the step-number header: move the APC40 view
            self._send({"op": "view", "step_page": step // self.state["page_steps"]})
        elif lane < len(self.state["lanes"]):
            self._send({"op": "cycle", "lane": lane, "step": step})

    def _on_right_click(self, event) -> None:
        cell = self._cell_at(event)
        if cell is not None and 0 <= cell[0] < len(self.state["lanes"]):
            self._send({"op": "velocity", "lane": cell[0], "step": cell[1], "velocity": 0})

    def _on_wheel(self, event) -> None:
        cell = self._cell_at(event)
        if cell is None or not 0 <= cell[0] < len(self.state["lanes"]):
            return
        lane, step = cell
        current = self.state["lanes"][lane]["steps"][step]
        fine = bool(event.state & 0x0001)  # Shift
        new = wheel_velocity(current, event.delta > 0, fine, self.state["velocities"])
        if new != current:
            self._send({"op": "velocity", "lane": lane, "step": step, "velocity": new})

    def _on_motion(self, event) -> None:
        cell = self._cell_at(event)
        if cell is None or not 0 <= cell[0] < len(self.state["lanes"]):
            self._set_hover("")
            return
        lane, step = cell
        item = self.state["lanes"][lane]
        velocity = item["steps"][step]
        text = f"{item['label']}  step {step + 1}  " + (f"velocity {velocity}" if velocity else "off")
        self._set_hover(text)

    def _set_hover(self, text: str) -> None:
        if self.hover.cget("text") != text:
            self.hover.configure(text=text)

    # -- lanes column ----------------------------------------------------

    def _build_lanes(self, count: int) -> None:
        tk = self.tk
        c = self.lanes_canvas
        c.delete("all")
        self._lane_widgets = []
        for lane in range(count):
            row = tk.Frame(c, bg=BG)
            number = self._label(row, str(lane + 1), fg=DIM, width=2, cursor="hand2")
            number.pack(side="left")
            number.bind("<Button-1>", lambda _e, i=lane: self._send_lane_view(i))
            name_var = tk.StringVar()
            name = tk.Entry(
                row, textvariable=name_var, width=17, font=(FONT_UI, 9), fg=FG, bg=PANEL,
                insertbackground=FG, relief="flat",
            )
            name.pack(side="left", padx=(2, 4))
            name.bind("<Return>", lambda _e, i=lane: self._commit_name(i))
            name.bind("<FocusOut>", lambda _e, i=lane: self._commit_name(i))
            note_box, note_var = self._spinbox(row, 0, 127, 36, lambda i=lane: self._commit_note(i))
            note_box.pack(side="left")
            note_name = self._label(row, "", fg=DIM, width=4, mono=True)
            note_name.pack(side="left", padx=(2, 2))
            for widget in (row, number, name, note_name):
                widget.bind("<Button-3>", lambda e, i=lane: self._lane_menu(e, i))
            c.create_window(0, self.header_h + lane * self.row_h + 1, window=row, anchor="nw", height=self.row_h - 2)
            self._lane_widgets.append(
                {"name": name, "name_var": name_var, "note": note_box, "note_var": note_var, "note_name": note_name,
                 "number": number}
            )
        # Column headings over the first row's widgets, and a column as wide as a row.
        if self._lane_widgets:
            first = self._lane_widgets[0]
            first["name"].master.update_idletasks()
            y = self.header_h // 2
            for text, widget in (("#", first["number"]), ("Name", first["name"]), ("Note", first["note"])):
                c.create_text(widget.winfo_x() + 2, y, text=text, fill=DIM, anchor="w", font=(FONT_UI, 8))
            c.configure(width=max(self.lane_w, first["name"].master.winfo_reqwidth() + 4))

    def _lane_menu(self, event, lane: int) -> None:
        """Right-click on a lane: move, add or remove it."""

        menu = self.tk.Menu(self.root, tearoff=False)
        last = len(self.state["lanes"]) - 1 if self.state else 0
        menu.add_command(label="Move up", state="normal" if lane > 0 else "disabled",
                         command=lambda: self._send({"op": "move_lane", "lane": lane, "delta": -1}))
        menu.add_command(label="Move down", state="normal" if lane < last else "disabled",
                         command=lambda: self._send({"op": "move_lane", "lane": lane, "delta": 1}))
        menu.add_separator()
        menu.add_command(label="Add lane", command=lambda: self._send({"op": "add_lane"}))
        menu.add_command(label="Remove this lane", state="normal" if last > 0 else "disabled",
                         command=lambda: self._send({"op": "remove_lane", "lane": lane}))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _send_lane_view(self, lane: int) -> None:
        if self.state:
            self._send({"op": "view", "lane_page": lane // self.state["page_lanes"]})

    def _commit_name(self, lane: int) -> None:
        if self.state is None or lane >= len(self.state["lanes"]):
            return
        text = self._lane_widgets[lane]["name_var"].get()
        if text != self.state["lanes"][lane]["label"]:
            self._send({"op": "lane", "lane": lane, "name": text})

    def _commit_note(self, lane: int) -> None:
        if self.state is None or lane >= len(self.state["lanes"]):
            return
        note = self._int(self._lane_widgets[lane]["note_var"], -1)
        if 0 <= note <= 127 and note != self.state["lanes"][lane]["note"]:
            self._send({"op": "lane", "lane": lane, "note": note})

    def _render_lanes(self) -> None:
        lanes = self.state["lanes"]
        if len(lanes) != len(self._lane_widgets):
            self._build_lanes(len(lanes))
        focus = self.root.focus_get()
        lane_page, page_lanes = self.state["lane_page"], self.state["page_lanes"]
        for index, (item, widgets) in enumerate(zip(lanes, self._lane_widgets)):
            if focus is not widgets["name"] and widgets["name_var"].get() != item["label"]:
                widgets["name_var"].set(item["label"])
            if focus is not widgets["note"] and widgets["note_var"].get() != str(item["note"]):
                widgets["note_var"].set(str(item["note"]))
            label = sq.note_label(item["note"])
            if widgets["note_name"].cget("text") != label:
                widgets["note_name"].configure(text=label)
            in_view = lane_page * page_lanes <= index < (lane_page + 1) * page_lanes
            color = VIEW if in_view else DIM
            if widgets["number"].cget("fg") != color:
                widgets["number"].configure(fg=color)
        height = self.header_h + len(lanes) * self.row_h + 4
        if self._lanes_height != height:
            self._lanes_height = height
            self.lanes_canvas.configure(height=height)

    # -- grid ------------------------------------------------------------

    def _render_grid(self) -> None:
        s = self.state
        c = self.grid_canvas
        steps, lanes = s["steps"], s["lanes"]
        key = (steps, tuple(tuple(item["steps"]) for item in lanes), tuple(sorted(s["velocities"].items())))
        if key != self._grid_key:
            self._grid_key = key
            c.delete("cell", "header")
            for step in range(steps):
                x = step * self.cell_w
                beat = step % 4 == 0
                c.create_text(
                    x + self.cell_w / 2, self.header_h / 2, text=str(step + 1), tags="header",
                    fill=FG if beat else DIM, font=(FONT_UI, 8, "bold" if beat else "normal"),
                )
                for lane, item in enumerate(lanes):
                    y = self.header_h + lane * self.row_h
                    c.create_rectangle(
                        x + 1, y + 2, x + self.cell_w - 2, y + self.row_h - 3, outline="", tags="cell",
                        fill=cell_color(item["steps"][step], s["velocities"], step),
                    )
            width = steps * self.cell_w
            height = self.header_h + len(lanes) * self.row_h + 4
            c.configure(scrollregion=(0, 0, width, height), height=height, width=min(width, 64 * self.cell_w))
        self._render_overlays()

    def _render_overlays(self) -> None:
        s = self.state
        c = self.grid_canvas
        c.delete("overlay")
        lanes = len(s["lanes"])
        bottom = self.header_h + lanes * self.row_h
        # The APC40's 8 x 5 view.
        x0 = s["step_page"] * s["page_steps"] * self.cell_w
        x1 = min(s["steps"], (s["step_page"] + 1) * s["page_steps"]) * self.cell_w
        y0 = self.header_h + s["lane_page"] * s["page_lanes"] * self.row_h
        y1 = self.header_h + min(lanes, (s["lane_page"] + 1) * s["page_lanes"]) * self.row_h
        c.create_rectangle(x0, y0, x1 - 1, y1 - 1, outline=VIEW, width=2, tags="overlay")
        playing = s.get("playing")
        if playing is not None and playing < s["steps"]:
            x = playing * self.cell_w
            c.create_rectangle(x, self.header_h - 3, x + self.cell_w - 1, bottom, outline=PLAYHEAD, width=1, tags="overlay")

    # -- loop ------------------------------------------------------------

    def _poll(self) -> None:
        try:
            states = self.receiver.poll("state")
            if states:
                self.state = states[-1]
                self.last_rx = time.monotonic()
                self._render()
            elif self.last_rx is not None and time.monotonic() - self.last_rx > STALE_SECONDS:
                self._set_status("apc40sonar is not responding", DIM)
        finally:
            self.root.after(POLL_MS, self._poll)

    def _render(self) -> None:
        s = self.state
        focus = self.root.focus_get()
        if focus is not self.steps_box and self.steps_var.get() != str(s["steps"]):
            self.steps_var.set(str(s["steps"]))
        self.lead_ms = s.get("lead_ms", 40)
        channel = s["lanes"][0]["channel"] if s["lanes"] else 10
        if self.channel_var.get() != channel:
            self.channel_var.set(channel)
        if self.length_var.get() != s["steps"]:
            self.length_var.set(s["steps"])
        self._render_lanes()
        self._render_grid()
        color = WARN if s.get("status_warn") else FG if s.get("status") else DIM
        self._set_status(s.get("status") or HINT, color)

    def _set_status(self, text: str, color: str) -> None:
        if self.status.cget("text") != text or self.status.cget("fg") != color:
            self.status.configure(text=text, fg=color)

    def _check_parent(self) -> None:
        if not _pid_alive(self.parent_pid):
            self.root.destroy()
            return
        self.root.after(PARENT_CHECK_MS, self._check_parent)

    # -- window position (kept across openings) ----------------------------

    def _restore_geometry(self) -> None:
        try:
            text = _window_file(self.pattern_dir).read_text(encoding="utf-8").strip()
        except OSError:
            return
        if text.startswith("+") and text.count("+") == 2:
            self.root.geometry(text)

    def _on_configure(self, event) -> None:
        if event.widget is not self.root:
            return
        if self._save_geometry_job is not None:
            self.root.after_cancel(self._save_geometry_job)
        self._save_geometry_job = self.root.after(500, self._save_geometry)

    def _save_geometry(self) -> None:
        self._save_geometry_job = None
        position = f"+{self.root.winfo_x()}+{self.root.winfo_y()}"
        try:
            self.pattern_dir.mkdir(parents=True, exist_ok=True)
            _window_file(self.pattern_dir).write_text(position, encoding="utf-8")
        except OSError:
            pass

    def run(self) -> None:
        self.root.mainloop()


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cfg = config_module.load_config(env_path=args.env)
    port = cfg.seq_editor_port if args.port is None else args.port
    pattern_dir = cfg.seq_dir if args.dir is None else args.dir
    try:
        receiver = seq_link.Receiver(port)
    except OSError as exc:
        print(f"error: cannot listen on UDP {seq_link.HOST}:{port}: {exc}", file=sys.stderr)
        return 1
    sender = seq_link.Sender(port + 1)

    from .hud import _set_dpi_aware

    _set_dpi_aware()
    app = EditorApp(receiver, sender, pattern_dir=pattern_dir, parent_pid=args.parent_pid)
    try:
        app.run()
    finally:
        receiver.close()
        sender.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
