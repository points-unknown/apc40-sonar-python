# TODO / Roadmap

Working backlog for apc40sonar. `README.md` is the big-picture quickstart;
`docs/GENERAL.md` is the detail; this file is what is left to build.

## Where we are

Of the 9 migration steps in [`plans/apc40-sonar-python-plan.md`](plans/apc40-sonar-python-plan.md):

- Steps 1-7 are done: scaffold, `midi_io`, `apc40`/`mcu`, `engine` mixer core, feedback
  rendering, startup lightshow, and end-to-end validation with Cakewalk.
- Remaining: **step 8** (grid modes, device/plug-in control, global commands) and
  **step 9** (polish), below.
- 235 hardware-free tests pass. Pan smoothing and latching-toggle fixes are in.

## Step 8 - complete the control surface

### Modes (Scene buttons)

Workflow: **Tracking** (record live parts) -> **Step Sequencer** (beats) -> **Mixing** (FX).
The Scene buttons select the mode; the lit Scene LED shows it. Only the utility row (and
the grid in the sequencer) change per mode. Faders, strip buttons, Pan/Send knobs,
transport, Cue (playhead), crossfader (zoom), Bank arrows, Stop x2 and the meters grid work
the same in every mode, and **Master toggles the strips between Tracks and Buses** in all
modes.

| Scene | Mode | Status |
|---|---|---|
| 1 | **Tracking** - utility row = editing / loop / punch (below) | To build |
| 2 | **Step Sequencer** (below) | Future |
| 3 | **Mixing** - utility row = C4 plug-in control (see Mixing mode) | Needs the C4 surface |
| 4-5 | Free | - |

- [x] Scene 1/2/3 select the mode; lit Scene LED; always Tracking at startup (done)
- [x] Loop/Punch (62-65) are the same in Mixing; only 58-61 become FX controls (done)
- [x] Master button (80) = toggle the 8 strips between Tracks and Buses (Cakewalk Mackie
      Track 76 / Aux 80); shown in the HUD, since the APC40 owns Master's LED. Cakewalk's
      Mackie surface cannot *select* a bus (Select highlights track only works on tracks)
      (done)

### Tracking mode (Scene 1)

Every button has one fixed meaning; the app drives Cakewalk's navigation modes (Marker 84,
Loop 85, Select 86, Punch 87) behind the scenes and always returns to Normal navigation.

| Button | Press | Shift + press |
|---|---|---|
| Clip/Track (58) | Undo (MCU 82) | Redo (MCU 83) |
| Device On/Off (59) | Insert marker (M1 + Marker) | *(free)* |
| < / > (60/61) | Previous / next marker (Marker nav + Rew/FF) | Go to selection start / end (Select nav + Rew/FF) |
| Detail View (62) | Loop <- selection (M2 + Loop) | Cakewalk meters on/off |
| Rec Quantize (63) | **Loop on/off** (Cakewalk note 89; LED = loop state) | *(free)* |
| MIDI Overdub (64) | Punch <- selection (M2 + Punch) | *(free)* |
| Metronome (65) | **Auto-punch on/off** (Mackie F2 in the preset; no LED - Cakewalk reports no auto-punch state) | Metronome during record (F1) |
| Nudge - / + | Move by `NUDGE_STEP`, repeating while held (done) | Selection start / end = playhead (Select nav + M1 + Rew/FF) |

- [x] Build the table above (Loop on/off and its LED moved from 65 to 63) (done)
- [x] Preset: F2 = Cakewalk's auto-punch toggle (the crossfader's fit uses Cakewalk's
      built-in Zoom + M4 + Right, so F2 was free); in the setup guide (done)
- [ ] Verify on hardware: marker jumps, selection edges, loop/punch from selection,
      auto-punch F2, Master Tracks/Buses (note 80 vs. bank dump)
