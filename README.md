# apc40sonar

Standalone Python integration between an **original Akai APC40** and **Cakewalk by
BandLab**, where the APC40 acts as an eight-channel mixer plus transport, knob modes,
plug-in control, and grid macros, with reliable **bidirectional** feedback (Cakewalk
state drives the APC40 LEDs and rings).

This replaces the earlier MIDIMonster + Lua prototype. The protocol and design work is
reused; the transport layer is now owned directly so the app can send exactly the bytes
it intends (real Note Offs, no output de-duplication) and log/test everything.

Design and reference material:

- [`plans/apc40-sonar-python-handoff.md`](plans/apc40-sonar-python-handoff.md) - start here
- [`plans/apc40-sonar-python-plan.md`](plans/apc40-sonar-python-plan.md) - module layout and behavior spec
- [`docs/apc40-communications-protocol.md`](docs/apc40-communications-protocol.md) - Akai protocol
- [`docs/apc40-output-reference.md`](docs/apc40-output-reference.md) - LED/ring authority
- [`docs/mcu-mapping.md`](docs/mcu-mapping.md) - Mackie Control mapping
- [`docs/setup-loopmidi-and-cakewalk.md`](docs/setup-loopmidi-and-cakewalk.md) - port topology and Cakewalk setup
- [`reference/`](reference/) - validated Lua engine and frozen baseline lightshow

## Status

Mixer core implemented and unit-tested (55 tests, no hardware required):

- `midi_io` - port enumeration, case-insensitive name resolution, open helpers
- `config` - port names loaded from an editable `.env` (no hard-coded names, no reboot to change)
- `apc40` - note/CC constants, color and ring values, message builders, and a
  cached/forced output renderer for LEDs and rings
- `mcu` - MCU encoders (real Note On/Off buttons, 14-bit faders, relative V-pot
  deltas, packed ring bytes) and decoders
- `engine` - mixer core: faders, strip buttons, transport, clip grid, knob modes
  (Pan/Send A/B/C with ring styles and pan centering), MCU feedback rendering,
  and momentary flashes
- `--list-ports` - prints live ports and verifies the configured names resolve

Next: run loop and the startup lightshow (ported from `reference/baseline/`), then
end-to-end validation with Cakewalk. See the plan.

## Requirements

- Python 3.14 (managed by `uv`; see `.python-version`)
- `uv` (this machine: `%USERPROFILE%\.local\bin\uv.exe`, not on `PATH`)
- Windows MIDI: the physical `Akai APC40` plus two loopMIDI cables, `APC40-MCU` and
  `APC40-DEBUG` (see the setup doc)

## Setup

```bat
uv sync
```

## Configuration

Port names live in `.env` (copied from [`.env.example`](.env.example)) and are read at
startup. Windows renames loopMIDI cables between iterations, so edit `.env` rather than
the code:

```ini
APC40_PORT=Akai APC40
MCU_OUT_PORT=APC40-MCU
MCU_IN_PORT=APC40-DEBUG
APC40_CLIENT_NAME=apc40sonar
```

`APC40SONAR_ENV` may point at an alternative file. Process-environment values override
the file, so a one-off run can use `set APC40_PORT=...` without editing anything.

## Usage

Verify the ports before anything else. This prints every device Windows exposes and, for
each configured name, whether it resolves:

```bat
uv run apc40sonar --list-ports
```

or use the launcher (locates `uv` automatically):

```bat
run-apc40-sonar.cmd --list-ports
```

Expected: the physical APC40 and both loopMIDI cables are present and all three
configured ports report `[OK]`. The command exits non-zero if any configured port is
missing.

### Verify the APC40 link

This open the physical APC40 and plays the startup lightshow, then leaves the surface in
its ready state (Pan mode, centered rings, Master + Scene 5 lit) and exits. It does not
need loopMIDI:

```bat
uv run apc40sonar --lightshow
```

### Run the engine

Opens the physical APC40 (read+write) plus the two loopMIDI cables and runs the
bidirectional loop. If the loopMIDI ports are missing it warns and runs APC40-only:

```bat
uv run apc40sonar               REM show, then run
uv run apc40sonar --no-show     REM skip the show
uv run apc40sonar --monitor     REM also print incoming MIDI
```

Stop with Ctrl+C.

## Tests

```bat
uv run pytest
```
