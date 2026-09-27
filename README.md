# apc40sonar

Standalone Python integration between an **original Akai APC40** and **Cakewalk by
BandLab**. The APC40 acts as an eight-channel mixer plus transport, knob modes, and more,
with **bidirectional feedback** so Cakewalk state drives the APC40 LEDs and rings.


> Details live in [`docs/GENERAL.md`](docs/GENERAL.md); this README stays big-picture.
> Remaining work and ideas are in [`TODO.md`](TODO.md).

## Quick start

Requirements: **Python 3.14** and **uv**; a physical `Akai APC40`; and two loopMIDI cables
(`APC40-IN`, `APC40-OUT`). **New here? Follow
[`docs/setup-loopmidi-and-cakewalk.md`](docs/setup-loopmidi-and-cakewalk.md)** for the
step-by-step loopMIDI and Cakewalk setup.

```bat
uv sync
```

Check that the physical APC40 and both loopMIDI cables are visible, then verify the
configured names resolve (this needs no loopMIDI):

```bat
uv run apc40sonar --list-ports
uv run apc40sonar --lightshow
```

Run the full engine (add `--monitor` to print MIDI traffic, `--no-show` to skip the show):

```bat
uv run apc40sonar
```

`run-apc40-sonar.cmd <args>` is a launcher that finds `uv` automatically. Stop with Ctrl+C.

### On-screen HUD (optional)

The APC40 has no display, so the app can show a small always-on-top window with the
knob mode, track window, selected track, transport, time, and a short message for each
action. Start the app with `--hud`:

```bat
uv run apc40sonar --hud
```

Or set `HUD=on` in `.env` to always show it (`--no-hud` turns it off for one run).
`HUD_LAYOUT=expanded` adds the 8 strips with track names, values and meters. Drag the
window to move it; right-click for layout, opacity and Quit. The HUD runs as its own
process and closes with the app. To attach one to an app that is already running:

```bat
uv run python -m apc40sonar.hud
```

What it shows and all `HUD_*` settings: [`docs/quick-reference.md`](docs/quick-reference.md#on-screen-hud)
and [`docs/GENERAL.md`](docs/GENERAL.md#on-screen-hud).

## Configuration

Port names and options live in `.env` at the repository root, copied from
[`.env.example`](.env.example). Windows renames loopMIDI cables between iterations, so
edit `.env` rather than the code:

```ini
APC40_PORT=Akai APC40        # physical controller (read + write)
MCU_OUT_PORT=APC40-IN       # app -> Cakewalk
MCU_IN_PORT=APC40-OUT      # Cakewalk -> app
APC40_CLIENT_NAME=apc40sonar
APC40_MODE=generic           # generic | ableton | alt-ableton
KNOB_STEP_LIMIT=3            # max V-pot steps per knob event
KNOB_NOISE_THRESHOLD=4       # ignore knob steps larger than this (0 disables)
HUD=off                      # on = small always-on-top status window
```

The full key reference, behavior notes, and architecture are in
[`docs/GENERAL.md`](docs/GENERAL.md).

## Tests

```bat
uv run pytest
```

## Troubleshooting

| Symptom | Fix |
|---|---|
| `cannot open APC40 port` | Close anything else using it (MIDI-OX, Cakewalk, Ableton), or uncheck `Akai APC40` in Cakewalk's MIDI Devices |
| `APC40-IN` / `APC40-OUT` missing | Start loopMIDI and re-add the ports; reboot after a fresh install |
| A button toggles twice per press | Remove any direct APC40 device/surface added in Cakewalk |
| LEDs flicker continuously | Ensure only this app routes back to the APC40 |
| Controls do nothing but LEDs work | Re-add the Mackie Control surface (In `APC40-IN`, Out `APC40-OUT`) |

Use `uv run apc40sonar --monitor` to see both MIDI directions and locate the failing path.
More detail in [`docs/GENERAL.md`](docs/GENERAL.md).

## Development

- Python 3.14, managed by `uv` (see `.python-version`); do not use the system Python.
- Source: `src/apc40sonar/`; tests: `tests/`.
- Dependencies: `python-rtmidi`, `PyYAML`; dev: `pytest`.
- Everything is unit-testable without hardware (ports are injected at the edges).

## Reference

- [`docs/quick-reference.md`](docs/quick-reference.md) - what every APC40 button does, per mode
- [`docs/GENERAL.md`](docs/GENERAL.md) - architecture, configuration, behavior, internals
- [`TODO.md`](TODO.md) - remaining work and enhancement ideas
- [`docs/apc40-output-reference.md`](docs/apc40-output-reference.md) - APC40 LED/ring/color map
- [`docs/mcu-mapping.md`](docs/mcu-mapping.md) - Mackie Control mapping
- [`docs/cakewalk-command-matrix.md`](docs/cakewalk-command-matrix.md) - MCU vs keystroke bridging
- [`docs/setup-loopmidi-and-cakewalk.md`](docs/setup-loopmidi-and-cakewalk.md) - step-by-step install, loopMIDI, and Cakewalk setup
- [`plans/`](plans/) - implementation plan and handoff
- [`reference/`](reference/) - the retired MIDIMonster/Lua prototype (historical) and frozen baseline lightshow
