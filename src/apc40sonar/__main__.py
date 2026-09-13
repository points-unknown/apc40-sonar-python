"""Command-line entry point for the APC40 <-> Cakewalk integration.

Modes:

    uv run apc40sonar --list-ports   list MIDI ports, verify the configured names
    uv run apc40sonar --lightshow    play the startup lightshow, render the ready
                                     state, and exit (verifies the APC40 link)
    uv run apc40sonar                run the full engine (lightshow, then the
                                     APC40 <-> Cakewalk event loop)
    uv run apc40sonar --no-show      as above but skip the lightshow
    uv run apc40sonar --monitor      also print incoming MIDI messages

The physical APC40 is opened read+write. The two loopMIDI cables (``APC40-MCU``
write, ``APC40-DEBUG`` read) are opened best-effort: if they are missing the app
still runs in APC40-only mode, which is enough for the lightshow test.

Run as ``uv run apc40sonar ...`` or ``uv run python -m apc40sonar ...``.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Callable, Sequence, TextIO

from . import apc40
from . import config as config_module
from . import engine
from . import lightshow
from . import midi_io

PROG = "apc40sonar"
POLL_SECONDS = 0.02


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

    return all_ok


def _open_mcu(cfg: config_module.Config):
    """Open the two loopMIDI cables best-effort. Returns (out, in), either may be None."""

    mcu_out = mcu_in = None
    try:
        mcu_out = midi_io.open_output(cfg.mcu_out_port, cfg.client_name)
    except Exception as exc:  # noqa: BLE001 - report and degrade, do not abort
        print(
            f"warning: MCU output port {cfg.mcu_out_port!r} unavailable ({exc}); "
            "running APC40-only",
            file=sys.stderr,
        )
    try:
        mcu_in = midi_io.open_input(cfg.mcu_in_port, cfg.client_name)
    except Exception as exc:  # noqa: BLE001
        print(
            f"warning: MCU input port {cfg.mcu_in_port!r} unavailable ({exc}); "
            "no Cakewalk feedback",
            file=sys.stderr,
        )
    return mcu_out, mcu_in


def _drain(port, handler: Callable[[Sequence[int]], None], label: str, monitor: bool) -> None:
    """Dispatch every queued message from *port* until it is empty."""

    while True:
        item = port.get_message()
        if item is None:
            return
        message, _delta = item
        if monitor:
            print(f"{label}: {message}")
        handler(message)


def _run(args: argparse.Namespace) -> int:
    cfg = config_module.load_config(env_path=args.env)

    try:
        apc_in = midi_io.open_input(cfg.apc40_port, cfg.client_name)
        apc_out_handle = midi_io.open_output(cfg.apc40_port, cfg.client_name)
    except Exception as exc:  # noqa: BLE001 - LookupError (missing) or backend error (busy)
        print(f"error: cannot open APC40 port {cfg.apc40_port!r}: {exc}", file=sys.stderr)
        return 1

    mcu_out, mcu_in = _open_mcu(cfg)

    apc_out = apc40.Apc40Output(lambda message: apc_out_handle.send_message(list(message)))

    def mcu_send(message: Sequence[int]) -> None:
        if mcu_out is not None:
            mcu_out.send_message(list(message))

    eng = engine.Engine(apc_out, mcu_send)

    try:
        if not args.no_show:
            print("startup lightshow...")
            lightshow.play(apc_out)

        eng.render_baseline()

        if args.lightshow:
            print("lightshow complete; APC40 surface ready")
            return 0

        print("running - press Ctrl+C to stop")
        try:
            while True:
                _drain(apc_in, eng.on_apc_message, "apc", args.monitor)
                if mcu_in is not None:
                    _drain(mcu_in, eng.on_mcu_message, "mcu", args.monitor)
                eng.tick()
                time.sleep(POLL_SECONDS)
        except KeyboardInterrupt:
            print("\nstopping")
        return 0
    finally:
        del apc_in, apc_out_handle, mcu_out, mcu_in


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
