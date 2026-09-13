"""MIDI I/O layer for the APC40 <-> Cakewalk integration.

This module is the only place that talks to python-rtmidi. Everything else in
the application works with port *names*, never raw indices, because Windows MIDI
indices are not stable across device/loopMIDI restarts.

Port topology (see docs/setup-loopmidi-and-cakewalk.md):

    Akai APC40   physical device      read + write   this app only
    APC40-MCU    app  -> Cakewalk     write          Cakewalk surface In Port
    APC40-DEBUG  Cakewalk -> app      read           Cakewalk surface Out Port

Note: python-rtmidi (WinMM backend) reports port names with a trailing
``" <index>"`` suffix, e.g. ``"Akai APC40 3"``. Name resolution strips that
suffix and matches case-insensitively, so the configured names from the docs
(``"Akai APC40"``, ``"APC40-MCU"``, ``"APC40-DEBUG"``) resolve correctly.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Sequence, TextIO

import rtmidi

DEFAULT_CLIENT_NAME = "apc40sonar"


@dataclass(frozen=True)
class MidiPorts:
    """Snapshot of the ports currently visible to the Windows MIDI stack."""

    inputs: list[str]
    outputs: list[str]


def strip_index(name: str) -> str:
    """Return *name* without a trailing ``" <digits>"`` index suffix.

    python-rtmidi appends the backend index to every port name, for example
    ``"APC40-MCU 1"``. Configuration and the Akai/MCU docs use the plain name,
    so this normalizes both sides of a comparison.
    """

    base, sep, tail = name.rpartition(" ")
    if sep and tail.isdigit():
        return base
    return name


def list_ports() -> MidiPorts:
    """Return the currently available input and output port names.

    Names are normalized with :func:`strip_index` so they match the
    configuration file and the documentation. No ports are opened.
    """

    midi_out = rtmidi.MidiOut()
    midi_in = rtmidi.MidiIn()
    try:
        inputs = [strip_index(n) for n in midi_in.get_ports()]
        outputs = [strip_index(n) for n in midi_out.get_ports()]
    finally:
        del midi_in, midi_out
    return MidiPorts(inputs=inputs, outputs=outputs)


def resolve_index(names: Sequence[str], wanted: str) -> int:
    """Resolve a configured port *name* to its index within *names*.

    Matching is case-insensitive and ignores the trailing index suffix. An
    exact (normalized) match wins; otherwise a unique substring match is
    accepted. Raises :class:`LookupError` listing the available ports when no
    candidate matches, which is the common failure mode when loopMIDI is not
    running.
    """

    normalized = [strip_index(n) for n in names]
    target = wanted.strip().casefold()

    for index, name in enumerate(normalized):
        if name.casefold() == target:
            return index

    matches = [index for index, name in enumerate(normalized) if target in name.casefold()]
    if len(matches) == 1:
        return matches[0]

    raise LookupError(
        f"MIDI port {wanted!r} not found. Available ports: {normalized}"
    )


def _open(factory, wanted: str, client_name: str, **open_kwargs):
    """Create a rtmidi object and open the port named *wanted* on it."""

    midi = factory()
    try:
        index = resolve_index(midi.get_ports(), wanted)
        midi.open_port(index, client_name, **open_kwargs)
    except Exception:
        del midi
        raise
    return midi


def open_output(name: str, client_name: str = DEFAULT_CLIENT_NAME) -> "rtmidi.MidiOut":
    """Open the output port named *name* for writing."""

    return _open(rtmidi.MidiOut, name, client_name)


def open_input(
    name: str,
    client_name: str = DEFAULT_CLIENT_NAME,
    *,
    ignore_sysex: bool = True,
    ignore_timing: bool = True,
    ignore_active_sense: bool = True,
) -> "rtmidi.MidiIn":
    """Open the input port named *name* for reading.

    SysEx is ignored by default because the MCU LCD text it carries is unused
    (the APC40 has no display). Timing and active-sense are ignored as well;
    only Note/CC/Pitch-Bend messages are needed. Set the flags to ``False`` to
    receive those message types during diagnosis.
    """

    midi = _open(rtmidi.MidiIn, name, client_name)
    midi.ignore_types(ignore_sysex, ignore_timing, ignore_active_sense)
    return midi


def print_ports(stream: TextIO = sys.stdout) -> MidiPorts:
    """Print the available ports in the documented layout and return them."""

    ports = list_ports()

    print(f"MIDI OUT devices: {len(ports.outputs)}", file=stream)
    for index, name in enumerate(ports.outputs):
        print(f"  {index}: {name}", file=stream)

    print(file=stream)

    print(f"MIDI IN devices: {len(ports.inputs)}", file=stream)
    for index, name in enumerate(ports.inputs):
        print(f"  {index}: {name}", file=stream)

    return ports