- [x] Nudge - / + move the playhead by `NUDGE_STEP`, repeating while held (done)
- [x] Playhead step sizes in `.env`: `CUE_STEP`, `SHIFT_CUE_STEP` (Shift + Cue = fine),
      `NUDGE_STEP`, `NUDGE_REPEAT_MS` as `<count> <measure|beat|tick|jog>` (done)

### Shift latching

| Action | Shift state | HUD |
|---|---|---|
| Hold Shift + press | Shifted while held | `SHIFT` |
| Tap Shift | One-shot: the next **button** press is shifted (any button, used up either way); expires after `SHIFT_ONESHOT_MS` (default 3000) | `SHIFT 1x` |
| Double-tap Shift (~0.4 s) | Locked until the next tap | `SHIFT LOCK` |

- [x] Implemented: `Engine.shift_state` (`off / held / once / locked`), HUD badge
      `SHIFT` / `SHIFT 1x` / `SHIFT LOCK`; no LED on the APC40 (done)
- [ ] Knobs/faders see only held or locked Shift for now (revisit later)

### Step sequencer grid mode (Scene 2)

The clip grid becomes a pattern editor that plays drum/note lanes in sync with Cakewalk.

Layout:

```text
            step 1 ... step 8        (current page of 8 steps)
grid row 1  [ ][ ][ ][ ][ ][ ][ ][ ]  lane 1   ^
grid row 2  [ ][ ][ ][ ][ ][ ][ ][ ]  lane 2   |  Bank Select Up/Down:
grid row 3  [ ][ ][ ][ ][ ][ ][ ][ ]  lane 3   |  lanes 1-5, 6-10, ...
grid row 4  [ ][ ][ ][ ][ ][ ][ ][ ]  lane 4   |
grid row 5  [ ][ ][ ][ ][ ][ ][ ][ ]  lane 5   v
Clip Stop   [ ][ ][*][ ][ ][ ][ ][ ]  playhead (lit = step now playing)
            <-- Bank Select Left/Right: steps 1-8, 9-16, 17-24, ... -->
```

Decisions (agreed):

- **Lanes:** the 5 grid rows are 5 note lanes. Bank Select **Up/Down** pages the rows
  (lanes 1-5, 6-10, ...). Lane count is configurable (default 10 = 2 row pages).
- **Steps:** the 8 columns are 8 steps. Bank Select **Left/Right** pages the steps
  (1-8, 9-16, 17-24, ...). Pattern length is configurable (default 16 = 2 pages).
- **Playhead:** the **Clip Stop row** lights the step currently playing (green, the only
  color that row has). Dark when the playing step is on another step page.
  Track Selection keeps its normal behavior.
- **Velocity:** the original APC40 pads are **not** pressure sensitive (they always send
  `7F`), so velocity is set two ways:
  - Tap cycles a step: off -> **green** (normal) -> **amber** (accent) -> **red** (soft)
    -> off. Default velocities: normal 100, accent 127, soft 60 (configurable).
  - **Hold a step + turn a Device Control knob** for an exact velocity 1-127; the ring
    shows the value, and the pad color follows the nearest level band.
- **Clock:** follow Cakewalk. Cakewalk sends MIDI Clock + Song Position Pointer; the
  sequencer runs only while Cakewalk plays, locked to its tempo and bar position, so
  recorded notes land on the grid. Default resolution 1/16 (6 clock ticks per step).
- **Note output:** a dedicated loopMIDI cable into a Cakewalk MIDI/instrument track (arm
  it to record the pattern). Never on the Mackie Control ports.
- **Unchanged in this mode:** faders, Record Arm / Solo / Activator / Track Selection,
  Track Control knobs, transport. Meters are not drawn while the sequencer owns the grid.

Tasks:

- [ ] Research: where Cakewalk enables MIDI Clock / SPP output to a port, and confirm it
      also sends Start / Stop / Continue with the transport
- [ ] Ports: two new loopMIDI cables, e.g. `APC40-SEQ` (app -> Cakewalk notes) and
      `APC40-CLOCK` (Cakewalk -> app clock), with `SEQ_OUT_PORT` / `CLOCK_IN_PORT` in
      `.env`, opened best-effort. Separate cables so neither side reads its own traffic
