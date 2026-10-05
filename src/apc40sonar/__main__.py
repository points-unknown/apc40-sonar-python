"""Command-line entry point for the APC40 <-> Cakewalk integration.

Modes:

    uv run apc40sonar --list-ports   list MIDI ports, verify the configured names
    uv run apc40sonar --lightshow    play the startup lightshow, render the ready
                                     state, and exit (verifies the APC40 link)
    uv run apc40sonar                run the full engine (lightshow, then the
                                     APC40 <-> Cakewalk event loop)
    uv run apc40sonar --no-show      as above but skip the lightshow
    uv run apc40sonar --monitor      also print incoming MIDI messages
    uv run apc40sonar --no-hud       run without the on-screen HUD (``HUD`` in
                                     ``.env``, default on; ``--hud`` forces it)

The physical APC40 is opened read+write and put into its configured operating
mode (``APC40_MODE`` in ``.env``) before any other message. The two loopMIDI
cables (``APC40-IN`` write, ``APC40-OUT`` read) are opened best-effort: if
they are missing the app still runs in APC40-only mode, which is enough for the
lightshow test.

The step sequencer's two cables (``SEQ_OUT_PORT`` notes to Cakewalk,
``CLOCK_IN_PORT`` MIDI clock from Cakewalk) are optional too: without the
note output Scene 2 stays off, and without the clock nothing plays.

Run as ``uv run apc40sonar ...`` or ``uv run python -m apc40sonar ...``.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, Sequence, TextIO

from . import apc40
from . import config as config_module
from . import engine
from . import hud_link
from . import lightshow
from . import logging_setup
from . import midi_file
from . import midi_io
from . import seq_link
from . import sequencer as sq
from .hud import POSITION_FILE as HUD_POSITION_FILE

PROG = "apc40sonar"
POLL_SECONDS = 0.02

# Reported to the APC40 in the Type 0 introduction so firmware can adapt.
APP_MAJOR, APP_MINOR, APP_BUGFIX = 0, 1, 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="Akai APC40 (original) <-> Cakewalk by BandLab control-surface engine.",
    )
    parser.add_argument(
        "--list-ports",
        action="store_true",
        help="List MIDI ports and report whether the configured names resolve, then exit.",
    )
    parser.add_argument(
        "--lightshow",
        action="store_true",
        help="Play the startup lightshow, render the ready state, and exit (no event loop).",
    )
    parser.add_argument(
        "--no-show",
        action="store_true",
        help="Skip the startup lightshow.",
    )
    parser.add_argument(
        "--monitor",
        action="store_true",
        help="Print every incoming MIDI message.",
    )
    parser.add_argument(
        "--hud",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Show the on-screen HUD (default: HUD in .env, on).",
    )
    parser.add_argument(
        "--reset-hud-position",
        action="store_true",
        help="Forget where the HUD was dragged; it opens at HUD_POSITION again.",
    )
    parser.add_argument(
        "--env",
        type=Path,
        default=None,
        metavar="PATH",
        help="Path to the .env file holding the port names (default: auto-detect).",
    )
    return parser


def _report_config(cfg: config_module.Config, ports: midi_io.MidiPorts, stream: TextIO) -> bool:
    """Print each configured port and whether it resolves. Return all-resolved."""

    if cfg.env_path is not None:
        print(f"Configuration: {cfg.env_path}", file=stream)
    else:
        print("Configuration: no .env found; using built-in defaults", file=stream)

    checks: list[tuple[str, str, list[str] | None, list[str] | None]] = [
        ("apc40   (read+write)", cfg.apc40_port, ports.outputs, ports.inputs),
        ("mcu_out (app->CW)    ", cfg.mcu_out_port, ports.outputs, None),
        ("mcu_in  (CW->app)    ", cfg.mcu_in_port, None, ports.inputs),
    ]
    # Step sequencer cables: optional, reported without failing the check.
    optional = [
        ("seq_out (app->CW)    ", cfg.seq_out_port, ports.outputs, "Scene 2 sequencer off"),
        ("clock   (CW->app)    ", cfg.clock_in_port, ports.inputs, "the sequencer will not play"),
    ]

    print("Configured ports:", file=stream)
    all_ok = True
    for label, name, outputs, inputs in checks:
        details: list[str] = []
        ok = True
        for direction, names in (("out", outputs), ("in", inputs)):
            if names is None:
                continue
            try:
                index = midi_io.resolve_index(names, name)
            except LookupError:
                ok = False
                details.append(f"{direction}: MISSING")
            else:
                details.append(f"{direction}: index {index}")
        all_ok = all_ok and ok
        status = "OK  " if ok else "FAIL"
        print(f"  [{status}] {label} {name!r} ({', '.join(details)})", file=stream)

    print("Step sequencer and plug-in (C4) ports (optional):", file=stream)
    optional += [
        ("c4_out  (app->CW)    ", cfg.c4_out_port, ports.outputs, "no plug-in control"),
        ("c4_in   (CW->app)    ", cfg.c4_in_port, ports.inputs, "no plug-in control"),
    ]
    for label, name, names, effect in optional:
        try:
            detail = f"index {midi_io.resolve_index(names, name)}"
            status = "OK  "
        except LookupError:
            detail, status = f"missing: {effect}", "--  "
        print(f"  [{status}] {label} {name!r} ({detail})", file=stream)

    return all_ok


def _open_mcu(cfg: config_module.Config, log: logging.Logger, *, sysex: bool = False):
    """Open the two loopMIDI cables best-effort. Returns (out, in), either may be None.

    *sysex* keeps Cakewalk's LCD SysEx on the input (for the HUD).
    """

    mcu_out = mcu_in = None
    try:
        mcu_out = midi_io.open_output(cfg.mcu_out_port, cfg.client_name)
        log.info("opened MCU output %r", cfg.mcu_out_port)
    except Exception as exc:  # noqa: BLE001 - report and degrade, do not abort
        log.warning("MCU output port %r unavailable: %s", cfg.mcu_out_port, exc)
        print(
            f"warning: MCU output port {cfg.mcu_out_port!r} unavailable ({exc}); "
            "running APC40-only",
            file=sys.stderr,
        )
    try:
        mcu_in = midi_io.open_input(cfg.mcu_in_port, cfg.client_name, ignore_sysex=not sysex)
        log.info("opened MCU input %r", cfg.mcu_in_port)
    except Exception as exc:  # noqa: BLE001
        log.warning("MCU input port %r unavailable: %s", cfg.mcu_in_port, exc)
        print(
            f"warning: MCU input port {cfg.mcu_in_port!r} unavailable ({exc}); "
            "no Cakewalk feedback",
            file=sys.stderr,
        )
    return mcu_out, mcu_in


def _open_sequencer(cfg: config_module.Config, log: logging.Logger, monitor: bool):
    """Open the sequencer cables best-effort. Returns (sequencer, out, in).

    The sequencer exists when its note output opened; clock messages are
    handled on rtmidi's input thread so notes go out on the clock, not on
    the 20 ms run loop.
    """

    try:
        seq_out = midi_io.open_output(cfg.seq_out_port, cfg.client_name)
    except Exception as exc:  # noqa: BLE001 - optional feature
        log.info("sequencer output %r unavailable: %s", cfg.seq_out_port, exc)
        print(f"note: sequencer port {cfg.seq_out_port!r} unavailable; Scene 2 off", file=sys.stderr)
        return None, None, None
    log.info("opened sequencer output %r", cfg.seq_out_port)

    def seq_send(message: Sequence[int]) -> None:
        if monitor:
            print(f"seq> {list(message)}")
        seq_out.send_message(list(message))

    normal, accent, soft = cfg.seq_velocities
    seq = sq.Sequencer(
        seq_send,
        lanes=[sq.Lane(note, cfg.seq_channel) for note in cfg.seq_notes],
        steps=cfg.seq_steps,
        velocities={"normal": normal, "accent": accent, "soft": soft},
    )
    saved = _pattern_file(cfg)
    try:
        if saved.is_file() and seq.load_dict(json.loads(saved.read_text(encoding="utf-8"))):
            log.info("loaded sequencer pattern %s", saved)
    except (OSError, ValueError) as exc:
        log.warning("cannot load sequencer pattern %s: %s", saved, exc)

    clock_in = None
    try:
        clock_in = midi_io.open_input(cfg.clock_in_port, cfg.client_name, ignore_timing=False)
    except Exception as exc:  # noqa: BLE001
        log.warning("clock input %r unavailable: %s", cfg.clock_in_port, exc)
        print(f"warning: clock port {cfg.clock_in_port!r} unavailable; the sequencer will not play",
              file=sys.stderr)
        return seq, seq_out, None
    log.info("opened clock input %r", cfg.clock_in_port)

    def on_clock(event, _data=None) -> None:
        message, _delta = event
        if monitor and message and message[0] != sq.CLOCK:
            print(f"clk: {message}")
        try:
            seq.on_clock(message)
        except Exception:  # noqa: BLE001 - never kill rtmidi's thread
            log.exception("sequencer error for clock message %r", message)

    clock_in.set_callback(on_clock)
    return seq, seq_out, clock_in


def _open_c4(cfg: config_module.Config, log: logging.Logger):
    """Open the C4 surface cables best-effort. Returns (out, in), or (None, None).

    Both are needed: Cakewalk only enables the C4 after the app answers its
    serial-number query (SysEx on the input).
    """

    if not cfg.c4:
        return None, None
    try:
        c4_out = midi_io.open_output(cfg.c4_out_port, cfg.client_name)
        c4_in = midi_io.open_input(cfg.c4_in_port, cfg.client_name, ignore_sysex=False)
    except Exception as exc:  # noqa: BLE001 - optional feature
        log.info("C4 ports %r / %r unavailable: %s", cfg.c4_out_port, cfg.c4_in_port, exc)
        print(f"note: C4 ports {cfg.c4_out_port!r} / {cfg.c4_in_port!r} unavailable; no plug-in control",
              file=sys.stderr)
        return None, None
    log.info("opened C4 ports %r / %r", cfg.c4_out_port, cfg.c4_in_port)
    return c4_out, c4_in


def _drain(
    port,
    handler: Callable[[Sequence[int]], None],
    label: str,
    monitor: bool,
    log: logging.Logger,
) -> None:
    """Dispatch every queued message from *port* until it is empty.

    A handler that raises is logged and skipped so a single bad event cannot
    stall the event loop or drop later messages.
    """

    while True:
        item = port.get_message()
        if item is None:
            return
        message, _delta = item
        if monitor:
            print(f"{label}: {message}")
        try:
            handler(message)
        except Exception:  # noqa: BLE001 - isolate per-message failures
            log.exception("handler error for %s message %r", label, message)


def _pattern_file(cfg: config_module.Config) -> Path:
    return cfg.seq_dir / "current.json"


def _settings_file(cfg: config_module.Config) -> Path:
    return cfg.seq_dir / "settings.json"


def _load_settings(cfg: config_module.Config) -> dict:
    """Sequencer settings changed in the editor (they override .env)."""

    try:
        data = json.loads(_settings_file(cfg).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


class _SeqEditor:
    """The sequencer's editor window, its UDP link, pattern autosave and .mid export.

    The window runs as a child process only while the Step Sequencer mode is
    active: entering Scene 2 opens it, leaving closes it. Closing it by hand
    keeps it closed until the next time Scene 2 is entered.
    """

    SAVE_DELAY = 1.0  # seconds after the last edit

    def __init__(self, cfg: config_module.Config, env_path: Path | None, seq: sq.Sequencer, log: logging.Logger):
        self.cfg = cfg
        self.seq = seq
        self.log = log
        self.argv = [sys.executable, "-m", "apc40sonar.seq_editor", "--parent-pid", str(os.getpid())]
        self.argv += ["--port", str(cfg.seq_editor_port), "--dir", str(cfg.seq_dir)]
        if env_path is not None:
            self.argv += ["--env", str(env_path)]
        self.publisher = seq_link.StatePublisher(seq_link.Sender(cfg.seq_editor_port))
        self.commands: seq_link.Receiver | None = None
        try:
            self.commands = seq_link.Receiver(cfg.seq_editor_port + 1)
        except OSError as exc:
            log.warning("sequencer editor commands unavailable (UDP %d): %s", cfg.seq_editor_port + 1, exc)
        self.process: hud_link.HudProcess | None = None
        self._was_active = False
        self._saved_version = seq.version
        self._save_at: float | None = None
        self._saved_lead: int | None = None

    def update(self, eng: engine.Engine) -> None:
        active = eng.mode == "sequencer"
        if active and not self._was_active and self.cfg.seq_editor and self.commands is not None:
            self.process = hud_link.HudProcess(self.argv, max_restarts=0, name="sequencer editor")
            self.process.start()
            self.publisher.reset()
        elif not active and self._was_active and self.process is not None:
            self.process.stop()
            self.process = None
        self._was_active = active

        if self.commands is not None:
            for cmd in self.commands.poll("cmd"):
                if cmd.get("op") == "export":
                    self._export(eng, cmd.get("bars", 4))
                elif cmd.get("op") == "import":
                    self._import(eng, cmd.get("path", ""))
                else:
                    eng.seq_command(cmd)
        if self.process is not None:
            self.process.poll()
            self.publisher.publish(eng.seq_state())
        self._autosave()
        self._save_settings(eng)

    def _save_settings(self, eng: engine.Engine) -> None:
        """Keep the editor's display lead across restarts."""

        lead = eng.seq_display_lead_ms
        if self._saved_lead is None:
            self._saved_lead = lead  # the value at startup is already stored
            return
        if lead == self._saved_lead:
            return
        self._saved_lead = lead
        path = _settings_file(self.cfg)
        try:
            data = _load_settings(self.cfg)
            data["display_lead_ms"] = lead
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, indent=1), encoding="utf-8")
        except OSError as exc:
            self.log.warning("cannot save sequencer settings %s: %s", path, exc)

    def _export(self, eng: engine.Engine, bars) -> None:
        try:
            bars = max(1, min(256, int(bars)))
            path = midi_file.export(self.seq, self.cfg.seq_dir, bars, time.strftime("%Y%m%d-%H%M%S"))
        except (OSError, TypeError, ValueError) as exc:
            self.log.warning("MIDI export failed: %s", exc)
            eng.seq_status = f"Export failed: {exc}"
            return
        self.log.info("exported %d bars to %s", bars, path)
        eng.seq_status = f"Exported {bars} bars: {path}  (drag it onto a Cakewalk track)"
        eng.toast(f"Exported {path.name}")
        if sys.platform == "win32":
            try:  # Explorer with the new file selected, ready to drag into Sonar
                subprocess.Popen(["explorer", f"/select,{path}"])
            except OSError as exc:
                self.log.warning("cannot open Explorer: %s", exc)

    def _import(self, eng: engine.Engine, path: str) -> None:
        try:
            data = Path(path).read_bytes()
            pattern, summary = midi_file.import_pattern(data, self.seq.to_dict())
        except (OSError, midi_file.MidiFileError) as exc:
            self.log.warning("MIDI import of %s failed: %s", path, exc)
            eng.seq_status = f"Import failed: {exc}"
            return
        eng.seq_command({"op": "load", "pattern": pattern})
        self.log.info("imported %s: %s", path, summary)
        eng.seq_status = f"Imported {Path(path).name}: {summary}"
        eng.toast("Pattern imported")

    def _autosave(self, *, now: bool = False) -> None:
        version = self.seq.version
        if version == self._saved_version:
            return
        clock = time.monotonic()
        if self._save_at is None:
            self._save_at = clock + self.SAVE_DELAY
        if not now and clock < self._save_at:
            return
        self._save_at = None
        path = _pattern_file(self.cfg)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.seq.to_dict(), indent=1), encoding="utf-8")
            os.replace(tmp, path)
            self._saved_version = version
        except OSError as exc:
            self.log.warning("cannot save sequencer pattern %s: %s", path, exc)
            self._saved_version = version  # do not retry every frame

    def stop(self) -> None:
        if self.process is not None:
            self.process.stop()
            self.process = None
        self._autosave(now=True)
        self.publisher.sender.close()
        if self.commands is not None:
            self.commands.close()


