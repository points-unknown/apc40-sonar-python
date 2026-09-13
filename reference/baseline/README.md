# Baseline: APC40 Startup Lightshow (Frozen Known-Good Fixture)

This folder is a **frozen, known-good** copy of the original APC40 startup lightshow.
It exists as a self-test fixture and a troubleshooting reference. **Do not edit these
files in place.** If you need a variation, copy them elsewhere first.

## Files

| File | Purpose |
|---|---|
| `apc40-startup-lightshow.cfg` | MIDIMonster configuration: opens the physical APC40 output and maps the Lua instance's channels |
| `apc40-startup-lightshow.lua` | Timer-driven ~10-second full-panel lightshow, clears all LEDs at completion |

## What a successful run proves

If this fixture runs correctly, then all of the following are working:

- Windows can open the physical APC40 output.
- MIDIMonster is loaded and can route MIDI to the APC40.
- The `lua` backend is healthy and can drive output.
- The APC40 clip grid, channel strips, Clip Stop, Master, Scene, utility row,
  transport, Track Control rings, and Device Control rings all respond.

If a later integration fails, the fault is almost certainly in virtual ports,
Cakewalk surface configuration, feedback routing, or mappings, not the hardware path.

## Runtime file locations (required)

MIDIMonster loads backend DLLs and the Lua library from **the same directory as
`midimonster.exe`** (and its `backends` subfolder). Required layout:

```text
<runtime root>/
  midimonster.exe            # the MIDIMonster v0.6 executable
  lua53.dll                  # Lua 5.3 runtime; MUST sit beside midimonster.exe
  backends/
    winmidi.dll              # Windows MIDI backend
    lua.dll                  # Lua scripting backend
    wininput.dll             # keyboard/mouse backend (needed in later phases)
    ...other backend DLLs...
```

Notes:

- The Windows loader searches for `lua53.dll` in the executable's directory.
  If it is missing or in the wrong place, the `lua` backend will fail to load.
- `backends/*.dll` must remain in the `backends` subfolder.

In this workspace the runtime already lives at the repository root:

```text
midimonster.exe
lua53.dll
backends\winmidi.dll
backends\lua.dll
backends\wininput.dll
```

## How to run the fixture

1. Close every other program that can hold the APC40 MIDI port: **MIDI-OX, Bome,
   Cakewalk by BandLab, Ableton**, and any other MIDI utility.
2. From the repository root, run:

   ```bat
   midimonster.exe baseline\apc40-startup-lightshow.cfg
   ```

   The Lua `script` path in the config is resolved **relative to the config file**,
   so the script is found inside `baseline\`.

3. The full panel should animate for about 10 seconds, then go dark.

## Expected console output

A healthy start includes lines similar to:

```text
Registered backend lua
Registered backend winmidi
Reading configuration file ...
Created winmidi instance apc40
Created lua instance show
winmidi Selected output device Akai APC40 ...
core Routing ...
APC40 v4 full-panel startup lightshow complete
```

The final `APC40 v4 full-panel startup lightshow complete` line is emitted by the
timer callback when it stops itself with `interval(update, 0)`.

## Known limitation

The original APC40 does **not** provide a host-addressable LED for the
**Stop All Clips** button. Sending note 81 to it does not illuminate it. Do not
attempt host LED feedback for that button in later work.