- [ ] `sequencer` module (hardware-free, unit-tested): pattern model (lanes x steps x
      velocity), clock tick -> step advance, SPP positioning, Start/Stop/Continue, Note
      On/Off scheduling (fixed gate, e.g. half a step), all notes off on Stop
- [ ] Lane config: note number + MIDI channel per lane in `.env` or a YAML file; default
      GM drums on channel 10 (kick 36, snare 38, closed hat 42, open hat 46, clap 39, ...)
- [ ] Grid rendering: pad colors from the current lane page + step page; playhead on
      Clip Stop; redraw on page change and when leaving/re-entering the mode
- [ ] Input: pad press cycles the step; hold pad + Device Control knob sets velocity
      (depends on handling Mode 0 Device Control banking - see Device / plug-in mode);
      Bank Select arrows page steps/lanes instead of sending MCU cursor keys
- [ ] Page indicator: on a page change, briefly show the page number (e.g. light Clip Stop
      LED *n* for page *n*) before returning to the playhead
- [ ] Clip Stop presses in this mode: no MCU V-pot push (the row is a display); decide
      later whether they get a function
- [ ] Pattern persistence: save/load patterns to a file so they survive a restart
- [ ] Docs: sequencer section in `docs/quick-reference.md`, cables and Cakewalk clock
      setup in `docs/setup-loopmidi-and-cakewalk.md`, internals in `docs/GENERAL.md`
- [ ] Later ideas: clear pattern (e.g. Shift + Stop All Clips), per-lane mute, copy page,
      swing, per-lane step length, internal clock for jamming without the transport

### Mixing mode (Scene 3)

Plan: [`plans/c4-surface-plan.md`](plans/c4-surface-plan.md). A Cakewalk *Mackie Control
C4* second surface drives the 8 Device Control knobs, so plug-in control works alongside
Pan/Sends on the top knobs (one Mackie surface has only one row of 8 V-pots). The C4
follows the selected track/bus; Master toggles Tracks/Buses for bus FX.

- [ ] C4 surface per the plan: two loopMIDI cables (`C4_OUT_PORT` / `C4_IN_PORT`), answer
      the C4 handshake, set split/assignment at connect, `c4` module, Device knobs -> C4
      row 1 with rings on the current bank's channel
- [ ] Utility row in Mixing: < / > = parameter page (Shift = +/-1), Clip/Track = next
      plug-in (Shift = previous), Device On/Off = bypass if a command can be bound
- [ ] Capture C4 LCD text (parameter names/values) for the HUD
- [ ] Setup guide + GENERAL.md for the second surface
- [x] Device knob baselines per APC40 bank; Device ring feedback on the current bank's
      channel (done)
- [x] Send A/B/C select sends 1/2/3 without flipping the knob layout (done, verified)

### Navigation and transport

- [x] Bank +/- (MCU 46/47) on Bank Select Left/Right and Channel +/- (48/49) on Shift +
      Left/Right (done). Bank Select arrow LEDs flash on press
- [ ] Show which bank is active (e.g. briefly on the grid); Cakewalk does not report the
      strip offset over MCU, so it would have to be tracked locally. The HUD now derives
      it from track selects (`Engine.bank_offset`); the grid could reuse that
- [x] Master fader (APC CC 14) -> MCU Pitch Bend ch 8 (done)
- [x] **Crossfader = horizontal zoom** (APC CC 15), all Mackie Control (done): MCU Zoom
      mode + Cursor Left/Right, auto on/off after `ZOOM_IDLE_MS`, following the Zoom LED;
      one step per `ZOOM_STEP_UNITS`, capped at 4 per event; fully left = fit project via
      Cakewalk's built-in Zoom + M4 + Right (no F2 preset assignment needed)
  - [x] Verified on hardware; `ZOOM_STEP_UNITS` default tuned to 6