class _Hud:
    """The HUD child process and the publisher feeding it."""

    def __init__(self, cfg: config_module.Config, env_path: Path | None, info: dict) -> None:
        argv = [sys.executable, "-m", "apc40sonar.hud", "--parent-pid", str(os.getpid())]
        argv += ["--port", str(cfg.hud_port)]
        if env_path is not None:
            argv += ["--env", str(env_path)]
        self.publisher = hud_link.HudPublisher(cfg.hud_port, info=info)
        self.process = hud_link.HudProcess(argv)
        self._next_check = 0.0

    def start(self) -> None:
        self.process.start()

    def update(self, eng: engine.Engine) -> None:
        """Publish a snapshot when due; check the child about once a second."""

        if self.publisher.due():
            self.publisher.publish(eng.hud_snapshot())
        now = time.monotonic()
        if now >= self._next_check:
            self._next_check = now + 1.0
            self.process.poll()

    def stop(self) -> None:
        self.process.stop()
        self.publisher.close()


def _run(args: argparse.Namespace) -> int:
    log = logging_setup.setup_logging()
    cfg = config_module.load_config(env_path=args.env)

    try:
        mode_id = apc40.resolve_mode(cfg.apc40_mode)
    except ValueError as exc:
        log.error("%s", exc)
        print(f"error: {exc}", file=sys.stderr)
        return 2

    log.info(
        "starting: apc40=%r mcu_out=%r mcu_in=%r mode=%s env=%s",
        cfg.apc40_port,
        cfg.mcu_out_port,
        cfg.mcu_in_port,
        cfg.apc40_mode,
        cfg.env_path,
    )

    try:
        apc_in = midi_io.open_input(cfg.apc40_port, cfg.client_name)
        apc_out_handle = midi_io.open_output(cfg.apc40_port, cfg.client_name)
    except Exception as exc:  # noqa: BLE001 - LookupError (missing) or backend error (busy)
        log.exception("cannot open APC40 port %r", cfg.apc40_port)
        print(f"error: cannot open APC40 port {cfg.apc40_port!r}: {exc}", file=sys.stderr)
        return 1
    log.info("opened APC40 input and output")

    hud_on = cfg.hud if args.hud is None else args.hud
    mcu_out, mcu_in = _open_mcu(cfg, log, sysex=hud_on and cfg.hud_lcd)

    def apc_send(message: Sequence[int]) -> None:
        if args.monitor:
            print(f"apc> {list(message)}")
        apc_out_handle.send_message(list(message))

    apc_out = apc40.Apc40Output(apc_send)
    seq, seq_out, clock_in = _open_sequencer(cfg, log, args.monitor)

    def mcu_send(message: Sequence[int]) -> None:
        if args.monitor:
            print(f"mcu> {list(message)}")
        if mcu_out is not None:
            mcu_out.send_message(list(message))

    c4_out, c4_in = _open_c4(cfg, log)

    def c4_send(message: Sequence[int]) -> None:
        if args.monitor:
            print(f"c4> {list(message)}")
        c4_out.send_message(list(message))

    # Select the operating mode before any other APC40-specific message.
    introduction = apc40.build_introduction(
        mode_id, major=APP_MAJOR, minor=APP_MINOR, bugfix=APP_BUGFIX
    )
    apc_send(introduction)
    log.info("sent APC40 introduction for mode 0x%02X", mode_id)

    eng = engine.Engine(
        apc_out,
        mcu_send,
        knob_step_limit=cfg.knob_step_limit,
        knob_noise_threshold=cfg.knob_noise_threshold,
        meters=cfg.meters,
        meter_decay_frames=round(cfg.meter_decay_ms / 1000 / POLL_SECONDS),
        meter_settle_frames=round(0.5 / POLL_SECONDS),
        stop_double_frames=round(0.4 / POLL_SECONDS),
        zoom_step_units=cfg.zoom_step_units,
        zoom_idle_frames=round(cfg.zoom_idle_ms / 1000 / POLL_SECONDS),
        cue_step=cfg.cue_step,
        shift_cue_step=cfg.shift_cue_step,
        nudge_step=cfg.nudge_step,
        nudge_hold_frames=round(0.4 / POLL_SECONDS),
        nudge_repeat_frames=round(cfg.nudge_repeat_ms / 1000 / POLL_SECONDS),
        shift_oneshot_frames=round(cfg.shift_oneshot_ms / 1000 / POLL_SECONDS),
        shift_double_frames=round(0.4 / POLL_SECONDS),
        sequencer=seq,
        seq_indicator_frames=round(0.6 / POLL_SECONDS),
        seq_hold_frames=round(1.0 / POLL_SECONDS),
        seq_clock_frames=round(1.5 / POLL_SECONDS),
        seq_display_lead_ms=_load_settings(cfg).get("display_lead_ms", cfg.seq_display_lead_ms),
        c4_send=c4_send if c4_out is not None else None,
        c4_knob_step_limit=cfg.c4_knob_step_limit,
        c4_reset_on_select=cfg.c4_reset_on_select,
    )

    hud: _Hud | None = None
    editor = _SeqEditor(cfg, args.env, seq, log) if seq is not None else None
    try:
        if not args.no_show:
            print("startup lightshow...")
            log.info("startup lightshow begin")
            lightshow.play(apc_out)
            log.info("startup lightshow complete")

        eng.render_baseline()
        log.info("ready state rendered (mode %s)", eng.knob_mode)

        if args.lightshow:
            print("lightshow complete; APC40 surface ready")
            return 0

        if hud_on:
            if args.reset_hud_position:
                saved = (cfg.env_path.parent if cfg.env_path else Path.cwd()) / HUD_POSITION_FILE
                saved.unlink(missing_ok=True)
                log.info("HUD position reset")
            try:
                hud = _Hud(cfg, args.env, {"mcu_out": mcu_out is not None, "mcu_in": mcu_in is not None})
                hud.start()
            except OSError as exc:
                log.warning("HUD unavailable: %s", exc)
                hud = None

        eng.c4_connect()

        print("running - press Ctrl+C to stop")
        try:
            while True:
                _drain(apc_in, eng.on_apc_message, "apc", args.monitor, log)
                if mcu_in is not None:
                    _drain(mcu_in, eng.on_mcu_message, "mcu", args.monitor, log)
                if c4_in is not None:
                    _drain(c4_in, eng.on_c4_message, "c4", args.monitor, log)
                eng.tick()
                if hud is not None:
                    try:
                        hud.update(eng)
                    except Exception:  # noqa: BLE001 - the HUD must never stop MIDI
                        log.exception("HUD update failed; HUD disabled")
                        hud.stop()
                        hud = None
                if editor is not None:
                    try:
                        editor.update(eng)
                    except Exception:  # noqa: BLE001 - the editor must never stop MIDI
                        log.exception("sequencer editor update failed; editor disabled")
                        editor.stop()
                        editor = None
                time.sleep(POLL_SECONDS)
        except KeyboardInterrupt:
            print("\nstopping")
            log.info("stopped by user")
            try:
                lightshow.goodbye(apc_out)  # leave the panel dark: app not running
            except Exception:  # noqa: BLE001 - a failed farewell must not block exit
                log.exception("exit animation failed")
        return 0
    finally:
        if hud is not None:
            hud.stop()
        if editor is not None:
            editor.stop()
        if clock_in is not None:
            clock_in.cancel_callback()
        if seq is not None:
            seq.all_notes_off()
        del apc_in, apc_out_handle, mcu_out, mcu_in, seq_out, clock_in, c4_out, c4_in


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.list_ports:
        ports = midi_io.print_ports()
        print()
        cfg = config_module.load_config(env_path=args.env)
        resolved = _report_config(cfg, ports, sys.stdout)
        return 0 if resolved else 1

    return _run(args)


if __name__ == "__main__":
    raise SystemExit(main())
