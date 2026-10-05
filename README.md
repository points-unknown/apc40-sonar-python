# apc40sonar

> [!CAUTION]
> **Vibecoded.** Code, scripts, reverse-engineering notes, plan and this README were written by an AI (Claude) in
> conversation with the author, not by hand. Actual operation has been tested extensively, physically an Akai APC40 
> (Gen 1). However, nobody has reviewed the code, audited it, conducted security reviews, or interviewed it for the
> cover of Rolling Stone. It is what it is.
>
> The author (the AI) or the facilitator (me) take no responsibility for it's actions, impacts to your hardware or
> software, music projects, other files, computers, music quality, well-being, good taste, etc.
>
> **If these things matter to you, READ THE CODE FIRST. No warranty, no support, you own all the risk.**

Standalone Python integration between an **original Akai APC40** and **Cakewalk by
BandLab**. The APC40 becomes a Mackie Control surface for Cakewalk: an eight-channel mixer
(tracks or buses) with pan and three sends, transport, playhead scrubbing, markers,
loop and punch, timeline zoom, level meters on the clip grid, **plug-in control** on the
Device Control knobs, a **drum step sequencer** on the clip grid, and a small on-screen
HUD, with **bidirectional feedback** so Cakewalk state drives the APC40 LEDs and rings.

Three modes on the Scene buttons: **1 Tracking** (record and edit: undo, markers, loop,
punch), **2 Step Sequencer** (the grid is a drum pattern, with an editor window),
**3 Mixing** (the utility row picks the plug-in and its parameters).

**What every button does:** [`docs/quick-reference.md`](docs/quick-reference.md).


> Details live in [`docs/GENERAL.md`](docs/GENERAL.md); this README stays big-picture.
> Remaining work and ideas are in [`TODO.md`](TODO.md).

## Quick start

Requirements: **Python 3.14** and **uv**; a physical `Akai APC40`; and two loopMIDI cables
(`APC40-IN`, `APC40-OUT`). Optional: two more for the step sequencer (`APC40-SEQ`,
`APC40-CLOCK`) and two for plug-in control (`C4-IN`, `C4-OUT`). **New here? Follow
[`docs/setup-loopmidi-and-cakewalk.md`](docs/setup-loopmidi-and-cakewalk.md)** for the
step-by-step loopMIDI and Cakewalk setup, including the one-time **Mackie Control preset**
(meters, master fader, F1 metronome, F2 auto-punch, *Select highlights track*) that the
APC40 needs in every project.

```bat
uv sync
```

Check that the physical APC40 and both loopMIDI cables are visible, then test the APC40
link on its own with the lightshow (that step needs no loopMIDI):

```bat
uv run apc40sonar --list-ports
uv run apc40sonar --lightshow
```

Run the full engine (add `--monitor` to print MIDI traffic, `--no-show` to skip the show):

```bat
uv run apc40sonar
```

The APC40 starts in **Tracking** mode (Scene 1 lit); Scene 3 is **Mixing**. Stop with
Ctrl+C: the panel plays a short exit animation and goes dark. `run-apc40-sonar.cmd <args>`
is a launcher that finds `uv` automatically.

### On-screen HUD

The APC40 has no display, so the app shows a small always-on-top window with the knob
mode, track window, selected track, transport, time, the plug-in on the Device knobs, and
a short message for each action. It opens automatically with `uv run apc40sonar`. To run
without it:

```bat
uv run apc40sonar --no-hud
```

or set `HUD=off` in `.env` to turn it off for good.
`HUD_LAYOUT=expanded` (or right-click > Expanded) adds, to its left, the 8 plug-in
parameters and the 8 strips with track names, values and meters. Drag the window to move
it; it remembers the spot (`--reset-hud-position` or right-click > Reset position forgets
it). The HUD runs as its own process and closes with the app. To attach one to an app that
is already running:

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
HUD=on                       # small always-on-top status window (off = none)
HUD_MARGIN=50,12             # HUD gap from its corner (top right), x,y pixels
C4_OUT_PORT=C4-IN            # plug-in control (optional), app -> Cakewalk
C4_IN_PORT=C4-OUT            # ... Cakewalk -> app
CUE_STEP=1 beat              # playhead per Cue Level detent (measure | beat | tick | jog)
SHIFT_CUE_STEP=30 tick       # ... with Shift held (fine)
NUDGE_STEP=1 measure         # playhead per Nudge press
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
| Controls do nothing but LEDs work | Re-add the Mackie Control surface (In `APC40-IN`, Out `APC40-OUT`); check *Disable handshake* is checked |
| Nothing responds; loopMIDI shows a cable as `[muted]` | Restart loopMIDI, then Cakewalk and the app |
| Meters dark, master fader or Track Selection do nothing | Apply the Mackie Control preset from the setup guide (step 4) |

More symptoms and fixes: the setup guide's
[troubleshooting](docs/setup-loopmidi-and-cakewalk.md#troubleshooting).

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
- [`plans/next-session-handoff.md`](plans/next-session-handoff.md) - current state and next steps (start here)
- [`plans/`](plans/) - implementation plan, handoff, C4 surface plan, HUD concept
- [`reference/`](reference/) - the retired MIDIMonster/Lua prototype (historical) and frozen baseline lightshow
