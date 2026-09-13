"""Command-line entry point for the APC40 <-> Cakewalk integration.

Run as either:

    uv run apc40sonar --list-ports     (console script)
    uv run python -m apc40sonar --list-ports

At this stage only ``--list-ports`` is implemented. Because Windows MIDI port
names change between iterations, this command prints the live ports *and*
reports whether the names in the active ``.env`` file resolve, so the config
can be corrected without a reboot. ``--monitor`` and ``--no-show`` are
reserved for the next stage (see plans/apc40-sonar-python-plan.md).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence, TextIO

from . import config as config_module
from . import midi_io

PROG = "apc40sonar"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="Akai APC40 (original) <-> Cakewalk by BandLab control-surface engine.",
    )
    parser.add_argument(
        "--list-ports",
        action="store_true",
        help="List MIDI ports and report whether the configured names resolve.",
    )
    parser.add_argument(
        "--env",
        type=Path,
        default=None,
        metavar="PATH",
        help="Path to the .env file holding the port names (default: auto-detect).",
    )
    return parser


def _report_config(
    cfg: config_module.Config,
    ports: midi_io.MidiPorts,
    stream: TextIO,
) -> bool:
    """Print each configured port and whether it resolves. Return all-resolved."""

    if cfg.env_path is not None:
        print(f"Configuration: {cfg.env_path}", file=stream)
    else:
        print("Configuration: no .env found; using built-in defaults", file=stream)

    # (label, name, output_list, input_list) - a port may be checked in either
    # or both directions.
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


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.list_ports:
        ports = midi_io.print_ports()
        print()
        cfg = config_module.load_config(env_path=args.env)
        resolved = _report_config(cfg, ports, sys.stdout)
        return 0 if resolved else 1

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