- [x] Bank Select arrows decided: Left/Right = bank, Shift + Left/Right = channel,
      Up/Down = Cakewalk arrow keys (done). In step-sequencer mode they will page steps
      (Left/Right) and lanes (Up/Down) instead
- [ ] Tap Tempo (99): only flashes its LED; needs the keystroke bridge for real tap tempo
- [x] Cue Level knob (CC 47) -> MCU jog (CC 60) by `CUE_STEP`; Shift + Cue by
      `SHIFT_CUE_STEP` (done)
- [x] Stop pressed twice quickly -> Cakewalk Home (go to start) (done)
- Footswitches 1 / 2 (CC 64 / 67): not planned (unused)
- [x] Removed the Rec Quantize "Cycle" LED placeholder: in Cakewalk mode LED 86 is the
      Select-navigation mode, and loop state is already on the Metronome LED
- [ ] Check: the original APC40's Track Control knobs appear to have no push switches;
      drop this idea if confirmed on the hardware

## Keystroke bridge (only if still needed)

Most keyboard-only ideas turned out to be reachable over Mackie Control (undo/redo,
markers, loop/punch from selection, selection start/end). What remains:

- [ ] Tap tempo (99): needs a keystroke; only flashes its LED today
- [ ] If built: add `pydirectinput` or `pynput`, a dedicated conflict-free Cakewalk keymap
      (see [`docs/cakewalk-command-matrix.md`](docs/cakewalk-command-matrix.md)), and a
      `keys` module

## Step 9 - polish and robustness

- [ ] Reconnect handling: detect loopMIDI/APC40 disappearing and recover without restart
- [ ] Move the control mapping into the config file so functions can be reassigned without code
- [ ] Decoded `--monitor` (human-readable note/CC names) alongside the raw dump
- [ ] Configurable log level and log rotation size
- [x] Shutdown: exit animation (grid fills red, drains top to bottom), then the panel is
      left dark so it is obvious the app is not running (done)
- [ ] Fallback for Windows MIDI Services loopback endpoints when loopMIDI is unavailable
- [x] Refresh the MIDIMonster-era wording in
      [`docs/setup-loopmidi-and-cakewalk.md`](docs/setup-loopmidi-and-cakewalk.md) to the Python app

## Ideas to make the APC40 most useful in Cakewalk/SONAR

Ordered roughly by value-to-effort:

- [x] **Track level meters** - MCU channel-pressure meters render as a 5-segment bar per
      track on the clip grid, with a latched clip indicator on Clip Stop (done; `METERS`).
- [ ] **Second surface: Mackie Control C4** - now the Mixing mode plan (above).
- [x] **Send-level control with rings** - Send A/B/C buttons plus the Track Control knobs
      set send 1/2/3 levels, with the rings showing the send amount (done).
- [ ] **Session/bank overview on the grid** - use the 8x5 grid to show which bank of tracks
      is active and which clips/scenes exist, instead of blank pads.
- [ ] **Shift modifiers** - Shift + strip button = alternate action (e.g. Shift+Mute =
      clear all mutes; Shift+Scene = record-enable scene).
- [ ] **More grid modes** - drum-pad and clip-launch modes on free Scene buttons (4-5).
- [ ] **Template + setup doc** - a ready-made Cakewalk project template (tracks, keymap,
      surface config) so setup is one import.
- [ ] **Performance pass** - throttle/coalesce feedback, batch LED writes, and cap per-frame
      messages to keep the event loop smooth under heavy knob movement.

## Notes

- Documentation policy: big picture only in `README.md`; all detail in `docs/GENERAL.md`.
  Every feature that changes a control's behavior also updates `docs/quick-reference.md`.
- Known limitation: Cakewalk's Mackie Control ignores MCU Rec note 0, so APC Track 1
  Record Arm cannot arm track 1 over the surface (use the mouse). Do not reintroduce the
  Remote Control workaround - it conflicts with the Mackie Control surface.
